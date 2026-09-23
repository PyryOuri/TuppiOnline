"""The best agent plays complete deals legally through the authoritative engine."""

from __future__ import annotations

import random

from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
                          create_match, match_observation_for)
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore
from tuppi_rules.cards import FULL_DECK

from tuppi_ai.best import EQUITY, ROLLOUT, best_agents


def test_model_files_are_tracked_and_present():
    assert ROLLOUT.exists() and EQUITY.exists()


def test_best_agent_plays_legal_deals():
    agents = best_agents(worlds=16)
    rng = random.Random("best-smoke")
    with trusted_transitions():
        for i in range(3):
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            state = begin_explicit_deal(create_match(initial_score=MatchScore(0, 0), initial_dealer=i % 4,
                                                     match_ref="best-smoke"), ExplicitDeal(dealer=i % 4, hands=hands))
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                action = agents[seat].choose_action(obs)
                assert action in obs.legal_actions
                state = apply_match_action(state, action)
