"""Deep Monte Carlo self-play (DouZero-style) for Tuppi.

One shared Q-network plays all four seats. Every decision's target is the
acting team's match-equity change over that deal (from the equity table fitted
on incumbent self-play), so score-dependent play is learnable: the network sees
the score and the reward prices points through the rising-score rule.

    python -m tuppi_ai.train --name dmc1 --hours 2
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import model as qmodel
from .equity import Equity
from .native import Env, feature_dim

ROOT = Path(__file__).resolve().parents[1]
WINDOW = 64  # a deal is at most 56 decisions


class Replay:
    def __init__(self, capacity: int, dim: int):
        self.feat = np.zeros((capacity, dim), dtype=np.uint8)
        self.act = np.zeros(capacity, dtype=np.int64)
        self.ret = np.zeros(capacity, dtype=np.float32)
        self.capacity, self.ptr, self.size = capacity, 0, 0

    def add(self, feat, act, ret) -> None:
        n = len(act)
        idx = (self.ptr + np.arange(n)) % self.capacity
        self.feat[idx], self.act[idx], self.ret[idx] = feat, act, ret
        self.ptr = (self.ptr + n) % self.capacity
        self.size = min(self.size + n, self.capacity)

    def sample(self, n: int, rng: np.random.Generator):
        idx = rng.integers(0, self.size, n)
        return self.feat[idx], self.act[idx], self.ret[idx]


def random_legal(mask: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    noise = rng.random(mask.shape) * mask
    return noise.argmax(axis=1)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--games", type=int, default=4096)
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--blocks", type=int, default=4)
    p.add_argument("--encoder", type=int, default=2)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--batch", type=int, default=4096)
    p.add_argument("--updates", type=int, default=1, help="SGD steps per environment step")
    p.add_argument("--replay", type=int, default=1_000_000)
    p.add_argument("--eps", type=float, default=0.03)
    p.add_argument("--p-random-start", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--resume", type=Path)
    p.add_argument("--ckpt-every", type=float, default=15.0, help="minutes")
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
    counters = {"deals": 0, "decisions": 0, "updates": 0}
    if args.resume:
        blob = torch.load(args.resume, map_location="cpu", weights_only=False)
        net = qmodel.QNet(**blob["config"])
        net.load_state_dict(blob["state"])
        counters.update(blob.get("counters", {}))
    env = Env(args.games, args.seed, equity.table, p_random_start=args.p_random_start, encoder=net.encoder)
    dim = feature_dim(net.encoder)
    net.to(device)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    replay = Replay(args.replay, dim)

    n = args.games
    ring_feat = np.zeros((WINDOW, n, dim), dtype=np.uint8)
    ring_act = np.zeros((WINDOW, n), dtype=np.int64)
    ring_team = np.zeros((WINDOW, n), dtype=np.int8)
    deal_start = np.zeros(n, dtype=np.int64)
    step = 0
    t_start = t_log = t_ckpt = time.time()
    stats = {"loss": [], "rami": 0, "stolen": 0, "deals": 0, "absdelta": 0.0, "matches": 0}

    log = open(out / "log.jsonl", "a")
    while time.time() - t_start < args.hours * 3600:
        feat, mask, seat, _ = env.observe()
        with torch.no_grad():
            q = net(torch.from_numpy(feat).to(device))
            m = torch.from_numpy(mask).to(device)
            acts = qmodel.masked_argmax(q, m).cpu().numpy()
        explore = rng.random(n) < args.eps
        if explore.any():
            acts[explore] = random_legal(mask[explore], rng)
        slot = step % WINDOW
        ring_feat[slot] = feat
        ring_act[slot] = acts
        ring_team[slot] = seat & 1
        illegal = env.step(acts)
        if illegal:
            raise RuntimeError(f"{illegal} illegal actions at step {step}")
        for i in np.nonzero(env.done)[0]:
            slots = np.arange(deal_start[i], step + 1) % WINDOW
            g0 = float(env.delta0[i]) * qmodel.RETURN_SCALE
            teams = ring_team[slots, i]
            replay.add(ring_feat[slots, i], ring_act[slots, i], np.where(teams == 0, g0, -g0))
            deal_start[i] = step + 1
            info = env.info[i]
            stats["deals"] += 1
            stats["rami"] += int(info[2] == 1)
            stats["stolen"] += int(info[2] == 1 and info[0] != (info[3] & 1))
            stats["absdelta"] += abs(float(env.delta0[i]))
            stats["matches"] += int(info[5])
        counters["decisions"] += n
        step += 1

        if replay.size >= 50 * args.batch:
            for _ in range(args.updates):
                f, a, r = replay.sample(args.batch, rng)
                x = torch.from_numpy(f).to(device)
                qa = net(x).gather(1, torch.from_numpy(a).to(device)[:, None])[:, 0]
                loss = torch.nn.functional.mse_loss(qa, torch.from_numpy(r).to(device))
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 10.0)
                opt.step()
                counters["updates"] += 1
                if counters["updates"] % 25 == 0:
                    stats["loss"].append(loss.item())

        now = time.time()
        if now - t_log > 60:
            counters["deals"] += stats["deals"]
            d = max(stats["deals"], 1)
            row = {"t": round(now - t_start), "deals": counters["deals"], "updates": counters["updates"],
                   "deals_per_s": round(stats["deals"] / (now - t_log), 1),
                   "loss": round(float(np.mean(stats["loss"])), 5) if stats["loss"] else None,
                   "rami": round(stats["rami"] / d, 4), "stolen_of_rami": round(stats["stolen"] / max(stats["rami"], 1), 4),
                   "mean_abs_delta": round(stats["absdelta"] / d, 5),
                   "deals_per_match": round(d / max(stats["matches"], 1), 2)}
            print(json.dumps(row), flush=True)
            log.write(json.dumps(row) + "\n")
            log.flush()
            stats = {"loss": [], "rami": 0, "stolen": 0, "deals": 0, "absdelta": 0.0, "matches": 0}
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
