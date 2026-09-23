"""Bank of realistic sooli positions (project_target_v2), for evaluating sooli play.

Random deals (random starting score) are shown by the rollout clone. At every
sooli offer whose hand passes the static prefilter, the offer is decided as
the best agent decides it (search, sooli play in the rollouts by the
heuristics, margin `--margin`); an accepted sooli is exchanged as the best
agent exchanges (searched give, heuristic return) and saved at the first
sooli lead, together with the realised offer-time state.

    python tools/sooli_bank.py --deals 20000 --out runs/sooli/bank.pkl
"""

from __future__ import annotations

import argparse
import ctypes as C
import pickle
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

_W: dict = {}


def _init(worlds: int, margin: float) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import model as qmodel
    from tuppi_ai import native
    from tuppi_ai.best import EQUITY, ROLLOUT
    from tuppi_ai.equity import Equity

    net = qmodel.load(ROLLOUT, "cpu")
    _W.update(net=net, mlp=native.Mlp(net), worlds=worlds, margin=margin,
              env=native.Env(worlds * 14, 1, Equity.load(EQUITY).table, single_deal=True, encoder=net.encoder),
              feat=np.zeros((1, native.feature_dim(net.encoder)), dtype=np.uint8))


def _greedy(d):
    from tuppi_ai import native
    native.encode(native.observe(d, d.cur), _W["feat"][0], _W["net"].encoder)
    q = _W["mlp"].forward(_W["feat"])[0]
    return max(native.legal(d), key=lambda a: q[a])


def _search(d, actions, play_heur, rng):
    from tuppi_ai import native
    _W["env"].set_sooli(1, False, play_heur)
    return native.search_values(_W["env"], _W["mlp"], native.observe(d, d.cur), actions, _W["worlds"], 6, rng)


def chunk(start: int, count: int) -> list[dict]:
    from tuppi_ai import native
    out = []
    for i in range(start, start + count):
        rng = random.Random(f"sooli-bank|{i}")
        st = C.c_uint64(i * 7919 + 1)
        cards = list(range(52))
        rng.shuffle(cards)
        hands = [sum(1 << c for c in cards[s * 13:(s + 1) * 13]) for s in range(4)]
        level = rng.randrange(13)
        score = (0, 0) if level == 0 else ((4 * level, 0) if rng.random() < 0.5 else (0, 4 * level))
        d = native.new_deal(hands, rng.randrange(4), score[0], score[1], ruleset=2)
        while d.phase == native.PH_SHOW:
            native.lib.tc_apply(d, _greedy(d))
        if d.phase != native.PH_SOOLI_OFFER:
            continue
        for _ in range(2):
            if native.lib.tc_sooli_offer_prefilter(d.hand[d.cur]):
                v = _search(d, [native.ACT_SOOLI_DECLINE, native.ACT_SOOLI_ACCEPT], True, st)
                if v[1] - v[0] > _W["margin"]:
                    offer = bytes(d)
                    native.lib.tc_apply(d, native.ACT_SOOLI_ACCEPT)
                    legal = native.legal(d)
                    h = native.sooli_policy(native.observe(d, d.cur), st)
                    order = [h] + [a for a in legal if a != h]
                    give = order[int(np.argmax(_search(d, order, False, st)))]
                    native.lib.tc_apply(d, give)
                    native.lib.tc_apply(d, native.sooli_policy(native.observe(d, d.cur), st))
                    out.append({"index": i, "offer": offer, "start": bytes(d), "gain": float(v[1] - v[0])})
                    break
            native.lib.tc_apply(d, native.ACT_SOOLI_DECLINE)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deals", type=int, default=20000)
    parser.add_argument("--worlds", type=int, default=64)
    parser.add_argument("--margin", type=float, default=0.02)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    t0 = time.time()
    size = 200
    starts = list(range(0, args.deals, size))
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.worlds, args.margin)) as pool:
        rows = [r for part in pool.map(chunk, starts, [size] * len(starts)) for r in part]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(pickle.dumps(rows))
    print(f"{len(rows)} soolis from {args.deals} deals in {time.time() - t0:.0f} s -> {args.out}")


if __name__ == "__main__":
    main()
