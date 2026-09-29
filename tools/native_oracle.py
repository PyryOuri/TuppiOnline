"""Exact-output oracles for native speed work (docs/EFFICIENCY_PLAN.md, E0).

`dump` builds deterministic inputs with the rules core (unchanged by the
speed work) and records the exact outputs of one component of whichever
`tuppi_ai` is on the path. Run it once per source tree (separate processes)
and `diff` the two files: every output must match bit for bit.

    PYTHONPATH=/path/to/baseline python tools/native_oracle.py dump --out a.npz
    PYTHONPATH=. python tools/native_oracle.py dump --out b.npz
    python tools/native_oracle.py diff a.npz b.npz

Components: dd (endgame solver, both polarities, 1-7 tricks left, mid-trick
too), sooli (sooli solver on offer-like positions, fresh and part-played),
offer (the sooli offer heuristic: decision and rng state after it),
sampler (world draws and the rng state after them, every phase and sooli
belief mode), mlp (native rollout-network logits on real feature rows).
"""

from __future__ import annotations

import argparse
import ctypes as C
import sys
import time

import numpy as np


def _deck(rng) -> list[int]:
    cards = rng.permutation(52)
    hands = [0, 0, 0, 0]
    for i, c in enumerate(cards):
        hands[i // 13] |= 1 << int(c)
    return hands


def _random_legal(native, deal, rng) -> int:
    acts = native.legal(deal)
    return int(acts[rng.integers(len(acts))])


def _to_play(native, rng, contract: int, ruleset: int = 1):
    """A fresh deal in trick play (NOLO: four NOLO shows; RAMI: the forehand declares)."""
    while True:
        deal = native.new_deal(_deck(rng), int(rng.integers(4)), ruleset=ruleset)
        acts = native.legal(deal)
        want = [a for a in acts if (a - 52) // 52 == contract]
        if not want:
            continue
        if contract == native.RAMI:
            native.lib.tc_apply(C.byref(deal), int(want[rng.integers(len(want))]))
            return deal
        for _ in range(4):
            acts = [a for a in native.legal(deal) if (a - 52) // 52 == native.NOLO]
            native.lib.tc_apply(C.byref(deal), int(acts[rng.integers(len(acts))]))
        return deal


def dump_dd(native, n: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    deals = []
    for i in range(n):
        deal = _to_play(native, rng, native.NOLO if i % 2 else native.RAMI)
        left = int(rng.integers(1, 8))
        extra = int(rng.integers(4))
        target = 52 - 4 * left + extra if left > 1 or extra == 0 else 48
        while deal.n_played < target:
            native.lib.tc_apply(C.byref(deal), _random_legal(native, deal, rng))
        deals.append(deal)
    t = time.perf_counter()
    out = np.array([native.dd_team0_tricks(d) for d in deals], dtype=np.int32)
    return {"dd": out, "dd_seconds": np.array([time.perf_counter() - t])}


def _sooli_play_deal(native, rng):
    """A v2 deal at the start of sooli play whose soolaaja hand passes the offer prefilter."""
    while True:
        deal = native.new_deal(_deck(rng), int(rng.integers(4)), ruleset=2)
        rami = [a for a in native.legal(deal) if a >= 104]
        if not rami:
            continue
        native.lib.tc_apply(C.byref(deal), int(rami[rng.integers(len(rami))]))
        # First or second defender plays sooli if its hand passes the prefilter.
        accepted = False
        for _ in range(2):
            if native.lib.tc_sooli_offer_prefilter(C.c_uint64(deal.hand[deal.cur])) and not accepted:
                native.lib.tc_apply(C.byref(deal), native.ACT_SOOLI_ACCEPT)
                accepted = True
                break
            native.lib.tc_apply(C.byref(deal), native.ACT_SOOLI_DECLINE)
        if not accepted:
            continue
        r = C.c_uint64(int(rng.integers(1 << 62)))
        for _ in range(2):  # the heuristic exchange
            obs = native.observe(deal, deal.cur)
            native.lib.tc_apply(C.byref(deal), native.sooli_policy(obs, r))
        return deal


def dump_sooli(native, n: int, seed: int) -> dict:
    rng = np.random.default_rng(seed + 1)
    deals = []
    for i in range(n):
        deal = _sooli_play_deal(native, rng)
        steps = 0 if i % 2 == 0 else int(rng.integers(1, 12))
        for _ in range(steps):
            if deal.phase != native.PH_SOOLI_PLAY:
                break
            native.lib.tc_apply(C.byref(deal), _random_legal(native, deal, rng))
        deals.append(deal)
    t = time.perf_counter()
    out = np.array([native.sooli_solve(d) for d in deals], dtype=np.int32)
    return {"sooli": out, "sooli_seconds": np.array([time.perf_counter() - t])}


def dump_offer(native, n: int, seed: int) -> dict:
    """The sooli offer heuristic (sampled worlds + exact solves) on defenders whose
    hand passes its prefilter: the decision and the rng state after it."""
    rng = np.random.default_rng(seed + 4)
    obs = []
    while len(obs) < n:
        deal = native.new_deal(_deck(rng), int(rng.integers(4)), ruleset=int(rng.choice([2, 3])))
        for _ in range(int(rng.integers(4))):  # some NOLO bids first
            nolo = [a for a in native.legal(deal) if 52 <= a < 104]
            native.lib.tc_apply(C.byref(deal), int(nolo[rng.integers(len(nolo))]))
        rami = [a for a in native.legal(deal) if a >= 104]
        if not rami:
            continue
        native.lib.tc_apply(C.byref(deal), int(rami[rng.integers(len(rami))]))
        if rng.integers(2):
            native.lib.tc_apply(C.byref(deal), native.ACT_SOOLI_DECLINE)
        if native.lib.tc_sooli_offer_prefilter(C.c_uint64(deal.hand[deal.cur])):
            obs.append(native.observe(deal, deal.cur))
    out, states = [], []
    t = time.perf_counter()
    for i, o in enumerate(obs):
        r = C.c_uint64((seed * 7_654_321 + i * 104_729) & (2**64 - 1))
        out.append(native.sooli_policy(o, r))
        states.append(r.value)
    return {"offer": np.array(out, dtype=np.int32), "offer_rng": np.array(states, dtype=np.uint64),
            "offer_seconds": np.array([time.perf_counter() - t])}


def _observations(native, n: int, rng) -> list:
    """Observations from every phase: v3 showing (locked), v1/v3 play, sooli phases."""
    obs = []
    while len(obs) < n:
        kind = len(obs) % 4
        if kind == 0:  # v3 showing: 0-3 earlier NOLO bids
            deal = native.new_deal(_deck(rng), int(rng.integers(4)), ruleset=3)
            for _ in range(int(rng.integers(4))):
                acts = [a for a in native.legal(deal) if 52 <= a < 104]
                native.lib.tc_apply(C.byref(deal), int(acts[rng.integers(len(acts))]))
            obs.append(native.observe(deal, deal.cur))
        elif kind == 1:  # trick play, some tricks in, random observer
            deal = _to_play(native, rng, int(rng.integers(2)), ruleset=3 if rng.integers(2) else 1)
            if deal.phase != native.PH_PLAY:  # a v3 RAMI: both defenders decline
                native.lib.tc_apply(C.byref(deal), native.ACT_SOOLI_DECLINE)
                native.lib.tc_apply(C.byref(deal), native.ACT_SOOLI_DECLINE)
            for _ in range(int(rng.integers(0, 40))):
                native.lib.tc_apply(C.byref(deal), _random_legal(native, deal, rng))
            obs.append(native.observe(deal, int(rng.integers(4))))
        else:  # sooli: return (partner) or play (any observer but the dead hand)
            deal = _sooli_play_deal(native, rng)
            for _ in range(int(rng.integers(0, 10))):
                if deal.phase != native.PH_SOOLI_PLAY:
                    break
                native.lib.tc_apply(C.byref(deal), _random_legal(native, deal, rng))
            if deal.phase != native.PH_SOOLI_PLAY:
                continue
            partner = (deal.soolaaja + 2) & 3
            seat = int(rng.choice([s for s in range(4) if s != partner]))
            obs.append(native.observe(deal, seat))
    return obs


def dump_sampler(native, n: int, seed: int) -> dict:
    rng = np.random.default_rng(seed + 2)
    obs = _observations(native, n, rng)
    modes = [(0, 0.0), (1, 0.0), (16, 0.3), (17, 0.3), (5, 0.3), (9, 0.0)]
    hands, states, codes = [], [], []
    t = time.perf_counter()
    for i, o in enumerate(obs):
        for mode, lam in modes:
            r = C.c_uint64((seed * 1_000_003 + i * 7919 + mode) & (2**64 - 1))
            for _ in range(8):
                world = native.TcDeal()
                rc = native.lib.tc_sample_world_sooli(C.byref(o), C.byref(r), C.byref(world), mode, lam)
                codes.append(rc)
                hands.append(list(world.hand) + [world.cur, world.phase] + list(bytes(world.show_card)))
            states.append(r.value)
    return {"sampler_hands": np.array(hands, dtype=np.uint64), "sampler_rc": np.array(codes, dtype=np.int32),
            "sampler_rng": np.array(states, dtype=np.uint64),
            "sampler_seconds": np.array([time.perf_counter() - t])}


def dump_mlp(native, n: int, seed: int) -> dict:
    from pathlib import Path

    from tuppi_ai import model as qmodel

    root = Path(native.__file__).resolve().parents[1]
    net = qmodel.load(root / "models" / "rollout_clone_small.pt", "cpu")
    mlp = native.Mlp(net)
    env = native.Env(512, seed, None, encoder=net.encoder)
    rng = np.random.default_rng(seed + 3)
    rows = []
    for step in range(60):
        f, mask, _, _ = env.observe()
        if step % 4 == 1:
            rows.append(f[mask.any(1)].copy())
        acts = np.array([rng.choice(np.flatnonzero(m)) if m.any() else 0 for m in mask], dtype=np.int32)
        env.step(acts)
    x = np.concatenate(rows)[:n]
    out = []
    t = time.perf_counter()
    for size in (1, 7, 32, 128):  # batch sizes the search uses, plus odd ones
        for i in range(0, len(x), size):
            out.append(mlp.forward(x[i:i + size]))
    return {"mlp": np.concatenate(out), "mlp_seconds": np.array([time.perf_counter() - t])}


DUMPS = {"dd": dump_dd, "sooli": dump_sooli, "offer": dump_offer, "sampler": dump_sampler, "mlp": dump_mlp}
SIZES = {"dd": 3000, "sooli": 3000, "offer": 1500, "sampler": 400, "mlp": 6000}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--out", required=True)
    d.add_argument("--kinds", default="dd,sooli,offer,sampler,mlp")
    d.add_argument("--seed", type=int, default=20260929)
    d.add_argument("--scale", type=float, default=1.0)
    f = sub.add_parser("diff")
    f.add_argument("a")
    f.add_argument("b")
    args = p.parse_args()
    if args.cmd == "dump":
        from tuppi_ai import native
        result = {}
        for kind in args.kinds.split(","):
            result.update(DUMPS[kind](native, max(1, int(SIZES[kind] * args.scale)), args.seed))
            print(f"{kind}: {float(result[kind + '_seconds'][0]):.3f}s", file=sys.stderr)
        np.savez(args.out, **result)
    else:
        a, b = np.load(args.a), np.load(args.b)
        keys = sorted(k for k in a.files if not k.endswith("_seconds"))
        if not keys:
            sys.exit("nothing to compare")
        bad = 0
        for k in keys:
            if k not in b.files:
                print(f"{k}: missing in b"); bad += 1; continue
            same = a[k].shape == b[k].shape and a[k].tobytes() == b[k].tobytes()
            print(f"{k}: {'identical' if same else 'DIFFERENT'} ({a[k].size} values)")
            bad += not same
        for k in sorted(x for x in a.files if x.endswith("_seconds") and x in b.files):
            print(f"{k}: a {float(a[k][0]):.3f}s  b {float(b[k][0]):.3f}s")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
