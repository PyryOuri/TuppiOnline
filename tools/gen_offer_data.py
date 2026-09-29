"""Training rows for the fast sooli-offer model (self-play engine).

Deals are bid by the rollout clone under project_target_v3, as in the search's
rollouts. For every sooli offer that is reached, and for the second defender
after the first declines, the defender's observation is encoded (encoder 1)
and labelled with the exact offer heuristic's decision
(`tuppi_sooli_policy.c: offer`: prefilter, then 8 sampled worlds with the
heuristic exchange and the exact solver). Only offers that pass the
heuristic's prefilter are kept: the others are declined without any solve.

    python tools/gen_offer_data.py --offers 400000 --seed 1 --out runs/offer/train.npz
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


def _label(job):
    blobs, seed = job
    from tuppi_ai import native

    rng = C.c_uint64(seed)
    out = []
    for b in blobs:
        out.append(int(native.sooli_policy(native.TcObs.from_buffer_copy(b), rng) == native.ACT_SOOLI_ACCEPT))
    return out


def offers(n_games: int, seed: int):
    """Defender observations (bytes) at sooli offers that pass the prefilter."""
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import model as qmodel
    from tuppi_ai import native
    from tuppi_ai.best import ROLLOUT

    net = qmodel.load(ROLLOUT, "cpu")
    mlp = native.Mlp(net)
    env = native.Env(n_games, seed, None, single_deal=True, encoder=net.encoder)
    rng = np.random.default_rng(seed)
    for i in range(n_games):
        cards = rng.permutation(52)
        hands = [sum(1 << int(c) for c in cards[13 * s:13 * s + 13]) for s in range(4)]
        level = int(rng.integers(1, 13)) if rng.random() < 0.5 else 0
        s0, s1 = (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)
        env.set_state(i, native.new_deal(hands, int(rng.integers(4)), s0, s1, ruleset=3))
    for _ in range(4):  # bids by the clone, greedily, as in rollouts
        feat, mask, seat, phase = env.observe()
        q = mlp.forward(feat)
        q[mask == 0] = -np.inf
        acts = np.where(mask.any(axis=1), q.argmax(axis=1), 0).astype(np.int32)
        env.step(acts)
    rows = []
    for i in range(n_games):
        d = native.TcDeal.from_buffer_copy(env.deal(i))
        if d.phase != native.PH_SOOLI_OFFER:
            continue
        for _ in range(2):
            obs = native.observe(d, d.cur)
            if native.lib.tc_sooli_offer_prefilter(C.c_uint64(obs.hand)):
                rows.append(bytes(obs))
            native.lib.tc_apply(C.byref(d), native.ACT_SOOLI_DECLINE)  # the next defender is asked
            if d.phase != native.PH_SOOLI_OFFER:
                break
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--offers", type=int, required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--workers", type=int, default=13)
    a = p.parse_args()
    from tuppi_ai import native

    t0 = time.time()
    blobs, batch = [], 0
    while len(blobs) < a.offers:
        blobs += offers(16384, a.seed * 1000 + batch)
        batch += 1
    blobs = blobs[:a.offers]
    parts = [blobs[i::a.workers] for i in range(a.workers)]
    with ProcessPoolExecutor(a.workers) as pool:
        labels_parts = list(pool.map(_label, [(part, a.seed * 7919 + k) for k, part in enumerate(parts)]))
    labels = np.zeros(len(blobs), dtype=np.uint8)
    for k, lab in enumerate(labels_parts):
        labels[k::a.workers] = lab
    feat = np.zeros((len(blobs), native.feature_dim(1)), dtype=np.uint8)
    for i, b in enumerate(blobs):
        native.encode(native.TcObs.from_buffer_copy(b), feat[i], 1)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(a.out, feat=np.packbits(feat, axis=1), label=labels)
    print(json.dumps({"offers": len(labels), "accept_rate": float(labels.mean()), "games_batches": batch,
                      "seconds": round(time.time() - t0, 1)}))


if __name__ == "__main__":
    main()
