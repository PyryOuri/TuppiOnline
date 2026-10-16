"""Read-only access to the frozen legacy heuristic as a historical oracle.

The archival package owns every path that touches ``Archive/``. This module
exposes the frozen ``HeuristicPolicy`` decisions for a clean
:class:`tuppi_engine.PlayerObservation`, so that Phase 4 characterization
fixtures can compare a pure port against the original implementation without
the strategic package ever importing legacy code.

Scope and honesty
-----------------
* Only ``HeuristicPolicy.choose_show_bid`` and
  ``HeuristicPolicy.choose_play_card`` are exposed. ``MonteCarloAI``,
  ``MonteCarloAdvisor``, and every rollout entry point are deliberately absent.
* ``TARGET_EQUIVALENT_BANNED_RANKS`` configures the legacy banned-rank set so
  that legacy show eligibility coincides with ``project_target_v1`` ranks 3-9.
  With any other banned set the two rulesets disagree by construction.
* The legacy hand order (``sort_hand``) is reproduced, because legacy
  ``min``/``max`` selections depended on it.
* Agreement is claimed only for the curated positions where the two rule sets
  coincide. It is not a claim of complete behavioural equivalence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from tuppi_engine import PlayerObservation
from tuppi_rules import Card, Contract, Rank, Suit

from .errors import ArtifactIntegrityError
from .legacy_loader import load_legacy_module


# Legacy suit indices were spades=0, hearts=1, diamonds=2, clubs=3.
_LEGACY_SUIT_ORDER: tuple[Suit, ...] = (
    Suit.SPADES,
    Suit.HEARTS,
    Suit.DIAMONDS,
    Suit.CLUBS,
)

# Legacy banned ranks {2, J, Q, K} left ranks 3-10 and the ace showable.
# project_target_v1 allows only 3-9, so the ten and the ace are banned here to
# make the two eligibility rules coincide.
TARGET_EQUIVALENT_BANNED_RANKS: tuple[int, ...] = (2, 10, 11, 12, 13, 14)

ORACLE_ID = "legacy_v9.HeuristicPolicy"


def to_legacy_card(card: Card) -> int:
    if not isinstance(card, Card):
        raise ArtifactIntegrityError("to_legacy_card requires a Card value")
    return _LEGACY_SUIT_ORDER.index(card.suit) * 13 + (card.rank.value - 2)


def from_legacy_card(value: int) -> Card:
    if type(value) is not int or value not in range(52):
        raise ArtifactIntegrityError("legacy card must be an integer in 0..51")
    suit_index, rank_index = divmod(value, 13)
    return Card(_LEGACY_SUIT_ORDER[suit_index], Rank(rank_index + 2))


def legacy_sorted_hand(cards: Sequence[Card]) -> list[int]:
    """Return the hand in the frozen ``sort_hand`` order."""

    legacy = load_legacy_module()
    return legacy.sort_hand([to_legacy_card(card) for card in cards])


def _score_state(observation: PlayerObservation) -> Any:
    legacy = load_legacy_module()
    up_team = observation.match_score.up_team
    return legacy.ScoreState(
        rising=True,
        rising_team=None if up_team is None else up_team.value,
        scores=observation.match_score.as_tuple(),
    )


def _public_state(observation: PlayerObservation) -> Any:
    legacy = load_legacy_module()
    if observation.contract is None:
        raise ArtifactIntegrityError("legacy play oracle requires a resolved contract")
    trick = [(play.seat, to_legacy_card(play.card)) for play in observation.current_trick]
    played = [
        (play.seat, to_legacy_card(play.card))
        for completed in observation.completed_tricks
        for play in completed.plays
    ] + trick
    per_player = [0, 0, 0, 0]
    for completed in observation.completed_tricks:
        per_player[completed.winner] += 1
    leader = (
        observation.current_trick[0].seat
        if observation.current_trick
        else observation.observing_seat
    )
    return legacy.PublicState(
        contract=(
            legacy.Contract.RAMI
            if observation.contract is Contract.RAMI
            else legacy.Contract.NOLO
        ),
        declarer=observation.declarer,
        dealer=observation.dealer,
        leader=leader,
        trick_index=len(observation.completed_tricks),
        current_trick=trick,
        played_cards=played,
        tricks_won_by_team=tuple(observation.team_tricks),
        tricks_won_by_player=tuple(per_player),
        revealed_show_cards={
            seat: to_legacy_card(card) for seat, card in observation.publicly_shown_cards
        },
        score_state=_score_state(observation),
    )


@dataclass(frozen=True, slots=True)
class LegacyShowChoice:
    contract: Contract
    card: Card | None
    verbal: bool


def legacy_show_choice(
    observation: PlayerObservation,
    *,
    banned_ranks: tuple[int, ...] = TARGET_EQUIVALENT_BANNED_RANKS,
) -> LegacyShowChoice:
    """Return the frozen heuristic's show bid for this observation."""

    legacy = load_legacy_module()
    bid = legacy.HeuristicPolicy.choose_show_bid(
        legacy_sorted_hand(observation.own_hand),
        observation.observing_seat,
        _score_state(observation),
        set(banned_ranks),
    )
    return LegacyShowChoice(
        contract=Contract.RAMI if bid.choice == legacy.Contract.RAMI else Contract.NOLO,
        card=None if bid.card is None else from_legacy_card(bid.card),
        verbal=bool(bid.verbal),
    )


def legacy_play_choice(observation: PlayerObservation) -> Card:
    """Return the frozen heuristic's played card for this observation."""

    legacy = load_legacy_module()
    chosen = legacy.HeuristicPolicy.choose_play_card(
        legacy_sorted_hand(observation.own_hand),
        _public_state(observation),
        observation.observing_seat,
    )
    return from_legacy_card(chosen)
