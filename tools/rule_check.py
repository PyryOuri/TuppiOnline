"""Offline check of candidate heuristic rules on fully priced mining data.

Input: `tools/heuristic_mining.py --price-all` output, where every decision has
every legal action's value (v2's clone continuing) and the decision's view
(own hand, cards played). A rule is a function of what the player can see and
the heuristic's action; it returns its own action or None (no change). Its
priced gain is q[rule action] - q[heuristic action] where it changes the
action, summed per deal. This is a screen only: a rule goes to paired games
(pre-registered) before any claim.

    python tools/rule_check.py runs/heuristic/mine4.pkl
"""

from __future__ import annotations

import argparse
import gzip
import sys
import math
import pickle
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from tuppi_ai.heuristic_rules import RULES as _R  # noqa: E402

RULES = {"underlead": _R["underlead"], "cash_singleton": _R["cash_singleton"],
         "cash_singleton_late": _R["cash_singleton_late"],
         "underlead+cash_singleton_late": lambda r: _R["cash_singleton_late"](r) or _R["underlead"](r)}


def check(rows: list[dict], deals: int, rule, split=None) -> dict:
    gains, groups = [], {}
    for r in rows:
        if r["phase"] != "play" or "qa" not in r:
            continue
        a = rule(r)
        if a is None or a == r["heur"]:
            continue
        g = r["qa"][a] - r["qa"][r["heur"]]
        gains.append(g)
        if split:
            groups.setdefault(split(r), []).append(g)
    def stats(gs):
        n = len(gs)
        if n < 2:
            return {"n": n}
        m = sum(gs) / n
        se = math.sqrt(sum((x - m) ** 2 for x in gs) / (n - 1) / n)
        return {"n": n, "per_change": m, "ci": 1.96 * se, "per_deal": sum(gs) / deals, "per_deal_ci": 1.96 * se * n / deals}
    out = {"all": stats(gains)}
    for k, gs in sorted(groups.items(), key=lambda x: str(x[0])):
        out[k] = stats(gs)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data", type=Path)
    a = p.parse_args()
    blob = pickle.load(gzip.open(a.data))
    rows, deals = blob["rows"], blob["args"]["deals"]
    split = lambda r: ("early" if r["tricks_left"] >= 10 else "mid" if r["tricks_left"] >= 6 else "late", r["role"])
    for name, rule in RULES.items():
        res = check(rows, deals, rule, split)
        print(f"\n{name}")
        for k, v in res.items():
            if v.get("n", 0) >= 2:
                print(f"  {str(k):24s} changes {v['n']:7d} ({v['n'] / deals:.3f}/deal)  per change {v['per_change']:+.5f} ± {v['ci']:.5f}"
                      f"  per deal {v['per_deal']:+.5f} ± {v['per_deal_ci']:.5f}")


if __name__ == "__main__":
    main()
