"""H2 on true-continuation show prices (tools/show_true_price.py).

y = value(RAMI) - value(NOLO) for the acting team, each contract with v2's own
show card and v2 (with TuppiProject's sooli fallback) playing the rest in the
authoritative engine. First the calibration against the H1 games, then a
linear fit on the even deals scored on the odd deals.

    python tools/fit_showing_true.py runs/heuristic/show_true1.pkl
"""

from __future__ import annotations

import argparse
import gzip
import math
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fit_showing import BASE, design  # noqa: E402


def y_of(r) -> float:
    return r["delta"] if r["heur_contract"] == "NOLO" else -r["delta"]


def score(rows, choose_rami, deals: int):
    per_deal: dict[int, float] = {}
    changed = 0
    for r, rami in zip(rows, choose_rami):
        if rami == (r["heur_contract"] == "RAMI"):
            continue
        changed += 1
        per_deal[r["deal"]] = per_deal.get(r["deal"], 0.0) + r["delta"]  # delta = the other contract's gain
    vals = np.array(list(per_deal.values()) + [0.0] * (deals - len(per_deal)))
    return vals.mean(), 1.96 * vals.std(ddof=1) / math.sqrt(len(vals)), changed / len(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data", type=Path)
    a = p.parse_args()
    blob = pickle.load(gzip.open(a.data))
    rows, deals = blob["rows"], blob["args"]["deals"]
    print(f"{len(rows)} show decisions from {deals} deals")
    games = {11: -0.00376, 12: -0.00195, 13: -0.00085, 14: -0.00013}
    print("H1 thresholds, all decisions (both teams), true continuation, vs the games (one team):")
    for t in (11, 12, 13, 14, 16, 17):
        m, ci, ch = score(rows, [r["rami_score"] >= t and r["nolo_score"] <= 2 for r in rows], deals)
        g = games.get(t)
        print(f"  threshold {t}: {m:+.5f} ± {ci:.5f} (changes {ch:.1%})" + (f"   games {g:+.5f}" if g else ""))
    train = [r for r in rows if r["deal"] % 2 == 0]
    test = [r for r in rows if r["deal"] % 2 == 1]
    names = BASE + ["own_score", "opp_score"]
    w, *_ = np.linalg.lstsq(design(train, names), np.array([y_of(r) for r in train]), rcond=None)
    cols = ["const"] + names + ["after1", "after2", "after3"]
    pred = design(test, names) @ w
    m, ci, ch = score(test, pred > 0, deals // 2)
    print(f"\nfitted linear rule on the held-out deals: {m:+.5f} ± {ci:.5f} per deal (changes {ch:.1%})")
    hcp_w = w[cols.index("hcp")]
    print(f"in HCP units (hcp weight {hcp_w:+.5f}):")
    for c, v in zip(cols, w):
        print(f"  {c:14s} {v / hcp_w:+.2f}")
    np.save(a.data.with_suffix(".w.npy"), w)


if __name__ == "__main__":
    main()
