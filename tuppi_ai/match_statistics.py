"""Paired-match summaries; an unfinished match is unknown, never a draw."""

from __future__ import annotations

import math
import statistics


def pair_result(a: dict, b: dict) -> dict:
    for leg in (a, b):
        if not leg["censored"] and leg["result"] not in (0.0, 1.0):
            raise ValueError("a completed match must have a winner")
    censored = int(a["censored"]) + int(b["censored"])
    lower = sum(0.0 if leg["censored"] else leg["result"] for leg in (a, b)) / 2
    upper = sum(1.0 if leg["censored"] else leg["result"] for leg in (a, b)) / 2
    return {"score": lower if not censored else None, "lower": lower, "upper": upper,
            "deals": a["deals"] + b["deals"], "censored": censored}


def summarize_pairs(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("cannot summarize an empty match comparison")
    censored = sum(r["censored"] for r in rows)
    scores = [r["score"] for r in rows]
    mean = statistics.fmean(scores) if not censored else None
    ci = None
    if not censored and len(rows) >= 2:
        se = statistics.stdev(scores) / math.sqrt(len(scores))
        ci = [max(0.0, mean - 1.96 * se), min(1.0, mean + 1.96 * se)]
    return {"scores": scores, "p_win": mean, "ci95": ci,
            "p_win_bounds": [statistics.fmean(r["lower"] for r in rows),
                             statistics.fmean(r["upper"] for r in rows)],
            "bounds_are": "identification bounds for observed censored outcomes, not confidence intervals",
            "pair_wins": sum(s == 1.0 for s in scores), "pair_ties": sum(s == 0.5 for s in scores),
            "pair_losses": sum(s == 0.0 for s in scores), "censored_legs": censored,
            "complete_pairs": sum(s is not None for s in scores),
            "mean_deals_per_leg": statistics.fmean(r["deals"] for r in rows) / 2}
