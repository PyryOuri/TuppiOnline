"""project_target_v2 engine behaviour: sooli offers, exchange, three-player play, scoring."""

from __future__ import annotations

import random

import pytest

from tuppi_engine import (
    EnginePhase,
    EventType,
    ExplicitDeal,
    InvalidActionError,
    PlayCardAction,
    ShowAction,
    SooliDecisionAction,
    SooliExchangeAction,
    WrongActorError,
    WrongPhaseError,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.events import DealOutcome
from tuppi_rules import Card, Contract, MatchScore, Rank, RulesetId, Suit, Team
from tuppi_rules.cards import FULL_DECK
from tuppi_rules.sooli import sooli_rank_value

V1, V2 = RulesetId.PROJECT_TARGET_V1, RulesetId.PROJECT_TARGET_V2


def _deal(rng):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


def _start(hands, dealer=0, score=MatchScore(0, 0), ruleset=V2):
    return begin_explicit_deal(
        create_match(initial_score=score, initial_dealer=dealer, match_ref="sooli-test", ruleset_id=ruleset),
        ExplicitDeal(dealer=dealer, hands=hands))


def _declare_rami_at(state, seat):
    """Everyone before `seat` shows NOLO, `seat` shows RAMI (first legal cards)."""
    while state.phase is EnginePhase.SHOWING:
        actor = state.current_actor
        legal = match_observation_for(state, actor).legal_actions
        want = Contract.RAMI if actor == seat else Contract.NOLO
        state = apply_match_action(state, next(a for a in legal if a.declared_contract is want))
    return state


def _random_play(state, rng, p_accept=0.5):
    """Play the active deal to completion with random legal actions."""
    from tuppi_engine.state import ACTIVE_PHASES
    while state.phase in ACTIVE_PHASES:
        actor = state.current_actor
        legal = match_observation_for(state, actor).legal_actions
        if state.phase is EnginePhase.SOOLI_OFFER:
            action = SooliDecisionAction(seat=actor, play_sooli=rng.random() < p_accept)
        else:
            action = rng.choice(legal)
        state = apply_match_action(state, action)
    return state


def test_random_v2_deals_are_valid_throughout():
    """Every accepted state is revalidated by the engine (not in trusted mode)."""
    rng = random.Random("v2-random")
    outcomes = set()
    for i in range(120):
        state = _start(_deal(rng), dealer=i % 4)
        state = _random_play(state, rng, p_accept=0.6)
        outcomes.add(state.completed_deals[-1].public_result.outcome)
    assert DealOutcome.SOOLI_LOST in outcomes and DealOutcome.NOLO in outcomes


def test_nolo_has_no_sooli_and_matches_v1():
    rng = random.Random("v2-nolo")
    hands = _deal(rng)
    results = []
    for ruleset in (V1, V2):
        state = _start(hands, dealer=1, ruleset=ruleset)
        while state.phase is EnginePhase.SHOWING:
            legal = match_observation_for(state, state.current_actor).legal_actions
            state = apply_match_action(state, next(a for a in legal if a.declared_contract is Contract.NOLO))
        assert state.phase is EnginePhase.TRICK_PLAY
        r2 = random.Random("same-play")
        while state.phase is EnginePhase.TRICK_PLAY:
            state = apply_match_action(state, r2.choice(match_observation_for(state, state.current_actor).legal_actions))
        results.append(state.completed_deals[-1].public_result)
    assert results[0].completed_tricks == results[1].completed_tricks
    assert results[0].deal_score == results[1].deal_score and results[0].score_after == results[1].score_after
    assert all(e.ruleset_id is V2 for e in results[1].events)


def test_declined_sooli_continues_exactly_as_v1():
    rng = random.Random("v2-decline")
    hands = _deal(rng)
    finals = []
    for ruleset in (V1, V2):
        state = _declare_rami_at(_start(hands, dealer=3, ruleset=ruleset), seat=1)
        if ruleset is V2:
            assert state.phase is EnginePhase.SOOLI_OFFER and state.current_actor == 2  # declarer + 1
            obs = match_observation_for(state, 2)
            assert obs.legal_actions == (SooliDecisionAction(2, False), SooliDecisionAction(2, True))
            state = apply_match_action(state, SooliDecisionAction(seat=2, play_sooli=False))
            assert state.phase is EnginePhase.SOOLI_OFFER and state.current_actor == 0  # declarer + 3
            with pytest.raises(WrongActorError):
                apply_match_action(state, SooliDecisionAction(seat=2, play_sooli=True))
            state = apply_match_action(state, SooliDecisionAction(seat=0, play_sooli=False))
        assert state.phase is EnginePhase.TRICK_PLAY and state.current_actor == 0  # (declarer - 1) mod 4
        r2 = random.Random("same")
        while state.phase is EnginePhase.TRICK_PLAY:
            state = apply_match_action(state, r2.choice(match_observation_for(state, state.current_actor).legal_actions))
        finals.append(state.completed_deals[-1].public_result)
    assert finals[0].completed_tricks == finals[1].completed_tricks
    assert finals[0].deal_score == finals[1].deal_score
    assert finals[1].sooli_decisions == ((2, False), (0, False)) and finals[1].soolaaja is None
    kinds = [e.event_type for e in finals[1].events]
    assert kinds.count(EventType.SOOLI_DECISION) == 2 and EventType.SOOLI_EXCHANGED not in kinds


def test_exchange_flow_and_privacy():
    rng = random.Random("v2-exchange")
    hands = _deal(rng)
    state = _declare_rami_at(_start(hands, dealer=0), seat=1)  # declarer 1; defenders 2 then 0
    state = apply_match_action(state, SooliDecisionAction(seat=2, play_sooli=True))
    assert state.phase is EnginePhase.SOOLI_GIVE and state.current_actor == 2
    deal = state.active_deal
    give = deal.hands[2][0]
    with pytest.raises(InvalidActionError):  # not in hand
        apply_match_action(state, SooliExchangeAction(seat=2, card=deal.hands[1][0]))
    with pytest.raises(WrongPhaseError):
        apply_match_action(state, PlayCardAction(seat=2, card=give))
    state = apply_match_action(state, SooliExchangeAction(seat=2, card=give))
    assert state.phase is EnginePhase.SOOLI_RETURN and state.current_actor == 0  # partner
    partner_obs = match_observation_for(state, 0)
    assert give in partner_obs.own_hand and partner_obs.sooli_given_card == give
    assert SooliExchangeAction(seat=0, card=give) not in partner_obs.legal_actions
    with pytest.raises(InvalidActionError):  # may not return the received card
        apply_match_action(state, SooliExchangeAction(seat=0, card=give))
    back = state.active_deal.hands[0][0]
    state = apply_match_action(state, SooliExchangeAction(seat=0, card=back))
    assert state.phase is EnginePhase.SOOLI_PLAY and state.current_actor == 1  # declarer leads
    for seat in range(4):
        obs = match_observation_for(state, seat)
        assert obs.soolaaja == 2 and obs.sooli_exchanged
        if seat in (2, 0):
            assert (obs.sooli_given_card, obs.sooli_returned_card) == (give, back)
        else:
            assert obs.sooli_given_card is None and obs.sooli_returned_card is None
    assert back in state.active_deal.hands[2] and give not in state.active_deal.hands[2]
    public = [e for e in state.public_events if e.event_type is EventType.SOOLI_EXCHANGED]
    assert len(public) == 1 and not any(isinstance(getattr(public[0].payload, f, None), Card)
                                        for f in ("soolaaja", "partner"))


def _to_sooli_play(hands, dealer, declarer_seat, soolaaja_first=True):
    state = _declare_rami_at(_start(hands, dealer=dealer), seat=declarer_seat)
    first, second = (declarer_seat + 1) % 4, (declarer_seat + 3) % 4
    if soolaaja_first:
        state = apply_match_action(state, SooliDecisionAction(seat=first, play_sooli=True))
        solo = first
    else:
        state = apply_match_action(state, SooliDecisionAction(seat=first, play_sooli=False))
        state = apply_match_action(state, SooliDecisionAction(seat=second, play_sooli=True))
        solo = second
    state = apply_match_action(state, SooliExchangeAction(seat=solo, card=state.active_deal.hands[solo][0]))
    partner = (solo + 2) % 4
    received = state.active_deal.sooli_given
    ret = next(c for c in state.active_deal.hands[partner] if c != received)
    state = apply_match_action(state, SooliExchangeAction(seat=partner, card=ret))
    return state, solo


def test_play_order_ace_low_and_early_end():
    rng = random.Random("v2-order")
    for trial in range(30):
        hands = _deal(rng)
        declarer = rng.randrange(4)
        state, solo = _to_sooli_play(hands, dealer=(declarer + 1) % 4, declarer_seat=declarer,
                                     soolaaja_first=rng.random() < 0.5)
        partner = (solo + 2) % 4
        other = (declarer + 2) % 4
        leader = declarer
        while state.phase is EnginePhase.SOOLI_PLAY:
            order = (leader, other if leader == declarer else declarer, solo)
            plays = []
            for seat in order:
                assert state.current_actor == seat
                action = rng.choice(match_observation_for(state, seat).legal_actions)
                plays.append(action.card)
                state = apply_match_action(state, action)
            led = plays[0].suit
            winner_pos = max((i for i in range(3) if plays[i].suit is led), key=lambda i: sooli_rank_value(plays[i]))
            winner = order[winner_pos]
            if winner == solo:
                break
            leader = winner
        result = state.completed_deals[-1].public_result
        assert result.soolaaja == solo and result.completed_tricks == ()
        assert all(p.seat != partner for t in result.sooli_tricks for p in t.plays)
        last = result.sooli_tricks[-1]
        if last.winner == solo:
            assert result.outcome is DealOutcome.SOOLI_LOST
            assert result.deal_score.winner_team is Team(declarer % 2) and result.deal_score.points == 24
        else:
            assert len(result.sooli_tricks) == 13 and result.outcome is DealOutcome.SOOLI_WON


@pytest.mark.parametrize("before, after", [
    (MatchScore(0, 0), MatchScore(0, 24)),    # level: soolaaja's team becomes up
    (MatchScore(0, 8), MatchScore(0, 32)),    # soolaaja's team up: adds 24
    (MatchScore(8, 0), MatchScore(0, 0)),     # soolaaja's team down: only resets
    (MatchScore(0, 28), MatchScore(0, 52)),   # reaches the target: match over
])
def test_sure_success_scores_24_through_the_rising_score(before, after):
    """Soolaaja holds A, 2, 3 of every suit and a 4: with ace low it can always duck."""
    low = [Card(s, Rank(r)) for s in (Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES) for r in (14, 2, 3)]
    four = Card(Suit.HEARTS, Rank(4))
    solo_hand = tuple(low + [four])
    rest = [c for c in FULL_DECK if c not in solo_hand]
    random.Random(4).shuffle(rest)
    # dealer 3 -> forehand 0; seat 0 declares RAMI; defender 1 plays sooli; seat 3 is the partner.
    hands = (tuple(rest[0:13]), solo_hand, tuple(rest[13:26]), tuple(rest[26:39]))
    state = _declare_rami_at(_start(hands, dealer=3, score=before), seat=0)
    state = apply_match_action(state, SooliDecisionAction(seat=1, play_sooli=True))
    state = apply_match_action(state, SooliExchangeAction(seat=1, card=four))
    back = min((c for c in state.active_deal.hands[3] if c != four), key=sooli_rank_value)
    state = apply_match_action(state, SooliExchangeAction(seat=3, card=back))
    rng = random.Random(9)
    while state.phase is EnginePhase.SOOLI_PLAY:
        seat = state.current_actor
        legal = match_observation_for(state, seat).legal_actions
        action = min(legal, key=lambda a: sooli_rank_value(a.card)) if seat == 1 else rng.choice(legal)
        state = apply_match_action(state, action)
    result = state.completed_deals[-1].public_result
    assert result.outcome is DealOutcome.SOOLI_WON and len(result.sooli_tricks) == 13
    assert all(t.winner in (0, 2) for t in result.sooli_tricks)
    assert result.deal_score.winner_team is Team.TEAM_1 and result.deal_score.points == 24
    assert result.score_after == after
    assert state.phase is (EnginePhase.MATCH_COMPLETE if after.team1 >= 52 else EnginePhase.DEAL_COMPLETE)


def test_v1_rejects_sooli():
    rng = random.Random("v1-no-sooli")
    state = _declare_rami_at(_start(_deal(rng), dealer=0, ruleset=V1), seat=1)
    assert state.phase is EnginePhase.TRICK_PLAY
    with pytest.raises((WrongPhaseError, InvalidActionError)):
        apply_match_action(state, SooliDecisionAction(seat=2, play_sooli=True))


def test_research_result_keeps_the_exchange_private():
    rng = random.Random("v2-research")
    state, solo = _to_sooli_play(_deal(rng), dealer=0, declarer_seat=1)
    given, returned = state.active_deal.sooli_given, state.active_deal.sooli_returned
    state = _random_play(state, rng)
    research = state.completed_deals[-1]
    assert (research.sooli_given, research.sooli_returned) == (given, returned)
    assert not hasattr(research.public_result, "sooli_given")
