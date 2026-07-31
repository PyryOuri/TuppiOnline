from __future__ import annotations

from hypothesis import given, strategies as st

from tuppi_rules import (
    FULL_DECK,
    Card,
    MatchScore,
    PlayedCard,
    Suit,
    Team,
    card_from_code,
    card_from_index,
    card_to_code,
    card_to_index,
    legal_cards,
    partner_for_seat,
    rotate_dealer,
    score_nolo,
    score_rami,
    team_for_seat,
    transition_rising_score,
    trick_winner,
)

cards = st.sampled_from(FULL_DECK)
suits = st.sampled_from(tuple(Suit))
teams = st.sampled_from(tuple(Team))


@given(card=cards)
def test_property_card_representation_round_trips(card: Card) -> None:
    assert card_from_index(card_to_index(card)) == card
    assert card_from_code(card_to_code(card)) == card


@given(selected=st.lists(cards, min_size=0, max_size=52, unique=True).map(tuple))
def test_property_distinct_cards_have_distinct_stable_representations(
    selected: tuple[Card, ...],
) -> None:
    assert len({card_to_index(card) for card in selected}) == len(selected)
    assert len({card_to_code(card) for card in selected}) == len(selected)


@given(seat=st.integers(min_value=0, max_value=3))
def test_property_partnership_is_symmetric_and_partner_of_partner_is_self(
    seat: int,
) -> None:
    partner = partner_for_seat(seat)
    assert partner_for_seat(partner) == seat
    assert team_for_seat(partner) is team_for_seat(seat)


@given(dealer=st.integers(min_value=0, max_value=3))
def test_property_dealer_rotation_visits_every_seat_and_cycles(dealer: int) -> None:
    observed = []
    current = dealer
    for _ in range(4):
        observed.append(current)
        current = rotate_dealer(current)
    assert set(observed) == set(range(4))
    assert current == dealer


@given(
    hand=st.lists(cards, min_size=1, max_size=13, unique=True).map(tuple),
    led_suit=st.one_of(st.none(), suits),
)
def test_property_legal_cards_obey_exact_follow_suit_invariant(
    hand: tuple[Card, ...], led_suit: Suit | None
) -> None:
    legal = legal_cards(hand, led_suit)
    assert legal
    assert legal.issubset(hand)
    if led_suit is None:
        assert legal == frozenset(hand)
        return
    matching = frozenset(card for card in hand if card.suit is led_suit)
    assert legal == (matching if matching else frozenset(hand))


@given(
    selected=st.lists(cards, min_size=4, max_size=4, unique=True).map(tuple),
    leader=st.integers(min_value=0, max_value=3),
)
def test_property_trick_winner_played_highest_led_suit_card(
    selected: tuple[Card, ...], leader: int
) -> None:
    plays = tuple(
        PlayedCard((leader + offset) % 4, card)
        for offset, card in enumerate(selected)
    )
    winner = trick_winner(plays)
    winner_play = next(play for play in plays if play.seat == winner)
    led_suit = plays[0].card.suit
    assert winner_play.card.suit is led_suit
    assert winner_play.card.rank.value == max(
        play.card.rank.value for play in plays if play.card.suit is led_suit
    )


@given(team0_tricks=st.integers(min_value=0, max_value=13))
def test_property_nolo_score_formula_for_every_valid_split(team0_tricks: int) -> None:
    team1_tricks = 13 - team0_tricks
    result = score_nolo(team0_tricks, team1_tricks)
    assert result.points == 4 * (7 - min(team0_tricks, team1_tricks))


@given(declaring_team=teams, declaring_tricks=st.integers(min_value=0, max_value=13))
def test_property_rami_score_formula_for_every_valid_total(
    declaring_team: Team, declaring_tricks: int
) -> None:
    opponent_tricks = 13 - declaring_tricks
    totals = (
        (declaring_tricks, opponent_tricks)
        if declaring_team is Team.TEAM_0
        else (opponent_tricks, declaring_tricks)
    )
    result = score_rami(declaring_team, *totals)
    expected = (
        4 * (declaring_tricks - 6)
        if declaring_tricks >= 7
        else 8 * (opponent_tricks - 6)
    )
    assert result.points == expected


@st.composite
def nonterminal_match_scores(draw):
    state = draw(st.sampled_from(("table", "team0", "team1")))
    if state == "table":
        return MatchScore()
    value = draw(st.integers(min_value=1, max_value=51))
    return MatchScore(value, 0) if state == "team0" else MatchScore(0, value)


@st.composite
def valid_deal_scores(draw):
    contract = draw(st.sampled_from(("NOLO", "RAMI")))
    team0_tricks = draw(st.integers(min_value=0, max_value=13))
    team1_tricks = 13 - team0_tricks
    if contract == "NOLO":
        return score_nolo(team0_tricks, team1_tricks)
    return score_rami(draw(teams), team0_tricks, team1_tricks)


@given(current=nonterminal_match_scores(), deal_score=valid_deal_scores())
def test_property_rising_transition_preserves_one_positive_team_invariant(
    current, deal_score
) -> None:
    result = transition_rising_score(current, deal_score)
    assert result.team0 >= 0 and result.team1 >= 0
    assert not (result.team0 > 0 and result.team1 > 0)
