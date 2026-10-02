"""H2 (docs/HEURISTIC_PLAN.md): a learned RAMI hand evaluation for partner_aware_lead_v2.

Every show decision of mining run 3 has the value of the best RAMI and the best
NOLO declaration (v2's clone continuing). A linear model of
q(RAMI) - q(NOLO) on visible hand features is fitted on the even deals; the
rule "declare RAMI when the prediction is above 0" is scored on the odd deals
against the heuristic's own contract choice (gain per deal, clustered by deal).
A rounded version with few terms is scored the same way.

    python tools/fit_showing.py runs/heuristic/mine3.pkl
"""

from __future__ import annotations

import argparse
import gzip
import math
import pickle
from pathlib import Path

import numpy as np

BASE = ["hcp", "aces", "kings", "queens", "jacks", "tens", "low4", "top_seq", "long_honours",
        "len1", "len2", "len3", "len4", "voids", "singletons", "doubletons"]


def design(rows, names):
    X = np.array([[float(r[n]) for n in names] for r in rows])
    pos = np.array([[float(r["n_shows"] == k) for k in (1, 2, 3)] for r in rows])  # position after k NOLO shows
    return np.hstack([np.ones((len(rows), 1)), X, pos])


def score(rows, choose_rami, deals: int) -> tuple[float, float, float]:
    """(gain per deal against the heuristic's contract, its 95% half-width, share of decisions changed)."""
    per_deal: dict[int, float] = {}
    changed = 0
    for r, rami in zip(rows, choose_rami):
        heur_rami = r["heur_contract"] == "RAMI"
        if rami == heur_rami:
            continue
        changed += 1
        g = (r["q_rami"] - r["q_nolo"]) * (1 if rami else -1)
        per_deal[r["deal"]] = per_deal.get(r["deal"], 0.0) + g
    vals = np.array(list(per_deal.values()) + [0.0] * (deals - len(per_deal)))
    m = vals.mean()
    return m, 1.96 * vals.std(ddof=1) / math.sqrt(len(vals)), changed / len(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data", type=Path)
    a = p.parse_args()
    blob = pickle.load(gzip.open(a.data))
    deals = blob["args"]["deals"]
    rows = [r for r in blob["rows"] if r["phase"] == "show" and r.get("q_rami") is not None
            and r.get("q_nolo") is not None]
    train = [r for r in rows if r["deal"] % 2 == 0]
    test = [r for r in rows if r["deal"] % 2 == 1]
    print(f"{len(rows)} show decisions with both contracts priced; train {len(train)}, test {len(test)}")
    # consistency: the logged scores reproduce the heuristic's choice (threshold 15, veto 2)
    agree = np.mean([(r["rami_score"] >= 15 and r["nolo_score"] <= 2) == (r["heur_contract"] == "RAMI") for r in rows])
    print(f"logged scores reproduce the heuristic's contract on {agree:.1%} of decisions")
    y_tr = np.array([r["q_rami"] - r["q_nolo"] for r in train])
    names = BASE + ["own_score", "opp_score"]
    X_tr, X_te = design(train, names), design(test, names)
    w, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
    cols = ["const"] + names + ["after1", "after2", "after3"]
    print("\nfitted q(RAMI) - q(NOLO), equity units:")
    for c, v in sorted(zip(cols, w), key=lambda x: -abs(x[1])):
        print(f"  {c:14s} {v:+.5f}")
    pred = X_te @ w
    print("\non the held-out (odd) deals, against the heuristic's contract choice:")
    m, ci, ch = score(test, pred > 0, deals // 2)
    print(f"  full linear rule      {m:+.5f} ± {ci:.5f} per deal   (changes {ch:.1%} of show decisions)")
    heur_rule = [r["heur_contract"] == "RAMI" for r in test]
    print(f"  (heuristic itself     {score(test, heur_rule, deals // 2)[0]:+.5f})")
    # oracle bound: the better contract on every decision
    print(f"  oracle (best contract each time) {score(test, [r['q_rami'] > r['q_nolo'] for r in test], deals // 2)[0]:+.5f}")
    # a readable rule: rescale to HCP units and round
    hcp_w = w[cols.index("hcp")]
    print(f"\nin HCP units (divide by the hcp weight {hcp_w:+.5f}):")
    for c, v in zip(cols, w):
        print(f"  {c:14s} {v / hcp_w:+.2f}")
    np.save(a.data.with_suffix(".showing_w.npy"), w)


if __name__ == "__main__":
    main()
