"""Deterministic observation-only baseline agents for ``project_target_v1``.

Phase 4 provides a reproducible reference population, not a strong agent. Every
policy here is deterministic, receives only a frozen
:class:`tuppi_engine.PlayerObservation`, and contains no search, no rollouts, no
hidden-hand sampling, no belief model, no solver, and no learning.

No agent in this package is expert-validated. The heuristics are a mixture of
mechanical consequences of the ruleset, adaptations of the frozen legacy
implementation, generic trick-taking hypotheses, and project hypotheses; each
one is catalogued with that provenance in
:mod:`tuppi_agents.rule_catalogue`.
"""

from .action_scoring import (
    ACTION_SCORING_SCHEMA_VERSION,
    CandidateEvaluation,
    ScoredActions,
    score_legal_actions,
)
from .controls import (
    CONTROL_FAMILIES,
    construct_control_agent,
    control_agent_specifications,
    control_specification,
)
from .counting import PublicCountingPolicy
from .diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    CandidateDiagnostic,
    DecisionDiagnostics,
    assert_no_foreign_cards,
    build_diagnostics,
    observation_digest,
)
from .errors import (
    AgentConstructionError,
    AgentsError,
    AgentsValidationError,
    DiagnosticsError,
    ObservationBoundaryError,
    PolicyError,
    ProfileError,
    RuleCatalogueError,
)
from .factory import (
    POLICY_IMPLEMENTATIONS,
    construct_agent,
    construct_registered_agent,
    profile_of,
)
from .features import (
    FEATURES_SCHEMA_VERSION,
    DealMatchContext,
    HandDescriptors,
    MatchRole,
    PublicFeatures,
    ShowingContext,
    VerbalFallbackCategory,
    build_deal_match_context,
    build_features,
    build_showing_context,
    describe_hand,
    verbal_fallback_category,
)
from .legacy_port import LegacyHeuristicPortPolicy
from .match_aware import MatchAwarePolicy
from .ordering import (
    ACTION_ORDERING_ID,
    CANONICAL_SUIT_PRECEDENCE_ID,
    LEGACY_SUIT_PRECEDENCE_ID,
    TIE_BREAK_ID,
    ordered_legal_actions,
)
from .partner_aware import PartnerAwarePolicy
from .profiles import (
    LEGACY_CONVENTION_ID,
    PROFILE_SCHEMA_VERSION,
    HeuristicProfile,
    PolicyFamily,
    ShowingPolicyId,
    profile_catalogue_to_data,
    profile_from_data,
    registered_profiles,
    require_profile,
)
from .protocol import (
    Decision,
    DiagnosticsRecordingAgent,
    ObservationOnlyAgent,
    RuleBasedPolicy,
)
from .public_inference import (
    PUBLIC_INFERENCE_SCHEMA_VERSION,
    PublicInference,
)
from .reactive import PlayMode, ReactiveContractPolicy
from .registry import (
    LADDER_PROFILE_KEYS,
    STRATEGIC_PROFILE_KEYS,
    control_agent_id,
    phase4_agent_specifications,
    phase4_registry,
    phase4_specifications_by_profile_key,
    phase4_team,
    phase4_team_specifications,
    specification_for_profile,
    strategic_agent_id,
    strategic_configuration,
)
from .rule_catalogue import (
    RULE_CATALOGUE,
    RULE_CATALOGUE_SCHEMA_VERSION,
    Provenance,
    StrategyRule,
    disableable_rule_ids,
    require_rule,
    rule_catalogue_by_id,
    rule_catalogue_to_data,
    rules_for_profile,
)
from .showing import contract_preference, score_showing, showing_scalars
from .trick_context import TrickContext, build_trick_context


AGENTS_VERSION = "0.4.0"


__all__ = (
    "ACTION_ORDERING_ID",
    "ACTION_SCORING_SCHEMA_VERSION",
    "AGENTS_VERSION",
    "AgentConstructionError",
    "AgentsError",
    "AgentsValidationError",
    "CANONICAL_SUIT_PRECEDENCE_ID",
    "CONTROL_FAMILIES",
    "CandidateDiagnostic",
    "CandidateEvaluation",
    "DIAGNOSTICS_SCHEMA_VERSION",
    "DealMatchContext",
    "Decision",
    "DecisionDiagnostics",
    "DiagnosticsError",
    "DiagnosticsRecordingAgent",
    "FEATURES_SCHEMA_VERSION",
    "HandDescriptors",
    "HeuristicProfile",
    "LADDER_PROFILE_KEYS",
    "LEGACY_CONVENTION_ID",
    "LEGACY_SUIT_PRECEDENCE_ID",
    "LegacyHeuristicPortPolicy",
    "MatchAwarePolicy",
    "MatchRole",
    "ObservationOnlyAgent",
    "PROFILE_SCHEMA_VERSION",
    "PUBLIC_INFERENCE_SCHEMA_VERSION",
    "POLICY_IMPLEMENTATIONS",
    "PartnerAwarePolicy",
    "PlayMode",
    "PolicyError",
    "PolicyFamily",
    "ProfileError",
    "Provenance",
    "PublicCountingPolicy",
    "PublicFeatures",
    "PublicInference",
    "RULE_CATALOGUE",
    "RULE_CATALOGUE_SCHEMA_VERSION",
    "ReactiveContractPolicy",
    "RuleBasedPolicy",
    "RuleCatalogueError",
    "STRATEGIC_PROFILE_KEYS",
    "ScoredActions",
    "ShowingContext",
    "ShowingPolicyId",
    "StrategyRule",
    "TIE_BREAK_ID",
    "TrickContext",
    "VerbalFallbackCategory",
    "ObservationBoundaryError",
    "assert_no_foreign_cards",
    "build_deal_match_context",
    "build_diagnostics",
    "build_features",
    "build_showing_context",
    "build_trick_context",
    "construct_agent",
    "construct_control_agent",
    "construct_registered_agent",
    "contract_preference",
    "control_agent_id",
    "control_agent_specifications",
    "control_specification",
    "describe_hand",
    "disableable_rule_ids",
    "observation_digest",
    "ordered_legal_actions",
    "phase4_agent_specifications",
    "phase4_registry",
    "phase4_specifications_by_profile_key",
    "phase4_team",
    "phase4_team_specifications",
    "profile_catalogue_to_data",
    "profile_from_data",
    "profile_of",
    "registered_profiles",
    "require_profile",
    "require_rule",
    "rule_catalogue_by_id",
    "rule_catalogue_to_data",
    "rules_for_profile",
    "score_legal_actions",
    "score_showing",
    "showing_scalars",
    "specification_for_profile",
    "strategic_agent_id",
    "strategic_configuration",
    "verbal_fallback_category",
)
