"""Where play inference spends its time (cost work, 2026-10-17).

Plays a few duplicate deals in one process, candidate `best:w=<W>:pib=4` against
`best:w=<W>`, and prints the native counters: seconds drawing candidate worlds
and replaying their histories, in the network, resampling, and in the
rollouts of searches with and without play inference.

    python tools/belief_profile.py --worlds 128 --deals 4
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tuppi_ai import evaluate, native

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worlds", type=int, default=128)
    ap.add_argument("--deals", type=int, default=4)
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--candidate", default="best:w={w}:pib=4:pibt=2:pibe=0.5")
    args = ap.parse_args()
    cand = args.candidate.format(w=args.worlds)
    evaluate._init(cand, f"best:w={args.worlds}", str(ROOT / "models" / "equity_incumbent.json"), "v3")
    counters = hasattr(native.lib, "tc_belief_profile")
    if counters:
        native.belief_profile(reset=True)
    t0, c0 = time.time(), time.process_time()
    values = [evaluate.measure(i, "tuppi-ai-eval-v1", "zero")["value"]
              for i in range(args.first, args.first + args.deals)]
    wall, cpu = time.time() - t0, time.process_time() - c0
    prof = native.belief_profile() if counters else {}
    print(json.dumps({"candidate": cand, "deals": args.deals, "wall": round(wall, 2), "cpu": round(cpu, 1),
                      "values": values,
                      **{k: round(v, 3) if isinstance(v, float) else v for k, v in prof.items()}}, indent=1))


if __name__ == "__main__":
    main()
