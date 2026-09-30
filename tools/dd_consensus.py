"""Double-dummy consensus of real information states (docs: the full-information solver packet).

For card-play decisions from self-play of a policy, sample W hidden-card
worlds consistent with the acting seat's observation (the search's uniform
sampler), solve every legal action exactly in every world, and measure:

  C(I)   consensus: the largest share of worlds in which one action is optimal
  H(I)   entropy of the optimal-action distribution (ties split evenly)
  G(I)   clairvoyance gap: E_w[max_a Q(w,a)] - max_a E_w[Q(w,a)], in match
         equity for the acting team (how much choosing per world would add)
  robust whether the policy's action is the robust-DD action argmax_a E_w[Q]

Q(w, a) is the acting team's exact match-equity change of the deal when a is
played in world w and all four seats then play perfectly with full
information. This is a diagnostic, not the imperfect-information value: it
ignores signalling and future information.

    python tools/dd_consensus.py --policy models/sp1_policy_043.pt --states 3000 --worlds 64 --out runs/dd_consensus.json
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_W: dict = {}


def _init():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    _W["eq"] = Equity.load(EQUITY)


def _team_equity(native, world, acting_team: int) -> float:
    """Acting team's equity change of the deal once `world` (in trick play) is finished exactly."""
    d = native.TcDeal.from_buffer_copy(world)
    if d.phase != native.PH_DONE:
        native.lib.tc_finish_with_tricks(C.byref(d), native.dd_team0_tricks(d))
    after = (C.c_uint8 * 2)()
    native.lib.tc_next_score(d.score, d.winner_team, d.points, after)
    d0 = _W["eq"].delta0((d.score[0], d.score[1]), (after[0], after[1]), d.dealer)
    return d0 if acting_team == 0 else -d0


def analyse(job):
    blob, action, worlds, seed = job
    from tuppi_ai import native
    native.lib.tc_finish_with_tricks.argtypes = [C.POINTER(native.TcDeal), C.c_int]
    obs = native.TcObs.from_buffer_copy(blob)
    ids = [a for a in native.legal_obs(obs) if a < 52]
    team = obs.seat & 1
    rng = C.c_uint64(seed)
    Q = np.zeros((worlds, len(ids)))
    t0 = time.perf_counter()
    for w in range(worlds):
        world = native.sample_world(obs, rng)
        if world is None:
            return None
        for j, a in enumerate(ids):
            child = native.TcDeal.from_buffer_copy(world)
            if native.lib.tc_apply(C.byref(child), a) != 0:
                return None
            Q[w, j] = _team_equity(native, child, team)
    best = Q.max(1, keepdims=True)
    opt = np.isclose(Q, best, atol=1e-12)
    share = (opt / opt.sum(1, keepdims=True)).mean(0)          # ties split evenly
    hit = opt.mean(0)                                           # P_w[a in A*(w)]
    mean = Q.mean(0)
    p = share[share > 0]
    return {"tricks_left": 13 - obs.n_played // 4, "mid_trick": obs.n_played % 4 != 0, "contract": int(obs.contract),
            "k": len(ids), "consensus": float(hit.max()), "entropy": float(-(p * np.log(p)).sum()),
            "gap": float(max(best.mean() - mean.max(), 0.0)),
            "robust_is_policy": bool(action in ids and mean[ids.index(action)] >= mean.max() - 1e-9),  # ties count
            "policy_hit": float(hit[ids.index(action)]) if action in ids else None,
            "policy_loss_vs_robust": float(mean.max() - mean[ids.index(action)]) if action in ids else None,
            "seconds": time.perf_counter() - t0}


def collect_states(policy: str, n: int, max_left: int, seed: int):
    """(observation bytes, policy action) for card-play decisions with <= max_left tricks left."""
    import torch
    from tuppi_ai import model as qmodel
    from tuppi_ai import native
    torch.set_num_threads(1)
    net = qmodel.load(policy, "cpu")
    mlp = native.Mlp(net)
    env = native.Env(16384, seed, None, single_deal=True, encoder=net.encoder)
    env.set_sooli(0, False, False, 0.0)
    rng = C.c_uint64(seed)
    out = []
    while len(out) < n:
        states, m = native.selfplay_states(env, mlp, 16384, 3, rng, 0.05, 0.0, 16384 * 8)
        feat, mask = native.encode_states(states, m, net.encoder)
        q = mlp.forward(feat)
        act = np.where(mask == 1, q, -np.inf).argmax(1)
        for i in range(m):
            d = states[i]
            left = 13 - d.n_played // 4
            if d.phase == native.PH_PLAY and 2 <= left <= max_left and mask[i].sum() > 1:
                out.append((bytes(native.observe(d, d.cur)), int(act[i])))
    rng2 = np.random.default_rng(seed)
    rng2.shuffle(out)
    return out[:n]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", required=True)
    p.add_argument("--states", type=int, default=3000)
    p.add_argument("--worlds", type=int, default=64)
    p.add_argument("--max-left", type=int, default=9)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=31)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    states = collect_states(a.policy, a.states, a.max_left, a.seed)
    jobs = [(b, act, a.worlds, a.seed * 100003 + i) for i, (b, act) in enumerate(states)]
    t0 = time.time()
    with ProcessPoolExecutor(a.workers, initializer=_init) as pool:
        rows = [r for r in pool.map(analyse, jobs, chunksize=8) if r is not None]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({"policy": a.policy, "worlds": a.worlds, "rows": rows}))
    print(json.dumps({"states": len(rows), "seconds": round(time.time() - t0, 1)}))
    report(rows)


def report(rows):
    import collections
    by = collections.defaultdict(list)
    for r in rows:
        by[("RAMI" if r["contract"] == 1 else "NOLO", r["tricks_left"])].append(r)
    print(f"{'contract':8s} {'left':>4s} {'n':>5s} {'consensus':>9s} {'C>=0.9':>7s} {'C<0.5':>6s} {'entropy':>7s} {'gap (eq)':>9s} {'policy=robust':>13s} {'policy loss':>11s}")
    for key in sorted(by):
        g = by[key]
        c = np.array([r["consensus"] for r in g])
        print(f"{key[0]:8s} {key[1]:4d} {len(g):5d} {c.mean():9.3f} {np.mean(c >= 0.9):7.1%} {np.mean(c < 0.5):6.1%} "
              f"{np.mean([r['entropy'] for r in g]):7.3f} {np.mean([r['gap'] for r in g]):9.5f} "
              f"{np.mean([r['robust_is_policy'] for r in g]):13.1%} {np.mean([r['policy_loss_vs_robust'] for r in g]):11.5f}")


if __name__ == "__main__":
    main()
