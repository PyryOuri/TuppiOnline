from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pytest
from hypothesis import HealthCheck, settings

from tuppi_agents import (
    LADDER_PROFILE_KEYS,
    STRATEGIC_PROFILE_KEYS,
    construct_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_engine import (
    Action,
    EnginePhase,
    ExplicitDeal,
    MatchState,
    PlayCardAction,
    PlayerObservation,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    play_active_deal,
)
from tuppi_rules import (
    FULL_DECK,
    Card,
    Contract,
    MatchScore,
    Suit,
    card_from_code,
)


settings.register_profile(
    "agents_deterministic",
    max_examples=30,
    derandomize=True,
    database=None,
    deadline=None,
    suppress_health_check=(HealthCheck.too_slow, HealthCheck.data_too_large),
)
settings.load_profile("agents_deterministic")


_SUIT_LETTERS = {"H": Suit.HEARTS, "D": Suit.DIAMONDS, "C": Suit.CLUBS, "S": Suit.SPADES}


def card(code: str) -> Card:
    """Accept both ``H3`` and ``3H`` so hands can be written suit-grouped."""

    text = code.strip().upper()
    if text and text[0] in _SUIT_LETTERS:
        text = f"{text[1:]}{text[0]}"
    return card_from_code(text)


def cards(codes: Iterable[str]) -> tuple[Card, ...]:
    return tuple(card(code) for code in codes)


def suit_of(letter: str) -> Suit:
    return _SUIT_LETTERS[letter.strip().upper()]


def partition_deck(
    fixed: Mapping[int, Sequence[str]],
    forbid: Mapping[int, Sequence[str]] | None = None,
) -> tuple[tuple[Card, ...], ...]:
    """Complete an explicit partial deal into a valid 52-card partition.

    ``fixed`` pins the cards a test depends on, in the order given, which is
    also the engine's legal-action order for that seat. ``forbid`` keeps *filler*
    cards of the named suits away from a seat; pinned cards are exempt. That
    combination gives a test exact control over a seat's holding in one suit -
    including an empty holding, which is how a genuine public failure-to-follow
    event is constructed.
    """

    hands: dict[int, list[Card]] = {seat: list(cards(fixed.get(seat, ()))) for seat in range(4)}
    used = [item for hand in hands.values() for item in hand]
    if len(set(used)) != len(used):
        raise AssertionError("fixed hands repeat a card")
    forbidden = {
        seat: frozenset(suit_of(letter) for letter in (forbid or {}).get(seat, ()))
        for seat in range(4)
    }
    pinned = set(used)
    # Deal the most constrained cards first so that several simultaneous voids
    # stay satisfiable. The order is a pure function of the constraints.
    remaining = sorted(
        (item for item in FULL_DECK if item not in pinned),
        key=lambda item: (
            sum(1 for seat in range(4) if item.suit not in forbidden[seat]),
            FULL_DECK.index(item),
        ),
    )
    for item in remaining:
        candidates = sorted(
            (
                seat
                for seat in range(4)
                if len(hands[seat]) < 13 and item.suit not in forbidden[seat]
            ),
            key=lambda seat: (len(hands[seat]), seat),
        )
        if not candidates:
            raise AssertionError(f"no seat may receive {item}; loosen the constraints")
        hands[candidates[0]].append(item)
    if any(len(hand) != 13 for hand in hands.values()):
        raise AssertionError("deck partition did not fill every hand")
    return tuple(tuple(hands[seat]) for seat in range(4))


def start_deal(
    hands: tuple[tuple[Card, ...], ...],
    *,
    dealer: int = 0,
    score: MatchScore | None = None,
    match_ref: str = "agents-test",
) -> MatchState:
    state = create_match(
        initial_score=score or MatchScore(),
        initial_dealer=dealer,
        match_ref=match_ref,
    )
    return begin_explicit_deal(state, ExplicitDeal(dealer=dealer, hands=hands))


def show_action_for(state: MatchState, contract: Contract) -> ShowAction:
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    return next(
        action
        for action in observation.legal_actions
        if isinstance(action, ShowAction) and action.declared_contract is contract
    )


def play_action_for(state: MatchState, code: str) -> PlayCardAction:
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    target = card(code)
    matches = [
        action
        for action in observation.legal_actions
        if isinstance(action, PlayCardAction) and action.card == target
    ]
    if not matches:
        raise AssertionError(
            f"seat {actor} cannot legally play {code}; "
            f"legal={[a.card.to_code() for a in observation.legal_actions]}"
        )
    return matches[0]


def build_position(
    hands: tuple[tuple[Card, ...], ...],
    *,
    dealer: int = 0,
    score: MatchScore | None = None,
    show_contracts: Sequence[Contract] = (Contract.NOLO,) * 4,
    plays: Sequence[str] = (),
) -> MatchState:
    """Drive an explicit deal to a target position with explicit actions."""

    state = start_deal(hands, dealer=dealer, score=score)
    for contract in show_contracts:
        state = apply_match_action(state, show_action_for(state, contract))
    for code in plays:
        state = apply_match_action(state, play_action_for(state, code))
    return state


def acting_observation(state: MatchState) -> PlayerObservation:
    actor = state.current_actor
    assert actor is not None, "position is not awaiting an action"
    return match_observation_for(state, actor)


def policy(profile_key: str, seat: int = 0):
    specification = phase4_specifications_by_profile_key()[profile_key]
    return construct_agent(specification, seat=seat)


def homogeneous_agents(profile_key: str) -> tuple[Action, ...]:
    specification = phase4_specifications_by_profile_key()[profile_key]
    return tuple(construct_agent(specification, seat=seat) for seat in range(4))


def run_full_deal(
    profile_key: str,
    hands: tuple[tuple[Card, ...], ...],
    *,
    dealer: int = 0,
    score: MatchScore | None = None,
) -> MatchState:
    agents = homogeneous_agents(profile_key)
    state = start_deal(hands, dealer=dealer, score=score)
    return play_active_deal(state, agents)


def decisions_of(state: MatchState, agents) -> list[tuple[int, Action]]:
    """Replay a deal, returning every acting seat and the action it chose."""

    taken: list[tuple[int, Action]] = []
    current = state
    while current.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = current.current_actor
        assert actor is not None
        observation = match_observation_for(current, actor)
        action = agents[actor].choose_action(observation)
        taken.append((actor, action))
        current = apply_match_action(current, action)
    return taken


@pytest.fixture(scope="session")
def ladder_keys() -> tuple[str, ...]:
    return LADDER_PROFILE_KEYS


@pytest.fixture(scope="session")
def strategic_keys() -> tuple[str, ...]:
    return STRATEGIC_PROFILE_KEYS
