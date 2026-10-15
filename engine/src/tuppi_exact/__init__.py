"""Phase 5B: the exact layer on top of Phase 4's hard public inference.

Five capabilities, all exact, and one diagnosis that uses them:

``constraints``
    The hard public constraint model. Phase 4's five facts plus the exclusions a
    public show action proves about the shower's whole hand.
``counting``
    The exact number of feasible hidden-hand assignments, and exact rational
    ownership frequencies under the uniform measure.
``sampling``
    Exactly uniform sampling over those assignments, from a deterministic
    unbiased integer source.
``continuation``
    A sampled assignment turned into a real, engine-validated ``DealState``, so
    the engine referees the sampler's soundness.
``solver``
    Exact perfect-information optimal play for a late-game position, with a hard
    budget: exact, or an error, never an estimate.
``integrity`` / ``diagnosis`` / ``variants``
    The frozen-baseline gate, the Phase 5B diagnostic agent identities, and the
    match-aware rule diagnosis those capabilities make possible.

The dependency direction is strict and checked: this package reads
``tuppi_rules``, ``tuppi_engine``, ``tuppi_eval``, ``tuppi_agents``, and
``tuppi_match``, and none of them may reference it. No Phase 4 agent can reach
the solver or the sampler, so no Phase 4 result becomes retroactively
search-assisted.
"""

from .constraints import (
    CONSTRAINT_MODEL_SCHEMA_VERSION,
    ELIGIBLE_SHOW_CARDS,
    ELIGIBLE_SHOW_CARDS_BY_COLOR,
    HardConstraintModel,
    derive_show_exclusions,
    own_show_exclusion_is_consistent,
    show_exclusion_for,
)
from .continuation import (
    CONTINUATION_SCHEMA_VERSION,
    HYPOTHETICAL_MATCH_REF_PREFIX,
    HypotheticalContinuation,
    continuations_for,
    hypothetical_continuation,
    reconstruct_initial_hands,
)
from .counting import (
    COUNTING_SCHEMA_VERSION,
    ClassAllocation,
    CountingPlan,
    assignments_with_card_at_seat,
    bounded_compositions,
    count_plan,
    count_summary,
    exact_ownership_counts,
    exact_uniform_marginals,
    feasible_assignment_count,
    multinomial,
)
from .errors import (
    ConstraintError,
    ContinuationError,
    CountingError,
    DiagnosisError,
    ExactError,
    IntegrityError,
    SamplingError,
    SolverBudgetError,
    SolverError,
)
from .integrity import (
    BASELINE_SCHEMA_VERSION,
    DISCLAIMED_CAPABILITY_FIELDS,
    FROZEN_ARTIFACT_PATHS,
    archive_manifest_agreement,
    build_baseline,
    capability_containment,
    integrity_report,
    repository_root,
    sealed_bank_containment,
    verify_baseline,
    working_tree_location,
)
from .sampling import (
    RANDOM_SOURCE_ID,
    SAMPLER_ALGORITHM_ID,
    SAMPLER_SCHEMA_VERSION,
    DeterministicBitSource,
    HiddenHandAssignment,
    UniformFeasibleSampler,
    sample_assignments,
    uniform_sampling_summary,
)
from .solver import (
    DEFAULT_MAXIMUM_TRICKS_REMAINING,
    DEFAULT_NODE_BUDGET,
    SOLVER_ALGORITHM_ID,
    SOLVER_SCHEMA_VERSION,
    LateGameSolution,
    SolvedAction,
    deal_outcome_for_split,
    is_within_exact_range,
    match_score_after_split,
    match_utility_is_monotone,
    monotonicity_certificate,
    optimal_play_actions,
    solve_continuation,
    solve_late_game,
    team0_prefers_more_tricks,
)
from .variants import (
    BASE_PROFILE_KEY,
    MATCH_PLAY_RULES,
    MATCH_RULES,
    MATCH_SHOW_RULES,
    VARIANT_SCHEMA_VERSION,
    DiagnosticVariant,
    all_match_rules_off_variant,
    base_profile,
    behaviour_digest_for_specification,
    composition_check,
    diagnostic_variants,
    protect_distance_variants,
    single_rule_off_variants,
    variants_by_label,
)


EXACT_LAYER_VERSION = "0.5.1"
PHASE = "phase5b"


__all__ = (
    "BASELINE_SCHEMA_VERSION",
    "BASE_PROFILE_KEY",
    "CONSTRAINT_MODEL_SCHEMA_VERSION",
    "CONTINUATION_SCHEMA_VERSION",
    "COUNTING_SCHEMA_VERSION",
    "ClassAllocation",
    "ConstraintError",
    "ContinuationError",
    "CountingError",
    "CountingPlan",
    "DEFAULT_MAXIMUM_TRICKS_REMAINING",
    "DEFAULT_NODE_BUDGET",
    "DISCLAIMED_CAPABILITY_FIELDS",
    "DeterministicBitSource",
    "DiagnosisError",
    "DiagnosticVariant",
    "ELIGIBLE_SHOW_CARDS",
    "ELIGIBLE_SHOW_CARDS_BY_COLOR",
    "EXACT_LAYER_VERSION",
    "ExactError",
    "FROZEN_ARTIFACT_PATHS",
    "HYPOTHETICAL_MATCH_REF_PREFIX",
    "HardConstraintModel",
    "HiddenHandAssignment",
    "HypotheticalContinuation",
    "IntegrityError",
    "LateGameSolution",
    "MATCH_PLAY_RULES",
    "MATCH_RULES",
    "MATCH_SHOW_RULES",
    "PHASE",
    "RANDOM_SOURCE_ID",
    "SAMPLER_ALGORITHM_ID",
    "SAMPLER_SCHEMA_VERSION",
    "SOLVER_ALGORITHM_ID",
    "SOLVER_SCHEMA_VERSION",
    "SamplingError",
    "SolvedAction",
    "SolverBudgetError",
    "SolverError",
    "UniformFeasibleSampler",
    "VARIANT_SCHEMA_VERSION",
    "all_match_rules_off_variant",
    "archive_manifest_agreement",
    "assignments_with_card_at_seat",
    "base_profile",
    "behaviour_digest_for_specification",
    "bounded_compositions",
    "build_baseline",
    "capability_containment",
    "composition_check",
    "continuations_for",
    "count_plan",
    "count_summary",
    "deal_outcome_for_split",
    "derive_show_exclusions",
    "diagnostic_variants",
    "exact_ownership_counts",
    "exact_uniform_marginals",
    "feasible_assignment_count",
    "hypothetical_continuation",
    "integrity_report",
    "is_within_exact_range",
    "match_score_after_split",
    "match_utility_is_monotone",
    "monotonicity_certificate",
    "multinomial",
    "optimal_play_actions",
    "own_show_exclusion_is_consistent",
    "protect_distance_variants",
    "reconstruct_initial_hands",
    "repository_root",
    "sample_assignments",
    "sealed_bank_containment",
    "show_exclusion_for",
    "single_rule_off_variants",
    "solve_continuation",
    "solve_late_game",
    "team0_prefers_more_tricks",
    "uniform_sampling_summary",
    "variants_by_label",
    "verify_baseline",
    "working_tree_location",
)
