"""partner_aware_lead_v3: the RAMI refinements over partner_aware_lead_v2."""

from __future__ import annotations

import random

import pytest

from tuppi_agents.improved_registry import construct_improved_agent
from tuppi_agents.refined_play import (CASH_REASON_CODE, SECOND_HAND_REASON_CODE, UNDERLEAD_REASON_CODE,
                                       certain_winner)
from tuppi_agents.sooli import SooliFallbackAgent
from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                          match_observation_for)
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import Card, Contract, MatchScore, Rank, RulesetId, Suit
from tuppi_rules.cards import FULL_DECK

REFINED = {CASH_REASON_CODE, UNDERLEAD_REASON_CODE, SECOND_HAND_REASON_CODE}


def test_certain_winner() -> None:
    ace, king, queen = (Card(suit=Suit.SPADES, rank=r) for r in (Rank.ACE, Rank.KING, Rank.QUEEN))
    assert certain_winner(ace, (ace,), frozenset())
    assert not certain_winner(king, (king,), frozenset())
    assert certain_winner(king, (king,), frozenset({ace}))
    assert certain_winner(queen, (king, queen), frozenset({ace}))
    assert not certain_winner(queen, (queen,), frozenset({ace}))


def _decisions(deals: int = 30):
    """(observation, v2 decision, v3 decision) at every v3 trick-play and showing decision."""
    v2 = {s: construct_improved_agent("partner_aware_lead_v2", seat=s) for s in range(4)}
    v3 = {s: construct_improved_agent("partner_aware_lead_v3", seat=s) for s in range(4)}
    play = {s: SooliFallbackAgent(a) for s, a in v3.items()}
    for index in range(deals):
        rng = random.Random(f"refined|{index}")
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
        state = begin_explicit_deal(
            create_match(initial_score=MatchScore(0, 0), initial_dealer=index % 4, match_ref="refined",
                         ruleset_id=RulesetId.PROJECT_TARGET_V3),
            ExplicitDeal(dealer=index % 4, hands=hands))
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            observation = match_observation_for(state, seat)
            if state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                yield observation, v2[seat].decide(observation, diagnostics=True), \
                    v3[seat].decide(observation, diagnostics=True)
            state = apply_match_action(state, play[seat].choose_action(observation))


def test_v3_departs_from_v2_only_through_a_refinement_in_rami_play() -> None:
    changed = 0
    for observation, d2, d3 in _decisions():
        selected = next(c for c in d3.diagnostics.candidates if c.selected)
        fired = REFINED & set(selected.reason_codes)
        if d3.action == d2.action:
            assert not fired
            continue
        changed += 1
        assert observation.phase is EnginePhase.TRICK_PLAY
        assert observation.contract is Contract.RAMI
        assert len(fired) == 1
    assert changed > 0


@pytest.mark.parametrize("profile_key", ["partner_aware_lead_v3"])
def test_refined_policy_is_deterministic(profile_key) -> None:
    a = list(_decisions(deals=4))
    b = list(_decisions(deals=4))
    assert [x[2].action for x in a] == [x[2].action for x in b]
