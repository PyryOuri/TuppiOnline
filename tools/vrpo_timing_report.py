"""Read existing VRPO logs; never imports Torch/native or launches a workload."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def summarize(rows: list[dict], old_every: int = 3, new_every: int = 12, warmup: int = 6) -> dict:
    if not rows or old_every < 1 or new_every < 0 or warmup < 0:
        raise ValueError("nonempty log, positive old cadence and nonnegative new cadence required")
    for r in rows:
        for key in ("total_s", "rollout_s"):
            if not math.isfinite(r[key]) or r[key] < 0:
                raise ValueError(f"invalid {key} at iteration {r['iteration']}")
    if any(a["iteration"] >= b["iteration"] for a, b in zip(rows, rows[1:])):
        raise ValueError("iterations must be strictly increasing")
    total = sum(r["total_s"] for r in rows)
    if total <= 0:
        raise ValueError("elapsed total must be positive")
    normal = [r for r in rows if r["iteration"] > warmup and "vs_ref" not in r]
    checks = [r for r in rows if r["iteration"] > warmup and "vs_ref" in r]
    direct = all("evaluation_s" in r for r in rows)
    if direct:
        if any(not math.isfinite(r["evaluation_s"]) or r["evaluation_s"] < 0 for r in rows):
            raise ValueError("invalid evaluation timing")
        overhead = sum(r["evaluation_s"] for r in rows)
        if not math.isfinite(overhead) or not 0 <= overhead <= total + 0.1 * len(rows):
            raise ValueError("invalid evaluation timing")
        method = "recorded evaluation_s (includes checkpoint writes)"
    else:
        overhead = 0.0
        for i, r in enumerate(rows):
            if r["iteration"] <= warmup or "vs_ref" not in r:
                continue
            neighbors = [q["total_s"] for q in rows[max(0, i - 2):i + 3] if "vs_ref" not in q]
            if neighbors:
                overhead += max(0.0, r["total_s"] - statistics.fmean(neighbors))
        method = "estimated excess over neighboring non-check iterations after warmup"
    retained_fraction = old_every / new_every if new_every else 0.0
    return {
        "iterations": len(rows), "elapsed_h": total / 3600,
        "mean_noncheck_s": statistics.fmean(r["total_s"] for r in normal) if normal else None,
        "mean_check_s": statistics.fmean(r["total_s"] for r in checks) if checks else None,
        "evaluation_overhead_h": overhead / 3600, "evaluation_share": overhead / total,
        "overhead_method": method, "old_eval_every": old_every, "new_eval_every": new_every,
        "projected_same_iterations_h": (total - overhead * (1 - retained_fraction)) / 3600,
        "qualification": "Projection, not a benchmark; excludes additional final checking and strength confirmation.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("log", type=Path)
    p.add_argument("--old-eval-every", type=int, default=3)
    p.add_argument("--new-eval-every", type=int, default=12)
    p.add_argument("--warmup", type=int, default=6)
    a = p.parse_args()
    rows = [json.loads(s) for s in a.log.read_text().splitlines() if s.strip()]
    print(json.dumps(summarize(rows, a.old_eval_every, a.new_eval_every, a.warmup), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
