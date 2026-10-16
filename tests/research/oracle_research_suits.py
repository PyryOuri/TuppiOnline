"""Isolated RESEARCH-environment oracle for the C1 proxy (V01). NOT a pytest module.

Run with the environment that sees the RESEARCH checkout (TuppiProject/src),
never the ENGINE one, so the two engine installations are never loaded into
one process:

    ~/.venvs/tuppi-ai/bin/python tests/research/oracle_research_suits.py

Checks, printed as JSON:
1. per-layout: `contested_liability` (tuppi_ai.research.c1_control_variate,
   dependency-free) equals RESEARCH `tuppi_valuation.suits.play_out` with the
   LOWEST policy, counted over contested rounds only, on seeded random
   multi-suit layouts with unequal hand sizes;
2. exact law: sum over RESEARCH `conditional_layouts` of probability x
   per-layout contested liability equals RESEARCH
   `tuppi_agents.nolo_discard.expected_ducking_tricks` exactly (Fractions) on
   the E024 grid - the same conditioning, so the per-layout proxy is the
   brute-force form of that law.
"""

from __future__ import annotations

import json
import random
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # TuppiAI, for the dependency-free proxy

from tuppi_agents.nolo_discard import expected_ducking_tricks  # noqa: E402  (RESEARCH)
from tuppi_valuation.suits import SuitPolicy, conditional_layouts, play_out  # noqa: E402  (RESEARCH)

from tuppi_ai.research.c1_control_variate import contested_liability  # noqa: E402

GRID = [  # E024's grid (tests/agents/test_nolo_discard.py)
    ((14, 10, 5), (), (13, 13, 13), (False, False, False)),
    ((13, 7, 2), (), (13, 13, 13), (False, False, False)),
    ((14, 10, 5), (2, 3, 4), (10, 10, 10), (False, False, False)),
    ((14, 10, 5), (2, 3, 4), (10, 9, 9), (False, False, False)),
    ((13, 7), (14, 2, 3, 4, 5), (8, 8, 8), (True, False, False)),
    ((9, 8, 7), (14, 13, 12, 11), (9, 8, 8), (False, True, False)),
    ((14, 2), (13, 12, 11, 10, 9), (7, 7, 6), (False, False, True)),
    ((11, 6, 4, 3), (14, 13), (11, 11, 10), (False, False, False)),
    ((5,), (14, 13, 12, 11, 10, 9, 8), (6, 5, 5), (True, True, False)),
]


def mask(ranks, suit=0):
    return sum(1 << (13 * suit + r - 2) for r in ranks)


def research_contested(root_masks, other_masks):
    total = 0
    for suit in range(4):
        own = [r + 2 for r in range(13) if root_masks >> (13 * suit + r) & 1]
        opp = [[r + 2 for r in range(13) if m >> (13 * suit + r) & 1] for m in other_masks]
        rounds = min(len(own), max((len(q) for q in opp), default=0))
        total += play_out(own, opp, times_led=rounds, policy=SuitPolicy.LOWEST)[0]
    return total


def main():
    engine_src = Path(__file__).resolve().parents[3] / "TuppiProject-current" / "src"
    loaded_engine = sorted(n for n, m in list(sys.modules.items()) if getattr(m, "__file__", None)
                           and Path(m.__file__).resolve().is_relative_to(engine_src))
    rng = random.Random("tuppi.research.oracle.v1")
    layout_rows, mismatches = 0, []
    for _ in range(400):
        cards = list(range(52))
        rng.shuffle(cards)
        sizes = [rng.randint(0, 13) for _ in range(4)]
        hands, at = [], 0
        for s in sizes:
            hands.append(sum(1 << c for c in cards[at:at + s]))
            at += s
        ours = contested_liability(hands[0], hands[1:])
        theirs = research_contested(hands[0], hands[1:])
        layout_rows += 1
        if ours != theirs:
            mismatches.append({"hands": hands, "ours": ours, "research": theirs})
    law_rows = []
    for own, seen, sizes, void in GRID:
        total = Fraction(0)
        for layout, prob in conditional_layouts(list(own), seen_ranks=list(seen), hand_sizes=sizes, void=void):
            total += prob * contested_liability(mask(own), [mask(h) for h in layout])
        held, gone = set(own), set(seen)
        outstanding = tuple(sorted((r for r in range(2, 15) if r not in held and r not in gone), reverse=True))
        exact = expected_ducking_tricks(tuple(sorted(own)), outstanding, sizes, void)
        law_rows.append({"own": own, "seen": seen, "sizes": sizes, "void": void,
                         "per_layout_expectation": str(total), "research_exact": str(exact), "equal": total == exact})
    print(json.dumps({"engine_modules_loaded": loaded_engine, "layouts_checked": layout_rows,
                      "layout_mismatches": mismatches, "law_rows": law_rows,
                      "research_modules": sorted(n for n in sys.modules if n.startswith(("tuppi_valuation",
                                                                                          "tuppi_agents")))}))


if __name__ == "__main__":
    main()
