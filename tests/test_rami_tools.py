"""Smoke tests of the RAMI analysis tools (tools/rami_rates.py, rami_outcomes.py, rami_vs_nolo.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import rami_outcomes  # noqa: E402
import rami_rates  # noqa: E402
import rami_vs_nolo  # noqa: E402


def test_bid_rates_follow_the_locked_bid_rule():
    rami_rates._init("heur:v3")
    rows = rami_rates.run((list(range(40)), "zero", "test"))
    for r in rows:
        assert r["rami_deal"] == any(b["rami"] for b in r["bids"])
        assert [b["k"] for b in r["bids"]] == list(range(len(r["bids"])))
        for b in r["bids"]:  # v3 bids exactly by its scores (threshold 15, veto 2)
            assert b["rami"] == (b["rami_score"] >= 15 and b["nolo_score"] <= 2)


def test_outcomes_are_consistent():
    rami_rates._init("heur:v3")
    for r in rami_outcomes.run((list(range(20)), "uniform", "test")):
        assert sum(r["team_tricks"]) == 13 or r["sooli"]
        if r["contract"] == "RAMI" and not r["sooli"]:
            made = r["team_tricks"][r["declarer"] % 2] >= 7
            assert made == (r["winner"] == r["declarer"] % 2)
            assert r["stolen"] == (not made)


def test_same_hand_branches():
    rami_vs_nolo._init("heur:v3")
    rows = rami_vs_nolo.run((list(range(20)), "zero", "test"))
    assert rows
    for r in rows:
        assert r["chosen"] in ("RAMI", "NOLO")
        assert {"won", "points", "equity"} <= set(r["rami"]) and {"won", "points", "equity"} <= set(r["nolo"])
