"""Exactly uniform sampling over the feasible hidden-hand assignments.

The sampler draws from the *uniform* distribution over every assignment the hard
public constraints permit, and it does so exactly: no Metropolis chain, no
accept-reject over the whole assignment, no repair step that quietly biases the
result, and no modulo bias in the underlying integer draws.

The construction is the standard one for a counted structure. The exact counter
already gives, for every prefix of the class decomposition, how many completions
each residual capacity vector admits. Walking the classes and choosing each
split with probability proportional to ``multinomial(split) x completions`` is
therefore uniform over assignments by construction, and choosing which specific
cards fill each part uses unranked combinations, which is uniform over the
multinomial arrangements. Composing two exactly uniform choices leaves the
result exactly uniform.

**What uniform-over-feasible is not.** It is not a posterior over opponents'
hands. A posterior would have to condition on the fact that the opponents chose
the actions they chose, which requires a model of how they choose - and this
package deliberately contains none. Uniform-over-feasible is the neutral
reference measure: correct as a determinization scheme whose bias is stated
rather than hidden, and the right baseline against which a later phase's belief
model must justify itself.

Determinism. Every draw comes from a SHA-256 counter stream seeded by explicit
canonical material. No module-global random state is touched, no clock or
process identity enters, and re-running the same request reproduces the same
assignments in the same order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from typing import Mapping

from tuppi_engine import PlayerObservation
from tuppi_rules import Card, card_to_code, card_to_index

from .constraints import HardConstraintModel
from .counting import (
    ClassAllocation,
    CountingPlan,
    bounded_compositions,
    multinomial,
    count_plan,
    feasible_assignment_count,
)
from .errors import SamplingError


SAMPLER_SCHEMA_VERSION = "tuppi.exact.uniform_feasible_sampler.v1"
SAMPLER_ALGORITHM_ID = "tuppi.exact.counted_prefix_uniform_v1"
RANDOM_SOURCE_ID = "sha256_counter_bit_reservoir_rejection_v1"


class DeterministicBitSource:
    """An unbiased deterministic source of uniform integers.

    Bits come from ``sha256(seed || counter)`` blocks held in a reservoir.
    :meth:`below` uses rejection on exactly ``bound.bit_length()`` bits, so the
    result is *exactly* uniform on ``range(bound)``. The deal generator's
    documented ``..._modulo_v1`` shortcut is deliberately not reused here:
    modulo bias is negligible when reducing 256 bits to 52, but a sampler whose
    whole claim is exact uniformity must not carry any bias at all.
    """

    __slots__ = ("_seed", "_counter", "_buffer", "_bits", "draws", "rejections")

    def __init__(self, seed: str) -> None:
        if not isinstance(seed, str) or not seed:
            raise SamplingError("the bit source requires a nonempty string seed")
        self._seed = seed.encode("utf-8")
        self._counter = 0
        self._buffer = 0
        self._bits = 0
        self.draws = 0
        self.rejections = 0

    def _refill(self) -> None:
        block = hashlib.sha256(
            self._seed + b"|" + str(self._counter).encode("ascii")
        ).digest()
        self._counter += 1
        self._buffer = (self._buffer << 256) | int.from_bytes(block, "big")
        self._bits += 256

    def _take(self, count: int) -> int:
        if count <= 0:
            return 0
        while self._bits < count:
            self._refill()
        shift = self._bits - count
        value = self._buffer >> shift
        self._buffer &= (1 << shift) - 1
        self._bits = shift
        return value

    def below(self, bound: int) -> int:
        """Return an exactly uniform integer in ``range(bound)``."""

        if type(bound) is not int or bound <= 0:
            raise SamplingError("the exclusive bound must be a positive integer")
        self.draws += 1
        if bound == 1:
            return 0
        width = bound.bit_length()
        while True:
            candidate = self._take(width)
            if candidate < bound:
                return candidate
            self.rejections += 1


@dataclass(frozen=True, slots=True)
class HiddenHandAssignment:
    """One complete feasible assignment of the unknown cards to seats.

    ``hands`` holds every seat's *current* hand: the publicly known cards plus
    the sampled unknown ones. The observing seat's entry is its real hand, which
    the sampler never alters.
    """

    observing_seat: int
    hands: tuple[tuple[Card, ...], ...]
    sampled_owner: Mapping[Card, int]
    sample_index: int
    schema_version: str = field(default=SAMPLER_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.hands) is not tuple or len(self.hands) != 4:
            raise SamplingError("an assignment needs four immutable hands")
        seen: set[Card] = set()
        for hand in self.hands:
            if type(hand) is not tuple:
                raise SamplingError("each assigned hand must be a tuple")
            for card in hand:
                if card in seen:
                    raise SamplingError("an assignment duplicated a card")
                seen.add(card)

    def hand_for(self, seat: int) -> tuple[Card, ...]:
        if type(seat) is not int or seat not in range(4):
            raise SamplingError("seat must be an integer in 0..3")
        return self.hands[seat]

    def content_key(self) -> tuple[tuple[str, ...], ...]:
        """A canonical comparable key, used to test uniformity and determinism."""

        return tuple(
            tuple(sorted(card_to_code(card) for card in hand)) for hand in self.hands
        )


@dataclass(frozen=True, slots=True)
class UniformFeasibleSampler:
    """A deterministic, exactly uniform sampler over feasible assignments."""

    model: HardConstraintModel
    plan: CountingPlan
    seed: str
    total_assignments: int
    schema_version: str = field(default=SAMPLER_SCHEMA_VERSION, init=False)
    algorithm_id: str = field(default=SAMPLER_ALGORITHM_ID, init=False)
    random_source_id: str = field(default=RANDOM_SOURCE_ID, init=False)

    @classmethod
    def build(
        cls, model: HardConstraintModel, *, seed: str
    ) -> "UniformFeasibleSampler":
        if not isinstance(model, HardConstraintModel):
            raise SamplingError("the sampler requires a HardConstraintModel")
        if not isinstance(seed, str) or not seed:
            raise SamplingError("the sampler requires a nonempty string seed")
        plan = CountingPlan.build(model)
        total = count_plan(plan)
        if total <= 0:
            raise SamplingError(
                "the hard constraints admit no assignment; nothing can be sampled"
            )
        return cls(model=model, plan=plan, seed=seed, total_assignments=total)

    @classmethod
    def for_observation(
        cls, observation: PlayerObservation, *, seed: str
    ) -> "UniformFeasibleSampler":
        if not isinstance(observation, PlayerObservation):
            raise SamplingError("for_observation requires a PlayerObservation")
        return cls.build(HardConstraintModel.build(observation), seed=seed)

    # ---------------------------------------------------------------- sampling

    def sample(self, count: int) -> tuple[HiddenHandAssignment, ...]:
        """Draw ``count`` independent, exactly uniform assignments.

        Draws are independent, so repeats are possible and are not filtered out:
        removing them would make the sample uniform over *distinct* assignments
        instead, which is a different and unstated distribution.
        """

        if type(count) is not int or count <= 0:
            raise SamplingError("sample count must be a positive integer")
        source = DeterministicBitSource(self._stream_seed())
        return tuple(
            self._draw(source, index) for index in range(count)
        )

    def sample_one(self, *, index: int = 0) -> HiddenHandAssignment:
        """Draw the assignment at ``index`` of the deterministic stream."""

        if type(index) is not int or index < 0:
            raise SamplingError("sample index must be a nonnegative integer")
        return self.sample(index + 1)[index]

    def _stream_seed(self) -> str:
        from tuppi_eval.serialization import content_digest

        return content_digest(
            {
                "algorithm_id": SAMPLER_ALGORITHM_ID,
                "model": self.model.identity_data(),
                "random_source_id": RANDOM_SOURCE_ID,
                "schema_version": SAMPLER_SCHEMA_VERSION,
                "seed": self.seed,
            }
        )

    def _draw(
        self, source: DeterministicBitSource, index: int
    ) -> HiddenHandAssignment:
        remaining = list(self.plan.capacities)
        owner: dict[Card, int] = {}
        for position, allocation in enumerate(self.plan.classes):
            self._draw_class(
                source=source,
                position=position,
                allocation=allocation,
                remaining=remaining,
                owner=owner,
            )
        if any(remaining):
            raise SamplingError("sampling left residual capacity unfilled")
        hands: list[list[Card]] = [
            list(self.model.known_held[seat]) for seat in range(4)
        ]
        for card, seat in owner.items():
            hands[seat].append(card)
        return HiddenHandAssignment(
            observing_seat=self.model.observing_seat,
            hands=tuple(
                tuple(sorted(hand, key=card_to_index)) for hand in hands
            ),
            sampled_owner=dict(owner),
            sample_index=index,
        )

    def _draw_class(
        self,
        *,
        source: DeterministicBitSource,
        position: int,
        allocation: ClassAllocation,
        remaining: list[int],
        owner: dict[Card, int],
    ) -> None:
        positions = self.plan.positions_for(allocation)
        bounds = tuple(remaining[item] for item in positions)
        weights: list[tuple[tuple[int, ...], int]] = []
        total = 0
        for split in bounded_compositions(allocation.size, bounds):
            following = list(remaining)
            for item, value in zip(positions, split):
                following[item] -= value
            completions = self._completions(position + 1, tuple(following))
            if not completions:
                continue
            weight = multinomial(allocation.size, split) * completions
            total += weight
            weights.append((split, weight))
        if total <= 0:
            raise SamplingError("no split of an equivalence class can be completed")
        target = source.below(total)
        chosen: tuple[int, ...] | None = None
        for split, weight in weights:
            if target < weight:
                chosen = split
                break
            target -= weight
        if chosen is None:  # pragma: no cover - the weights sum to ``total``
            raise SamplingError("weighted split selection fell through")

        available = list(allocation.cards)
        for item, seat, size in zip(
            positions, allocation.allowed_seats, chosen, strict=True
        ):
            if size:
                picked = _unrank_combination(
                    available, size, source.below(math.comb(len(available), size))
                )
                for card in picked:
                    owner[card] = seat
                    available.remove(card)
            remaining[item] -= size

    def _completions(self, position: int, remaining: tuple[int, ...]) -> int:
        """Exact number of ways to finish from ``position`` with ``remaining``."""

        suffix = CountingPlan(
            seat_order=self.plan.seat_order,
            capacities=remaining,
            classes=self.plan.classes[position:],
        ) if sum(remaining) == sum(
            item.size for item in self.plan.classes[position:]
        ) else None
        if suffix is None:
            return 0
        return count_plan(suffix)

    # ------------------------------------------------------------------ report

    def provenance(self) -> dict[str, object]:
        """Canonical, hand-free provenance for a sampling request."""

        return {
            "algorithm_id": self.algorithm_id,
            "distribution": "uniform_over_feasible_assignments",
            "feasible_assignment_count": self.total_assignments,
            "is_posterior_over_opponent_hands": False,
            "posterior_caveat": (
                "Uniform over feasible assignments is a neutral reference "
                "measure, not a posterior: a posterior would condition on how "
                "the opponents chose their observed actions, and this package "
                "models no policy."
            ),
            "random_source_id": self.random_source_id,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "stream_seed_digest": self._stream_seed(),
            "unknown_card_count": len(self.model.unknown_cards),
        }


def _unrank_combination(
    available: list[Card], size: int, rank: int
) -> tuple[Card, ...]:
    """Return the ``rank``-th size-``size`` combination in colex-free order.

    Unranking is what makes the choice exactly uniform: every one of the
    ``C(len(available), size)`` combinations has exactly one rank.
    """

    if size < 0 or size > len(available):
        raise SamplingError("combination size is out of range")
    total = math.comb(len(available), size)
    if not 0 <= rank < total:
        raise SamplingError("combination rank is out of range")
    chosen: list[Card] = []
    index = 0
    left = size
    remaining_rank = rank
    while left:
        available_after = len(available) - index - 1
        skip = math.comb(available_after, left - 1)
        if remaining_rank < skip:
            chosen.append(available[index])
            left -= 1
        else:
            remaining_rank -= skip
        index += 1
    return tuple(chosen)


def sample_assignments(
    observation: PlayerObservation, *, seed: str, count: int
) -> tuple[HiddenHandAssignment, ...]:
    """Convenience entry point: build the model and draw ``count`` assignments."""

    sampler = UniformFeasibleSampler.for_observation(observation, seed=seed)
    return sampler.sample(count)


def uniform_sampling_summary(
    observation: PlayerObservation, *, seed: str, count: int
) -> dict[str, object]:
    """Return a canonical summary of a sampling request without leaking a hand."""

    model = HardConstraintModel.build(observation)
    sampler = UniformFeasibleSampler.build(model, seed=seed)
    drawn = sampler.sample(count)
    distinct = len({item.content_key() for item in drawn})
    return {
        "distinct_assignments_drawn": distinct,
        "feasible_assignment_count": feasible_assignment_count(model),
        "provenance": sampler.provenance(),
        "requested_count": count,
        "schema_version": SAMPLER_SCHEMA_VERSION,
    }
