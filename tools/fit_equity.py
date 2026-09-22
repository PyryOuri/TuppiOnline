"""Fit the deal-outcome model from incumbent self-play and solve match equity.

    python tools/fit_equity.py --deals 20000 --out runs/equity_incumbent.json
"""

from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from tuppi_ai.equity import DealModel, Equity
from tuppi_ai.incumbent import incumbent_agents

_AGENTS = None


def _play(index: int) -> tuple[bool, int]:
    global _AGENTS
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore
    from tuppi_rules.cards import FULL_DECK

    if _AGENTS is None:
        _AGENTS = incumbent_agents()
    rng = random.Random(f"fit-equity|{index}")
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
    dealer = index % 4
    with trusted_transitions():
        state = begin_explicit_deal(
            create_match(initial_score=MatchScore(0, 0), initial_dealer=dealer, match_ref="fit-equity"),
            ExplicitDeal(dealer=dealer, hands=hands))
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            state = apply_match_action(state, _AGENTS[seat].choose_action(match_observation_for(state, seat)))
    score = state.completed_deals[-1].public_result.deal_score
    return (score.winner_team.value == dealer % 2), score.points


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deals", type=int, default=20000)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path("runs/equity_incumbent.json"))
    args = parser.parse_args()
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as pool:
        outcomes = list(pool.map(_play, range(args.deals), chunksize=64))
    model = DealModel.from_outcomes(outcomes)
    eq = Equity(model)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    eq.save(args.out)
    print(f"{args.deals} deals in {time.time() - t0:.1f}s; dealer_win={model.dealer_win:.4f}")
    print("V(0-0), team 0 deals:", eq.team0(0, 0, 0), " up 48:", eq.team0(48, 0, 0), " down 48:", eq.team0(0, 48, 0))
    try:  # cross-check against TuppiProject's solver on the same model
        from tuppi_valuation.equity import DealModel as VM, EquityTable
        from tuppi_rules import MatchScore, Team
        ref = EquityTable.build(VM(model.dealer_win, model.points_given_dealer, model.points_given_other))
        worst = 0.0
        for s0 in range(0, 52, 4):
            for s1 in ([0] if s0 else range(0, 52, 4)):
                for dealer in range(4):
                    a = eq.team0(s0, s1, dealer)
                    b = ref.equity(MatchScore(s0, s1), Team.TEAM_0, we_deal=(dealer % 2 == 0))
                    worst = max(worst, abs(a - b))
        print(f"max |difference| vs tuppi_valuation.equity: {worst:.2e}")
    except ImportError as exc:
        print("tuppi_valuation unavailable for cross-check:", exc)


if __name__ == "__main__":
    main()
