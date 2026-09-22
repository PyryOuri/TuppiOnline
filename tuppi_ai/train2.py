"""Self-play with paired counterfactual targets.

Plain Deep Monte Carlo (train.py) trains Q(obs, a_taken) on one deal outcome,
whose variance is dominated by where the hidden cards lie; the effect of a
single card is a small fraction of it, so the network learns state value long
before it learns which card is better.

Here, at a random subset of decisions, the full game state is copied and every
legal action is played out from the *same* state with the current greedy
policy. Each branch shares the hidden cards, so the differences between
branch outcomes are free of that noise (most decisions change nothing and give
exactly zero differences). The network is trained on:

  * the usual Monte Carlo target for the taken action (level), and
  * for branched decisions, every legal action's branch outcome (level) plus
    the centred differences (advantage), weighted by `--adv-weight`.

Every target is an unbiased sample of Q^pi(obs, a) for the current policy pi,
because the branch state is a draw from the true posterior over hidden cards.

    python -m tuppi_ai.train2 --name pair1 --hours 3
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import model as qmodel
from . import native
from .equity import Equity
from .native import NUM_ACTIONS, Env, feature_dim
from .train import WINDOW, Replay, random_legal

ROOT = Path(__file__).resolve().parents[1]


class AllActionReplay:
    def __init__(self, capacity: int, dim: int):
        self.feat = np.zeros((capacity, dim), dtype=np.uint8)
        self.mask = np.zeros((capacity, NUM_ACTIONS), dtype=np.uint8)
        self.ret = np.zeros((capacity, NUM_ACTIONS), dtype=np.float32)
        self.capacity, self.ptr, self.size = capacity, 0, 0

    def add(self, feat, mask, ret) -> None:
        i = self.ptr
        self.feat[i], self.mask[i], self.ret[i] = feat, mask, ret
        self.ptr = (i + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, n: int, rng):
        idx = rng.integers(0, self.size, n)
        return self.feat[idx], self.mask[idx], self.ret[idx]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--games", type=int, default=2048)
    p.add_argument("--branch-games", type=int, default=16384)
    p.add_argument("--p-branch", type=float, default=0.04, help="per unforced decision")
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--encoder", type=int, default=2)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--batch", type=int, default=2048)
    p.add_argument("--adv-batch", type=int, default=1024)
    p.add_argument("--adv-weight", type=float, default=4.0)
    p.add_argument("--replay", type=int, default=600_000)
    p.add_argument("--adv-replay", type=int, default=200_000)
    p.add_argument("--eps", type=float, default=0.03)
    p.add_argument("--p-random-start", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--resume", type=Path)
    p.add_argument("--ckpt-every", type=float, default=20.0, help="minutes")
    p.add_argument("--equity", type=Path, default=ROOT / "runs" / "equity_incumbent.json")
    args = p.parse_args()

    out = ROOT / "runs" / args.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "args.json").write_text(json.dumps({k: str(v) for k, v in vars(args).items()}, indent=1))
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    equity = Equity.load(args.equity)

    net = qmodel.QNet(args.width, args.blocks, args.encoder)
    counters = {"deals": 0, "decisions": 0, "updates": 0, "branches": 0}
    if args.resume:
        blob = torch.load(args.resume, map_location="cpu", weights_only=False)
        net = qmodel.QNet(**blob["config"])
        net.load_state_dict(blob["state"])
        counters.update(blob.get("counters", {}))
    net.to(device)
    enc = net.encoder
    dim = feature_dim(enc)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr, fused=device.type == "mps")

    n, nb = args.games, args.branch_games
    env = Env(n, args.seed, equity.table, p_random_start=args.p_random_start, encoder=enc)
    benv = Env(nb, args.seed + 7919, equity.table, single_deal=True, encoder=enc)
    for j in range(nb):  # park every branch slot
        benv.deal(j).phase = native.PH_DONE
    replay = Replay(args.replay, dim)
    areplay = AllActionReplay(args.adv_replay, dim)

    ring_feat = np.zeros((WINDOW, n, dim), dtype=np.uint8)
    ring_act = np.zeros((WINDOW, n), dtype=np.int64)
    ring_team = np.zeros((WINDOW, n), dtype=np.int8)
    deal_start = np.zeros(n, dtype=np.int64)

    free = list(range(nb))
    slot_group = np.full(nb, -1, dtype=np.int64)
    forced = np.full(nb, -1, dtype=np.int32)  # first action of a fresh child
    groups: dict[int, dict] = {}
    next_group = 0

    step = 0
    t_start = t_log = t_ckpt = time.time()
    stats = {"loss": [], "adv": [], "rami": 0, "deals": 0, "matches": 0, "branches": 0,
             "zero_diff": 0, "live_children": 0, "steps": 0}
    log = open(out / "log.jsonl", "a")
    while time.time() - t_start < args.hours * 3600:
        feat, mask, seat, _ = env.observe()
        bfeat, bmask, bseat, _ = benv.observe()
        blive = np.nonzero((bseat >= 0) & (forced < 0))[0]
        x = np.concatenate([feat, bfeat[blive]]) if len(blive) else feat
        m = np.concatenate([mask, bmask[blive]]) if len(blive) else mask
        with torch.no_grad():
            q = net(torch.from_numpy(x).to(device)).cpu().numpy()
        acts_all = np.where(m == 1, q, -np.inf).argmax(axis=1)
        acts = acts_all[:n].copy()
        explore = rng.random(n) < args.eps
        if explore.any():
            acts[explore] = random_legal(mask[explore], rng)

        # Branch a random subset of unforced main decisions before stepping.
        legal_count = mask.sum(axis=1)
        want = np.nonzero((legal_count > 1) & (rng.random(n) < args.p_branch))[0]
        for i in want:
            legal = np.nonzero(mask[i])[0]
            if len(free) < len(legal):
                break
            gid = next_group
            next_group += 1
            state = env.deal(int(i))
            slots = [free.pop() for _ in legal]
            for s_, a_ in zip(slots, legal):
                benv.set_state(s_, state)
                slot_group[s_] = gid
                forced[s_] = a_
            groups[gid] = {"feat": feat[i].copy(), "mask": mask[i].copy(), "team": int(seat[i] & 1),
                           "slots": dict(zip(slots, legal.tolist())), "ret": np.zeros(NUM_ACTIONS, np.float32),
                           "pending": len(slots)}
            stats["branches"] += 1

        bacts = np.zeros(nb, dtype=np.int32)
        if len(blive):
            bacts[blive] = acts_all[n:]
        fresh = forced >= 0
        bacts[fresh] = forced[fresh]
        forced[fresh] = -1

        slot = step % WINDOW
        ring_feat[slot] = feat
        ring_act[slot] = acts
        ring_team[slot] = seat & 1
        if env.step(acts) or benv.step(bacts):
            raise RuntimeError(f"illegal action at step {step}")

        for i in np.nonzero(env.done)[0]:
            slots_ = np.arange(deal_start[i], step + 1) % WINDOW
            g0 = float(env.delta0[i]) * qmodel.RETURN_SCALE
            teams = ring_team[slots_, i]
            replay.add(ring_feat[slots_, i], ring_act[slots_, i], np.where(teams == 0, g0, -g0))
            deal_start[i] = step + 1
            info = env.info[i]
            stats["deals"] += 1
            stats["rami"] += int(info[2] == 1)
            stats["matches"] += int(info[5])
        for s_ in np.nonzero(benv.done)[0]:
            gid = int(slot_group[s_])
            g = groups[gid]
            g0 = float(benv.delta0[s_]) * qmodel.RETURN_SCALE
            g["ret"][g["slots"][int(s_)]] = g0 if g["team"] == 0 else -g0
            g["pending"] -= 1
            slot_group[s_] = -1
            benv.deal(int(s_)).phase = native.PH_DONE
            free.append(int(s_))
            if g["pending"] == 0:
                legal = g["mask"].astype(bool)
                vals = g["ret"][legal]
                stats["zero_diff"] += int(np.all(vals == vals[0]))
                areplay.add(g["feat"], g["mask"], g["ret"])
                del groups[gid]
        stats["live_children"] += nb - len(free)
        stats["steps"] += 1
        counters["decisions"] += n
        step += 1

        if replay.size >= 20 * args.batch and areplay.size >= 5 * args.adv_batch:
            f, a, r = replay.sample(args.batch, rng)
            fa, ma, ra = areplay.sample(args.adv_batch, rng)
            xt = torch.from_numpy(np.concatenate([f, fa])).to(device)
            qall = net(xt)
            qmc = qall[: len(a)].gather(1, torch.from_numpy(a).to(device)[:, None])[:, 0]
            loss_mc = torch.nn.functional.mse_loss(qmc, torch.from_numpy(r).to(device))
            qa = qall[len(a):]
            mt = torch.from_numpy(ma).to(device).float()
            rt = torch.from_numpy(ra).to(device)
            cnt = mt.sum(1, keepdim=True)
            level = (((qa - rt) ** 2) * mt).sum(1) / cnt[:, 0]
            qc = qa - (qa * mt).sum(1, keepdim=True) / cnt
            rc = rt - (rt * mt).sum(1, keepdim=True) / cnt
            adv = (((qc - rc) ** 2) * mt).sum(1) / cnt[:, 0]
            loss = loss_mc + level.mean() + args.adv_weight * adv.mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 10.0)
            opt.step()
            counters["updates"] += 1
            if counters["updates"] % 25 == 0:
                stats["loss"].append(loss_mc.item())
                stats["adv"].append(adv.mean().item())

        now = time.time()
        if now - t_log > 60:
            counters["deals"] += stats["deals"]
            counters["branches"] += stats["branches"]
            d = max(stats["deals"], 1)
            done_groups = max(stats["branches"] - len(groups), 1)
            row = {"t": round(now - t_start), "deals": counters["deals"], "updates": counters["updates"],
                   "deals_per_s": round(stats["deals"] / (now - t_log), 1),
                   "branches_per_s": round(stats["branches"] / (now - t_log), 1),
                   "mc_loss": round(float(np.mean(stats["loss"])), 5) if stats["loss"] else None,
                   "adv_loss": round(float(np.mean(stats["adv"])), 5) if stats["adv"] else None,
                   "rami": round(stats["rami"] / d, 4),
                   "zero_diff_share": round(stats["zero_diff"] / done_groups, 3),
                   "mean_live_children": round(stats["live_children"] / max(stats["steps"], 1)),
                   "deals_per_match": round(d / max(stats["matches"], 1), 2)}
            print(json.dumps(row), flush=True)
            log.write(json.dumps(row) + "\n")
            log.flush()
            stats = {k: ([] if isinstance(v, list) else 0) for k, v in stats.items()}
            t_log = now
        if now - t_ckpt > args.ckpt_every * 60:
            qmodel.save(net, out / f"ckpt_{counters['deals']:010d}.pt", counters=counters)
            qmodel.save(net, out / "latest.pt", counters=counters)
            t_ckpt = now
    counters["deals"] += stats["deals"]
    qmodel.save(net, out / f"ckpt_{counters['deals']:010d}.pt", counters=counters)
    qmodel.save(net, out / "latest.pt", counters=counters)


if __name__ == "__main__":
    main()
