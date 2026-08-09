"""Phase 5F release gates and frozen-identity checks."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tuppi_search import SEARCH_LAYER_VERSION
from tuppi_search.multi_observer_registry import registry_snapshot
from tuppi_search.phase5f_evaluation import phase5f_match_bank


ROOT = Path(__file__).resolve().parents[2]


def test_phase5f_docs_and_schema_are_present_and_substantial():
    for relative in (
        "docs/search/phase5f_profiling.md",
        "docs/search/phase5f_sampler_optimization.md",
        "docs/search/phase5f_results.md",
    ):
        path = ROOT / relative
        assert path.is_file()
        assert len(path.read_text(encoding="utf-8")) > 1500
    schema = ROOT / "schemas/search/phase5f_results.schema.json"
    assert schema.is_file()
    payload = json.loads(schema.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(payload)
    assert payload["additionalProperties"] is False


def test_phase5f_version_and_frozen_registries():
    assert SEARCH_LAYER_VERSION == "0.9.0"
    snapshot = registry_snapshot()
    assert snapshot["registry_digest"] == (
        "sha256:0e58bc6f3445b1b102c2253c282ae9ad95584cbea52768a4efa0acdaff8c0707"
    )
    assert snapshot["promotion_status"].startswith("No Phase 5E agent is promoted")
    bank = phase5f_match_bank(stream_count=2).to_data()
    assert bank["name"] == "phase5f_match_v1"
    assert bank["supports_promotion"] is False
    assert bank["role"] == "development"


def test_phase5f_docs_state_scope_and_gate():
    text = " ".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "docs/search/phase5f_profiling.md",
            "docs/search/phase5f_sampler_optimization.md",
            "docs/search/phase5f_results.md",
        )
    ).lower()
    for phrase in (
        "exact phase 5b",
        "sample_one",
        "semantic",
        "h2",
        "sealed promotion bank",
        "no approximate sampler",
    ):
        assert phrase in text
