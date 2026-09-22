"""Evaluate every new checkpoint of a run against the incumbent, on fixed deals.

    python tools/watch_eval.py --run dmc1 --deals 1024 --hours 5
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from tuppi_ai.evaluate import evaluate

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--deals", type=int, default=1024)
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--hours", type=float, default=5.0)
    p.add_argument("--scores", default="zero")
    args = p.parse_args()
    run = ROOT / "runs" / args.run
    out = run / f"eval_{args.scores}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["checkpoint"] for line in out.read_text().splitlines() if line}
    t0 = time.time()
    while time.time() - t0 < args.hours * 3600:
        pending = sorted(c for c in run.glob("ckpt_*.pt") if c.name not in done)
        if not pending:
            time.sleep(30)
            continue
        ckpt = pending[-1] if len(pending) > 2 else pending[0]  # catch up by skipping ahead
        summary = evaluate(str(ckpt), args.deals, scores=args.scores, workers=args.workers)
        summary["checkpoint"] = ckpt.name
        with open(out, "a") as f:
            f.write(json.dumps(summary) + "\n")
        print(f"{ckpt.name}: {summary['equity_per_deal']:+.5f} "
              f"[{summary['ci95'][0]:+.5f}, {summary['ci95'][1]:+.5f}] won={summary['won']:.3f} "
              f"rami={summary['rami']:.3f} ({summary['seconds']}s)", flush=True)
        done.add(ckpt.name)


if __name__ == "__main__":
    main()
