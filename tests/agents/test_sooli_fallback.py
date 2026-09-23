"""SooliFallbackAgent: complete v2/v3 matches with the default agents, all actions legal."""

from __future__ import annotations

import random

import pytest

from tuppi_agents.sooli import SooliFallbackAgent
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    FirstLegalActionAgent,
    SooliDecisionAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK


class _AlwaysSooli:
    """Accept every offer (so sooli play is exercised), else first legal."""

    def choose_action(self, observation):
        if observation.phase is EnginePhase.SOOLI_OFFER:
            return SooliDecisionAction(seat=observation.observing_seat, play_sooli=True)
        return observation.legal_actions[0]


@pytest.mark.parametrize("ruleset", [RulesetId.PROJECT_TARGET_V2, RulesetId.PROJECT_TARGET_V3])
def test_fallback_plays_legal_complete_matches(ruleset):
    from tuppi_agents.void_lead import construct_void_lead_agent
    rng = random.Random(f"fallback-{ruleset.value}")
    agents = {s: SooliFallbackAgent(construct_void_lead_agent(s)) for s in range(4)}
    offers = soolis = 0
    for match in range(2):
        state = create_match(initial_score=MatchScore(0, 0), initial_dealer=match, match_ref=f"fb-{match}",
                             ruleset_id=ruleset)
        while not state.terminal:
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            state = begin_explicit_deal(state, ExplicitDeal(
                dealer=state.dealer, hands=tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))))
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                offers += state.phase is EnginePhase.SOOLI_OFFER
                # every other deal, force a sooli to exercise the exchange and the play
                actor = _AlwaysSooli() if (state.phase is EnginePhase.SOOLI_OFFER and len(state.completed_deals) % 2) \
                    else agents[seat]
                action = actor.choose_action(obs)
                assert action in obs.legal_actions
                state = apply_match_action(state, action)
            soolis += state.completed_deals[-1].public_result.soolaaja is not None
    assert offers > 0 and soolis > 0
