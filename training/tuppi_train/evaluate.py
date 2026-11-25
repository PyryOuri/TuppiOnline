"""Large paired duplicate evaluation of one network against others.

    python -m tuppi_train.evaluate --a training/runs/run1/best_actor.pt --b vrpo4_final.pt,vrpo3_final.pt \\
        --base 65536 --seed 7

Each base deal is played 8 times (4 rotations x 2 team assignments, dealer 0, 0-0), both
sides greedy, sooli phases by the heuristics (the exact offer heuristic unless --offer-model):
this is the plain lite bot's play. The result is the A pair's match-equity change per deal
with a 95% interval. A fresh --seed gives fresh deals: use one the training run never saw
(its monitoring seed is Config.eval_seed) to confirm a checkpoint picked on monitoring deals.
`--sampled T` makes both sides sample at temperature T instead.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time

import numpy as np

from . import device, lockstep, offer, tn  # noqa: F401
from .vrpo_gpu import resolve_model
from tuppi_ai import model as qmodel
from tuppi_ai import native


def compare(net_a, net_b, dev, base: int, seed: int, sampled: float = 0.0, paired: bool = True, chunk: int = 4096,
            ruleset: int = 3) -> np.ndarray:
    """Per-base-deal values of net_a's pair against net_b's over `base` base deals."""
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    chunk = min(chunk, base)
    env = native.Env(8 * chunk, 1, Equity.load(EQUITY).table, single_deal=True, encoder=net_a.encoder)
    env.set_sooli(0, False, False, 0.0)

    def chooser(net, k):
        if sampled > 0:
            return lockstep.TorchSampler(net, dev, sampled, device.generator(dev, seed + k), net.encoder)
        return lockstep.TorchGreedy(net, dev, net.encoder)

    rng, values = C.c_uint64(seed), []
    for done in range(0, base, chunk):
        values.append(lockstep.duplicate_eval(env, chooser(net_a, 1), chooser(net_b, 2), min(chunk, base - done),
                                              ruleset, rng, net_a.encoder, paired=paired))
    return np.concatenate(values)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True, help="comma-separated networks (files in ai/models or paths)")
    p.add_argument("--base", type=int, default=65536)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--sampled", type=float, default=0.0)
    p.add_argument("--unpaired", action="store_true", help="the native function's seeds (noisier)")
    p.add_argument("--offer-model", default=None)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    dev = device.pick(a.device)
    device.setup(dev)
    native.set_offer_model(offer.load_native(a.offer_model) if a.offer_model else None)
    net_a = qmodel.load(resolve_model(a.a), dev)
    for name in a.b.split(","):
        t = time.perf_counter()
        v = compare(net_a, qmodel.load(resolve_model(name.strip()), dev), dev, a.base, a.seed, a.sampled,
                    not a.unpaired)
        mean, half = lockstep.interval(v)
        print(json.dumps({"a": a.a, "b": name.strip(), "base_deals": a.base, "seed": a.seed, "sampled": a.sampled,
                          "paired": not a.unpaired, "mean": mean, "ci95": half, "sd_per_base_deal": float(v.std(ddof=1)),
                          "significant": abs(mean) > half, "seconds": round(time.perf_counter() - t, 1)}), flush=True)


if __name__ == "__main__":
    main()
