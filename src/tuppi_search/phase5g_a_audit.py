"""Evaluation-integrity helpers for the Phase 5G-A cross-bank audit.

This module does not alter any agent or match semantics.  It provides the
small, explicit boundaries needed to reconstruct pair-level records from
external replay artifacts and to compare evaluation manifests without
mistaking operational metadata for semantic inputs.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from tuppi_agents import phase4_specifications_by_profile_key
from tuppi_match.executor import _pair_from_data
from tuppi_match.records import PairRecord
from tuppi_match.statistics import pair_inference

from .multi_observer_registry import multi_observer_specifications
from .root_info_uct_registry import root_info_uct_specifications


PHASE5G_A_SCHEMA_VERSION = "tuppi.search.phase5g_a_audit.v1"
REFERENCE_PROFILE_KEY = "development_reference_v1"
REFERENCE_RESOLVED_PROFILE_KEY = "partner_aware_v1"
OPERATIONAL_MANIFEST_FIELDS = frozenset(
    {"operational_wall_seconds", "worker_count", "output_path", "timestamp"}
)


class AuditArtifactError(ValueError):
    """Raised when an audit artifact cannot support the requested check."""


def resolve_agent_identity(profile_key: str) -> tuple[str, str]:
    """Resolve a display profile to its canonical profile and agent ID."""

    resolved = (
        REFERENCE_RESOLVED_PROFILE_KEY
        if profile_key == REFERENCE_PROFILE_KEY
        else profile_key
    )
    if resolved in phase4_specifications_by_profile_key():
        return resolved, phase4_specifications_by_profile_key()[resolved].agent_id
    if resolved in root_info_uct_specifications():
        return resolved, root_info_uct_specifications()[resolved].agent_id
    if resolved in multi_observer_specifications():
        return resolved, multi_observer_specifications()[resolved].agent_id
    raise AuditArtifactError(f"unknown evaluation profile {profile_key!r}")


def rebuild_pair_records(artifact: Mapping[str, object]) -> tuple[PairRecord, ...]:
    """Rebuild immutable pair records from a raw replay artifact.

    Aggregate historical reports intentionally do not satisfy this interface;
    the explicit error prevents a summary from being presented as raw evidence.
    """

    rows = artifact.get("pair_records")
    if not isinstance(rows, list) or not rows:
        raise AuditArtifactError(
            "artifact has no pair_records; aggregate summaries cannot be "
            "independently reconstructed without a deterministic replay"
        )
    ordered: dict[int, PairRecord] = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("ordinal")) is not int:
            raise AuditArtifactError("each pair record needs an integer ordinal")
        ordinal = row["ordinal"]
        if ordinal in ordered:
            raise AuditArtifactError(f"duplicate pair ordinal {ordinal}")
        payload = row.get("record")
        if not isinstance(payload, dict):
            raise AuditArtifactError("each pair record needs a serialized record")
        ordered[ordinal] = _pair_from_data(payload)
    expected = tuple(range(len(ordered)))
    if tuple(sorted(ordered)) != expected:
        raise AuditArtifactError("pair ordinals must be a contiguous zero-based prefix")
    return tuple(ordered[index] for index in expected)


def reconstruct_pair_inference(
    artifact: Mapping[str, object],
    *,
    bootstrap_replicates: int = 2_000,
    sign_flip_replicates: int = 10_000,
) -> dict[str, object]:
    """Recompute the primary inference from raw pair records only."""

    records = rebuild_pair_records(artifact)
    seed = artifact.get("analysis_seed")
    if not isinstance(seed, (str, int)):
        bank = artifact.get("bank")
        seed = bank.get("root_seed") if isinstance(bank, dict) else None
    if not isinstance(seed, (str, int)):
        raise AuditArtifactError("raw artifact has no analysis seed")
    return pair_inference(
        records,
        confidence_level=0.95,
        analysis_seed=seed,
        bootstrap_replicates=bootstrap_replicates,
        sign_flip_replicates=sign_flip_replicates,
    )


def semantic_manifest(report: Mapping[str, object]) -> dict[str, object]:
    """Extract semantic comparison fields from an evaluation report.

    The result deliberately excludes output paths, timestamps, worker counts,
    and elapsed time.  Fields absent from older reports are resolved from the
    frozen registry or the complete-match protocol constants.
    """

    bank = report.get("bank")
    if not isinstance(bank, dict):
        raise AuditArtifactError("evaluation report has no bank manifest")
    candidate_key = report.get("candidate_profile_key")
    opponent_key = report.get("opponent_profile_key")
    if not isinstance(candidate_key, str) or not isinstance(opponent_key, str):
        raise AuditArtifactError("evaluation report has no candidate/opponent keys")
    candidate_resolved, candidate_id = resolve_agent_identity(candidate_key)
    opponent_resolved, opponent_id = resolve_agent_identity(opponent_key)
    reported_candidate_id = report.get("candidate_agent_id")
    reported_opponent_id = report.get("opponent_agent_id")
    if reported_candidate_id is not None and reported_candidate_id != candidate_id:
        raise AuditArtifactError("candidate profile resolves to a different agent ID")
    if reported_opponent_id is not None and reported_opponent_id != opponent_id:
        raise AuditArtifactError("opponent profile resolves to a different agent ID")
    inference = report.get("primary_match_inference")
    if not isinstance(inference, dict):
        raise AuditArtifactError("evaluation report has no primary inference")
    return {
        "ruleset_id": "project_target_v1",
        "candidate_profile_key": candidate_key,
        "candidate_resolved_profile_key": candidate_resolved,
        "candidate_agent_id": candidate_id,
        "opponent_profile_key": opponent_key,
        "opponent_resolved_profile_key": opponent_resolved,
        "opponent_agent_id": opponent_id,
        "bank_id": bank.get("bank_id"),
        "bank_name": bank.get("name"),
        "bank_role": bank.get("role"),
        "root_seed": bank.get("root_seed"),
        "initial_dealer": bank.get("initial_dealer"),
        "bank_stream_count": bank.get("stream_count"),
        "pair_count": report.get("pair_count"),
        "safety_cap": report.get("safety_cap", 704),
        "starting_score": [0, 0],
        "natural_termination": True,
        "failure_policy": "strict",
        "pairing_orientation": "candidate_even_in_E_and_O_complementary_legs",
        "match_protocol_version": "tuppi.match.complete_duplicate_pair.v1",
        "stream_protocol_version": "tuppi.match.stream.v1",
        "statistics_version": inference.get("statistics_version"),
        "evaluator_schema_version": report.get("schema_version"),
        "sealed_bank_opened": report.get("sealed_bank_opened"),
    }


def semantic_manifest_diff(
    left: Mapping[str, object], right: Mapping[str, object]
) -> dict[str, tuple[object, object]]:
    """Return semantic field differences between two normalized manifests."""

    keys = sorted((set(left) | set(right)) - OPERATIONAL_MANIFEST_FIELDS)
    return {
        key: (left.get(key), right.get(key))
        for key in keys
        if left.get(key) != right.get(key)
    }


def pair_outcome_rows(records: Sequence[PairRecord]) -> list[dict[str, object]]:
    """Return privacy-safe pair-level replay rows for an audit artifact."""

    return [
        {
            "ordinal": ordinal,
            "pair_record_id": record.pair_record_id,
            "stream_id": record.stream_id,
            "status": record.status.value,
            "d_match": record.d_match,
            "candidate_won_even": record.leg_even.candidate_won,
            "candidate_won_odd": record.leg_odd.candidate_won,
            "deals_even": record.leg_even.deals_consumed,
            "deals_odd": record.leg_odd.deals_consumed,
        }
        for ordinal, record in enumerate(records)
    ]


__all__ = (
    "AuditArtifactError",
    "PHASE5G_A_SCHEMA_VERSION",
    "REFERENCE_PROFILE_KEY",
    "REFERENCE_RESOLVED_PROFILE_KEY",
    "pair_outcome_rows",
    "rebuild_pair_records",
    "reconstruct_pair_inference",
    "resolve_agent_identity",
    "semantic_manifest",
    "semantic_manifest_diff",
)
