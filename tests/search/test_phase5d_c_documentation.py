"""Repository-level release gates for Phase 5D-C."""

from __future__ import annotations

import json
from pathlib import Path

from tuppi_search import SEARCH_LAYER_VERSION
from tuppi_search.root_info_uct_registry import registry_snapshot


ROOT = Path(__file__).resolve().parents[2]


def test_phase5d_c_documents_and_schema_are_present() -> None:
    for relative in (
        "docs/search/phase5d_c_profiling.md",
        "docs/search/phase5d_c_optimization.md",
        "docs/search/phase5d_c_results.md",
        "schemas/search/phase5d_c_results.schema.json",
    ):
        path = ROOT / relative
        assert path.is_file(), relative
        if path.suffix == ".md":
            assert len(path.read_text(encoding="utf-8")) > 1500, relative


def test_phase5d_c_result_schema_is_strict_and_valid() -> None:
    schema = json.loads(
        (ROOT / "schemas/search/phase5d_c_results.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_phase5d_c_version_and_frozen_registry_boundary() -> None:
    assert SEARCH_LAYER_VERSION == "0.9.0"
    snapshot = registry_snapshot()
    assert len(snapshot["agents"]) == 3
    assert snapshot["promotion_status"].startswith("No Phase 5D-B agent is promoted")


def test_phase5d_c_docs_state_semantic_and_scope_boundaries() -> None:
    text = " ".join(
        " ".join((ROOT / relative).read_text(encoding="utf-8").split())
        for relative in (
            "docs/search/phase5d_c_profiling.md",
            "docs/search/phase5d_c_optimization.md",
            "docs/search/phase5d_c_results.md",
        )
    ).lower()
    for phrase in (
        "differential",
        "authoritative engine",
        "phase 5d-b search protocol",
        "path f2",
        "sealed promotion bank remains unopened",
        "no exact tail",
    ):
        assert phrase in text, phrase
