"""Exact counting over the hard public constraint model.

This module answers questions of the form *"how many hidden-hand assignments does
public information still permit?"* with an exact integer, and *"what fraction of
them place this card at this seat?"* with an exact rational.

Neither answer is a belief. A count is a property of the constraint system, and
the uniform measure it induces is the *combinatorially neutral* one: it treats
every feasible assignment as one object because the hard facts genuinely cannot
distinguish them. It is emphatically **not** a posterior over opponents' hands,
because a real posterior depends on the policies that produced the observed
actions, and this package models no policy. :mod:`tuppi_exact.sampling` states
the same warning where it can actually mislead a search agent.

The method is exact and cheap for one specific structural reason. Two unknown
cards with the same allowed-seat set are interchangeable, so the whole system
collapses to a transportation problem over at most fifteen equivalence classes
and at most three open seats. Counting it is a dynamic program over residual
capacity vectors, with an exact multinomial factor for the cards inside each
class - no permanent, no inclusion-exclusion, and no sampling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from functools import lru_cache
import math
from types import MappingProxyType
from typing import Iterator, Mapping

from tuppi_rules import Card

from .constraints import HardConstraintModel
from .errors import CountingError


COUNTING_SCHEMA_VERSION = "tuppi.exact.feasible_assignment_count.v1"


@dataclass(frozen=True, slots=True)
class ClassAllocation:
    """One interchangeable group of unknown cards and the seats it may go to."""

    allowed_seats: tuple[int, ...]
    cards: tuple[Card, ...]

    def __post_init__(self) -> None:
        if type(self.allowed_seats) is not tuple or not self.allowed_seats:
            raise CountingError("a class needs a nonempty allowed-seat tuple")
        if tuple(sorted(set(self.allowed_seats))) != self.allowed_seats:
            raise CountingError("class allowed seats must be sorted and unique")
        if type(self.cards) is not tuple or not self.cards:
            raise CountingError("a class needs at least one card")

    @property
    def size(self) -> int:
        return len(self.cards)


@dataclass(frozen=True, slots=True)
class CountingPlan:
    """The exact transportation problem induced by a constraint model.

    ``seat_order`` fixes a canonical index for every open seat so that residual
    capacity vectors are comparable, hashable, and reproducible. The plan is a
    pure function of the model, so two runs on the same observation produce the
    same plan and therefore the same counts and the same samples.
    """

    seat_order: tuple[int, ...]
    capacities: tuple[int, ...]
    classes: tuple[ClassAllocation, ...]
    schema_version: str = field(default=COUNTING_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if len(self.seat_order) != len(self.capacities):
            raise CountingError("capacities must align with the seat order")
        if tuple(sorted(set(self.seat_order))) != self.seat_order:
            raise CountingError("seat order must be sorted and unique")
        if any(value < 0 for value in self.capacities):
            raise CountingError("capacities must be nonnegative")
        total = sum(item.size for item in self.classes)
        if total != sum(self.capacities):
            raise CountingError(
                "class card total disagrees with the total residual capacity"
            )
        for item in self.classes:
            if any(seat not in self.seat_order for seat in item.allowed_seats):
                raise CountingError("a class allows a seat with no residual capacity")

    @classmethod
    def build(cls, model: HardConstraintModel) -> "CountingPlan":
        if not isinstance(model, HardConstraintModel):
            raise CountingError("CountingPlan.build requires a HardConstraintModel")
        seat_order = model.unknown_seats
        classes = tuple(
            ClassAllocation(
                allowed_seats=tuple(sorted(seats)),
                cards=cards,
            )
            for seats, cards in model.equivalence_classes()
        )
        return cls(
            seat_order=seat_order,
            capacities=tuple(model.capacity[seat] for seat in seat_order),
            classes=classes,
        )

    def positions_for(self, allocation: ClassAllocation) -> tuple[int, ...]:
        return tuple(self.seat_order.index(seat) for seat in allocation.allowed_seats)

    def without(self, *, card: Card, seat: int) -> "CountingPlan | None":
        """Return the plan that remains after pinning ``card`` to ``seat``.

        This is the exact reduction used for a marginal count: the pinned card
        leaves its class, and the seat's residual capacity falls by one. The
        other cards of that class stay free, because pinning one member of an
        interchangeable group says nothing about the rest.

        ``None`` means the pinning is infeasible, so its exact count is zero.
        """

        if seat not in self.seat_order:
            raise CountingError("cannot pin a card to a seat with no capacity")
        position = self.seat_order.index(seat)
        if self.capacities[position] == 0:
            raise CountingError("cannot pin a card to a seat with no capacity")
        rebuilt: list[ClassAllocation] = []
        removed = False
        for item in self.classes:
            if not removed and card in item.cards:
                if seat not in item.allowed_seats:
                    raise CountingError("the pinned seat is excluded for this card")
                remaining = tuple(other for other in item.cards if other != card)
                removed = True
                if remaining:
                    rebuilt.append(
                        ClassAllocation(
                            allowed_seats=item.allowed_seats, cards=remaining
                        )
                    )
                continue
            rebuilt.append(item)
        if not removed:
            raise CountingError("the pinned card is not an unknown card of this plan")
        capacities = list(self.capacities)
        capacities[position] -= 1
        surviving_seats = tuple(
            self.seat_order[index]
            for index in range(len(self.seat_order))
            if capacities[index] > 0
        )
        if any(
            not set(item.allowed_seats) & set(surviving_seats) for item in rebuilt
        ):
            # A card whose every allowed seat is now full makes the reduced
            # problem infeasible. Report that as "no plan", so callers can ask
            # about impossible pinnings and receive an exact zero.
            return None
        trimmed = tuple(
            ClassAllocation(
                allowed_seats=tuple(
                    seat for seat in item.allowed_seats if seat in surviving_seats
                ),
                cards=item.cards,
            )
            for item in rebuilt
        )
        return CountingPlan(
            seat_order=surviving_seats,
            capacities=tuple(value for value in capacities if value > 0),
            classes=trimmed,
        )

    def identity_key(self) -> tuple:
        """A hashable canonical key, used for memoization across calls."""

        return (
            self.seat_order,
            self.capacities,
            tuple((item.allowed_seats, item.size) for item in self.classes),
        )


def bounded_compositions(total: int, bounds: tuple[int, ...]) -> Iterator[tuple[int, ...]]:
    """Yield every way to split ``total`` items into parts within ``bounds``."""

    if not bounds:
        if total == 0:
            yield ()
        return
    head, *rest = bounds
    remaining_capacity = sum(rest)
    lowest = max(0, total - remaining_capacity)
    for value in range(lowest, min(head, total) + 1):
        for tail in bounded_compositions(total - value, tuple(rest)):
            yield (value,) + tail


@lru_cache(maxsize=65_536)
def _bounded_compositions_cached(
    total: int, bounds: tuple[int, ...]
) -> tuple[tuple[int, ...], ...]:
    """Return the canonical composition sequence without rebuilding it.

    The generator above remains the reference implementation and preserves its
    public lazy behaviour.  Exact sampling repeatedly asks for the same small
    ``(total, bounds)`` shapes while skipping indexed assignments; caching the
    materialized sequence removes recursion and tuple allocation from that hot
    path without changing ordering or values.
    """

    return tuple(bounded_compositions(total, bounds))


def multinomial(total: int, parts: tuple[int, ...]) -> int:
    ways = 1
    left = total
    for part in parts:
        ways *= math.comb(left, part)
        left -= part
    if left != 0:
        raise CountingError("multinomial parts do not sum to the total")
    return ways


@lru_cache(maxsize=8192)
def _count_from(
    key: tuple, index: int, remaining: tuple[int, ...]
) -> int:
    seat_order, capacities, class_shapes = key
    del capacities
    if index == len(class_shapes):
        return 1 if not any(remaining) else 0
    left = sum(shape[1] for shape in class_shapes[index:])
    if left != sum(remaining):
        return 0
    allowed_seats, size = class_shapes[index]
    positions = tuple(seat_order.index(seat) for seat in allowed_seats)
    bounds = tuple(remaining[position] for position in positions)
    total = 0
    for split in bounded_compositions(size, bounds):
        following = list(remaining)
        for position, value in zip(positions, split):
            following[position] -= value
        deeper = _count_from(key, index + 1, tuple(following))
        if deeper:
            total += multinomial(size, split) * deeper
    return total


def count_plan(plan: CountingPlan) -> int:
    """Return the exact number of assignments the plan permits."""

    if not isinstance(plan, CountingPlan):
        raise CountingError("count_plan requires a CountingPlan")
    if not plan.classes:
        return 1 if not any(plan.capacities) else 0
    return _count_from(plan.identity_key(), 0, plan.capacities)


def feasible_assignment_count(model: HardConstraintModel) -> int:
    """Return the exact number of feasible hidden-hand assignments.

    Zero means the public record admits no assignment at all, which for a legal
    ``project_target_v1`` state cannot happen and indicates a defect in the
    constraint model or a forged observation. One means the hidden hands are
    fully determined by public information.
    """

    if not isinstance(model, HardConstraintModel):
        raise CountingError("feasible_assignment_count requires a constraint model")
    return count_plan(CountingPlan.build(model))


def assignments_with_card_at_seat(
    model: HardConstraintModel, card: Card, seat: int
) -> int:
    """Return how many feasible assignments place ``card`` at ``seat``."""

    if not isinstance(model, HardConstraintModel):
        raise CountingError("assignments_with_card_at_seat needs a constraint model")
    if not isinstance(card, Card):
        raise CountingError("assignments_with_card_at_seat requires a Card")
    if type(seat) is not int or seat not in range(4):
        raise CountingError("seat must be an integer in 0..3")
    if card not in model.allowed_seat_map:
        proven = model.proven_owner(card)
        if proven is None:
            return 0
        return feasible_assignment_count(model) if proven == seat else 0
    if seat not in model.allowed_seats(card):
        return 0
    reduced = CountingPlan.build(model).without(card=card, seat=seat)
    return 0 if reduced is None else count_plan(reduced)


def exact_ownership_counts(
    model: HardConstraintModel,
) -> Mapping[Card, tuple[int, ...]]:
    """Return, per unknown card, how many assignments place it at each seat.

    The four entries always sum to the total feasible count, which the test
    suite checks directly: an off-by-one in the reduction would break that
    identity immediately.
    """

    counts: dict[Card, tuple[int, ...]] = {}
    for card in model.unknown_cards:
        counts[card] = tuple(
            assignments_with_card_at_seat(model, card, seat) for seat in range(4)
        )
    return MappingProxyType(counts)


def exact_uniform_marginals(
    model: HardConstraintModel,
) -> Mapping[Card, tuple[Fraction, ...]]:
    """Return exact rational ownership frequencies under the uniform measure.

    These are exact rationals, not floating-point estimates, and they are a
    property of the constraint system. Reading them as "the chance seat 2 holds
    the ace" imports an assumption this package does not make; see the module
    docstring.
    """

    total = feasible_assignment_count(model)
    if total <= 0:
        raise CountingError("an infeasible model has no uniform measure")
    counts = exact_ownership_counts(model)
    return MappingProxyType(
        {
            card: tuple(Fraction(value, total) for value in per_seat)
            for card, per_seat in counts.items()
        }
    )


def count_summary(model: HardConstraintModel) -> dict[str, object]:
    """Return a compact canonical description of the exact counting result."""

    plan = CountingPlan.build(model)
    total = count_plan(plan)
    return {
        "class_count": len(plan.classes),
        "classes": [
            {"allowed_seats": list(item.allowed_seats), "card_count": item.size}
            for item in plan.classes
        ],
        "feasible_assignment_count": total,
        "feasible_assignment_count_log10": (
            round(math.log10(total), 6) if total > 0 else None
        ),
        "fully_determined": total == 1,
        "open_seat_capacities": [
            {"capacity": capacity, "seat": seat}
            for seat, capacity in zip(plan.seat_order, plan.capacities)
        ],
        "schema_version": COUNTING_SCHEMA_VERSION,
        "structurally_feasible": model.is_structurally_feasible(),
        "unknown_card_count": len(model.unknown_cards),
    }
