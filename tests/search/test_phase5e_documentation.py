"""Release and boundary gates for Phase 5E."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tuppi_search import SEARCH_LAYER_VERSION
from tuppi_search.multi_observer_registry import (
    REGISTERED_MULTI_OBSERVER_CONFIGURATIONS,
    multi_observer_specifications,
    registry_snapshot,
)
from tuppi_search.tiny_multi_observer_reference import TinyMultiObserverReference


ROOT = Path(__file__).resolve().parents[2]


def test_phase5e_documents_and_schemas_are_present_and_substantial():
    for relative in (
        "docs/search/multi_observer_search.md",
        "docs/search/redeterminization.md",
        "docs/search/observer_privacy.md",
        "docs/search/tiny_multi_observer_oracle.md",
        "docs/search/phase5e_results.md",
        "schemas/search/multi_observer_configuration.schema.json",
        "schemas/search/multi_observer_diagnostics.schema.json",
        "schemas/search/phase5e_evaluation.schema.json",
        "schemas/search/tiny_multi_observer_reference.schema.json",
    ):
        path = ROOT / relative
        assert path.is_file(), relative
        if path.suffix == ".md":
            assert len(path.read_text(encoding="utf-8")) > 1500, relative


def test_phase5e_schemas_are_strict_draft_2020_12_objects():
    for path in (
        ROOT / "schemas/search/multi_observer_configuration.schema.json",
        ROOT / "schemas/search/multi_observer_diagnostics.schema.json",
        ROOT / "schemas/search/phase5e_evaluation.schema.json",
        ROOT / "schemas/search/tiny_multi_observer_reference.schema.json",
    ):
        schema = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_live_phase5e_configuration_validates():
    schema = json.loads(
        (ROOT / "schemas/search/multi_observer_configuration.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = jsonschema.Draft202012Validator(schema)
    for configuration in REGISTERED_MULTI_OBSERVER_CONFIGURATIONS.values():
        validator.validate(configuration.to_data())


def test_phase5e_registry_is_new_and_unsealed():
    snapshot = registry_snapshot()
    assert snapshot["schema_version"] == "tuppi.search.phase5e_registry.v1"
    assert snapshot["promotion_status"].startswith("No Phase 5E agent is promoted")
    assert len(snapshot["agents"]) == 3
    assert len({item["agent_id"] for item in snapshot["agents"]}) == 3


def test_phase5e_version_and_algorithm_boundaries():
    assert SEARCH_LAYER_VERSION == "0.8.0"
    text = (ROOT / "src/tuppi_search/multi_observer.py").read_text(encoding="utf-8")
    assert "PimcConfiguration" not in text
    assert "UniformFeasiblePimcAgent" not in text
    simulation_body = text.split("def _run_simulation", 1)[1].split("def _showing_decision", 1)[0]
    assert "decide(" not in simulation_body
    assert "exact_tail_enabled" in text


def test_phase5e_docs_state_the_scope_limits():
    text = " ".join(
        " ".join((ROOT / relative).read_text(encoding="utf-8").split())
        for relative in (
            "docs/search/multi_observer_search.md",
            "docs/search/redeterminization.md",
            "docs/search/observer_privacy.md",
            "docs/search/tiny_multi_observer_oracle.md",
        )
    ).lower()
    for phrase in (
        "partner_aware_v1",
        "exact-tail",
        "not an equilibrium",
        "uniform-feasible",
        "parent state is never replaced",
    ):
        assert phrase in text, phrase


def test_tiny_oracle_release_values_are_frozen():
    reference = TinyMultiObserverReference.structural_counterexample()
    assert reference.pimc_values() == {"A": 1.0, "B": 0.6}
    assert reference.exact_information_set_values() == {"B": 0.6, "A": 0.5}
    assert reference.root_only_prefix(1)["action"] == "A"
    assert reference.multi_observer_prefix(4)["action"] == "B"
