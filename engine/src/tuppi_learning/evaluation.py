"""Deterministic complete-match evaluation of frozen learned checkpoints."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match import MatchComparison, MatchStream, pair_inference, run_pair, secondary_metrics

from .checkpoints import CheckpointMetadata, weight_digest
from .errors import LearningConfigurationError
from .models import ObservationOnlyActor


EVALUATION_SCHEMA_VERSION = "tuppi.learning.complete_match_evaluation.v1"


class FrozenLearnedAgent:
    """Engine agent that exposes only the deployment actor boundary."""

    def __init__(self, actor: ObservationOnlyActor, identity: str) -> None:
        self._actor = actor
        self._identity = identity

    @property
    def identity(self) -> str:
        return self._identity

    def choose_action(self, observation):
        return self._actor.choose_action(observation)


@dataclass(frozen=True, slots=True)
class CompleteMatchEvaluation:
    comparison_id: str
    candidate_agent_id: str
    opponent_agent_id: str
    root_seed: int | str
    pair_count: int
    pairs: tuple[Any, ...]
    inference: dict[str, object]
    secondary: dict[str, object]
    schema_version: str = EVALUATION_SCHEMA_VERSION

    def to_data(self) -> dict[str, object]:
        return {
            "candidate_agent_id": self.candidate_agent_id,
            "comparison_id": self.comparison_id,
            "inference": self.inference,
            "opponent_agent_id": self.opponent_agent_id,
            "pair_count": self.pair_count,
            "pairs": [pair.to_data() for pair in self.pairs],
            "root_seed": self.root_seed,
            "schema_version": self.schema_version,
            "secondary": self.secondary,
        }


def learned_agent_id(*, checkpoint_id: str, weight_sha256: str, configuration_id: str) -> str:
    payload = json.dumps(
        {
            "configuration_id": configuration_id,
            "inference_rule": "greedy_logit_then_engine_action_order_v1",
            "learning_agent_version": "seat_relative_policy_v1",
            "checkpoint_id": checkpoint_id,
            "weight_sha256": weight_sha256,
        }, sort_keys=True, separators=(",", ":")
    ).encode()
    return "agent:sha256:" + hashlib.sha256(payload).hexdigest()


def evaluate_learned_against_phase4(
    actor_module: Any,
    checkpoint_metadata: CheckpointMetadata,
    *,
    root_seed: int | str,
    pair_count: int,
    opponent_profile_key: str = "partner_aware_v1",
    safety_cap: int = 512,
    analysis_seed: int | str = "phase6-evaluation",
) -> CompleteMatchEvaluation:
    if type(pair_count) is not int or pair_count <= 0:
        raise LearningConfigurationError("pair_count must be positive")
    if type(safety_cap) is not int or safety_cap <= 0:
        raise LearningConfigurationError("safety_cap must be positive")
    phase4 = phase4_specifications_by_profile_key()
    if opponent_profile_key not in phase4:
        raise LearningConfigurationError("unknown Phase 4 opponent profile")
    actor_configuration = getattr(actor_module, "configuration", None)
    if not hasattr(actor_configuration, "to_data") or (
        actor_configuration.to_data() != checkpoint_metadata.actor_configuration
    ):
        raise LearningConfigurationError(
            "actor configuration disagrees with checkpoint metadata"
        )
    if weight_digest(actor_module) != checkpoint_metadata.weight_sha256:
        raise LearningConfigurationError(
            "actor weights disagree with checkpoint metadata"
        )
    candidate_actor = ObservationOnlyActor(actor_module, device="cpu")
    candidate_id = learned_agent_id(
        checkpoint_id=checkpoint_metadata.checkpoint_id,
        weight_sha256=checkpoint_metadata.weight_sha256,
        configuration_id=actor_module.configuration.configuration_id,
    )
    opponent_id = phase4[opponent_profile_key].agent_id
    comparison = MatchComparison.build(
        name="phase6 learned policy versus frozen reference",
        candidate_profile_key="seat_relative_policy_v1",
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=candidate_id,
        opponent_agent_id=opponent_id,
        result_class="development",
        hypothesis="bounded learned-policy strength comparison",
    )

    def build_candidate(_seat: int):
        return FrozenLearnedAgent(candidate_actor, candidate_id)

    def build_opponent(seat: int):
        return construct_agent(phase4[opponent_profile_key], seat=seat)

    pairs = tuple(
        run_pair(
            stream=MatchStream.build(
                root_seed=root_seed,
                stream_index=index,
                initial_dealer=index % 4,
            ),
            comparison=comparison,
            safety_cap=safety_cap,
            ordinal=index,
            build_candidate=build_candidate,
            build_opponent=build_opponent,
        )
        for index in range(pair_count)
    )
    inference = pair_inference(
        pairs,
        confidence_level=0.95,
        analysis_seed=analysis_seed,
        bootstrap_replicates=2_000,
        sign_flip_replicates=2_000,
    )
    return CompleteMatchEvaluation(
        comparison_id=comparison.comparison_id,
        candidate_agent_id=candidate_id,
        opponent_agent_id=opponent_id,
        root_seed=root_seed,
        pair_count=pair_count,
        pairs=pairs,
        inference=inference,
        secondary=secondary_metrics(pairs),
    )
