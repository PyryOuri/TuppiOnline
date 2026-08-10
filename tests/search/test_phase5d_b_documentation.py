"""Documentation, schema, and registry gates for Phase 5D-B."""

from __future__ import annotations

import json
from pathlib import Path

from tuppi_search.root_info_uct_registry import (
    registry_snapshot,
    root_info_uct_specifications,
)


ROOT = Path(__file__).resolve().parents[2]


def test_phase5d_b_documentation_and_schemas_are_present():
    for relative in (
        "docs/search/root_information_uct.md",
        "docs/search/information_state_nodes.md",
        "docs/search/tiny_exact_information_reference.md",
        "docs/search/phase5d_b_results.md",
        "schemas/search/root_info_uct_configuration.schema.json",
        "schemas/search/root_info_uct_diagnostics.schema.json",
        "schemas/search/tiny_exact_information_reference.schema.json",
        "schemas/search/phase5d_b_evaluation.schema.json",
    ):
        assert (ROOT / relative).is_file(), relative


def test_phase5d_b_schemas_are_strict_json_objects():
    for path in (ROOT / "schemas" / "search").glob("*phase5d_b*.schema.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False


def test_phase5d_b_registry_is_separate_and_unsealed():
    snapshot = registry_snapshot()
    assert snapshot["schema_version"] == "tuppi.search.phase5d_b_registry.v1"
    assert snapshot["promotion_status"].startswith("No Phase 5D-B agent is promoted")
    assert len(root_info_uct_specifications()) == 3
    for specification in root_info_uct_specifications().values():
        assert specification.configuration["information_set_search"] == (
            "tuppi.search.root_info_uct.v1"
        )
        assert specification.configuration["persistent_search_tree"] is None
        assert specification.configuration["exact_tail_enabled"] is False


def test_phase5d_b_docs_state_the_structural_limits():
    text = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "docs/search/root_information_uct.md",
            "docs/search/phase5d_b_results.md",
        )
    ).lower()
    for phrase in (
        "partner_aware_v1",
        "exact-tail",
        "no recursive",
        "equilibrium",
        "sealed",
    ):
        assert phrase in text


def test_phase5d_b_source_does_not_modify_pimc_configuration_or_recurse():
    text = (ROOT / "src" / "tuppi_search" / "root_info_uct.py").read_text(
        encoding="utf-8"
    )
    assert "class PimcConfiguration" not in text
    assert "UniformFeasiblePimcAgent" not in text
    simulation_body = text.split("def _run_simulation", 1)[1].split("def _failure", 1)[0]
    assert "construct_root_info_uct_agent(" not in simulation_body
