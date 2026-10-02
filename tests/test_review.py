"""The after-deal review prices moves as the live bot does (tuppi_ai/review.py)."""

import math
import random

from tuppi_ai.incumbent import incumbent_agents
from tuppi_ai.review import DealReviewer


def test_best_reviewer_uses_the_live_rollouts():
    reviewer = DealReviewer.best(worlds=16, confirm_worlds=32)
    assert reviewer._team_mlp is not None
    assert reviewer.reviewer_id.endswith(".v2")


def test_review_of_real_decisions_is_well_formed():
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    reviewer = DealReviewer.best(worlds=16, confirm_worlds=32)
    agents = incumbent_agents()
    rng = random.Random(4)
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="review-test",
                     ruleset_id=RulesetId.PROJECT_TARGET_V3),
        ExplicitDeal(dealer=0, hands=hands))
    reviewed = 0
    while reviewed < 6 and state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        action = agents[seat].choose_action(observation)
        item = reviewer.review_one(reviewed, observation, action)
        if len(observation.legal_actions) < 2:
            assert item is None
        else:
            assert math.isfinite(item.cost) and item.standard_error >= 0
            assert item.recommended in [a for a in range(156)]
            reviewed += 1
        state = apply_match_action(state, action)
    assert reviewed > 0
