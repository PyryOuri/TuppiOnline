from __future__ import annotations

import pytest
from pathlib import Path

from tuppi_match.statistics import pair_inference
from tuppi_search import SEARCH_LAYER_VERSION
from tuppi_search.phase5g_a_audit import (
    AuditArtifactError,
    rebuild_pair_records,
    reconstruct_pair_inference,
    resolve_agent_identity,
    semantic_manifest,
    semantic_manifest_diff,
)

from tests.match.conftest import synthetic_pair


ANALYSIS = {
    "confidence_level": 0.95,
    "bootstrap_replicates": 50,
    "sign_flip_replicates": 50,
}


def _raw_artifact(pairs):
    return {
        "analysis_seed": "phase5g-a-test",
        "bank": {
            "bank_id": "streambank:sha256:" + "2" * 64,
            "name": "test_audit_bank",
            "role": "development",
            "root_seed": "phase5g-a-test",
            "initial_dealer": 0,
            "stream_count": len(pairs),
        },
        "pair_records": [
            {"ordinal": index, "record": pair.to_data()}
            for index, pair in enumerate(pairs)
        ],
    }


def test_raw_pair_reconstruction_reproduces_primary_inference() -> None:
    pairs = (
        synthetic_pair(even_winner=0, odd_winner=1, index=0),
        synthetic_pair(even_winner=1, odd_winner=0, index=1),
        synthetic_pair(even_winner=0, odd_winner=0, index=2),
        synthetic_pair(even_winner=1, odd_winner=1, index=3),
    )
    artifact = _raw_artifact(pairs)
    rebuilt = rebuild_pair_records(artifact)
    assert tuple(item.pair_record_id for item in rebuilt) == tuple(
        item.pair_record_id for item in pairs
    )
    expected = pair_inference(pairs, **ANALYSIS, analysis_seed="phase5g-a-test")
    observed = reconstruct_pair_inference(
        artifact, bootstrap_replicates=50, sign_flip_replicates=50
    )
    assert observed == expected


def test_aggregate_summary_cannot_be_presented_as_raw_evidence() -> None:
    with pytest.raises(AuditArtifactError, match="no pair_records"):
        rebuild_pair_records({"primary_match_inference": {}})


def test_phase5f_control_identity_is_multi_observer_against_root_uct() -> None:
    candidate_key, candidate_id = resolve_agent_identity(
        "multi_observer_ismcts_standard_v1"
    )
    opponent_key, opponent_id = resolve_agent_identity("root_info_uct_standard_v1")
    assert candidate_key == "multi_observer_ismcts_standard_v1"
    assert opponent_key == "root_info_uct_standard_v1"
    assert candidate_id != opponent_id
    assert opponent_key != "partner_aware_v1"


def test_development_reference_resolves_exactly_to_partner_aware() -> None:
    resolved_key, resolved_id = resolve_agent_identity("development_reference_v1")
    partner_key, partner_id = resolve_agent_identity("partner_aware_v1")
    assert resolved_key == partner_key == "partner_aware_v1"
    assert resolved_id == partner_id


def test_semantic_manifest_diff_ignores_operational_fields() -> None:
    left = {"bank_id": "a", "candidate_agent_id": "x", "worker_count": 1}
    right = {"bank_id": "a", "candidate_agent_id": "x", "worker_count": 8}
    assert semantic_manifest_diff(left, right) == {}
    right["candidate_agent_id"] = "y"
    assert semantic_manifest_diff(left, right) == {
        "candidate_agent_id": ("x", "y")
    }


def test_manifest_resolves_missing_control_agent_ids() -> None:
    report = {
        "candidate_profile_key": "multi_observer_ismcts_standard_v1",
        "opponent_profile_key": "root_info_uct_standard_v1",
        "pair_count": 8,
        "schema_version": "tuppi.search.phase5f_control.v1",
        "sealed_bank_opened": False,
        "bank": {
            "bank_id": "streambank:sha256:" + "3" * 64,
            "name": "phase5f_root_uct_control_v1",
            "role": "development",
            "root_seed": "tuppi-phase5f-root-uct-control-v1",
            "initial_dealer": 0,
            "stream_count": 8,
        },
        "primary_match_inference": {
            "statistics_version": "tuppi.match.pair_inference.v1"
        },
    }
    manifest = semantic_manifest(report)
    assert manifest["candidate_agent_id"].startswith("agent:sha256:")
    assert manifest["opponent_agent_id"].startswith("agent:sha256:")
    assert manifest["opponent_profile_key"] == "root_info_uct_standard_v1"
    assert manifest["natural_termination"] is True


def test_phase5g_a_documentation_and_patch_version_are_present() -> None:
    root = Path(__file__).resolve().parents[2]
    document = root / "docs/evaluation/phase5g_a_consistency_audit.md"
    assert SEARCH_LAYER_VERSION == "0.9.1"
    assert document.is_file()
    text = document.read_text(encoding="utf-8").lower()
    for phrase in ("i4", "0/0/32", "5/3/0", "sealed promotion bank"):
        assert phrase in text
