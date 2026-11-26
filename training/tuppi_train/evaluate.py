"""Large paired duplicate evaluation of one network against others.

    python -m tuppi_train.evaluate --a training/runs/run1/best_actor.pt --b vrpo4_final.pt,vrpo3_final.pt \\
        --base 65536 --seed 7

Each base deal is played 8 times (4 rotations x 2 team assignments, dealer 0, 0-0), both
sides greedy. Sooli offers use the native heuristic unless --offer-model is supplied.
Sooli trick play defaults to the open-card solver; --sooli-play heuristic uses the
observation-only policy used by the live lite bots. The result is the A pair's
match-equity change per deal with a 95% interval. A fresh --seed gives fresh deals: use one the training run never saw
(its monitoring seed is Config.eval_seed) to confirm a checkpoint picked on monitoring deals.
`--sampled T` makes both sides sample at temperature T instead.

A network name with the prefix "sym:" is played averaged over the four suit views
(symmetry.Symmetric), e.g. `--a sym:vrpo4_final.pt --b vrpo4_final.pt`.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time

import numpy as np

from . import device, lockstep, offer, symmetry, tn  # noqa: F401
from tuppi_ai import native


def compare(net_a, net_b, dev, base: int, seed: int, sampled: float = 0.0, paired: bool = True, chunk: int = 4096,
            ruleset: int = 3, amp=None, *, sooli_play_heuristic: bool = False) -> np.ndarray:
    """Per-base-deal values of net_a's pair against net_b's over `base` base deals."""
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    chunk = min(chunk, base)
    env = native.Env(8 * chunk, 1, Equity.load(EQUITY).table, single_deal=True, encoder=net_a.encoder)
    env.set_sooli(play_heur=sooli_play_heuristic)

    def chooser(net, k):
        if sampled > 0:
            return lockstep.TorchSampler(net, dev, sampled, device.generator(dev, seed + k), net.encoder, amp=amp)
        return lockstep.TorchGreedy(net, dev, net.encoder, amp=amp)

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
    p.add_argument("--sooli-play", choices=("solver", "heuristic"), default="solver",
                   help="how to play sooli tricks; solver reproduces the original benchmark")
    p.add_argument("--amp", default="off", choices=sorted(device.AMP), help="forward precision of both sides")
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    dev = device.pick(a.device)
    device.setup(dev)
    native.set_offer_model(offer.load_native(a.offer_model) if a.offer_model else None)
    net_a = symmetry.load_net(a.a, dev)
    for name in a.b.split(","):
        t = time.perf_counter()
        v = compare(net_a, symmetry.load_net(name.strip(), dev), dev, a.base, a.seed, a.sampled,
                    not a.unpaired, amp=device.AMP[a.amp], sooli_play_heuristic=a.sooli_play == "heuristic")
        mean, half = lockstep.interval(v)
        print(json.dumps({"a": a.a, "b": name.strip(), "base_deals": a.base, "seed": a.seed, "sampled": a.sampled,
                          "paired": not a.unpaired, "sooli_play": a.sooli_play, "mean": mean, "ci95": half,
                          "sd_per_base_deal": float(v.std(ddof=1)),
                          "significant": abs(mean) > half, "seconds": round(time.perf_counter() - t, 1)}), flush=True)


if __name__ == "__main__":
    main()
