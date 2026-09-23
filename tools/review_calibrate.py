"""Calibrate the after-deal review's 'clear mistake' threshold.

v3 deals (seed per index): seats 0 and 2 are the best agent, 1 and 3 the
incumbent with the sooli fallback. Every seat's decisions are reviewed with a
permissive first pass (all gaps and standard errors recorded) and, for gaps
above the loosest candidate threshold, a confirming pass. Thresholds are then
compared offline: flags per seat-deal for the bot (false alarms: the bot is
the reviewer) and for the incumbent, and the flagged cost per seat-deal.

    python tools/review_calibrate.py --deals 48 --workers 12 --out runs/review_calib.json
"""

from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

_W: dict = {}


def _init(worlds: int) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_agents.sooli import SooliFallbackAgent
    from tuppi_ai.best import best_agents
    from tuppi_ai.incumbent import incumbent_agents
    from tuppi_ai.review import DealReviewer

    bots = best_agents((0, 2))
    inc = incumbent_agents()
    _W["agents"] = {0: bots[0], 2: bots[2], 1: SooliFallbackAgent(inc[1]), 3: SooliFallbackAgent(inc[3])}
    _W["reviewer"] = DealReviewer.best(worlds=worlds, confirm_worlds=4 * worlds, min_cost=0.0015, z=1.5)


def run(index: int) -> list[dict]:
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    rng = random.Random(f"review-calib|{index}")
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
    level = rng.randrange(13)
    score = MatchScore(0, 0) if level == 0 else (MatchScore(4 * level, 0) if rng.random() < 0.5 else MatchScore(0, 4 * level))
    decisions = {s: [] for s in range(4)}
    with trusted_transitions():
        state = begin_explicit_deal(create_match(initial_score=score, initial_dealer=index % 4, match_ref="calib",
                                                 ruleset_id=RulesetId.PROJECT_TARGET_V3),
                                    ExplicitDeal(dealer=index % 4, hands=hands))
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            action = _W["agents"][seat].choose_action(obs)
            decisions[seat].append((obs, action))
            state = apply_match_action(state, action)
        out = []
        for seat in range(4):
            for item in _W["reviewer"].review(decisions[seat]):
                out.append({"deal": index, "seat": seat, "bot": seat % 2 == 0, "kind": item.kind,
                            "cost": item.cost, "se": item.standard_error, "confirmed": item.flagged,
                            "differs": item.recommended != item.played})
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, default=48)
    p.add_argument("--worlds", type=int, default=256)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.worlds,)) as pool:
        rows = [r for part in pool.map(run, range(a.deals)) for r in part]
    a.out.write_text(json.dumps(rows))
    seat_deals = a.deals * 2
    for min_cost in (0.002, 0.004, 0.006, 0.01):
        for z in (2.0, 2.5, 3.0):
            for bot in (True, False):
                sel = [r for r in rows if r["bot"] is bot and r["confirmed"] and r["cost"] >= min_cost
                       and r["cost"] >= z * r["se"]]
                print(f"min {min_cost:.3f} z {z:.1f} {'bot ' if bot else 'inc '} flags/seat-deal "
                      f"{len(sel) / seat_deals:.3f} cost/seat-deal {sum(r['cost'] for r in sel) / seat_deals:.4f}")


if __name__ == "__main__":
    main()
