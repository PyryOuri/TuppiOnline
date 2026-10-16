"""The immutable indexed set of sampled hypothetical worlds.

One world set is built per decision and shared by **every** candidate root action.
That is the single most important property in Phase 5C, and it is enforced
structurally rather than by convention: :func:`build_world_set` takes an
observation and a configuration and has no parameter through which a candidate
action could enter, and :meth:`SampledWorldSet.identity_data` does not contain one
either. A world set that depended on the action would turn the comparison between
actions into a comparison between sampling noise.

Duplicates are kept
-------------------

Independent uniform draws over a finite feasible set produce repeats, and late in
a deal the feasible set can be tiny - sometimes a single world. Duplicates are
therefore *counted and reported*, never removed. Deduplicating would silently
change a uniform average over draws into a uniform average over distinct worlds,
which is a different estimator that nobody asked for.

Enumeration versus sampling
---------------------------

When the exact feasible-assignment count is small enough, the whole set can be
enumerated instead of sampled, which removes Monte Carlo error entirely. That mode
is available and is labelled ``enumeration`` in the record, never conflated with
sampling: an enumerated set answers a different question - the exact PIMC value
rather than an estimate of it - and a reader must be able to tell which they have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_engine import DealState, PlayerObservation
from tuppi_eval.serialization import content_digest
from tuppi_exact import (
    HardConstraintModel,
    HypotheticalContinuation,
    UniformFeasibleSampler,
    feasible_assignment_count,
    hypothetical_continuation,
)
from tuppi_exact.sampling import HiddenHandAssignment
from tuppi_rules import card_to_code, card_to_index

from .config import PimcConfiguration
from .errors import WorldSetError
from .random import SearchSeedHierarchy


WORLD_SET_SCHEMA_VERSION = "tuppi.search.sampled_world_set.v1"

#: Above this exact feasible count, enumeration is refused as impractical. The
#: bound is a work limit, not an accuracy limit: sampling remains available.
MAXIMUM_ENUMERATION_COUNT = 512


class WorldSetMode(StrEnum):
    """How the world set was obtained. Never conflated in a record."""

    UNIFORM_SAMPLING = "uniform_sampling"
    EXACT_ENUMERATION = "exact_enumeration"


class WorldStatus(StrEnum):
    CONSTRUCTED = "constructed"


@dataclass(frozen=True, slots=True)
class SampledWorld:
    """One hypothetical world, addressable by its index."""

    sample_index: int
    world_id: str
    continuation: HypotheticalContinuation
    status: WorldStatus = field(default=WorldStatus.CONSTRUCTED, init=False)

    def __post_init__(self) -> None:
        if type(self.sample_index) is not int or self.sample_index < 0:
            raise WorldSetError("sample_index must be a nonnegative integer")
        if not isinstance(self.continuation, HypotheticalContinuation):
            raise WorldSetError("a world wraps a HypotheticalContinuation")
        if not self.world_id.startswith("world:"):
            raise WorldSetError("world_id must carry the world: prefix")

    @property
    def state(self) -> DealState:
        return self.continuation.state


def world_identity(assignment: HiddenHandAssignment) -> str:
    """Content identity of one hidden-hand assignment.

    Derived from the assigned hands themselves, so two draws of the *same*
    assignment share an identity and the duplicate count is exact. The observing
    seat's hand is excluded: it is identical in every world and is real rather
    than sampled, so including it would leak a true hand into a record that must
    not contain one.
    """

    if not isinstance(assignment, HiddenHandAssignment):
        raise WorldSetError("world_identity requires a HiddenHandAssignment")
    return "world:" + content_digest(
        {
            "hidden_hands": [
                sorted(
                    card_to_code(card)
                    for card in assignment.hands[seat]
                )
                for seat in range(4)
                if seat != assignment.observing_seat
            ],
            "observing_seat": assignment.observing_seat,
            "schema_version": "tuppi.search.world_identity.v1",
        }
    )


@dataclass(frozen=True, slots=True)
class SampledWorldSet:
    """An immutable, indexed, candidate-independent set of hypothetical worlds."""

    mode: WorldSetMode
    worlds: tuple[SampledWorld, ...]
    information_state: str
    constraint_model_digest: str
    feasible_assignment_count: int
    world_sampling_seed: str
    requested_indices: tuple[int, ...]
    unique_world_count: int
    duplicate_count: int
    unknown_card_count: int
    schema_version: str = field(default=WORLD_SET_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.worlds:
            raise WorldSetError("a world set needs at least one world")
        if tuple(item.sample_index for item in self.worlds) != self.requested_indices:
            raise WorldSetError("world order must follow the requested indices")
        if self.requested_indices != tuple(range(len(self.requested_indices))):
            raise WorldSetError(
                "Phase 5C consumes the contiguous prefix, so indices must run "
                "from zero without gaps"
            )
        distinct = len({item.world_id for item in self.worlds})
        if distinct != self.unique_world_count:
            raise WorldSetError("unique_world_count disagrees with the world ids")
        if self.duplicate_count != len(self.worlds) - distinct:
            raise WorldSetError("duplicate_count disagrees with the world ids")
        if self.feasible_assignment_count < 1:
            raise WorldSetError("the feasible assignment count must be positive")
        if self.mode is WorldSetMode.EXACT_ENUMERATION:
            if self.duplicate_count:
                raise WorldSetError("an enumerated set cannot contain duplicates")
            if len(self.worlds) != self.feasible_assignment_count:
                raise WorldSetError(
                    "an enumerated set must contain every feasible assignment"
                )

    def __len__(self) -> int:
        return len(self.worlds)

    def world(self, sample_index: int) -> SampledWorld:
        """Random access by sample index."""

        if type(sample_index) is not int or not 0 <= sample_index < len(self.worlds):
            raise WorldSetError(f"sample index {sample_index!r} is out of range")
        return self.worlds[sample_index]

    def prefix(self, count: int) -> "SampledWorldSet":
        """Return the first ``count`` worlds as a smaller set.

        Prefix stability is what makes an action-stability study cheap: a larger
        budget's worlds are a strict superset of a smaller budget's, so the two
        share every world they have in common instead of re-rolling.
        """

        if type(count) is not int or not 1 <= count <= len(self.worlds):
            raise WorldSetError("prefix count is out of range")
        kept = self.worlds[:count]
        distinct = len({item.world_id for item in kept})
        return SampledWorldSet(
            mode=self.mode,
            worlds=kept,
            information_state=self.information_state,
            constraint_model_digest=self.constraint_model_digest,
            feasible_assignment_count=self.feasible_assignment_count,
            world_sampling_seed=self.world_sampling_seed,
            requested_indices=tuple(range(count)),
            unique_world_count=distinct,
            duplicate_count=count - distinct,
            unknown_card_count=self.unknown_card_count,
        )

    @property
    def duplicate_fraction(self) -> float:
        return self.duplicate_count / len(self.worlds)

    @property
    def fully_determined(self) -> bool:
        """True when public information leaves exactly one feasible world."""

        return self.feasible_assignment_count == 1

    def identity_data(self) -> dict[str, object]:
        """Canonical, candidate-free, hand-free identity of the world set."""

        return {
            "constraint_model_digest": self.constraint_model_digest,
            "feasible_assignment_count": self.feasible_assignment_count,
            "information_state": self.information_state,
            "mode": self.mode.value,
            "requested_world_count": len(self.worlds),
            "schema_version": WORLD_SET_SCHEMA_VERSION,
            "world_ids": [item.world_id for item in self.worlds],
            "world_sampling_seed": self.world_sampling_seed,
        }

    @property
    def world_set_id(self) -> str:
        return "worldset:" + content_digest(self.identity_data())

    def to_data(self) -> dict[str, object]:
        """Compact summary. Contains no hand and no candidate action."""

        return {
            "constraint_model_digest": self.constraint_model_digest,
            "duplicate_count": self.duplicate_count,
            "duplicate_fraction": round(self.duplicate_fraction, 6),
            "exact_feasible_assignment_count": self.feasible_assignment_count,
            "fully_determined": self.fully_determined,
            "mode": self.mode.value,
            "requested_indices": list(self.requested_indices),
            "requested_world_count": len(self.worlds),
            "schema_version": WORLD_SET_SCHEMA_VERSION,
            "unique_world_count": self.unique_world_count,
            "unknown_card_count": self.unknown_card_count,
            "world_construction_status": WorldStatus.CONSTRUCTED.value,
            "world_sampling_seed": self.world_sampling_seed,
            "world_set_id": self.world_set_id,
        }


def build_world_set(
    observation: PlayerObservation,
    *,
    configuration: PimcConfiguration,
    seeds: SearchSeedHierarchy,
    mode: WorldSetMode = WorldSetMode.UNIFORM_SAMPLING,
) -> SampledWorldSet:
    """Build the decision's world set.

    Note the signature: there is no candidate action parameter, and there is no
    way to pass one. Every legal root action is later evaluated against the object
    this returns.
    """

    if not isinstance(observation, PlayerObservation):
        raise WorldSetError("build_world_set requires a PlayerObservation")
    if not isinstance(configuration, PimcConfiguration):
        raise WorldSetError("build_world_set requires a PimcConfiguration")
    if not isinstance(seeds, SearchSeedHierarchy):
        raise WorldSetError("build_world_set requires a SearchSeedHierarchy")

    model = HardConstraintModel.build(observation)
    exact_count = feasible_assignment_count(model)
    if exact_count < 1:
        raise WorldSetError(
            "the hard public constraints admit no world; the observation cannot "
            "have come from a legal project_target_v1 state"
        )
    model_digest = "constraints:" + content_digest(model.identity_data())
    sampling_seed = seeds.world_sampling_seed()

    if mode is WorldSetMode.EXACT_ENUMERATION:
        assignments = _enumerate_assignments(model, observation)
    else:
        sampler = UniformFeasibleSampler.build(model, seed=sampling_seed)
        assignments = sampler.sample(configuration.world_count)

    worlds: list[SampledWorld] = []
    for index, assignment in enumerate(assignments):
        try:
            continuation = hypothetical_continuation(observation, assignment)
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed failure
            raise WorldSetError(
                f"world {index} could not be constructed: {type(exc).__name__}: {exc}"
            ) from exc
        worlds.append(
            SampledWorld(
                sample_index=index,
                world_id=world_identity(assignment),
                continuation=continuation,
            )
        )

    distinct = len({item.world_id for item in worlds})
    return SampledWorldSet(
        mode=mode,
        worlds=tuple(worlds),
        information_state=seeds.information_state,
        constraint_model_digest=model_digest,
        feasible_assignment_count=exact_count,
        world_sampling_seed=sampling_seed,
        requested_indices=tuple(range(len(worlds))),
        unique_world_count=distinct,
        duplicate_count=len(worlds) - distinct,
        unknown_card_count=len(model.unknown_cards),
    )


def can_enumerate(observation: PlayerObservation) -> bool:
    """Whether the feasible set is small enough to enumerate exactly."""

    model = HardConstraintModel.build(observation)
    return feasible_assignment_count(model) <= MAXIMUM_ENUMERATION_COUNT


def _enumerate_assignments(
    model: HardConstraintModel, observation: PlayerObservation
) -> tuple[HiddenHandAssignment, ...]:
    """Enumerate every feasible assignment, in canonical order.

    Used only for exact reference work and for tiny information states. The order
    is canonical so an enumerated set is reproducible, and the result is checked
    against the exact counter: if enumeration and counting disagree, one of them
    is wrong and neither may be used.
    """

    total = feasible_assignment_count(model)
    if total > MAXIMUM_ENUMERATION_COUNT:
        raise WorldSetError(
            f"{total} feasible assignments exceed the enumeration limit of "
            f"{MAXIMUM_ENUMERATION_COUNT}; sample instead"
        )
    seats = model.unknown_seats
    cards = list(model.unknown_cards)
    results: list[dict[int, tuple]] = []

    def recurse(position: int, remaining: dict[int, int], chosen: dict[int, list]):
        if position == len(cards):
            if all(value == 0 for value in remaining.values()):
                results.append(
                    {seat: tuple(chosen.get(seat, ())) for seat in range(4)}
                )
            return
        card = cards[position]
        for seat in sorted(model.allowed_seats(card)):
            if remaining.get(seat, 0) <= 0:
                continue
            remaining[seat] -= 1
            chosen.setdefault(seat, []).append(card)
            recurse(position + 1, remaining, chosen)
            chosen[seat].pop()
            remaining[seat] += 1

    recurse(0, {seat: model.capacity[seat] for seat in seats}, {})
    if len(results) != total:
        raise WorldSetError(
            f"enumeration produced {len(results)} assignments but the exact count "
            f"is {total}; the constraint model and the counter disagree"
        )

    own = model.observing_seat
    built: list[HiddenHandAssignment] = []
    for index, allocation in enumerate(results):
        hands: list[tuple] = []
        for seat in range(4):
            if seat == own:
                hands.append(tuple(observation.own_hand))
                continue
            combined = set(model.known_held[seat]) | set(allocation[seat])
            hands.append(tuple(sorted(combined, key=card_to_index)))
        owner = {
            card: seat
            for seat in range(4)
            for card in allocation[seat]
            if seat != own
        }
        built.append(
            HiddenHandAssignment(
                observing_seat=own,
                hands=tuple(hands),
                sampled_owner=owner,
                sample_index=index,
            )
        )
    built.sort(key=lambda item: world_identity(item))
    return tuple(
        HiddenHandAssignment(
            observing_seat=item.observing_seat,
            hands=item.hands,
            sampled_owner=item.sampled_owner,
            sample_index=index,
        )
        for index, item in enumerate(built)
    )
