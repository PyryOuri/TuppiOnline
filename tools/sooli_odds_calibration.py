"""How well the live sooli odds match the bot's own soolis.

The odds tool's sooli view (``tuppi_ai.sooli_odds.SooliOdds``) samples the
hidden cards facts-only, or under the search's sooli belief (offer prefilter +
exposure tilt). On the bank of soolis the bot itself accepted
(``runs/sooli/bank_v1.pkl``), from a RAMI player's seat at the first sooli
lead: mean negative log-likelihood of each unseen card's true holder, and
calibration.

    python tools/sooli_odds_calibration.py --positions 600 --worlds 400
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import math
import pickle
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tuppi_ai import native  # noqa: E402
from tuppi_ai.search import SOOLI_DEFAULTS  # noqa: E402

CLIP = 1e-3


def marginals(obs, mode, lam, worlds, rng):
    counts = np.zeros((52, 4))
    world = native.TcDeal()
    for _ in range(worlds):
        if native.lib.tc_sample_world_sooli(C.byref(obs), C.byref(rng), C.byref(world), mode, lam) != 0:
            raise ValueError("no layout")
        for seat in range(4):
            mask = world.hand[seat]
            for i in range(52):
                if mask >> i & 1:
                    counts[i, seat] += 1
    return counts / worlds


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--positions", type=int, default=600)
    p.add_argument("--worlds", type=int, default=400)
    p.add_argument("--out", type=Path, default=ROOT / "runs" / "sooli" / "odds_calibration.json")
    args = p.parse_args()
    rows = pickle.loads((ROOT / "runs" / "sooli" / "bank_v1.pkl").read_bytes())[: args.positions]
    rng = C.c_uint64(4242)
    per = {"facts": [], "inferred": []}
    by_holder = {"facts": {}, "inferred": {}}
    buckets = {name: [[0, 0.0, 0] for _ in range(10)] for name in per}
    for row in rows:
        deal = native.TcDeal.from_buffer_copy(row["start"])
        s = deal.soolaaja
        observer = (s + 1) % 4
        obs = native.observe(deal, observer)
        truth = {i: seat for seat in range(4) for i in range(52) if deal.hand[seat] >> i & 1}
        unseen = [i for i in range(52) if truth.get(i, observer) != observer]
        for name, mode in (("facts", 0), ("inferred", SOOLI_DEFAULTS["belief"])):
            m = marginals(obs, mode, SOOLI_DEFAULTS["lam"], args.worlds, rng)
            total = 0.0
            for i in unseen:
                owner = truth[i]
                total += -math.log(max(m[i, owner], CLIP))
                role = "soolaaja" if owner == s else "dead hand" if owner == (s + 2) % 4 else "partner"
                cell = by_holder[name].setdefault(role, [0.0, 0])
                cell[0] += -math.log(max(m[i, owner], CLIP))
                cell[1] += 1
                for seat in range(4):
                    if seat == observer:
                        continue
                    b = min(int(m[i, seat] * 10), 9)
                    buckets[name][b][0] += 1
                    buckets[name][b][1] += m[i, seat]
                    buckets[name][b][2] += int(owner == seat)
            per[name].append(total / len(unseen))
    diff = np.array(per["inferred"]) - np.array(per["facts"])
    summary = {
        "positions": len(rows), "worlds": args.worlds,
        "facts": round(float(np.mean(per["facts"])), 4),
        "inferred": round(float(np.mean(per["inferred"])), 4),
        "inferred_minus_facts": [round(float(diff.mean()), 4), round(float(1.96 * diff.std(ddof=1) / math.sqrt(len(diff))), 4)],
        "by_true_holder": {name: {role: round(v[0] / v[1], 4) for role, v in roles.items()} for name, roles in by_holder.items()},
        "calibration": {name: [(f"{b/10:.1f}", c[0], round(c[1] / c[0], 3) if c[0] else None,
                                round(c[2] / c[0], 3) if c[0] else None) for b, c in enumerate(cells)]
                        for name, cells in buckets.items()},
    }
    args.out.write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
