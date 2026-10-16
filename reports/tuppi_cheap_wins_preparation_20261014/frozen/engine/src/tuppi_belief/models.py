"""Observation-only action likelihood models.

Each model returns a probability distribution over the legal actions in the
observation.  A candidate hidden world is visible to this module only through
the reconstructed observation of the acting seat.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from functools import lru_cache
from typing import Mapping

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import Action, PlayerObservation


MODEL_SCHEMA_VERSION = "tuppi.belief.behavior_model.v1"
SUPPORTED_POLICY_PROFILES = frozenset(
    {"reactive_contract_v1", "public_counting_v1", "partner_aware_v1"}
)


def _validate_observation(observation: PlayerObservation) -> tuple[Action, ...]:
    if not isinstance(observation, PlayerObservation):
        raise TypeError("a behaviour model requires a PlayerObservation")
    if observation.current_actor != observation.observing_seat:
        raise ValueError("behaviour likelihood requires the acting seat's observation")
    if not observation.legal_actions:
        raise ValueError("behaviour likelihood requires at least one legal action")
    return observation.legal_actions


class BehaviorModel(ABC):
    """The minimal deployable action-likelihood boundary."""

    model_id: str

    @abstractmethod
    def identity_data(self) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    def probabilities(self, observation: PlayerObservation) -> Mapping[Action, float]:
        raise NotImplementedError

    def probability(self, observation: PlayerObservation, action: Action) -> float:
        probabilities = self.probabilities(observation)
        if action not in probabilities:
            raise ValueError("observed action is not legal in the reconstructed observation")
        return probabilities[action]

    def log_probability(self, observation: PlayerObservation, action: Action) -> float:
        probability = self.probability(observation, action)
        return -math.inf if probability == 0.0 else math.log(probability)


@dataclass(frozen=True, slots=True)
class UniformLegalActionModel(BehaviorModel):
    """Control model: every currently legal action receives equal mass."""

    model_id: str = field(default="uniform_legal_action_model_v1", init=False)

    def identity_data(self) -> dict[str, object]:
        return {"model_id": self.model_id, "schema_version": MODEL_SCHEMA_VERSION}

    def probabilities(self, observation: PlayerObservation) -> Mapping[Action, float]:
        legal = _validate_observation(observation)
        probability = 1.0 / len(legal)
        return {action: probability for action in legal}


@lru_cache(maxsize=None)
def _frozen_policy(profile_key: str, seat: int):
    specifications = phase4_specifications_by_profile_key()
    if profile_key not in SUPPORTED_POLICY_PROFILES:
        raise ValueError(f"unsupported behaviour policy {profile_key!r}")
    return construct_agent(specifications[profile_key], seat=seat)


@dataclass(frozen=True, slots=True)
class DeterministicPolicyLikelihoodModel(BehaviorModel):
    """Oracle-like likelihood: the frozen policy action has probability one."""

    profile_key: str
    model_id: str = field(default="deterministic_policy_likelihood_v1", init=False)

    def __post_init__(self) -> None:
        if self.profile_key not in SUPPORTED_POLICY_PROFILES:
            raise ValueError(f"unsupported behaviour policy {self.profile_key!r}")

    def identity_data(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "profile_key": self.profile_key,
            "schema_version": MODEL_SCHEMA_VERSION,
        }

    def probabilities(self, observation: PlayerObservation) -> Mapping[Action, float]:
        legal = _validate_observation(observation)
        selected = _frozen_policy(self.profile_key, observation.observing_seat).choose_action(
            observation
        )
        return {action: 1.0 if action == selected else 0.0 for action in legal}


@dataclass(frozen=True, slots=True)
class EpsilonSmoothedPolicyLikelihoodModel(BehaviorModel):
    """A fixed uniform mixture around a deterministic frozen policy."""

    profile_key: str
    epsilon: float = 0.10
    model_id: str = field(default="epsilon_smoothed_policy_likelihood_v1", init=False)

    def __post_init__(self) -> None:
        if self.profile_key not in SUPPORTED_POLICY_PROFILES:
            raise ValueError(f"unsupported behaviour policy {self.profile_key!r}")
        if not math.isfinite(self.epsilon) or not 0.0 < self.epsilon < 1.0:
            raise ValueError("epsilon must be finite and strictly between zero and one")

    def identity_data(self) -> dict[str, object]:
        return {
            "epsilon": self.epsilon,
            "model_id": self.model_id,
            "profile_key": self.profile_key,
            "schema_version": MODEL_SCHEMA_VERSION,
        }

    def probabilities(self, observation: PlayerObservation) -> Mapping[Action, float]:
        legal = _validate_observation(observation)
        selected = _frozen_policy(self.profile_key, observation.observing_seat).choose_action(
            observation
        )
        uniform = self.epsilon / len(legal)
        return {action: uniform + (1.0 - self.epsilon if action == selected else 0.0)
                for action in legal}


@dataclass(frozen=True, slots=True)
class MixtureBehaviorModel(BehaviorModel):
    """An explicit, hidden-state-independent mixture of action models."""

    components: tuple[BehaviorModel, ...]
    weights: tuple[float, ...]
    model_id: str = field(default="policy_family_mixture_v1", init=False)

    def __post_init__(self) -> None:
        if not self.components or len(self.components) != len(self.weights):
            raise ValueError("mixture needs one weight per component")
        if any(not isinstance(item, BehaviorModel) for item in self.components):
            raise TypeError("mixture components must be behaviour models")
        if any(not math.isfinite(weight) or weight < 0.0 for weight in self.weights):
            raise ValueError("mixture weights must be finite and nonnegative")
        if not math.isclose(sum(self.weights), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("mixture weights must sum to one")

    def identity_data(self) -> dict[str, object]:
        return {
            "components": [component.identity_data() for component in self.components],
            "model_id": self.model_id,
            "schema_version": MODEL_SCHEMA_VERSION,
            "weights": list(self.weights),
        }

    def probabilities(self, observation: PlayerObservation) -> Mapping[Action, float]:
        legal = _validate_observation(observation)
        result = {action: 0.0 for action in legal}
        for weight, component in zip(self.weights, self.components, strict=True):
            probabilities = component.probabilities(observation)
            if set(probabilities) != set(legal):
                raise ValueError("mixture components disagree on legal actions")
            for action in legal:
                result[action] += weight * probabilities[action]
        return result


def default_policy_family_mixture(*, epsilon: float = 0.10) -> MixtureBehaviorModel:
    """The preregistered equal-weight robust diagnostic mixture."""

    components = tuple(
        EpsilonSmoothedPolicyLikelihoodModel(profile, epsilon=epsilon)
        for profile in ("reactive_contract_v1", "public_counting_v1", "partner_aware_v1")
    )
    return MixtureBehaviorModel(components=components, weights=(1 / 3, 1 / 3, 1 / 3))


EpsilonSmoothedPolicyModel = EpsilonSmoothedPolicyLikelihoodModel
