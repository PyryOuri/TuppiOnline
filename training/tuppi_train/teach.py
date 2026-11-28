"""Teach the plain network the look-ahead's decisions (a pilot, judged by play).

The look-ahead beats the plain network, but only where its model of the hidden
cards is faithful: scored by real outcomes (calibrate.py), about a third of its
claims are real in tricks 5-9 and nearly all of them from trick 10, against a
tenth in the bidding and the first four tricks. An earlier attempt to train on
single play-outs (focus.py) drowned in noise. Here the labels are the
look-ahead's means over many sampled deals, taken only in the phases where they
can be trusted, and the network is asked for one thing: where the look-ahead
would change its move, prefer that move.

    python -m tuppi_train.teach record --net <net> --out <dir> --hours 1 [--offer-model <file>]
    python -m tuppi_train.teach fit --net <net> --out <dir>

record  (--hours is the total recording time of the folder; a rerun continues
        up to it.) Self-play of the plain network (the training mix of match scores). At
        every decision of the chosen phases with at least two candidates, the
        look-ahead's mean gain of each candidate over the network's move and
        its standard error are stored with the observation. Resumable shards.
fit     A copy of the network is trained on those decisions: its target is the
        original network's own policy, with the look-ahead's choice and the
        network's move exchanged where the rule would change the move (so the
        choice becomes the favourite, by the margin the old favourite had).
        Unchanged decisions hold it in place. Each minibatch is seen through a
        random exact suit view, as in bake.py. Snapshots along the way play the
        original network; the best is kept as taught.pt and then plays complete
        matches against the original.

The rule is applied at fit time (`--z-by-phase`, `--keep`), so one recording
serves several rules.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import device, evaluate, lockstep, lookahead, matches, symmetry, tn
from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.value import _unpack

A = native.NUM_ACTIONS
PAD = native.NUM_ACTIONS
KEYS = ("feat", "mask", "cand", "k", "m", "se", "effective", "phase")


def record(out: Path, net_name: str, settings: "lookahead.Settings", hours: float = 1.0, games: int = 4096,
           seed: int = 1, rollout_name: str = "", likelihood_name: str = "", dev=None, amp_name: str = "",
           lane_games: int = 65536, offer_model_path: str = "", max_shards: int = 10**9, log=print) -> int:
    """Shards of labelled decisions in out/labels (see the module text); returns their number."""
    from . import offer
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    out = Path(out)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    dev = dev or device.pick()
    device.setup(dev)
    amp_name = amp_name or ("fp16" if dev.type == "cuda" else "off")
    never = lookahead.Settings(**{**vars(settings), "keep": 1e9, "keep_show": 1e9})
    config = {"net": net_name, "rollout": rollout_name or net_name, "likelihood": likelihood_name, "games": games,
              "seed": seed, "amp": amp_name, "offer_model": bool(offer_model_path),
              "settings": {k: v for k, v in vars(settings).items() if k in
                           ("worlds", "top", "min_prob", "dd_left", "belief", "belief_t", "belief_eps", "phases", "show")}}
    cfg = out / "labels" / "config.json"
    if cfg.exists() and json.loads(cfg.read_text()) != config:
        raise SystemExit(f"{out} holds labels made with other settings; use another --out")
    cfg.write_text(json.dumps(config, indent=1))
    native.set_showing_fix(True)
    native.set_offer_model(None)
    table = Equity.load(EQUITY).table
    net = symmetry.load_net(net_name, dev)
    env = native.Env(games, 1, table, single_deal=True, encoder=net.encoder)
    env.set_sooli(0, False, True, 0.0)
    offer_model = offer.load_native(offer_model_path) if offer_model_path else None
    look = lookahead.build(net, dev, never, env, table, symmetry.load_net(rollout_name, dev) if rollout_name else None,
                           device.AMP[amp_name], 2, lane_games, True, offer_model,
                           likelihood_net=symmetry.load_net(likelihood_name, dev) if likelihood_name else None)
    progress = out / "labels" / "progress.json"          # hours is the total for this folder: a rerun continues up to it
    used = json.loads(progress.read_text())["seconds"] if progress.exists() else 0.0
    t_start = time.time()
    t_end = t_start + max(0.0, 3600 * hours - used)
    i = len(list((out / "labels").glob("shard_*.npz")))
    while time.time() < t_end and i < max_shards:
        look.reset(seed + 7919 * i)
        look.trace = []
        t0 = time.perf_counter()
        lockstep.rollouts(env, look, games, 3, C.c_uint64(seed * 1_000_003 + i), net.encoder)
        if look.trace:
            t = {k: np.concatenate([part[k] for part in look.trace]) for k in look.trace[0] if k != "state"}
            diff = t["q"].astype(np.float64) - t["q"][:, :, :1]
            data = {"feat": t["feat"], "mask": t["mask"], "cand": t["cand"].astype(np.uint8), "k": t["k"].astype(np.int8),
                    "m": diff.mean(1).astype(np.float32),
                    "se": (diff.std(1, ddof=1) / np.sqrt(diff.shape[1])).astype(np.float32),
                    "effective": t["effective"], "phase": t["phase"]}
            path = out / "labels" / f"shard_{i:05d}.npz"
            tmp = path.with_name(path.name + ".tmp.npz")
            np.savez_compressed(tmp, **data)
            tmp.replace(path)
            log(f"shard {i}: {len(data['k']):,} labelled decisions from {games:,} deals in {time.perf_counter() - t0:.0f} s")
        i += 1
        progress.write_text(json.dumps({"seconds": used + time.time() - t_start}))
    return len(list((out / "labels").glob("shard_*.npz")))


def load_labels(out: Path, max_shards: int = 10**9) -> dict:
    files = sorted((Path(out) / "labels").glob("shard_*.npz"))[:max_shards]
    if not files:
        raise SystemExit(f"no label shards in {out}/labels")
    parts = [np.load(f) for f in files]
    return {k: np.concatenate([p[k] for p in parts]) for k in KEYS}


def choices(d: dict, keep: float = 0.003, z_by_phase=(2.0, 2.0, 1.0, 0.0), all_worlds: bool = True) -> np.ndarray:
    """The candidate the rule would play at each labelled decision (0 = the network's own move):
    the largest mean gain among those above `keep` and above the phase's z standard errors."""
    m, se = d["m"].astype(np.float64), d["se"].astype(np.float64)
    if not all_worlds:
        w = d["effective"].astype(np.float64)
        se = se * np.sqrt(w.max() / w)[:, None]
    z = np.asarray(z_by_phase, np.float64)[d["phase"]][:, None]
    valid = np.arange(m.shape[1])[None, :] < d["k"][:, None]
    ok = valid & (m > keep) & (m > z * se)
    ok[:, 0] = False
    score = np.where(ok, m, -np.inf)
    best = score.argmax(1)
    return np.where(ok.any(1), best, 0)


def targets(logits: torch.Tensor, own: torch.Tensor, chosen: torch.Tensor) -> torch.Tensor:
    """The original network's masked logits with the entries of its own move and of the chosen
    move exchanged (rows where they are the same action are unchanged)."""
    t = logits.clone()
    rows = torch.arange(len(t), device=t.device)
    a, b = logits[rows, own], logits[rows, chosen]
    t[rows, own], t[rows, chosen] = b, a
    return t


def fit(out: Path, net_name: str, dev=None, steps: int = 0, epochs: float = 3.0, batch: int = 16384, lr: float = 2e-5,
        switch_weight: float = 4.0, keep: float = 0.003, z_by_phase=(2.0, 2.0, 1.0, 0.0), all_worlds: bool = True,
        snapshots: int = 6, eval_base: int = 16384, eval_seed: int = 20261129, match_pairs: int = 10000,
        max_shards: int = 10**9, seed: int = 1, amp_name: str = "off", log=print) -> dict:
    """Trains a copy of `net_name` on the labels in `out` (see the module text). Returns and writes
    out/fit.json: per snapshot the duplicate result against the original at 0-0, the best
    snapshot's matches, and how the labels were used."""
    out = Path(out)
    dev = dev or device.pick()
    device.setup(dev)
    amp = device.AMP[amp_name]
    torch.manual_seed(seed)
    d = load_labels(out, max_shards)
    n = len(d["k"])
    hold = np.arange(n) >= n - max(1, n // 20)             # the last shards' decisions, never trained on
    choice = choices(d, keep, z_by_phase, all_worlds)
    rows = np.arange(n)
    own, chosen = d["cand"][:, 0].astype(np.int64), d["cand"][rows, choice].astype(np.int64)
    switch = choice > 0
    original = symmetry.load_net(net_name, dev).eval()
    for p in original.parameters():
        p.requires_grad_(False)
    student = qmodel.QNet(**original.config)
    student.load_state_dict(original.state_dict())
    student = student.to(dev).train()
    opt = device.adamw(student.parameters(), lr, 0.0, dev)
    scaler = torch.amp.GradScaler(dev.type, enabled=amp is torch.float16)
    encoder, dim = original.encoder, native.feature_dim(original.encoder)
    T = {k: torch.from_numpy(np.ascontiguousarray(v)).to(dev) for k, v in
         (("feat", d["feat"]), ("mask", d["mask"]), ("own", own), ("chosen", chosen),
          ("w", np.where(switch, switch_weight, 1.0).astype(np.float32)))}
    train_rows = torch.from_numpy(np.flatnonzero(~hold)).to(dev)
    steps = steps or max(1, int(epochs * len(train_rows) / batch))
    marks = sorted({max(1, round(steps * (j + 1) / snapshots)) for j in range(snapshots)})
    views: dict = {}

    def forward(net, x):
        if amp is None:
            return net(x)
        with torch.autocast(dev.type, dtype=amp):
            return net(x).float()

    def agreement(net) -> dict:
        """On held-out decisions: share where the net's greedy move is the rule's choice, among the
        decisions the rule changes and among those it leaves."""
        idx = torch.from_numpy(np.flatnonzero(hold)).to(dev)
        hit = []
        with torch.no_grad():
            for i in range(0, len(idx), 65536):
                j = idx[i:i + 65536]
                legal = _unpack(T["mask"][j], A).bool()
                g = lockstep.greedy(forward(net, _unpack(T["feat"][j], dim)).float().masked_fill(~legal, -1e9))
                hit.append((g == T["chosen"][j]).cpu().numpy())
        hit = np.concatenate(hit)
        sw = switch[hold]
        return {"changed": float(hit[sw].mean()) if sw.any() else float("nan"), "kept": float(hit[~sw].mean())}

    log(f"{n:,} labelled decisions ({int(hold.sum()):,} held out); the rule changes {switch.mean():.1%} of them: "
        + ", ".join(f"{name} {switch[d['phase'] == j].mean():.1%} of {int((d['phase'] == j).sum()):,}"
                    for j, name in enumerate(lookahead.PHASES) if (d["phase"] == j).any()))
    result = {"decisions": int(n), "changed_share": float(switch.mean()), "steps": steps, "batch": batch, "lr": lr,
              "switch_weight": switch_weight, "keep": keep, "z_by_phase": list(z_by_phase), "all_worlds": all_worlds,
              "before": agreement(student), "snapshots": {}}
    log(f"before: the network plays the rule's move in {result['before']['changed']:.1%} of the decisions the rule changes "
        f"and {result['before']['kept']:.1%} of those it leaves")
    gen = torch.Generator(device=dev).manual_seed(seed) if dev.type != "mps" else None
    best, t0, losses = None, time.perf_counter(), []
    for step in range(1, steps + 1):
        idx = train_rows[torch.randint(0, len(train_rows), (batch,), device=dev, generator=gen)]
        x, legal = _unpack(T["feat"][idx], dim), _unpack(T["mask"][idx], A).bool()
        with torch.no_grad():
            base = forward(original, x).float().masked_fill(~legal, -1e9)
            t = torch.log_softmax(targets(base, T["own"][idx], T["chosen"][idx]), 1)
        view = int(torch.randint(0, 4, (1,)).item())
        x, legal, t = symmetry.view_of(x, legal, t, view, encoder, views)
        logp = torch.log_softmax(forward(student, x).float().masked_fill(~legal, -1e9), 1)
        kl = (torch.exp(t) * (t - logp)).masked_fill(~legal, 0.0).sum(1)
        w = T["w"][idx]
        loss = (kl * w).sum() / w.sum()
        opt.zero_grad(set_to_none=True)
        if scaler.is_enabled():
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
        else:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(student.parameters(), 1.0)
            opt.step()
        losses.append(float(loss.detach()))
        if step in marks:
            student.eval()
            agree = agreement(student)
            values = evaluate.compare(student, original, dev, eval_base, eval_seed, sooli_play_heuristic=True)
            mean, half = lockstep.interval(values)
            result["snapshots"][str(step)] = {"mean": mean, "ci95": half, **agree, "loss": float(np.mean(losses[-50:]))}
            log(f"step {step:6d} ({step * batch / len(train_rows):.2f} passes, {time.perf_counter() - t0:.0f} s): against the "
                f"original {mean:+.5f} +/- {half:.5f} per deal; plays the rule's move in {agree['changed']:.1%} of the "
                f"decisions it changes, {agree['kept']:.1%} of those it leaves")
            if best is None or mean > best[0]:
                best = (mean, step, {k: v.detach().cpu().clone() for k, v in student.state_dict().items()})
            student.train()
    taught = qmodel.QNet(**original.config)
    taught.load_state_dict(best[2])
    qmodel.save(taught.eval(), out / "taught.pt", step=best[1], taught_from=net_name)
    result["best_step"] = best[1]
    taught = taught.to(dev)
    fresh = evaluate.compare(taught, original, dev, eval_base, eval_seed + 1, sooli_play_heuristic=True)
    result["confirm"] = dict(zip(("mean", "ci95"), lockstep.interval(fresh)))
    log(f"best snapshot (step {best[1]}) on fresh deals: {result['confirm']['mean']:+.5f} +/- {result['confirm']['ci95']:.5f} per deal")
    if match_pairs > 0:
        from tuppi_ai.best import EQUITY
        from tuppi_ai.equity import Equity
        chunk = min(8192, match_pairs)
        env = native.Env(2 * chunk, 1, Equity.load(EQUITY).table, single_deal=True, encoder=encoder)
        env.set_sooli(0, False, True, 0.0)
        native.set_offer_model(None)
        a, b = lockstep.TorchGreedy(taught, dev, encoder), lockstep.TorchGreedy(original, dev, encoder)
        wins = np.concatenate([matches.play_matches(env, a, b, min(chunk, match_pairs - s), eval_seed + 2 + s)["a_wins"]
                               for s in range(0, match_pairs, chunk)])
        share, half = matches.win_rate(wins)
        result["matches"] = {"pairs": match_pairs, "won": share, "ci95": half}
        log(f"complete matches against the original: {share:.1%} +/- {half:.1%} of {2 * match_pairs:,}")
    (out / "fit.json").write_text(json.dumps(result, indent=1))
    return result


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("command", choices=("record", "fit"))
    p.add_argument("--net", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--games", type=int, default=4096, help="record: deals per shard")
    p.add_argument("--worlds", type=int, default=64)
    p.add_argument("--top", type=int, default=4)
    p.add_argument("--min-prob", type=float, default=0.01)
    p.add_argument("--belief", type=int, default=4)
    p.add_argument("--belief-t", type=float, default=2.0)
    p.add_argument("--belief-eps", type=float, default=0.5)
    p.add_argument("--dd", type=int, default=0)
    p.add_argument("--phases", default="0,0,1,1", help="record: label only these phases (bids, tricks 1-4, 5-9, 10-13)")
    p.add_argument("--rollout", default="")
    p.add_argument("--likelihood", default="")
    p.add_argument("--offer-model", default="")
    p.add_argument("--lane-games", type=int, default=65536)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--batch", type=int, default=16384)
    p.add_argument("--lr", type=float, default=2e-5)
    p.add_argument("--switch-weight", type=float, default=4.0)
    p.add_argument("--keep", type=float, default=0.003)
    p.add_argument("--z-by-phase", default="2,2,1,0")
    p.add_argument("--eval-base", type=int, default=16384)
    p.add_argument("--match-pairs", type=int, default=10000)
    p.add_argument("--amp", default="", choices=["", "off", "bf16", "fp16"])
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    tn.use_cpus(a.threads)
    dev = device.pick(a.device)
    if a.command == "record":
        settings = lookahead.Settings(worlds=a.worlds, top=a.top, min_prob=a.min_prob, dd_left=a.dd, belief=a.belief,
                                      belief_t=a.belief_t, belief_eps=a.belief_eps, phases=a.phases)
        n = record(a.out, a.net, settings, a.hours, a.games, a.seed, a.rollout, a.likelihood, dev, a.amp, a.lane_games,
                   a.offer_model)
        print(f"{n} shards in {a.out / 'labels'}")
    else:
        fit(a.out, a.net, dev, epochs=a.epochs, batch=a.batch, lr=a.lr, switch_weight=a.switch_weight, keep=a.keep,
            z_by_phase=tuple(float(v) for v in a.z_by_phase.split(",")), eval_base=a.eval_base,
            match_pairs=a.match_pairs, seed=a.seed, amp_name=a.amp or "off")


if __name__ == "__main__":
    main()
