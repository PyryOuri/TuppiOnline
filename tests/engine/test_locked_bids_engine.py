"""project_target_v3 engine behaviour: locked bids on top of the v2 sooli rules.

During showing no seat sees any bid, the public event log carries only who has
bid, and at resolution the bids taken are revealed in seat order. Outcomes and
every later phase are exactly those of project_target_v2.
"""

from __future__ import annotations

import random

from tuppi_engine import (
    EnginePhase,
    EventType,
    ExplicitDeal,
    SooliDecisionAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    event_to_data,
    match_observation_for,
    observation_to_data,
)
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import Contract, MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK

V2, V3 = RulesetId.PROJECT_TARGET_V2, RulesetId.PROJECT_TARGET_V3


def _deal(rng):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


def _start(hands, dealer, ruleset, score=MatchScore(0, 0)):
    return begin_explicit_deal(
        create_match(initial_score=score, initial_dealer=dealer, match_ref="locked-test", ruleset_id=ruleset),
        ExplicitDeal(dealer=dealer, hands=hands))


def _chooser(rng, p_nolo=0.6, p_accept=0.5):
    def choose(state):
        actor = state.current_actor
        legal = match_observation_for(state, actor).legal_actions
        if state.phase is EnginePhase.SHOWING:
            nolo = [a for a in legal if a.declared_contract is Contract.NOLO]
            rami = [a for a in legal if a.declared_contract is Contract.RAMI]
            return rng.choice(nolo if nolo and (rng.random() < p_nolo or not rami) else rami)
        if state.phase is EnginePhase.SOOLI_OFFER:
            return SooliDecisionAction(seat=actor, play_sooli=rng.random() < p_accept)
        return rng.choice(legal)
    return choose


def test_bids_are_hidden_until_showing_resolves():
    rng = random.Random("v3-hidden")
    for i in range(200):
        state = _start(_deal(rng), dealer=i % 4, ruleset=V3)
        choose = _chooser(rng)
        while state.phase is EnginePhase.SHOWING:
            taken = len(state.active_deal.show_actions)
            for seat in range(4):
                obs = match_observation_for(state, seat)
                assert obs.show_actions == () and obs.publicly_shown_cards == ()
                assert obs.bids_locked == taken
                data = observation_to_data(obs)
                assert data["show_actions"] == [] and data["publicly_shown_cards"] == []
            deal_events = [e for e in state.public_events if e.deal_ref == state.active_deal.deal_ref]
            assert all(e.event_type is not EventType.SHOW_ACCEPTED for e in deal_events)
            locked = [e for e in deal_events if e.event_type is EventType.BID_LOCKED]
            assert [(e.payload.seat, e.payload.bid_index) for e in locked] == [
                (show.seat, index) for index, show in enumerate(state.active_deal.show_actions)]
            for event in locked:
                assert set(event_to_data(event)["payload"]) == {"bid_index", "seat"}
            state = apply_match_action(state, choose(state))
        # Resolution reveals every bid taken, in order, right before the contract.
        shows = state.active_deal.show_actions
        deal_events = [e for e in state.public_events if e.deal_ref == state.active_deal.deal_ref]
        types = [e.event_type for e in deal_events]
        n = types.count(EventType.BID_LOCKED)
        reveal_at = types.index(EventType.SHOW_ACCEPTED)
        assert types[reveal_at:reveal_at + n] == [EventType.SHOW_ACCEPTED] * n
        assert types[reveal_at + n] is EventType.CONTRACT_RESOLVED
        revealed = [(e.payload.seat, e.payload.shown_card, e.payload.declared_contract)
                    for e in deal_events[reveal_at:reveal_at + n]]
        assert revealed == [(s.seat, s.shown_card, s.declared_contract) for s in shows]
        for seat in range(4):
            assert match_observation_for(state, seat).show_actions == shows


def test_v3_plays_exactly_like_v2():
    """Same deals and actions: identical outcomes, scores and later events."""
    rng = random.Random("v3-equals-v2")
    for i in range(150):
        hands, dealer = _deal(rng), i % 4
        seed = rng.random()
        results = {}
        for ruleset in (V2, V3):
            state = _start(hands, dealer, ruleset)
            choose = _chooser(random.Random(seed))
            while state.phase in ACTIVE_PHASES:
                state = apply_match_action(state, choose(state))
            r = state.completed_deals[-1].public_result
            events = [e for e in r.events if e.event_type not in (EventType.BID_LOCKED, EventType.SHOW_ACCEPTED)]
            results[ruleset] = (r.outcome, r.deal_score, r.score_after, r.show_actions, r.sooli_decisions,
                                r.soolaaja, r.team_tricks,
                                [(e.event_type, e.payload) for e in events])
        assert results[V2] == results[V3]


def test_sooli_offers_follow_a_locked_rami():
    rng = random.Random("v3-sooli")
    seen_sooli = 0
    for i in range(200):
        state = _start(_deal(rng), dealer=i % 4, ruleset=V3)
        choose = _chooser(rng, p_nolo=0.3, p_accept=0.7)
        while state.phase in ACTIVE_PHASES:
            state = apply_match_action(state, choose(state))
        r = state.completed_deals[-1].public_result
        seen_sooli += r.soolaaja is not None
    assert seen_sooli > 20


def test_later_bids_never_exist():
    """A RAMI by the forehand ends showing: the other three seats never bid."""
    rng = random.Random("v3-first-rami")
    for i in range(40):
        state = _start(_deal(rng), dealer=i % 4, ruleset=V3)
        legal = match_observation_for(state, state.current_actor).legal_actions
        state = apply_match_action(state, next(a for a in legal if a.declared_contract is Contract.RAMI))
        assert state.phase is EnginePhase.SOOLI_OFFER
        assert len(state.active_deal.show_actions) == 1
        deal_events = [e for e in state.public_events if e.deal_ref == state.active_deal.deal_ref]
        assert [e.event_type for e in deal_events][:4] == [
            EventType.DEAL_STARTED, EventType.BID_LOCKED, EventType.SHOW_ACCEPTED, EventType.CONTRACT_RESOLVED]


def test_v1_and_v2_keep_sequential_showing():
    rng = random.Random("v3-others")
    for ruleset in (RulesetId.PROJECT_TARGET_V1, V2):
        state = _start(_deal(rng), dealer=1, ruleset=ruleset)
        legal = match_observation_for(state, state.current_actor).legal_actions
        state = apply_match_action(state, next(a for a in legal if a.declared_contract is Contract.NOLO))
        other = (state.current_actor + 1) % 4
        assert len(match_observation_for(state, other).show_actions) == 1
        assert match_observation_for(state, other).bids_locked == 0


def test_locked_bid_options_match_the_turn_options():
    """Any seat that has not bid may lock exactly the bids it will have at its turn."""
    from tuppi_engine import locked_bid_options
    rng = random.Random("v3-options")
    for i in range(60):
        state = _start(_deal(rng), dealer=i % 4, ruleset=V3)
        early = {seat: locked_bid_options(state.active_deal, seat) for seat in range(4)}
        choose = _chooser(rng)
        while state.phase is EnginePhase.SHOWING:
            actor = state.current_actor
            assert match_observation_for(state, actor).legal_actions == early[actor]
            assert locked_bid_options(state.active_deal, actor) == early[actor]
            state = apply_match_action(state, choose(state))
            assert locked_bid_options(state.active_deal, actor) == ()
    v2 = _start(_deal(rng), dealer=0, ruleset=V2)
    assert all(locked_bid_options(v2.active_deal, seat) == () for seat in range(4))
