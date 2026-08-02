"""The definitive complete-match duplicate protocol for ``project_target_v1``.

Phase 4 measured agents on *deals*. That endpoint cannot value a policy whose
objective is the match: a partnership that is behind scores nothing for any
win, so signed deal points are blind to match safety. Phase 4's match mode also
capped streams at 40 deals, which sat near the median observed match length and
censored roughly a third of all pairs.

Phase 5A replaces that with one protocol:

* an **extensible deterministic stream** addressed by
  ``(protocol version, root seed, stream index, deal index)`` with true random
  access, so both legs of a pair read the same deals even though they run to
  different lengths;
* a **complementary duplicate pair** - Leg E with the candidate on seats 0 and
  2, Leg O with the candidate on seats 1 and 3 - each from 0-0, each to natural
  termination at 52 or more;
* ``D_match = (Y_E - Y_O) / 2`` as the pair value and
  ``(1 + mean(D_match)) / 2`` as the primary endpoint;
* **censoring as an infrastructure status**, never a draw and never a policy
  result;
* explicit **development, calibration, and promotion-sealed** bank roles.

No search, solver, hidden-hand sampler, belief model, or learning is added here,
and the five frozen Phase 4 agents are measured, never modified.
"""

from .banks import (
    BANK_SCHEMA_VERSION,
    BankRole,
    StreamBank,
    open_sealed_bank,
    require_not_sealed,
    require_role,
    sealed_commitment,
    write_sealed_seed,
)
from .calibration import (
    ABLATION_STEP,
    LADDER_STEPS,
    calibrate_safety_cap,
    calibration_bank,
    development_bank,
    diagnostic_bank,
    ladder_comparisons,
)
from .diagnostics import (
    DIAGNOSTIC_SCORES,
    score_state_comparisons,
    summarize_score_states,
)
from .errors import (
    BankRoleError,
    ExecutionError,
    InferenceError,
    IntegrityConflictError,
    ManifestError,
    MatchProtocolError,
    MatchValidationError,
    RecordError,
    SealedBankError,
    StreamError,
)
from .executor import (
    WorkUnit,
    default_worker_count,
    execute_unit,
    run_experiment,
    work_units,
)
from .experiment import (
    EXPERIMENT_SCHEMA_VERSION,
    ExperimentResult,
    build_report,
    load_report,
    run,
)
from .freeze import (
    FROZEN_SNAPSHOT_SCHEMA_VERSION,
    PHASE4_IMPLEMENTATION_COMMIT,
    FrozenAgent,
    behaviour_actions,
    behaviour_digest,
    build_snapshot,
    frozen_agent,
    verify_snapshot,
)
from .manifest import (
    DEFAULT_SAFETY_CAP,
    MATCH_MANIFEST_SCHEMA_VERSION,
    MATCH_PROTOCOL_VERSION,
    STATISTICS_VERSION,
    MatchComparison,
    MatchManifest,
)
from .protocol import (
    candidate_engine_team,
    match_reference,
    run_leg,
    run_pair,
    seat_assignment,
)
from .records import (
    LegIdentity,
    LegRecord,
    LegStatus,
    PairRecord,
    PairStatus,
    ScoreStateOccupancy,
)
from .statistics import length_distribution, pair_inference, secondary_metrics
from .streams import (
    DEFAULT_CHUNK_SIZE,
    STREAM_GENERATOR_ID,
    STREAM_PROTOCOL_VERSION,
    MatchStream,
    StreamDeal,
    stream_family,
)


MATCH_VERSION = "0.5.0"


__all__ = (
    "ABLATION_STEP",
    "BANK_SCHEMA_VERSION",
    "BankRole",
    "BankRoleError",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_SAFETY_CAP",
    "DIAGNOSTIC_SCORES",
    "EXPERIMENT_SCHEMA_VERSION",
    "ExecutionError",
    "ExperimentResult",
    "FROZEN_SNAPSHOT_SCHEMA_VERSION",
    "FrozenAgent",
    "InferenceError",
    "IntegrityConflictError",
    "LADDER_STEPS",
    "LegIdentity",
    "LegRecord",
    "LegStatus",
    "MATCH_MANIFEST_SCHEMA_VERSION",
    "MATCH_PROTOCOL_VERSION",
    "MATCH_VERSION",
    "ManifestError",
    "MatchComparison",
    "MatchManifest",
    "MatchProtocolError",
    "MatchStream",
    "MatchValidationError",
    "PHASE4_IMPLEMENTATION_COMMIT",
    "PairRecord",
    "PairStatus",
    "RecordError",
    "STATISTICS_VERSION",
    "STREAM_GENERATOR_ID",
    "STREAM_PROTOCOL_VERSION",
    "ScoreStateOccupancy",
    "SealedBankError",
    "StreamBank",
    "StreamDeal",
    "StreamError",
    "WorkUnit",
    "behaviour_actions",
    "behaviour_digest",
    "build_report",
    "build_snapshot",
    "calibrate_safety_cap",
    "calibration_bank",
    "candidate_engine_team",
    "default_worker_count",
    "development_bank",
    "diagnostic_bank",
    "execute_unit",
    "frozen_agent",
    "ladder_comparisons",
    "length_distribution",
    "load_report",
    "match_reference",
    "open_sealed_bank",
    "pair_inference",
    "require_not_sealed",
    "require_role",
    "run",
    "run_experiment",
    "run_leg",
    "run_pair",
    "score_state_comparisons",
    "sealed_commitment",
    "seat_assignment",
    "secondary_metrics",
    "stream_family",
    "summarize_score_states",
    "verify_snapshot",
    "work_units",
    "write_sealed_seed",
)
