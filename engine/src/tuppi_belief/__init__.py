"""Observation-safe behavioural beliefs over the exact Phase 5B prior.

This package deliberately stops at belief construction.  It does not alter any
search agent.  The public boundary is a :class:`PlayerObservation`, a causal
public-action prefix, and an immutable behaviour-model configuration; private
deal labels are confined to offline evaluation helpers.
"""

from .history import CausalPublicHistory, PublicAction
from .models import (
    BehaviorModel,
    DeterministicPolicyLikelihoodModel,
    EpsilonSmoothedPolicyModel,
    MixtureBehaviorModel,
    UniformLegalActionModel,
    default_policy_family_mixture,
)
from .posterior import (
    BehavioralBeliefConfiguration,
    BeliefDegeneracyError,
    WeightedBelief,
    build_belief,
    build_uniform_belief,
)
from .resampling import DeterministicResample, systematic_resample


BELIEF_LAYER_VERSION = "0.10.0"
BEHAVIORAL_BELIEF_SCHEMA_VERSION = "tuppi.belief.behavioral_belief.v1"

__all__ = (
    "BEHAVIORAL_BELIEF_SCHEMA_VERSION",
    "BELIEF_LAYER_VERSION",
    "BehaviorModel",
    "BeliefDegeneracyError",
    "BehavioralBeliefConfiguration",
    "CausalPublicHistory",
    "DeterministicPolicyLikelihoodModel",
    "DeterministicResample",
    "EpsilonSmoothedPolicyModel",
    "MixtureBehaviorModel",
    "default_policy_family_mixture",
    "PublicAction",
    "UniformLegalActionModel",
    "WeightedBelief",
    "build_belief",
    "build_uniform_belief",
    "systematic_resample",
)
