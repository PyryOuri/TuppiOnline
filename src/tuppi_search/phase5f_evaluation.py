"""Phase 5F unsealed complete-match evaluation instruments.

The bank and schema are separate from Phase 5E.  The agent identities are not
changed: this module only supplies a fresh development stream and the same
frozen duplicate-pair protocol.
"""

from __future__ import annotations

from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.records import PairRecord
from tuppi_match.statistics import pair_inference, secondary_metrics

from .errors import SearchError
from .multi_observer_registry import (
    MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
)
from .phase5e_evaluation import (
    PHASE5E_DEFAULT_SAFETY_CAP,
    phase5e_agent_builder,
    phase5e_agent_identity,
)


PHASE5F_MATCH_ROOT_SEED = "tuppi-phase5f-match-v1"
PHASE5F_EVALUATION_SCHEMA_VERSION = "tuppi.search.phase5f_evaluation.v1"


def phase5f_match_bank(*, stream_count: int) -> StreamBank:
    """Return the fresh, unsealed Phase 5F development bank."""

    return StreamBank.build(
        name="phase5f_match_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5F_MATCH_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5F semantics-preserving optimization strength bank for "
            "redeterminizing multi-observer search; unsealed and separate from "
            "all earlier banks."
        ),
    )


def _comparison(
    *, candidate_profile_key: str, opponent_profile_key: str
) -> MatchComparison:
    return MatchComparison.build(
        name=f"phase5f_{candidate_profile_key}_vs_{opponent_profile_key}",
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=phase5e_agent_identity(candidate_profile_key),
        opponent_agent_id=phase5e_agent_identity(opponent_profile_key),
        result_class="development",
        hypothesis=(
            f"Does {candidate_profile_key} beat {opponent_profile_key} over "
            "fresh complete matches from 0-0 after Phase 5F optimization?"
        ),
    )


def _pair_from_data(data: dict) -> PairRecord:
    from tuppi_match.executor import _pair_from_data as rebuild

    return rebuild(data)


def _unit(payload: tuple) -> tuple[int, dict]:
    candidate_key, opponent_key, comparison_data, stream_count, safety_cap, ordinal = payload
    comparison = MatchComparison.build(
        name=comparison_data["name"],
        candidate_profile_key=comparison_data["candidate_profile_key"],
        opponent_profile_key=comparison_data["opponent_profile_key"],
        candidate_agent_id=comparison_data["candidate_agent_id"],
        opponent_agent_id=comparison_data["opponent_agent_id"],
        result_class=comparison_data["result_class"],
        hypothesis=comparison_data["hypothesis"],
        starting_score=tuple(comparison_data["starting_score"]),
    )
    record = run_pair(
        stream=phase5f_match_bank(stream_count=stream_count).stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=phase5e_agent_builder(candidate_key),
        build_opponent=phase5e_agent_builder(opponent_key),
    )
    return ordinal, record.to_data()


def _run_units(
    *,
    candidate_key: str,
    opponent_key: str,
    comparison: MatchComparison,
    pairs: int,
    safety_cap: int,
    workers: int | None,
    progress=None,
) -> tuple[PairRecord, ...]:
    units = [
        (candidate_key, opponent_key, comparison.to_data(), pairs, safety_cap, ordinal)
        for ordinal in range(pairs)
    ]
    collected: dict[int, PairRecord] = {}
    if workers is None or workers <= 1:
        iterator = map(_unit, units)
    else:
        from concurrent.futures import ProcessPoolExecutor

        pool = ProcessPoolExecutor(max_workers=workers)
        iterator = pool.map(_unit, units, chunksize=1)
    try:
        for index, (ordinal, data) in enumerate(iterator):
            collected[ordinal] = _pair_from_data(data)
            if progress is not None:
                progress(index + 1, pairs)
    finally:
        if workers is not None and workers > 1:
            pool.shutdown()
    return tuple(collected[index] for index in range(pairs))


def run_phase5f_match_comparison(
    *,
    candidate_profile_key: str = MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
    opponent_profile_key: str = "partner_aware_v1",
    pairs: int,
    safety_cap: int = PHASE5E_DEFAULT_SAFETY_CAP,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Run a fresh Phase 5F complementary complete-match comparison."""

    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be positive")
    comparison = _comparison(
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
    )
    records = _run_units(
        candidate_key=candidate_profile_key,
        opponent_key=opponent_profile_key,
        comparison=comparison,
        pairs=pairs,
        safety_cap=safety_cap,
        workers=workers,
        progress=progress,
    )
    return {
        "bank": phase5f_match_bank(stream_count=pairs).to_data(),
        "candidate_agent_id": phase5e_agent_identity(candidate_profile_key),
        "candidate_profile_key": candidate_profile_key,
        "comparison_id": comparison.comparison_id,
        "design": "homogeneous_partnership",
        "hypothesis": comparison.hypothesis,
        "name": comparison.name,
        "opponent_agent_id": phase5e_agent_identity(opponent_profile_key),
        "opponent_profile_key": opponent_profile_key,
        "pair_count": pairs,
        "primary_match_inference": pair_inference(
            records,
            confidence_level=0.95,
            analysis_seed=PHASE5F_MATCH_ROOT_SEED,
            bootstrap_replicates=2000,
            sign_flip_replicates=10000,
        ),
        "safety_cap": safety_cap,
        "schema_version": PHASE5F_EVALUATION_SCHEMA_VERSION,
        "secondary_metrics": secondary_metrics(records),
        "sealed_bank_opened": False,
        "worker_independence": (
            "Each pair is a pure function of the fresh Phase 5F bank, "
            "comparison, safety cap, and ordinal."
        ),
    }


__all__ = (
    "PHASE5F_EVALUATION_SCHEMA_VERSION",
    "PHASE5F_MATCH_ROOT_SEED",
    "phase5f_match_bank",
    "run_phase5f_match_comparison",
)
