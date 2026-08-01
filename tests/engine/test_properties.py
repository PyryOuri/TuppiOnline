from __future__ import annotations

from hypothesis import given, settings, strategies as st

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    InvalidActionError,
    PlayCardAction,
    apply_match_action,
    match_observation_for,
)
from tuppi_rules import FULL_DECK, MatchScore, card_to_code

from .conftest import apply_first_legal, resolve_all_nolo, run_first_legal, start_match_deal


dealers = st.integers(min_value=0, max_value=3)
deck_permutations = st.permutations(FULL_DECK)
nonterminal_scores = st.one_of(
    st.just(MatchScore()),
    st.sampled_from(tuple(MatchScore(points, 0) for points in range(4, 52, 4))),
    st.sampled_from(tuple(MatchScore(0, points) for points in range(4, 52, 4))),
)


def partition(cards):
    return tuple(tuple(cards[seat * 13 : (seat + 1) * 13]) for seat in range(4))


@given(cards=deck_permutations, dealer=dealers)
def test_property_full_deck_partitions_construct_valid_immutable_deals(
    cards, dealer: int
) -> None:
    hands = partition(cards)
    deal = ExplicitDeal(dealer=dealer, hands=hands)
    assert deal.hands == hands
    assert len(deal.hands) == 4
    assert all(len(hand) == 13 for hand in deal.hands)
    assert len({card for hand in deal.hands for card in hand}) == 52


@given(cards=deck_permutations, dealer=dealers, step_count=st.integers(0, 24))
@settings(max_examples=20)
def test_property_observation_privacy_across_random_valid_prefixes(
    cards, dealer: int, step_count: int
) -> None:
    state = start_match_deal(hands=partition(cards), dealer=dealer)
    for _ in range(step_count):
        if state.phase not in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            break
        state = apply_first_legal(state)
    active = state.active_deal
    assert active is not None
    public_cards = {
        action.shown_card for action in active.show_actions
    } | {
        play.card
        for trick in active.completed_tricks
        for play in trick.plays
    } | {play.card for play in active.current_trick}
    for seat in range(4):
        observation = match_observation_for(state, seat)
        reachable_cards = set(observation.own_hand)
        reachable_cards.update(action.shown_card for action in observation.show_actions)
        reachable_cards.update(
            play.card
            for trick in observation.completed_tricks
            for play in trick.plays
        )
        reachable_cards.update(play.card for play in observation.current_trick)
        assert reachable_cards <= set(active.hands[seat]) | public_cards


@given(cards=deck_permutations, dealer=dealers, data=st.data())
@settings(max_examples=20)
def test_property_every_accepted_play_removes_exactly_one_card_and_conserves_52(
    cards, dealer: int, data
) -> None:
    state = resolve_all_nolo(start_match_deal(hands=partition(cards), dealer=dealer))
    actor = state.current_actor
    observation = match_observation_for(state, actor)
    action = data.draw(st.sampled_from(observation.legal_actions))
    before = state.active_deal
    state = apply_match_action(state, action)
    after = state.active_deal
    assert before is not None and after is not None
    assert len(before.hands[actor]) - len(after.hands[actor]) == 1  # type: ignore[index]
    for seat in range(4):
        if seat != actor:
            assert after.hands[seat] == before.hands[seat]
    played_count = sum(len(trick.plays) for trick in after.completed_tricks) + len(
        after.current_trick
    )
    assert sum(len(hand) for hand in after.hands) + played_count == 52


@given(cards=deck_permutations, dealer=dealers)
@settings(max_examples=10)
def test_property_complete_first_legal_deal_has_52_distinct_plays_and_13_tricks(
    cards, dealer: int
) -> None:
    state = run_first_legal(start_match_deal(hands=partition(cards), dealer=dealer))
    result = state.completed_deals[-1].public_result
    plays = tuple(play for trick in result.completed_tricks for play in trick.plays)
    assert len(result.completed_tricks) == 13
    assert all(len(trick.plays) == 4 for trick in result.completed_tricks)
    assert len(plays) == 52
    assert len({play.card for play in plays}) == 52
    assert sum(result.team_tricks) == 13
    assert not (result.score_after.team0 > 0 and result.score_after.team1 > 0)


@given(cards=deck_permutations, dealer=dealers, score=nonterminal_scores)
@settings(max_examples=12)
def test_property_complete_deal_preserves_one_sided_rising_score(
    cards, dealer: int, score: MatchScore
) -> None:
    state = run_first_legal(
        start_match_deal(hands=partition(cards), dealer=dealer, score=score)
    )
    result = state.completed_deals[-1].public_result
    assert result.score_before == score
    assert result.score_after.team0 == 0 or result.score_after.team1 == 0


@given(cards=deck_permutations, dealer=dealers, steps=st.integers(0, 40))
@settings(max_examples=15)
def test_property_team_trick_totals_track_completed_trick_count_and_actions_exist(
    cards, dealer: int, steps: int
) -> None:
    state = start_match_deal(hands=partition(cards), dealer=dealer)
    for _ in range(steps):
        if state.phase not in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            break
        actor = state.current_actor
        observation = match_observation_for(state, actor)
        assert observation.legal_actions
        state = apply_match_action(state, observation.legal_actions[0])
        assert sum(state.active_deal.team_tricks) == len(  # type: ignore[union-attr]
            state.active_deal.completed_tricks  # type: ignore[union-attr]
        )


@given(cards=deck_permutations, dealer=dealers)
@settings(max_examples=8)
def test_property_every_enumerated_legal_action_is_accepted(cards, dealer: int) -> None:
    showing = start_match_deal(hands=partition(cards), dealer=dealer)
    actor = showing.current_actor
    actions = match_observation_for(showing, actor).legal_actions
    assert actions
    for action in actions:
        result = apply_match_action(showing, action)
        assert result != showing

    playing = resolve_all_nolo(showing)
    actor = playing.current_actor
    actions = match_observation_for(playing, actor).legal_actions
    assert actions
    for action in actions:
        result = apply_match_action(playing, action)
        assert result.active_deal.hands[actor] != playing.active_deal.hands[actor]  # type: ignore[index,union-attr]


@given(cards=deck_permutations, dealer=dealers, data=st.data())
@settings(max_examples=20)
def test_property_clearly_illegal_follow_suit_action_is_rejected(
    cards, dealer: int, data
) -> None:
    state = resolve_all_nolo(start_match_deal(hands=partition(cards), dealer=dealer))
    active = state.active_deal
    assert active is not None
    leader = state.current_actor
    follower = (leader + 1) % 4  # type: ignore[operator]
    candidates = [
        card
        for card in active.hands[leader]  # type: ignore[index]
        if any(other.suit is card.suit for other in active.hands[follower])
        and any(other.suit is not card.suit for other in active.hands[follower])
    ]
    if not candidates:
        return
    lead = data.draw(st.sampled_from(candidates))
    state = apply_match_action(state, PlayCardAction(leader, lead))  # type: ignore[arg-type]
    illegal = data.draw(
        st.sampled_from(
            [card for card in active.hands[follower] if card.suit is not lead.suit]
        )
    )
    try:
        apply_match_action(state, PlayCardAction(follower, illegal))
    except InvalidActionError:
        pass
    else:
        raise AssertionError("off-suit play was accepted despite a held led-suit card")
