"""The hard public constraint model: every exact exclusion, and nothing else.

Phase 4's :class:`tuppi_agents.PublicInference` answers *"is this excluded by
public information?"* from five facts. This module is the Phase 5B layer that
sits directly on top of it and turns those facts into the explicit combinatorial
object a counter, a sampler, and a solver can consume:

* which seats each unknown card may still belong to;
* exactly how many unknown cards each seat must still receive.

It adds one class of exclusion that Phase 4 did not model, and that omission was
not cosmetic: **a show action constrains the shower's whole initial hand.**

``project_target_v1`` derives ``verbal_required`` from the complete 13-card hand
through a mandatory three-level hierarchy, so the public
``(seat, shown_card, declared_contract, verbal_required)`` tuple is a hard
statement about cards the shower does *not* hold:

============================================  ===========================================
Public show action                             Exact deduction about the initial hand
============================================  ===========================================
``verbal_required`` is false                   Priority 1 applied. The shown card is itself
                                               an eligible card of the contract's normal
                                               colour, so nothing new is excluded.
``verbal_required`` and the shown rank is       Priority 2 applied. The hand holds **no**
eligible (3-9)                                 eligible card of the contract's normal
                                               colour: 14 cards are excluded.
``verbal_required`` and the shown rank is       Priority 3 applied. The hand holds **no**
ineligible                                     eligible card of *either* colour: all 28
                                               cards of ranks 3-9 are excluded.
============================================  ===========================================

Priority 3 cannot show an eligible card, because under priority 3 the hand
contains none; that is why the shown card's rank separates the two fallback
levels with certainty rather than by guess.

The deduction is about the *initial* hand, but every card that seat has played is
already public, so the only live consequence is an exclusion over the seat's
remaining unknown cards. A legal state can never show an excluded card as
already played by that seat, and :func:`derive_show_exclusions` treats that
combination as a contradiction rather than silently dropping it.

There is no probability anywhere in this module. An unknown card's allowed-seat
set is the full set the facts permit, with no ordering and no weight among them.
Counting and sampling live in :mod:`tuppi_exact.counting` and
:mod:`tuppi_exact.sampling`; a *count* over that set is a combinatorial fact
about the constraint system, never a claim about what an opponent would do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from types import MappingProxyType
from typing import Mapping

from tuppi_agents import PublicInference
from tuppi_engine import PlayerObservation
from tuppi_rules import (
    CARDS_PER_HAND,
    Card,
    Color,
    Contract,
    FULL_DECK,
    ShowAction,
    Suit,
    card_color,
    contract_color,
    is_show_rank_eligible,
)

from .errors import ConstraintError


CONSTRAINT_MODEL_SCHEMA_VERSION = "tuppi.exact.hard_constraint_model.v1"

#: The full set of cards whose rank is show-eligible under ``project_target_v1``.
ELIGIBLE_SHOW_CARDS: frozenset[Card] = frozenset(
    card for card in FULL_DECK if is_show_rank_eligible(card.rank)
)

#: Eligible show cards partitioned by colour, precomputed once.
ELIGIBLE_SHOW_CARDS_BY_COLOR: Mapping[Color, frozenset[Card]] = MappingProxyType(
    {
        color: frozenset(
            card for card in ELIGIBLE_SHOW_CARDS if card_color(card) is color
        )
        for color in Color
    }
)
_SUIT_ORDER = {suit: index for index, suit in enumerate(Suit)}


def show_exclusion_for(action: ShowAction) -> frozenset[Card]:
    """Return the cards one public show action proves are absent from the hand.

    The result is a statement about the shower's complete initial hand and is a
    direct consequence of the mandatory showing hierarchy, not an inference
    about the shower's intentions.
    """

    if not isinstance(action, ShowAction):
        raise ConstraintError("show_exclusion_for requires a rules ShowAction")
    if not action.verbal_required:
        return frozenset()
    if is_show_rank_eligible(action.shown_card.rank):
        # Priority 2: no eligible card of the contract's normal colour exists.
        return ELIGIBLE_SHOW_CARDS_BY_COLOR[contract_color(action.declared_contract)]
    # Priority 3: no eligible card of either colour exists.
    return ELIGIBLE_SHOW_CARDS


def derive_show_exclusions(
    observation: PlayerObservation,
) -> tuple[frozenset[Card], ...]:
    """Return the per-seat show-derived exclusion sets for one observation.

    The observing seat's own entry is always empty: its hand is known outright,
    so an exclusion over it would be redundant, and applying one would risk
    contradicting the very hand the engine handed over.
    """

    if not isinstance(observation, PlayerObservation):
        raise ConstraintError("derive_show_exclusions requires a PlayerObservation")
    exclusions: list[set[Card]] = [set(), set(), set(), set()]
    played_by_seat: list[set[Card]] = [set(), set(), set(), set()]
    for trick in observation.completed_tricks:
        for play in trick.plays:
            played_by_seat[play.seat].add(play.card)
    for play in observation.current_trick:
        played_by_seat[play.seat].add(play.card)

    for action in observation.show_actions:
        if action.seat == observation.observing_seat:
            continue
        excluded = show_exclusion_for(action)
        contradiction = excluded & played_by_seat[action.seat]
        if contradiction:
            raise ConstraintError(
                "a show-derived exclusion contradicts a card that seat already "
                "played; the public record is not a legal project_target_v1 state"
            )
        exclusions[action.seat] |= excluded
    return tuple(frozenset(item) for item in exclusions)


@dataclass(frozen=True, slots=True)
class HardConstraintModel:
    """An exact, immutable description of every feasible hidden-hand assignment.

    The model is a degree-constrained bipartite structure: unknown cards on one
    side, seats with exact residual capacities on the other, and an edge
    wherever public information permits. Nothing in it is approximate, and no
    field carries a weight, a prior, or a likelihood.
    """

    observing_seat: int
    unknown_cards: tuple[Card, ...]
    allowed_seat_map: Mapping[Card, frozenset[int]]
    capacity: tuple[int, ...]
    known_held: tuple[frozenset[Card], ...]
    played_cards: frozenset[Card]
    void_suits: tuple[frozenset[Suit], ...]
    show_exclusions: tuple[frozenset[Card], ...]
    cards_remaining: tuple[int, ...]
    refinement_passes: int
    schema_version: str = field(
        default=CONSTRAINT_MODEL_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        if type(self.observing_seat) is not int or self.observing_seat not in range(4):
            raise ConstraintError("observing seat must be an integer in 0..3")
        for label, value in (
            ("capacity", self.capacity),
            ("known_held", self.known_held),
            ("void_suits", self.void_suits),
            ("show_exclusions", self.show_exclusions),
            ("cards_remaining", self.cards_remaining),
        ):
            if type(value) is not tuple or len(value) != 4:
                raise ConstraintError(f"{label} must be a four-seat tuple")
        if any(type(value) is not int or value < 0 for value in self.capacity):
            raise ConstraintError("capacities must be nonnegative integers")
        if self.capacity[self.observing_seat] != 0:
            raise ConstraintError("the observing seat has no unknown capacity")
        if sum(self.capacity) != len(self.unknown_cards):
            raise ConstraintError(
                "total residual capacity disagrees with the unknown card count"
            )
        if len(set(self.unknown_cards)) != len(self.unknown_cards):
            raise ConstraintError("unknown cards must be distinct")
        if set(self.allowed_seat_map) != set(self.unknown_cards):
            raise ConstraintError("allowed-seat map must cover exactly the unknowns")
        for card, seats in self.allowed_seat_map.items():
            if not isinstance(seats, frozenset) or not seats:
                raise ConstraintError(
                    "every unknown card needs a nonempty frozen allowed-seat set"
                )
            if any(seat not in range(4) for seat in seats):
                raise ConstraintError("allowed seats must be in 0..3")
            if any(self.capacity[seat] == 0 for seat in seats):
                raise ConstraintError(
                    "an allowed seat with zero residual capacity was not propagated"
                )
            if card in self.played_cards:
                raise ConstraintError("a played card cannot be unknown")
        for seat in range(4):
            if self.known_held[seat] & self.played_cards:
                raise ConstraintError("a played card cannot be publicly held")
            if len(self.known_held[seat]) + self.capacity[seat] != (
                self.cards_remaining[seat]
            ):
                raise ConstraintError(
                    "known cards plus residual capacity must equal the hand size"
                )
            if self.known_held[seat] & self.show_exclusions[seat]:
                raise ConstraintError(
                    "a show-derived exclusion contradicts a publicly held card"
                )
            if any(
                card.suit in self.void_suits[seat] for card in self.known_held[seat]
            ):
                raise ConstraintError("a proven void contradicts a publicly held card")

    # ---------------------------------------------------------------- builders

    @classmethod
    def build(cls, observation: PlayerObservation) -> "HardConstraintModel":
        """Derive the model from one player observation.

        The Phase 4 inference object supplies the five original facts. This
        method intersects them with the show-derived exclusions and re-runs the
        same two sound deductions - singleton and pigeonhole - plus the seat
        subset (Hall) propagation that exact capacities make available, to a
        fixed point.
        """

        inference = PublicInference.build(observation)
        exclusions = derive_show_exclusions(observation)
        return cls._from_facts(inference=inference, show_exclusions=exclusions)

    @classmethod
    def from_inference(
        cls,
        inference: PublicInference,
        show_exclusions: tuple[frozenset[Card], ...],
    ) -> "HardConstraintModel":
        """Build directly from an existing inference plus explicit exclusions."""

        if not isinstance(inference, PublicInference):
            raise ConstraintError("from_inference requires a PublicInference")
        if type(show_exclusions) is not tuple or len(show_exclusions) != 4:
            raise ConstraintError("show_exclusions must be a four-seat tuple")
        return cls._from_facts(inference=inference, show_exclusions=show_exclusions)

    @classmethod
    def _from_facts(
        cls,
        *,
        inference: PublicInference,
        show_exclusions: tuple[frozenset[Card], ...],
    ) -> "HardConstraintModel":
        seat = inference.observing_seat
        known: list[set[Card]] = [set(item) for item in inference.known_held]
        capacity = list(inference.unknown_capacity)
        allowed: dict[Card, frozenset[int]] = {}
        for card in inference.unaccounted_cards:
            seats = frozenset(
                candidate
                for candidate in inference.possible_owners(card)
                if card not in show_exclusions[candidate]
            )
            if not seats:
                raise ConstraintError(
                    "hard public constraints exclude every holder of an unknown card"
                )
            allowed[card] = seats

        passes = _refine(allowed=allowed, capacity=capacity, known=known)

        unknown = tuple(sorted(allowed, key=_card_key))
        return cls(
            observing_seat=seat,
            unknown_cards=unknown,
            allowed_seat_map=MappingProxyType(dict(allowed)),
            capacity=tuple(capacity),
            known_held=tuple(frozenset(item) for item in known),
            played_cards=inference.played_cards,
            void_suits=inference.void_suits,
            show_exclusions=tuple(show_exclusions),
            cards_remaining=inference.cards_remaining,
            refinement_passes=passes,
        )

    # ----------------------------------------------------------------- queries

    @property
    def unknown_seats(self) -> tuple[int, ...]:
        """Seats that must still receive at least one unknown card."""

        return tuple(seat for seat in range(4) if self.capacity[seat] > 0)

    def allowed_seats(self, card: Card) -> frozenset[int]:
        """Return every seat the hard facts still permit to hold ``card``.

        Empty for a played card and for a card whose owner is already proven -
        in the latter case :meth:`proven_owner` answers instead.
        """

        if not isinstance(card, Card):
            raise ConstraintError("allowed_seats requires a Card")
        return self.allowed_seat_map.get(card, frozenset())

    def proven_owner(self, card: Card) -> int | None:
        """Return the seat publicly proven to hold ``card``, or ``None``."""

        if not isinstance(card, Card):
            raise ConstraintError("proven_owner requires a Card")
        for seat in range(4):
            if card in self.known_held[seat]:
                return seat
        return None

    def equivalence_classes(self) -> tuple[tuple[frozenset[int], tuple[Card, ...]], ...]:
        """Group unknown cards by their allowed-seat set.

        Two unknown cards with the same allowed-seat set are interchangeable for
        every feasibility, counting, and uniform-sampling question. Collapsing
        them is what makes the exact counter cheap, and it is exact rather than
        an approximation: the constraint system genuinely cannot distinguish
        them.
        """

        grouped: dict[frozenset[int], list[Card]] = {}
        for card in self.unknown_cards:
            grouped.setdefault(self.allowed_seat_map[card], []).append(card)
        return tuple(
            (seats, tuple(sorted(cards, key=_card_key)))
            for seats, cards in sorted(
                grouped.items(), key=lambda item: tuple(sorted(item[0]))
            )
        )

    def hall_deficiency(self) -> tuple[tuple[tuple[int, ...], int, int], ...]:
        """Return every seat subset whose capacity cannot absorb its captive cards.

        A card is *captive* to a seat subset when no seat outside that subset may
        hold it. With at most three unknown seats, enumerating all subsets is a
        complete feasibility test, not a heuristic screen.
        """

        seats = self.unknown_seats
        failures: list[tuple[tuple[int, ...], int, int]] = []
        for size in range(1, len(seats) + 1):
            for subset in combinations(seats, size):
                chosen = frozenset(subset)
                captive = sum(
                    1
                    for card in self.unknown_cards
                    if self.allowed_seat_map[card] <= chosen
                )
                available = sum(self.capacity[item] for item in subset)
                if captive > available:
                    failures.append((subset, captive, available))
        return tuple(failures)

    def is_structurally_feasible(self) -> bool:
        """True when no seat subset is over-subscribed.

        This is the complete Gale-Hoffman condition for the transportation
        problem the model describes, so for ``project_target_v1`` - where at most
        three seats are ever unknown - it is exact. The authoritative oracle is
        still :func:`tuppi_exact.counting.feasible_assignment_count`, which
        returns zero for an infeasible model.
        """

        return not self.hall_deficiency()

    def identity_data(self) -> dict[str, object]:
        """Canonical content for digesting a model without revealing a hand."""

        from tuppi_rules import card_to_code

        return {
            "allowed_seats": {
                card_to_code(card): sorted(self.allowed_seat_map[card])
                for card in self.unknown_cards
            },
            "capacity": list(self.capacity),
            "observing_seat": self.observing_seat,
            "schema_version": CONSTRAINT_MODEL_SCHEMA_VERSION,
            "unknown_cards": [card_to_code(card) for card in self.unknown_cards],
        }


def _refine(
    *,
    allowed: dict[Card, frozenset[int]],
    capacity: list[int],
    known: list[set[Card]],
) -> int:
    """Run singleton, zero-capacity, tight-seat, and Hall propagation to a fixed point.

    Each deduction is exact. The loop is bounded by the number of unknown cards
    plus a small constant because every pass that changes anything either proves
    one card's owner or removes at least one edge, and both are monotone.
    """

    ordered_cards = tuple(sorted(allowed, key=_card_key))
    limit = len(allowed) * 4 + 8
    for completed in range(limit):
        changed = False

        for card in ordered_cards:
            if card not in allowed:
                continue
            seats = allowed[card]
            if len(seats) == 1:
                (owner,) = tuple(seats)
                known[owner].add(card)
                capacity[owner] -= 1
                if capacity[owner] < 0:
                    raise ConstraintError(
                        "propagation drove a seat's residual capacity negative"
                    )
                del allowed[card]
                changed = True

        for seat in range(4):
            if capacity[seat] != 0:
                continue
            for card in ordered_cards:
                if card not in allowed:
                    continue
                if seat in allowed[card]:
                    reduced = allowed[card] - {seat}
                    if not reduced:
                        raise ConstraintError(
                            "propagation excluded every holder of an unknown card"
                        )
                    allowed[card] = reduced
                    changed = True

        open_seats = tuple(seat for seat in range(4) if capacity[seat] > 0)
        for seat in open_seats:
            candidates = tuple(
                card
                for card in ordered_cards
                if card in allowed and seat in allowed[card]
            )
            if len(candidates) < capacity[seat]:
                raise ConstraintError(
                    "a seat cannot be filled from the cards it may still hold"
                )
            if len(candidates) == capacity[seat]:
                for card in candidates:
                    if allowed[card] != frozenset((seat,)):
                        allowed[card] = frozenset((seat,))
                        changed = True

        for size in range(1, len(open_seats)):
            for subset in combinations(open_seats, size):
                chosen = frozenset(subset)
                captive = tuple(
                    card
                    for card in ordered_cards
                    if card in allowed and allowed[card] <= chosen
                )
                available = sum(capacity[item] for item in subset)
                if len(captive) > available:
                    raise ConstraintError(
                        "a seat subset cannot absorb the cards captive to it"
                    )
                if len(captive) == available:
                    for card in ordered_cards:
                        if card not in allowed:
                            continue
                        if allowed[card] <= chosen:
                            continue
                        reduced = allowed[card] - chosen
                        if not reduced:
                            raise ConstraintError(
                                "Hall propagation excluded every holder of a card"
                            )
                        if reduced != allowed[card]:
                            allowed[card] = reduced
                            changed = True

        if not changed:
            return completed + 1
    raise ConstraintError("hard constraint propagation did not reach a fixed point")


def _card_key(card: Card) -> tuple[int, int]:
    return (_SUIT_ORDER[card.suit], card.rank.value)


def own_show_exclusion_is_consistent(
    observation: PlayerObservation,
) -> bool:
    """True when the observer's own show action agrees with its own hand.

    This is a self-check rather than an inference: the observer knows its hand,
    so a disagreement would mean the engine handed over an inconsistent
    observation, not that a deduction is unsound.
    """

    if not isinstance(observation, PlayerObservation):
        raise ConstraintError("own_show_exclusion_is_consistent needs an observation")
    own_initial = set(observation.own_hand)
    for trick in observation.completed_tricks:
        for play in trick.plays:
            if play.seat == observation.observing_seat:
                own_initial.add(play.card)
    for play in observation.current_trick:
        if play.seat == observation.observing_seat:
            own_initial.add(play.card)
    if len(own_initial) != CARDS_PER_HAND:
        return False
    for action in observation.show_actions:
        if action.seat != observation.observing_seat:
            continue
        if show_exclusion_for(action) & own_initial:
            return False
    return True


def contract_normal_colour(contract: Contract) -> Color:
    """Re-export the ruleset's contract colour so callers need no rules import."""

    return contract_color(contract)
