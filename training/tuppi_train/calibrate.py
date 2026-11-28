"""What are the look-ahead's estimates really worth, decision by decision?

A match tells how much a look-ahead gains in total. This records, at the plain
network's own decisions, what the look-ahead's model says about every candidate
(its value in each sampled world) and what the candidate is really worth: one
play-out from the true deal with the network itself on all four seats, an
unbiased sample of the value of deviating once. Any decision rule can then be
scored offline by the real values of the moves it would choose, on the same
decisions, and the model's claims can be compared with reality by phase and by
confidence.

    python -m tuppi_train.calibrate record --net <net> --out <dir> --base 1280 --worlds 64 \\
        [--rollout vrpo1_actor_0504.pt --dd 6] [--belief 4 --likelihood <net>]
    python -m tuppi_train.calibrate report --out <dir>

First use (VRPO4, 64 uniform worlds, VRPO1 play-outs, solver tail of 6; 130,000
decisions on the CPU): where the current rule changes a move the model claims
+0.010 on average and reality gives +0.0025, a quarter (a tenth in the bidding
and the first four tricks, a half in the last four). Model gains below about 1.5
standard errors are worth nothing in reality. So the look-ahead is limited by
how faithful its model is (which worlds, which play-out policy), not by the
number of worlds, and the rule's threshold of 2 standard errors is about right.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
import warnings
from pathlib import Path

import numpy as np

from . import device, lockstep, lookahead, symmetry, tn
from tuppi_ai import native


def record(out: Path, net_name: str, settings: "lookahead.Settings", base: int = 1280, chunk: int = 32,
           seed: int = 4000, rollout_name: str = "", likelihood_name: str = "", dev=None, amp_name: str = "",
           lane_games: int = 65536, offer_model_path: str = "", log=print) -> None:
    """Parts of `chunk` base deals in `out` (resumable): the trace of a look-ahead that never changes
    a move (so the deals are the plain network's), plus `real` [n, top]: each candidate's value in
    the true deal, the network on all seats, no solver tail."""
    from . import offer
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dev = dev or device.pick()
    device.setup(dev)
    amp_name = amp_name or ("fp16" if dev.type == "cuda" else "off")
    config = {"net": net_name, "rollout": rollout_name or net_name, "likelihood": likelihood_name,
              "settings": {**vars(settings), "keep": None, "keep_show": None}, "chunk": chunk, "seed": seed, "amp": amp_name}
    cfg = out / "config.json"
    if cfg.exists():
        old = json.loads(cfg.read_text())
        old["settings"] = {**config["settings"], **old["settings"], "z": settings.z, "all_worlds": settings.all_worlds,
                           "z_by_phase": settings.z_by_phase}     # the rule does not enter a recording
        old["settings"].setdefault("phases", "")
        if old != config:
            raise SystemExit(f"{out} holds a recording with other settings; use another --out")
    cfg.write_text(json.dumps(config, indent=1))
    native.set_showing_fix(True)
    native.set_offer_model(None)
    table = Equity.load(EQUITY).table
    net = symmetry.load_net(net_name, dev)
    env = native.Env(8 * chunk, 1, table, single_deal=True, encoder=net.encoder)
    env.set_sooli(0, False, True, 0.0)
    never = lookahead.Settings(**{**vars(settings), "keep": 1e9, "keep_show": 1e9})
    offer_model = offer.load_native(offer_model_path) if offer_model_path else None
    look = lookahead.build(net, dev, never, env, table, symmetry.load_net(rollout_name, dev) if rollout_name else None,
                           device.AMP[amp_name], 2, lane_games, True, offer_model,
                           likelihood_net=symmetry.load_net(likelihood_name, dev) if likelihood_name else None)
    plain = lockstep.TorchGreedy(net, dev, net.encoder)
    truth = lookahead.Searcher(table, lockstep.TorchGreedy(net, dev, net.encoder, amp=device.AMP[amp_name]),
                               net.encoder, 2, lane_games, True, 0, offer_model)
    for c in range((base + chunk - 1) // chunk):
        path = out / f"part_{c:04d}.npz"
        if path.exists():
            continue
        look.reset(seed + 7919 * c)
        look.trace = []
        t0 = time.perf_counter()
        values = lockstep.duplicate_eval(env, look, plain, chunk, 3, C.c_uint64(seed + c), net.encoder)
        assert not values.any()
        data = {k: np.concatenate([t[k] for t in look.trace]) for k in look.trace[0] if k not in ("state", "feat", "mask")}
        states = np.ascontiguousarray(np.concatenate([t["state"] for t in look.trace]))
        cand = np.zeros((len(states), lookahead.MAX_K), np.int32)
        cand[:, :data["cand"].shape[1]] = data["cand"]
        seeds = np.random.default_rng(seed + 104729 * c).integers(1, 2**63, len(states), dtype=np.uint64)
        data["real"] = truth.play(states, 1, cand, data["k"], seeds)[:, 0, :data["cand"].shape[1]].astype(np.float32)
        tmp = path.with_name(path.name + ".tmp.npz")
        np.savez_compressed(tmp, **data, games=8 * chunk)
        tmp.replace(path)
        log(f"part {c}: {len(states):,} decisions in {time.perf_counter() - t0:.0f} s")


def load(out: Path) -> dict:
    parts = [np.load(f) for f in sorted(Path(out).glob("part_*.npz"))]
    if not parts:
        raise SystemExit(f"no parts in {out}")
    d = {k: np.concatenate([p[k] for p in parts]) for k in ("q", "k", "logp", "phase", "real", "effective")}
    d["part"] = np.concatenate([np.full(len(p["k"]), i) for i, p in enumerate(parts)])
    d["games"] = np.array([int(p["games"]) for p in parts])
    return d


def quantities(d: dict, worlds: int = 0) -> dict:
    """Per (decision, candidate): the model's mean gain over the anchor `m`, its standard error
    `se`, `z` = m / se, the real gain `r`; `alt` marks the alternatives (not the anchor, not padding)."""
    q = d["q"].astype(np.float64)
    if worlds:
        q = q[:, :worlds]
    n, w, top = q.shape
    valid = np.arange(top)[None, :] < d["k"][:, None]
    alt = valid.copy()
    alt[:, 0] = False
    diff = q - q[:, :, :1]
    m, se = diff.mean(1), diff.std(1, ddof=1) / np.sqrt(w)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(se > 0, m / se, np.where(m > 0, 99.0, np.where(m < 0, -99.0, 0.0)))
    real = d["real"].astype(np.float64)
    # as the look-ahead's default counts them after resampling: fewer independent worlds
    se_eff = se * np.sqrt(w / np.minimum(d["effective"].astype(np.float64), w))[:, None]
    with np.errstate(divide="ignore", invalid="ignore"):
        z_eff = np.where(se_eff > 0, m / se_eff, z)
    return {"m": m, "se": se, "z": z, "z_effective": z_eff, "r": real - real[:, :1], "alt": alt, "valid": valid, "worlds": w,
            "gap": (d["logp"][:, :1] - d["logp"]).astype(np.float64)}


def choose(score: np.ndarray, ok: np.ndarray, valid: np.ndarray) -> np.ndarray:
    """Per decision the candidate with the largest score among those allowed, 0 (the anchor) if none."""
    s = np.where(ok & valid, score, -np.inf)
    s[:, 0] = -np.inf
    best = s.argmax(1)
    return np.where(np.isfinite(s[np.arange(len(s)), best]), best, 0)


def rule_value(d: dict, x: dict, choice: np.ndarray) -> dict:
    """Real gain per game of the searching pair for the given choices, with a 95% half-width from
    the spread over the parts; what the model claims; the share of decisions changed."""
    rows = np.arange(len(choice))
    per_part = np.bincount(d["part"], x["r"][rows, choice], len(d["games"])) / d["games"]
    return {"real": float(per_part.mean()), "ci95": float(1.96 * per_part.std(ddof=1) / np.sqrt(len(per_part))),
            "claimed": float(x["m"][rows, choice].sum() / d["games"].sum()), "changed": float((choice > 0).mean()),
            "per_part": per_part}


def report(out: Path, worlds: int = 0, log=print) -> dict:
    warnings.simplefilter("ignore")
    d = load(out)
    x = quantities(d, worlds)
    m, z, r, alt, phase = x["m"], x["z"], x["r"], x["alt"], d["phase"]
    games = d["games"].sum()
    log(f"{Path(out).name}: {len(m):,} searched decisions in {games:,} games, {x['worlds']} worlds, {alt.sum():,} alternatives")
    result = {"decisions": int(len(m)), "games": int(games), "bins": {}, "rules": {}}

    def row(label, sel):
        n = int(sel.sum())
        if n < 200:
            return
        real, half, model = r[sel].mean(), 1.96 * r[sel].std() / np.sqrt(n), m[sel].mean()
        result["bins"][label] = {"n": n, "model": float(model), "real": float(real), "ci95": float(half)}
        ratio = f"{real / model:+.2f}" if abs(model) > 1e-6 else "    "
        log(f"  {label:<28} {n:>8,}  model {model:+.5f}   real {real:+.5f} +/- {half:.5f}   real/model {ratio}")

    log("\nalternatives by the model's confidence (gain / standard error):")
    edges = [-99.5, -2, -1, -0.25, 0.25, 0.5, 1, 1.5, 2, 2.5, 3, 4, 99.5]
    for lo, hi in zip(edges[:-1], edges[1:]):
        row(f"z {lo} to {hi}", alt & (z > lo) & (z <= hi))
    log("\nwhere the current rule acts (model gain above 0.003, z above 2), by phase:")
    for j, name in enumerate(lookahead.PHASES):
        row(name, alt & (m > 0.003) & (z > 2) & (phase == j)[:, None])
    log(f"\nrules decided from the {x['worlds']} model worlds, scored by reality (per game, searching pair). 'current' counts")
    log("repeated worlds once (the default with play inference; the same as 'all worlds' without it):")
    base = None
    ze = x["z_effective"]
    by_phase = np.array([2.0, 2.0, 1.0, 0.0])[phase][:, None]
    rules = [("z 2 (current)", (m > 0.003) & (ze > 2)), ("z 1", (m > 0.003) & (ze > 1)),
             ("all worlds, z 3", (m > 0.003) & (z > 3)), ("all worlds, z 2", (m > 0.003) & (z > 2)),
             ("all worlds, z 1.5", (m > 0.003) & (z > 1.5)), ("all worlds, z 1", (m > 0.003) & (z > 1)),
             ("all worlds, z 0 (argmax and margin)", m > 0.003), ("all worlds, z 2,2,1,0 by phase", (m > 0.003) & (z > by_phase)),
             ("all worlds, margin 0.01, z 2", (m > 0.01) & (z > 2)),
             ("all worlds, z 2, card play only", (m > 0.003) & (z > 2) & (phase > 0)[:, None]),
             ("all worlds, z 2, from trick 5", (m > 0.003) & (z > 2) & (phase > 1)[:, None])]
    for name, ok in rules:
        v = rule_value(d, x, choose(m, ok, x["valid"]))
        if "current" in name:
            base = v["per_part"]
        versus = ""
        if base is not None and "current" not in name:
            diff = v["per_part"] - base
            versus = f"   against the current rule {diff.mean():+.5f} +/- {1.96 * diff.std(ddof=1) / np.sqrt(len(diff)):.5f}"
        result["rules"][name] = {k: v[k] for k in ("real", "ci95", "claimed", "changed")}
        log(f"  {name:<36} real {v['real']:+.5f} +/- {v['ci95']:.5f}   model claims {v['claimed']:+.5f}   changes "
            f"{v['changed']:5.1%}{versus}")
    return result


RULES = {"z 2, repeated worlds once": lambda x, ph: (x["m"] > 0.003) & (x["z_effective"] > 2),
         "all worlds, z 2": lambda x, ph: (x["m"] > 0.003) & (x["z"] > 2),
         "all worlds, z 1": lambda x, ph: (x["m"] > 0.003) & (x["z"] > 1),
         "all worlds, z 2,2,1,0": lambda x, ph: (x["m"] > 0.003) & (x["z"] > np.array([2.0, 2.0, 1.0, 0.0])[ph][:, None])}


def compare(folders: list, log=print) -> dict:
    """Recordings of the same decisions under different models (same network, seed and size): how
    much of each model's claims is real by phase, and what each rule is really worth, with the
    difference to the first recording (paired: the decisions and their real values are the same)."""
    warnings.simplefilter("ignore")
    data = [load(f) for f in folders]
    n = min(len(d["k"]) for d in data)
    parts = min(len(d["games"]) for d in data)
    keep = [d["part"] < parts for d in data]
    first_real = data[0]["real"][keep[0]]
    out = {}
    for f, d, kp in zip(folders, data, keep):
        if d["real"][kp].shape != first_real.shape or not np.array_equal(d["real"][kp], first_real):
            raise SystemExit(f"{f} does not hold the same decisions as {folders[0]} (another network, seed or size)")
    log(f"{int(keep[0].sum()):,} decisions in {int(data[0]['games'][:parts].sum()):,} games, common to {len(folders)} recordings\n")
    base = {}
    for f, d, kp in zip(folders, data, keep):
        d = {k: (v[kp] if k not in ("games",) else v[:parts]) for k, v in d.items()}
        x = quantities(d)
        name = Path(f).name
        ratio = []
        for j in range(len(lookahead.PHASES)):
            sel = x["alt"] & (x["m"] > 0.003) & (x["z"] > 2) & (d["phase"] == j)[:, None]
            ratio.append(x["r"][sel].mean() / x["m"][sel].mean() if sel.sum() > 100 else float("nan"))
        log(f"{name}: share of the model's claims that is real, by phase " + ", ".join(
            f"{p} {r:.0%}" for p, r in zip(lookahead.PHASES, ratio)))
        out[name] = {"real_share": ratio, "rules": {}}
        for rule, ok in RULES.items():
            v = rule_value(d, x, choose(x["m"], ok(x, d["phase"]), x["valid"]))
            versus = ""
            if rule in base:
                diff = v["per_part"] - base[rule]
                versus = f"   against {Path(folders[0]).name} {diff.mean():+.5f} +/- {1.96 * diff.std(ddof=1) / np.sqrt(len(diff)):.5f}"
            else:
                base[rule] = v["per_part"]
            out[name]["rules"][rule] = {k: v[k] for k in ("real", "ci95", "claimed", "changed")}
            log(f"   {rule:<28} real {v['real']:+.5f} +/- {v['ci95']:.5f}   changes {v['changed']:5.1%}{versus}")
    return out


def main(argv=None) -> None:
    d = lookahead.Settings()
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("command", choices=("record", "report", "compare"))
    p.add_argument("--with", dest="others", default="", help="compare: further recordings, comma-separated folders")
    p.add_argument("--belief-t", type=float, default=d.belief_t)
    p.add_argument("--belief-eps", type=float, default=d.belief_eps)
    p.add_argument("--seed", type=int, default=4000, help="record: the same seed gives the same decisions")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--net", default="")
    p.add_argument("--base", type=int, default=1280)
    p.add_argument("--chunk", type=int, default=32)
    p.add_argument("--worlds", type=int, default=d.worlds)
    p.add_argument("--top", type=int, default=d.top)
    p.add_argument("--min-prob", type=float, default=d.min_prob)
    p.add_argument("--dd", type=int, default=0)
    p.add_argument("--belief", type=int, default=0)
    p.add_argument("--rollout", default="")
    p.add_argument("--likelihood", default="")
    p.add_argument("--offer-model", default="")
    p.add_argument("--amp", default="", choices=["", "off", "bf16", "fp16"])
    p.add_argument("--lane-games", type=int, default=65536)
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    if a.command == "record":
        if not a.net:
            p.error("record needs --net")
        tn.use_cpus(a.threads)
        settings = lookahead.Settings(worlds=a.worlds, top=a.top, min_prob=a.min_prob, dd_left=a.dd, belief=a.belief,
                                      belief_t=a.belief_t, belief_eps=a.belief_eps)
        record(a.out, a.net, settings, a.base, a.chunk, seed=a.seed, rollout_name=a.rollout, likelihood_name=a.likelihood,
               dev=device.pick(a.device), amp_name=a.amp, lane_games=a.lane_games, offer_model_path=a.offer_model)
    if a.command == "compare":
        compare([a.out] + [Path(x.strip()) for x in a.others.split(",") if x.strip()])
        return
    result = report(a.out, a.worlds if a.command == "report" and a.worlds != d.worlds else 0)
    (a.out / "report.json").write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
