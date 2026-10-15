"""Finite weighted beliefs over the exact hard-feasible prior."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from tuppi_engine import PlayerObservation
from tuppi_eval.serialization import content_digest
from tuppi_exact.constraints import HardConstraintModel
from tuppi_exact.sampling import HiddenHandAssignment, UniformFeasibleSampler

from .history import CausalPublicHistory
from .models import BehaviorModel
from .reconstruction import replay_candidate


POSTERIOR_SCHEMA_VERSION = "tuppi.belief.weighted_feasible_posterior.v1"


class BeliefDegeneracyError(ValueError):
    """No sampled feasible candidate has finite behavioural support."""


@dataclass(frozen=True, slots=True)
class BehavioralBeliefConfiguration:
    """Identity-bearing causal weighting choices."""

    candidate_count: int = 128
    seed: str = "phase5g-b-default"
    include_showing: bool = True
    include_trick_play: bool = True
    actor_seats: tuple[int, ...] | None = None
    temperature: float = 1.0
    model_id: str = field(default="behavioral_feasible_importance_v1", init=False)
    schema_version: str = field(default=POSTERIOR_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.candidate_count) is not int or self.candidate_count <= 0:
            raise ValueError("candidate_count must be positive")
        if not isinstance(self.seed, str) or not self.seed:
            raise ValueError("belief seed must be a nonempty string")
        if type(self.include_showing) is not bool or type(self.include_trick_play) is not bool:
            raise TypeError("history inclusion flags must be booleans")
        if not math.isfinite(self.temperature) or self.temperature <= 0.0:
            raise ValueError("temperature must be finite and positive")
        if self.actor_seats is not None:
            if type(self.actor_seats) is not tuple:
                raise TypeError("actor_seats must be a tuple")
            if any(type(seat) is not int or seat not in range(4) for seat in self.actor_seats):
                raise ValueError("actor_seats must contain seats in 0..3")
            if len(set(self.actor_seats)) != len(self.actor_seats):
                raise ValueError("actor_seats must not repeat a seat")

    def identity_data(self, *, model: BehaviorModel) -> dict[str, object]:
        return {
            "actor_seats": self.actor_seats,
            "candidate_count": self.candidate_count,
            "include_showing": self.include_showing,
            "include_trick_play": self.include_trick_play,
            "model": model.identity_data(),
            "model_id": self.model_id,
            "schema_version": self.schema_version,
            "seed": self.seed,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class BeliefDiagnostics:
    """Privacy-safe numerical diagnostics for one finite belief."""

    finite_candidate_count: int
    zero_weight_count: int
    effective_sample_size: float
    normalized_entropy: float
    max_log_weight: float
    min_finite_log_weight: float | None
    history_action_count: int
    scored_action_count: int
    replay_count: int
    schema_version: str = field(default="tuppi.belief.diagnostics.v1", init=False)

    def to_data(self) -> dict[str, object]:
        return {
            "effective_sample_size": self.effective_sample_size,
            "finite_candidate_count": self.finite_candidate_count,
            "history_action_count": self.history_action_count,
            "max_log_weight": self.max_log_weight,
            "min_finite_log_weight": self.min_finite_log_weight,
            "normalized_entropy": self.normalized_entropy,
            "replay_count": self.replay_count,
            "schema_version": self.schema_version,
            "scored_action_count": self.scored_action_count,
            "zero_weight_count": self.zero_weight_count,
        }


@dataclass(frozen=True, slots=True)
class WeightedBelief:
    """A weighted finite candidate set.

    ``assignments`` is intentionally retained only in memory for offline
    computation.  :meth:`to_data` contains no hands or candidate allocations.
    """

    observation: PlayerObservation = field(repr=False, compare=False)
    model_id: str
    candidate_ids: tuple[str, ...]
    assignments: tuple[HiddenHandAssignment, ...] = field(repr=False, compare=False)
    log_weights: tuple[float, ...]
    normalized_weights: tuple[float, ...]
    feasible_world_count: int
    diagnostics: BeliefDiagnostics
    schema_version: str = field(default=POSTERIOR_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        count = len(self.assignments)
        if len(self.candidate_ids) != count or len(self.log_weights) != count:
            raise ValueError("candidate arrays have inconsistent lengths")
        if len(self.normalized_weights) != count or count == 0:
            raise ValueError("a weighted belief needs nonempty candidate arrays")
        if any(weight < 0.0 or not math.isfinite(weight) for weight in self.normalized_weights):
            raise ValueError("normalized weights must be finite and nonnegative")
        if not math.isclose(sum(self.normalized_weights), 1.0, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError("normalized weights must sum to one")

    @property
    def candidate_count(self) -> int:
        return len(self.assignments)

    @property
    def effective_sample_size(self) -> float:
        return 1.0 / sum(weight * weight for weight in self.normalized_weights)

    @property
    def entropy(self) -> float:
        return -sum(
            weight * math.log(weight)
            for weight in self.normalized_weights
            if weight > 0.0
        )

    def owner_marginals(self) -> dict[str, dict[int, float]]:
        """Return P(owner=seat) for every currently unknown card."""

        hard = HardConstraintModel.build(self.observation)
        result: dict[str, dict[int, float]] = {}
        for card in hard.unknown_cards:
            owners = {seat: 0.0 for seat in hard.allowed_seat_map[card]}
            for assignment, weight in zip(self.assignments, self.normalized_weights, strict=True):
                owner = assignment.sampled_owner[card]
                owners[owner] = owners.get(owner, 0.0) + weight
            total = sum(owners.values())
            if total <= 0.0:
                raise ValueError("owner marginal has no mass")
            result[card.to_code()] = {
                seat: probability / total for seat, probability in sorted(owners.items())
            }
        return result

    def to_data(self) -> dict[str, object]:
        """Serialize only deployable/privacy-safe belief information."""

        return {
            "candidate_count": self.candidate_count,
            "candidate_ids": list(self.candidate_ids),
            "diagnostics": self.diagnostics.to_data(),
            "feasible_world_count": self.feasible_world_count,
            "model_id": self.model_id,
            "normalized_weights": list(self.normalized_weights),
            "owner_marginals": self.owner_marginals(),
            "schema_version": self.schema_version,
        }


def build_belief(
    observation: PlayerObservation,
    behavior_model: BehaviorModel,
    *,
    configuration: BehavioralBeliefConfiguration | None = None,
    history: CausalPublicHistory | None = None,
) -> WeightedBelief:
    """Build a self-normalized importance belief over exact feasible samples."""

    if not isinstance(observation, PlayerObservation):
        raise TypeError("belief construction requires a PlayerObservation")
    if not isinstance(behavior_model, BehaviorModel):
        raise TypeError("belief construction requires a BehaviorModel")
    config = configuration or BehavioralBeliefConfiguration()
    public_history = history or CausalPublicHistory.from_observation(observation)
    model = HardConstraintModel.build(observation)
    sampler = UniformFeasibleSampler.build(model, seed=config.seed)
    assignments = sampler.sample(config.candidate_count)
    actor_seats = (
        tuple(seat for seat in range(4) if seat != observation.observing_seat)
        if config.actor_seats is None
        else config.actor_seats
    )
    log_weights: list[float] = []
    scored_action_count = 0
    for assignment in assignments:
        replay = replay_candidate(observation, assignment, public_history)
        score = 0.0
        supported = True
        for item, actor_observation in replay.observations_before_actions():
            if item.action.seat not in actor_seats:
                continue
            if item.phase == "SHOWING" and not config.include_showing:
                continue
            if item.phase == "TRICK_PLAY" and not config.include_trick_play:
                continue
            scored_action_count += 1
            log_probability = behavior_model.log_probability(actor_observation, item.action)
            if not math.isfinite(log_probability):
                supported = False
                break
            score += log_probability
        log_weights.append(score / config.temperature if supported else -math.inf)
    finite = [value for value in log_weights if math.isfinite(value)]
    if not finite:
        raise BeliefDegeneracyError(
            "all sampled feasible worlds have zero behavioural likelihood; "
            "use an epsilon-smoothed or mixture model, or record this degeneracy"
        )
    maximum = max(finite)
    unnormalized = [math.exp(value - maximum) if math.isfinite(value) else 0.0 for value in log_weights]
    total = math.fsum(unnormalized)
    normalized = tuple(value / total for value in unnormalized)
    finite_count = len(finite)
    zero_count = len(log_weights) - finite_count
    entropy = -sum(weight * math.log(weight) for weight in normalized if weight > 0.0)
    diagnostics = BeliefDiagnostics(
        finite_candidate_count=finite_count,
        zero_weight_count=zero_count,
        effective_sample_size=1.0 / math.fsum(weight * weight for weight in normalized),
        normalized_entropy=entropy / math.log(len(normalized)) if len(normalized) > 1 else 1.0,
        max_log_weight=max(finite),
        min_finite_log_weight=min(finite),
        history_action_count=len(public_history.actions),
        scored_action_count=scored_action_count,
        replay_count=len(assignments),
    )
    ids = tuple(_assignment_id(assignment) for assignment in assignments)
    return WeightedBelief(
        observation=observation,
        model_id=content_digest(config.identity_data(model=behavior_model)),
        candidate_ids=ids,
        assignments=assignments,
        log_weights=tuple(log_weights),
        normalized_weights=normalized,
        feasible_world_count=sampler.total_assignments,
        diagnostics=diagnostics,
    )


def build_uniform_belief(
    observation: PlayerObservation,
    *,
    candidate_count: int = 128,
    seed: str = "phase5g-b-default",
) -> WeightedBelief:
    """Return the hard-uniform finite prior using the same candidate prefix."""

    model = HardConstraintModel.build(observation)
    sampler = UniformFeasibleSampler.build(model, seed=seed)
    assignments = sampler.sample(candidate_count)
    weights = tuple(1.0 / len(assignments) for _ in assignments)
    diagnostics = BeliefDiagnostics(
        finite_candidate_count=len(assignments),
        zero_weight_count=0,
        effective_sample_size=float(len(assignments)),
        normalized_entropy=1.0 if len(assignments) > 1 else 0.0,
        max_log_weight=0.0,
        min_finite_log_weight=0.0,
        history_action_count=len(CausalPublicHistory.from_observation(observation).actions),
        scored_action_count=0,
        replay_count=0,
    )
    return WeightedBelief(
        observation=observation,
        model_id="hard_uniform_feasible_prior_v1",
        candidate_ids=tuple(_assignment_id(item) for item in assignments),
        assignments=assignments,
        log_weights=tuple(0.0 for _ in assignments),
        normalized_weights=weights,
        feasible_world_count=sampler.total_assignments,
        diagnostics=diagnostics,
    )


def _assignment_id(assignment: HiddenHandAssignment) -> str:
    return content_digest(
        {
            "content": assignment.content_key(),
            "schema": "tuppi.belief.candidate_world.v1",
        }
    )
