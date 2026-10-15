"""Seat-relative, observation-only feature encoding for Phase 6.

The encoder deliberately accepts only ``PlayerObservation``.  It has no
conversion from ``MatchState`` or ``DealState``: the centralized critic owns
that private-state boundary during training, while the actor never crosses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from tuppi_engine import PlayCardAction, PlayerObservation, ShowAction
from tuppi_engine.state import EnginePhase
from tuppi_rules import Card, Contract, Team, card_to_index, team_for_seat

from .errors import LearningDependencyError, ObservationBoundaryError


ENCODER_VERSION = "seat_relative_observation_encoder_v2"
ACTION_ENCODER_VERSION = "legal_action_card_contract_v1"
PREPROCESSING_VERSION = "tuppi_learning.preprocessing.v2"

CARD_VOCAB_SIZE = 53  # 52 cards plus padding
CARD_PADDING = 52
MAX_HISTORY_EVENTS = 56  # four shows plus 52 plays
MAX_CURRENT_TRICK = 3
CONTEXT_DIM = 32
RELATIVE_ROLE_COUNT = 4
ACTION_KIND_SHOW = 1
ACTION_KIND_PLAY = 2
CONTRACT_NONE = 0
CONTRACT_NOLO = 1
CONTRACT_RAMI = 2
HISTORY_PADDING_POSITION = 4


def _require_observation(value: object) -> PlayerObservation:
    if not isinstance(value, PlayerObservation):
        raise ObservationBoundaryError(
            "the learned actor accepts only a formal PlayerObservation"
        )
    if value.current_actor != value.observing_seat:
        raise ObservationBoundaryError(
            "the learned actor may act only on its own acting observation"
        )
    if not value.legal_actions:
        raise ObservationBoundaryError("the acting observation has no legal actions")
    return value


def relative_seat(observing_seat: int, seat: int) -> int:
    """Return self/left/partner/right role relative to ``observing_seat``."""

    if observing_seat not in range(4) or seat not in range(4):
        raise ObservationBoundaryError("seat values must be in 0..3")
    return (seat - observing_seat) % 4


def contract_index(contract: Contract | None) -> int:
    if contract is None:
        return CONTRACT_NONE
    if contract is Contract.NOLO:
        return CONTRACT_NOLO
    if contract is Contract.RAMI:
        return CONTRACT_RAMI
    raise ObservationBoundaryError("unsupported contract")


def action_card_index(action: ShowAction | PlayCardAction) -> int:
    return card_to_index(action.shown_card if isinstance(action, ShowAction) else action.card)


def action_kind(action: ShowAction | PlayCardAction) -> int:
    if isinstance(action, ShowAction):
        return ACTION_KIND_SHOW
    if isinstance(action, PlayCardAction):
        return ACTION_KIND_PLAY
    raise ObservationBoundaryError("unsupported engine action")


def _void_flags(observation: PlayerObservation) -> tuple[float, ...]:
    """Encode public void evidence in observer-relative seat/suit order.

    A suit is marked void for a seat when that seat failed to follow a led
    suit in a completed or current trick.  This is public information and is
    intentionally derived without constructing ``PublicInference``.
    """

    flags = [[0.0] * 4 for _ in range(4)]
    suit_indices = {"hearts": 0, "diamonds": 1, "clubs": 2, "spades": 3}
    all_tricks = list(observation.completed_tricks)
    if observation.current_trick:
        # A current trick is public even though it is not yet a CompletedTrick.
        all_plays = (observation.current_trick,)
    else:
        all_plays = ()
    for trick in all_tricks:
        plays = trick.plays
        if plays:
            led = plays[0].card.suit
            for play in plays[1:]:
                if play.card.suit is not led:
                    flags[relative_seat(observation.observing_seat, play.seat)][
                        suit_indices[led.value]
                    ] = 1.0
    for plays in all_plays:
        led = plays[0].card.suit
        for play in plays[1:]:
            if play.card.suit is not led:
                suit_index = suit_indices[led.value]
                flags[relative_seat(observation.observing_seat, play.seat)][suit_index] = 1.0
    return tuple(value for role in flags for value in role)


def _context(observation: PlayerObservation) -> tuple[float, ...]:
    score = observation.match_score.as_tuple()
    observing_team = team_for_seat(observation.observing_seat)
    own_team = observing_team.value
    opponent_team = 1 - own_team
    completed = len(observation.completed_tricks)
    first_leader = (
        0 if observation.first_leader is None else relative_seat(observation.observing_seat, observation.first_leader)
    )
    declarer = (
        0 if observation.declarer is None else relative_seat(observation.observing_seat, observation.declarer)
    )
    dealer = relative_seat(observation.observing_seat, observation.dealer)
    forehand = relative_seat(observation.observing_seat, observation.forehand)
    current_actor = (
        0 if observation.current_actor is None else relative_seat(observation.observing_seat, observation.current_actor)
    )
    contract = contract_index(observation.contract)
    # Keep values in small, stable ranges.  This is preprocessing, not a
    # strategic prior; the network learns the rescaling from held-out data.
    values = (
        1.0 if observation.phase is EnginePhase.TRICK_PLAY else 0.0,
        observation.team_tricks[own_team] / 13.0,
        observation.team_tricks[opponent_team] / 13.0,
        min(score[own_team], 52) / 52.0,
        min(score[opponent_team], 52) / 52.0,
        completed / 13.0,
        len(observation.current_trick) / 3.0,
        dealer / 3.0,
        forehand / 3.0,
        first_leader / 3.0,
        declarer / 3.0,
        current_actor / 3.0,
        contract / 2.0,
        1.0 if observation.declarer == observation.observing_seat else 0.0,
        1.0 if observation.declarer is not None and team_for_seat(observation.declarer) is observing_team else 0.0,
        1.0 if observation.match_score.team0 == observation.match_score.team1 else 0.0,
    )
    return values + _void_flags(observation)


@dataclass(frozen=True, slots=True)
class EncodedObservation:
    """Pure integer/float representation derived only from one observation."""

    hand_cards: tuple[int, ...]
    history_cards: tuple[int, ...]
    history_roles: tuple[int, ...]
    history_kinds: tuple[int, ...]
    history_contracts: tuple[int, ...]
    history_positions: tuple[int, ...]
    history_winners: tuple[int, ...]
    current_cards: tuple[int, ...]
    current_roles: tuple[int, ...]
    context: tuple[float, ...]
    legal_card_indices: tuple[int, ...]
    legal_kinds: tuple[int, ...]
    legal_contracts: tuple[int, ...]
    observation_id: str

    @property
    def legal_action_count(self) -> int:
        return len(self.legal_card_indices)


def _history(observation: PlayerObservation) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    cards: list[int] = []
    roles: list[int] = []
    kinds: list[int] = []
    contracts: list[int] = []
    positions: list[int] = []
    winners: list[int] = []
    for action in observation.show_actions:
        cards.append(card_to_index(action.shown_card))
        roles.append(relative_seat(observation.observing_seat, action.seat))
        kinds.append(ACTION_KIND_SHOW)
        contracts.append(contract_index(action.declared_contract))
        positions.append(0)
        winners.append(0)
    for trick in observation.completed_tricks:
        winner = relative_seat(observation.observing_seat, trick.winner)
        for position, play in enumerate(trick.plays):
            cards.append(card_to_index(play.card))
            roles.append(relative_seat(observation.observing_seat, play.seat))
            kinds.append(ACTION_KIND_PLAY)
            contracts.append(CONTRACT_NONE)
            positions.append(position)
            winners.append(winner)
    if len(cards) > MAX_HISTORY_EVENTS:
        raise ObservationBoundaryError("public history exceeds the engine maximum")
    return tuple(cards), tuple(roles), tuple(kinds), tuple(contracts), tuple(positions), tuple(winners)


def encode_observation(observation: PlayerObservation) -> EncodedObservation:
    checked = _require_observation(observation)
    cards, roles, kinds, contracts, positions, winners = _history(checked)
    current_cards = tuple(card_to_index(play.card) for play in checked.current_trick)
    current_roles = tuple(
        relative_seat(checked.observing_seat, play.seat)
        for play in checked.current_trick
    )
    if len(current_cards) > MAX_CURRENT_TRICK:
        raise ObservationBoundaryError("current trick exceeds three cards")
    legal_cards = tuple(action_card_index(action) for action in checked.legal_actions)
    legal_kinds = tuple(action_kind(action) for action in checked.legal_actions)
    legal_contracts = tuple(
        contract_index(action.declared_contract) if isinstance(action, ShowAction) else CONTRACT_NONE
        for action in checked.legal_actions
    )
    # ``match_ref`` and ``deal_ref`` are deliberately absent.  This id is a
    # compact local identity for diagnostics and does not become a persistent
    # model feature.
    observation_id = repr(
        (
            checked.observing_seat,
            tuple(card_to_index(card) for card in checked.own_hand),
            checked.phase.value,
            checked.contract.value if checked.contract else None,
            checked.declarer,
            checked.first_leader,
            tuple((p.seat, card_to_index(p.card)) for t in checked.completed_tricks for p in t.plays),
            tuple((p.seat, card_to_index(p.card)) for p in checked.current_trick),
            checked.team_tricks,
            checked.match_score.as_tuple(),
            tuple((action.seat, action_card_index(action), action_kind(action), action_contract) for action, action_contract in zip(checked.legal_actions, legal_contracts)),
        )
    )
    return EncodedObservation(
        hand_cards=tuple(sorted(card_to_index(card) for card in checked.own_hand)),
        history_cards=cards,
        history_roles=roles,
        history_kinds=kinds,
        history_contracts=contracts,
        history_positions=positions,
        history_winners=winners,
        current_cards=current_cards,
        current_roles=current_roles,
        context=_context(checked),
        legal_card_indices=legal_cards,
        legal_kinds=legal_kinds,
        legal_contracts=legal_contracts,
        observation_id=observation_id,
    )


def _torch() -> Any:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - exercised without optional deps
        raise LearningDependencyError(
            "Phase 6 neural features require optional 'learning' dependencies"
        ) from exc
    return torch


def batch_from_observations(observations: Iterable[PlayerObservation], *, device: str = "cpu") -> dict[str, Any]:
    """Encode formal observations into padded tensors for the actor."""

    torch = _torch()
    encoded = tuple(encode_observation(item) for item in observations)
    if not encoded:
        raise ObservationBoundaryError("cannot batch an empty observation sequence")
    batch_size = len(encoded)
    hand = torch.full((batch_size, 13), CARD_PADDING, dtype=torch.long, device=device)
    history_cards = torch.full((batch_size, MAX_HISTORY_EVENTS), CARD_PADDING, dtype=torch.long, device=device)
    history_roles = torch.zeros((batch_size, MAX_HISTORY_EVENTS), dtype=torch.long, device=device)
    history_kinds = torch.zeros((batch_size, MAX_HISTORY_EVENTS), dtype=torch.long, device=device)
    history_contracts = torch.zeros((batch_size, MAX_HISTORY_EVENTS), dtype=torch.long, device=device)
    history_positions = torch.full((batch_size, MAX_HISTORY_EVENTS), HISTORY_PADDING_POSITION, dtype=torch.long, device=device)
    history_winners = torch.zeros((batch_size, MAX_HISTORY_EVENTS), dtype=torch.long, device=device)
    current_cards = torch.full((batch_size, MAX_CURRENT_TRICK), CARD_PADDING, dtype=torch.long, device=device)
    current_roles = torch.zeros((batch_size, MAX_CURRENT_TRICK), dtype=torch.long, device=device)
    context = torch.zeros((batch_size, CONTEXT_DIM), dtype=torch.float32, device=device)
    max_actions = max(item.legal_action_count for item in encoded)
    legal_cards = torch.full((batch_size, max_actions), CARD_PADDING, dtype=torch.long, device=device)
    legal_kinds = torch.zeros((batch_size, max_actions), dtype=torch.long, device=device)
    legal_contracts = torch.zeros((batch_size, max_actions), dtype=torch.long, device=device)
    legal_mask = torch.zeros((batch_size, max_actions), dtype=torch.bool, device=device)
    history_lengths = torch.zeros((batch_size,), dtype=torch.long, device=device)
    current_lengths = torch.zeros((batch_size,), dtype=torch.long, device=device)
    for row, item in enumerate(encoded):
        hand[row, : len(item.hand_cards)] = torch.tensor(item.hand_cards, dtype=torch.long, device=device)
        history_lengths[row] = len(item.history_cards)
        if item.history_cards:
            history_cards[row, : len(item.history_cards)] = torch.tensor(item.history_cards, dtype=torch.long, device=device)
            history_roles[row, : len(item.history_roles)] = torch.tensor(item.history_roles, dtype=torch.long, device=device)
            history_kinds[row, : len(item.history_kinds)] = torch.tensor(item.history_kinds, dtype=torch.long, device=device)
            history_contracts[row, : len(item.history_contracts)] = torch.tensor(item.history_contracts, dtype=torch.long, device=device)
            history_positions[row, : len(item.history_positions)] = torch.tensor(item.history_positions, dtype=torch.long, device=device)
            history_winners[row, : len(item.history_winners)] = torch.tensor(item.history_winners, dtype=torch.long, device=device)
        current_lengths[row] = len(item.current_cards)
        if item.current_cards:
            current_cards[row, : len(item.current_cards)] = torch.tensor(item.current_cards, dtype=torch.long, device=device)
            current_roles[row, : len(item.current_roles)] = torch.tensor(item.current_roles, dtype=torch.long, device=device)
        context[row] = torch.tensor(item.context, dtype=torch.float32, device=device)
        count = item.legal_action_count
        legal_cards[row, :count] = torch.tensor(item.legal_card_indices, dtype=torch.long, device=device)
        legal_kinds[row, :count] = torch.tensor(item.legal_kinds, dtype=torch.long, device=device)
        legal_contracts[row, :count] = torch.tensor(item.legal_contracts, dtype=torch.long, device=device)
        legal_mask[row, :count] = True
    return {
        "hand": hand,
        "history_cards": history_cards,
        "history_roles": history_roles,
        "history_kinds": history_kinds,
        "history_contracts": history_contracts,
        "history_positions": history_positions,
        "history_winners": history_winners,
        "history_lengths": history_lengths,
        "current_cards": current_cards,
        "current_roles": current_roles,
        "current_lengths": current_lengths,
        "context": context,
        "legal_cards": legal_cards,
        "legal_kinds": legal_kinds,
        "legal_contracts": legal_contracts,
        "legal_mask": legal_mask,
    }
