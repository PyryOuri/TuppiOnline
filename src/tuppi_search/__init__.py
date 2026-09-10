"""Phase 5C: the first search-based Tuppi baseline.

``tuppi_search`` implements **classical root Perfect-Information Monte Carlo** over
the exactly uniform hard-feasible worlds Phase 5B provides:

1. build the Phase 5B hard constraint set from the acting seat's observation;
2. sample an indexed set of uniformly feasible hidden-hand assignments;
3. construct one engine-validated hypothetical world per sample;
4. force each legal root action into **every** world of that one common set;
5. complete each deal with observation-only rollout policies, optionally handing
   the endgame to the Phase 5B exact solver;
6. average root-team-oriented utility and select deterministically.

What it is not
--------------

A PIMC baseline, not an equilibrium solver. It must never be described as optimal
imperfect-information play. Each sampled world is evaluated as one complete world and
the averaging happens afterwards, so PIMC can combine strategies that are
individually sensible in one world and mutually incompatible across worlds. That is
**strategy fusion**: it is structural, and more samples shrink Monte Carlo error
without touching it.

Phase 5C deliberately contains **no** information-set tree search (ISMCTS, MO-ISMCTS,
RIS-MCTS, POMCP), no persistent search tree or tree reuse, no neural policy or value
model, no learned or heuristic hidden-hand likelihood weighting, no particle filter,
no Bayesian belief model, no counterfactual regret minimization, no reinforcement
learning, no self-play or population training, and no search distillation.
:mod:`tuppi_search.validation` scans for those families rather than trusting this
paragraph.

Boundaries
----------

The deployable agent receives a :class:`tuppi_engine.PlayerObservation`, an immutable
configuration, and an explicit policy seed. It has no parameter for engine state,
real hands, deal identity, fixture identity, or sealed metadata. Rollout policies
receive only their own seat's projected observation. The dependency direction is
one-way: this package reads the earlier ones and none of them may reference it.
"""

from .agents import (
    DEFAULT_POLICY_SEED,
    UniformFeasiblePimcAgent,
    construct_pimc_agent,
)
from .config import (
    ACTION_ORDERING_ID,
    DEFAULT_EXACT_TAIL_MAX_TRICKS_REMAINING,
    DEVELOPMENT_REFERENCE_POLICY,
    MAXIMUM_EXACT_TAIL_TRICKS_REMAINING,
    PIMC_CONFIGURATION_SCHEMA_VERSION,
    PIMC_PROTOCOL_VERSION,
    SAMPLE_INDEX_PROTOCOL,
    SUPPORTED_ROLLOUT_POLICIES,
    TIE_BREAK_ID,
    ExactTailFailurePolicy,
    FailurePolicy,
    PimcConfiguration,
    RootContinuation,
)
from .diagnostics import (
    DIAGNOSTICS_SCHEMA_VERSION,
    FORBIDDEN_KEYS,
    PimcDecisionDiagnostics,
    observation_visible_card_codes,
    require_privacy_safe,
)
from .errors import (
    ExactTailError,
    IllegalRolloutActionError,
    OracleError,
    PimcDecisionError,
    RootInfoUctDecisionError,
    RootInfoUctInvariantError,
    RolloutError,
    SearchConfigurationError,
    SearchDiagnosticsError,
    SearchError,
    SeedError,
    UtilityError,
    WorldSetError,
)
from .information_state import (
    ROOT_INFORMATION_STATE_SCHEMA_VERSION,
    root_information_state_data,
    root_information_state_key,
)
from .root_info_uct import (
    ROOT_INFO_UCT_ACTION_ORDERING_ID,
    ROOT_INFO_UCT_CONFIGURATION_SCHEMA_VERSION,
    ROOT_INFO_UCT_DIAGNOSTICS_SCHEMA_VERSION,
    ROOT_INFO_UCT_EXPANSION_RULE_ID,
    ROOT_INFO_UCT_FINAL_ACTION_RULE_ID,
    ROOT_INFO_UCT_NORMALIZATION_ID,
    ROOT_INFO_UCT_PROTOCOL_VERSION,
    ROOT_INFO_UCT_SEED_PROTOCOL_VERSION,
    RootInfoUctAgent,
    RootInfoUctConfiguration,
    RootInfoUctDecision,
    RootInfoUctFailureKind,
    RootInfoUctTree,
    construct_root_info_uct_agent,
    decide as decide_root_info_uct,
)
from .root_info_uct_registry import (
    ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
    build_agent as build_root_info_uct_profile_agent,
    configuration_for as root_info_uct_configuration_for,
    registry_snapshot as root_info_uct_registry_snapshot,
    root_info_uct_specifications,
    specification_for as root_info_uct_specification_for,
)
from .multi_observer import (
    MULTI_OBSERVER_ALGORITHM_ID,
    MULTI_OBSERVER_AVAILABILITY_RULE_ID,
    MULTI_OBSERVER_CONFIGURATION_SCHEMA_VERSION,
    MULTI_OBSERVER_DIAGNOSTICS_SCHEMA_VERSION,
    MULTI_OBSERVER_EXPANSION_RULE_ID,
    MULTI_OBSERVER_FINAL_ACTION_RULE_ID,
    MULTI_OBSERVER_PROTOCOL_VERSION,
    MULTI_OBSERVER_REDETERMINIZATION_RULE_ID,
    MULTI_OBSERVER_SEED_PROTOCOL_VERSION,
    MultiObserverAgent,
    MultiObserverConfiguration,
    MultiObserverDecision,
    MultiObserverFailureKind,
    MultiObserverTree,
    construct_multi_observer_agent,
    decide as decide_multi_observer,
)
from .multi_observer_registry import (
    MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
    build_agent as build_multi_observer_profile_agent,
    configuration_for as multi_observer_configuration_for,
    multi_observer_specifications,
    registry_snapshot as multi_observer_registry_snapshot,
    specification_for as multi_observer_specification_for,
)
from .exact_tail import EXACT_TAIL_SCHEMA_VERSION, ExactTail, TailVerdict
from .pimc import (
    PIMC_DECISION_SCHEMA_VERSION,
    CandidateSummary,
    PimcDecision,
    WorldEvaluation,
    decide,
)
from .random import (
    CANDIDATE_DEPENDENT_DOMAINS,
    INFORMATION_STATE_SCHEMA_VERSION,
    SEED_PROTOCOL_VERSION,
    SearchSeedHierarchy,
    SeedDomain,
    canonical_action_id,
    information_state_digest,
    stable_text_digest,
)
from .registry import (
    AGENT_FAMILY,
    PRIMARY_PROFILE_KEY,
    REGISTERED_CONFIGURATIONS,
    build_agent,
    configuration_for,
    homogeneous_team,
    phase5c_specifications,
    registry_snapshot,
    specification_for,
)
from .rollout import (
    MAXIMUM_ROLLOUT_ACTIONS,
    ROLLOUT_SCHEMA_VERSION,
    RolloutOutcome,
    SeatPolicies,
    complete_deal,
)
from .utilities import (
    MAXIMUM_DEAL_POINTS,
    UTILITY_SCHEMA_VERSION,
    DealOutcomeSummary,
    OutcomeSource,
    UtilityId,
    exact_tail_summary,
    is_registerable,
    summary_from_completed_deal,
    summary_from_fast_completion,
    utility_catalogue,
    utility_description,
    utility_range,
    utility_value,
)
from .validation import (
    EARLIER_PACKAGES,
    EXCLUDED_TECHNIQUE_PATTERNS,
    VALIDATION_SCHEMA_VERSION,
    boundary_report,
    dependency_direction_problems,
    development_reference_problems,
    excluded_technique_problems,
    frozen_agent_problems,
    match_aware_not_retuned,
    require_no_full_state,
)
from .worlds import (
    MAXIMUM_ENUMERATION_COUNT,
    WORLD_SET_SCHEMA_VERSION,
    SampledWorld,
    SampledWorldSet,
    WorldSetMode,
    WorldStatus,
    build_world_set,
    can_enumerate,
    world_identity,
)


SEARCH_LAYER_VERSION = "0.9.1"
PHASE = "phase5g-a"


__all__ = (
    "ACTION_ORDERING_ID",
    "AGENT_FAMILY",
    "CANDIDATE_DEPENDENT_DOMAINS",
    "CandidateSummary",
    "DEFAULT_EXACT_TAIL_MAX_TRICKS_REMAINING",
    "DEFAULT_POLICY_SEED",
    "DEVELOPMENT_REFERENCE_POLICY",
    "DIAGNOSTICS_SCHEMA_VERSION",
    "DealOutcomeSummary",
    "EARLIER_PACKAGES",
    "EXACT_TAIL_SCHEMA_VERSION",
    "EXCLUDED_TECHNIQUE_PATTERNS",
    "ExactTail",
    "ExactTailError",
    "ExactTailFailurePolicy",
    "FORBIDDEN_KEYS",
    "FailurePolicy",
    "INFORMATION_STATE_SCHEMA_VERSION",
    "IllegalRolloutActionError",
    "MAXIMUM_DEAL_POINTS",
    "MAXIMUM_ENUMERATION_COUNT",
    "MAXIMUM_EXACT_TAIL_TRICKS_REMAINING",
    "MAXIMUM_ROLLOUT_ACTIONS",
    "OracleError",
    "OutcomeSource",
    "PHASE",
    "PIMC_CONFIGURATION_SCHEMA_VERSION",
    "PIMC_DECISION_SCHEMA_VERSION",
    "PIMC_PROTOCOL_VERSION",
    "PRIMARY_PROFILE_KEY",
    "PimcConfiguration",
    "PimcDecision",
    "PimcDecisionDiagnostics",
    "PimcDecisionError",
    "ROOT_INFORMATION_STATE_SCHEMA_VERSION",
    "ROOT_INFO_UCT_ACTION_ORDERING_ID",
    "ROOT_INFO_UCT_CONFIGURATION_SCHEMA_VERSION",
    "ROOT_INFO_UCT_DIAGNOSTICS_SCHEMA_VERSION",
    "ROOT_INFO_UCT_EXPANSION_RULE_ID",
    "ROOT_INFO_UCT_FINAL_ACTION_RULE_ID",
    "ROOT_INFO_UCT_NORMALIZATION_ID",
    "ROOT_INFO_UCT_PROTOCOL_VERSION",
    "ROOT_INFO_UCT_PRIMARY_PROFILE_KEY",
    "ROOT_INFO_UCT_SEED_PROTOCOL_VERSION",
    "RootInfoUctAgent",
    "RootInfoUctConfiguration",
    "RootInfoUctDecision",
    "RootInfoUctDecisionError",
    "RootInfoUctFailureKind",
    "RootInfoUctInvariantError",
    "RootInfoUctTree",
    "MULTI_OBSERVER_ALGORITHM_ID",
    "MULTI_OBSERVER_AVAILABILITY_RULE_ID",
    "MULTI_OBSERVER_CONFIGURATION_SCHEMA_VERSION",
    "MULTI_OBSERVER_DIAGNOSTICS_SCHEMA_VERSION",
    "MULTI_OBSERVER_EXPANSION_RULE_ID",
    "MULTI_OBSERVER_FINAL_ACTION_RULE_ID",
    "MULTI_OBSERVER_PROTOCOL_VERSION",
    "MULTI_OBSERVER_REDETERMINIZATION_RULE_ID",
    "MULTI_OBSERVER_SEED_PROTOCOL_VERSION",
    "MultiObserverAgent",
    "MultiObserverConfiguration",
    "MultiObserverDecision",
    "MultiObserverFailureKind",
    "MultiObserverTree",
    "build_multi_observer_profile_agent",
    "construct_multi_observer_agent",
    "decide_multi_observer",
    "multi_observer_configuration_for",
    "multi_observer_registry_snapshot",
    "multi_observer_specification_for",
    "multi_observer_specifications",
    "REGISTERED_CONFIGURATIONS",
    "ROLLOUT_SCHEMA_VERSION",
    "RolloutError",
    "RolloutOutcome",
    "RootContinuation",
    "SAMPLE_INDEX_PROTOCOL",
    "SEARCH_LAYER_VERSION",
    "SEED_PROTOCOL_VERSION",
    "SUPPORTED_ROLLOUT_POLICIES",
    "SampledWorld",
    "SampledWorldSet",
    "SearchConfigurationError",
    "SearchDiagnosticsError",
    "SearchError",
    "SearchSeedHierarchy",
    "SeatPolicies",
    "SeedDomain",
    "SeedError",
    "TIE_BREAK_ID",
    "TailVerdict",
    "UTILITY_SCHEMA_VERSION",
    "UniformFeasiblePimcAgent",
    "UtilityError",
    "UtilityId",
    "VALIDATION_SCHEMA_VERSION",
    "WORLD_SET_SCHEMA_VERSION",
    "WorldEvaluation",
    "WorldSetError",
    "construct_root_info_uct_agent",
    "decide_root_info_uct",
    "root_information_state_data",
    "root_information_state_key",
    "WorldSetMode",
    "WorldStatus",
    "boundary_report",
    "build_agent",
    "build_root_info_uct_profile_agent",
    "build_world_set",
    "can_enumerate",
    "canonical_action_id",
    "complete_deal",
    "configuration_for",
    "root_info_uct_configuration_for",
    "construct_pimc_agent",
    "decide",
    "dependency_direction_problems",
    "development_reference_problems",
    "exact_tail_summary",
    "excluded_technique_problems",
    "frozen_agent_problems",
    "homogeneous_team",
    "information_state_digest",
    "is_registerable",
    "match_aware_not_retuned",
    "observation_visible_card_codes",
    "phase5c_specifications",
    "registry_snapshot",
    "root_info_uct_registry_snapshot",
    "require_no_full_state",
    "require_privacy_safe",
    "specification_for",
    "root_info_uct_specification_for",
    "root_info_uct_specifications",
    "stable_text_digest",
    "summary_from_completed_deal",
    "summary_from_fast_completion",
    "utility_catalogue",
    "utility_description",
    "utility_range",
    "utility_value",
    "world_identity",
)
