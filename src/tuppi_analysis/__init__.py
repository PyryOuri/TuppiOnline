"""Research-only analyses built on the frozen Tuppi engine and policies."""

from .rami_nolo_threshold import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentConfig,
    apply_forced_choice,
    collect_corpus,
    current_production_rule,
    evaluate_source_deal,
    forced_action_for_contract,
    paired_threshold_comparison,
    run_experiment,
    threshold_choice,
    threshold_sweep,
)


__all__ = (
    "EXPERIMENT_SCHEMA_VERSION",
    "ExperimentConfig",
    "apply_forced_choice",
    "collect_corpus",
    "current_production_rule",
    "evaluate_source_deal",
    "forced_action_for_contract",
    "paired_threshold_comparison",
    "run_experiment",
    "threshold_choice",
    "threshold_sweep",
)
