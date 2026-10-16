"""Fast duplicate evaluation between two networks, entirely in the native core.

Same design as `evaluate.py` (each base deal played 4 rotations x 2 team
assignments, dealer 0, candidate-team equity change averaged over the 8 games)
but both teams are networks, so thousands of base deals take seconds. Use it
for model selection; claims against the incumbent go through `evaluate.py`.

    python -m tuppi_ai.native_eval --a runs/x/latest.pt --b runs/x/ckpt_....pt --deals 20000
"""

from __future__ import annotations

import argparse
import json
import math

import numpy as np
import torch

from . import model as qmodel
from . import native
from .equity import Equity
from .evaluate import ROOT


def _hands(rng: np.random.Generator, n: int) -> np.ndarray:
    decks = np.argsort(rng.random((n, 52)), axis=1)
    masks = np.zeros((n, 4), dtype=np.uint64)
    for s in range(4):
        cards = decks[:, 13 * s:13 * (s + 1)]
        masks[:, s] = np.bitwise_or.reduce(np.left_shift(np.uint64(1), cards.astype(np.uint64)), axis=1)
    return masks


def _features(env: native.Env, encoder: int) -> np.ndarray:
    """Re-encode every live game's current observation with another encoder."""
    out = np.zeros((env.n, native.feature_dim(encoder)), dtype=np.uint8)
    for i in range(env.n):
        d = env.deal(i)
        if d.phase != native.PH_DONE:
            native.encode(native.observe(d, d.cur), out[i], encoder)
    return out


def duplicate(net_a, net_b, deals: int, seed: int = 0, scores: str = "zero",
              device: str = "cpu", batch_deals: int = 512, equity: Equity | None = None) -> dict:
    """net_a / net_b: batched policies (policies.Greedy/Conservative) or bare networks."""
    from .policies import Greedy
    if not hasattr(net_a, "act"):
        net_a = Greedy(net_a, device)
    if not hasattr(net_b, "act"):
        net_b = Greedy(net_b, device)
    equity = equity or Equity.load(ROOT / "runs" / "equity_incumbent.json")
    rng = np.random.default_rng(seed)
    values = []
    for start in range(0, deals, batch_deals):
        nb = min(batch_deals, deals - start)
        base = _hands(rng, nb)
        if scores == "zero":
            sc = np.zeros((nb, 2), dtype=np.int64)
        else:
            level = rng.integers(0, 13, nb)
            side = rng.integers(0, 2, nb)
            sc = np.zeros((nb, 2), dtype=np.int64)
            sc[np.arange(nb), side] = 4 * level
        env = native.Env(nb * 8, seed + start, equity.table, single_deal=True, encoder=net_a.encoder)
        mixed = net_b.encoder != net_a.encoder
        cand_team = np.zeros(nb * 8, dtype=np.int64)
        for d in range(nb):
            for rot in range(4):
                hands = [int(base[d, (s + rot) % 4]) for s in range(4)]
                for team in (0, 1):
                    g = d * 8 + rot * 2 + team
                    env.set_deal(g, hands, 0, int(sc[d, 0]), int(sc[d, 1]))
                    cand_team[g] = team
        total = np.zeros(nb * 8)
        live = np.ones(nb * 8, dtype=bool)
        while live.any():
            feat, mask, seat, phase = env.observe()
            fb = _features(env, net_b.encoder) if mixed else feat
            acts_a = net_a.act(feat, mask, phase)
            acts_b = net_b.act(fb, mask, phase)
            use_a = (seat & 1) == cand_team
            acts = np.where(use_a, acts_a, acts_b).astype(np.int32)
            acts[mask.sum(axis=1) == 0] = 0
            env.step(acts)
            done = env.done.astype(bool)
            total[done] = env.delta0[done]
            live &= ~done
        signed = np.where(cand_team == 0, total, -total)
        values.extend(signed.reshape(nb, 8).mean(axis=1).tolist())
    v = np.array(values)
    se = v.std(ddof=1) / math.sqrt(len(v))
    return {"base_deals": len(v), "equity_per_deal": float(v.mean()),
            "ci95": [float(v.mean() - 1.96 * se), float(v.mean() + 1.96 * se)], "sd": float(v.std(ddof=1))}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--deals", type=int, default=10000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--scores", choices=("zero", "uniform"), default="zero")
    p.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
    args = p.parse_args()
    from .policies import from_spec
    a = from_spec(args.a, args.device)
    b = from_spec(args.b, args.device)
    print(json.dumps(duplicate(a, b, args.deals, args.seed, args.scores, args.device), indent=1))


if __name__ == "__main__":
    main()
