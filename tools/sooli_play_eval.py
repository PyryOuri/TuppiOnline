"""Sooli trick play on a bank of positions (tools/sooli_bank.py): survival rates.

Every position is played from the first sooli lead with one policy for the
soolaaja and one for the RAMI pair. Policies:

    heur                                 tuppi_sooli_policy.c
    search[:w=64][:b=1][:l=0][:ph=0]     native search: w worlds, belief mode b
                                         (tc_sample_world_sooli), tilt l, rollouts
                                         finished by the heuristics if ph=1, else
                                         by the solver; ties go to the heuristic
    pi                                   perfect information (reference only)
    knows[:w=32]                         RAMI only: knows the soolaaja's hand but
                                         not the other RAMI hand (reference only)

    python tools/sooli_play_eval.py --bank runs/sooli/bank_v1.pkl --s heur --rami heur search:b=5:l=0.17
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import pickle
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

_W: dict = {}


def _opts(spec: str) -> tuple[str, dict]:
    name, *rest = spec.split(":")
    return name, dict(p.split("=") for p in rest)


def _init(max_worlds: int) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import model as qmodel
    from tuppi_ai import native
    from tuppi_ai.best import EQUITY, ROLLOUT
    from tuppi_ai.equity import Equity

    net = qmodel.load(ROLLOUT, "cpu")
    _W.update(mlp=native.Mlp(net),
              env=native.Env(max_worlds * 14, 1, Equity.load(EQUITY).table, single_deal=True, encoder=net.encoder))


def _move(d, spec, st, rng):
    from tuppi_ai import native
    legal = native.legal(d)
    if len(legal) == 1:
        return legal[0]
    obs = native.observe(d, d.cur)
    h = native.sooli_policy(obs, st)
    name, o = _opts(spec)
    if name == "heur":
        return h
    order = [h] + [a for a in legal if a != h]
    rami = d.cur != d.soolaaja
    if name == "pi":
        v = native.sooli_move_values(d, order)
        return order[int(np.argmin(v) if rami else np.argmax(v))]
    if name == "knows":
        me, other, partner = d.cur, (d.cur + 2) % 4, (d.soolaaja + 2) % 4
        voids = set()
        for t in range(0, d.n_played, 3):
            led = d.play_card[t] // 13
            for i in range(t, min(t + 3, d.n_played)):
                if d.play_seat[i] == other and d.play_card[i] // 13 != led:
                    voids.add(led)
        pool = d.hand[other] | d.hand[partner]
        ok = [c for c in range(52) if pool >> c & 1 and c // 13 not in voids]
        size = bin(d.hand[other]).count("1")
        total = np.zeros(len(order))
        for _ in range(int(o.get("w", 32))):
            m = sum(1 << c for c in rng.sample(ok, size))
            w = native.TcDeal.from_buffer_copy(d)
            w.hand[other], w.hand[partner] = m, pool & ~m
            total += native.sooli_move_values(w, order)
        return order[int(np.argmin(total))]
    env = _W["env"]
    env.set_sooli(int(o.get("b", 1)), False, bool(int(o.get("ph", 0))), float(o.get("l", 0.0)))
    v = native.search_values(env, _W["mlp"], obs, order, int(o.get("w", 64)), 6, st)
    # values are for the observer's team: the soolaaja maximises, and so does the RAMI pair
    return order[int(np.argmax(v))]


def play(args) -> list[int]:
    from tuppi_ai import native
    rows, s_spec, r_spec, seed = args
    out = []
    for row in rows:
        d = native.TcDeal.from_buffer_copy(row["start"])
        st = C.c_uint64(row["index"] * 31 + seed)
        rng = random.Random(row["index"] * 31 + seed)
        while d.phase == native.PH_SOOLI_PLAY:
            spec = s_spec if d.cur == d.soolaaja else r_spec
            native.lib.tc_apply(d, _move(d, spec, st, rng))
        out.append(int(d.sooli_won))
    return out


def evaluate(bank: list, s_spec: str, r_spec: str, workers: int, seed: int = 0) -> list[int]:
    worlds = max(int(_opts(x)[1].get("w", 64)) for x in (s_spec, r_spec))
    parts = [bank[i::workers * 4] for i in range(workers * 4)]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(worlds,)) as pool:
        res = list(pool.map(play, [(p, s_spec, r_spec, seed) for p in parts]))
    out = [0] * len(bank)
    for i, r in enumerate(res):
        for j, v in enumerate(r):
            out[i + j * workers * 4] = v
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--s", nargs="+", default=["heur"])
    parser.add_argument("--rami", nargs="+", default=["heur"])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    bank = pickle.loads(args.bank.read_bytes())
    if args.limit:
        bank = bank[:args.limit]
    results = {}
    for s_spec in args.s:
        for r_spec in args.rami:
            alive = evaluate(bank, s_spec, r_spec, args.workers)
            results[f"{s_spec} | {r_spec}"] = alive
            p = float(np.mean(alive))
            print(f"S {s_spec:28s} RAMI {r_spec:28s} survival {p:.3f} +- {1.96 * (p * (1 - p) / len(alive)) ** 0.5:.3f}",
                  flush=True)
    if args.out:
        args.out.write_text(json.dumps(results))


if __name__ == "__main__":
    main()
