"""Phase 5C documentation, schemas, and committed reports must agree.

The strongest tests here check that a *number* in a document still matches the
committed report, not merely that a paragraph exists. A claim that drifts away from
the artifact that produced it is the failure mode these guard against.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "search"
SCHEMAS = ROOT / "schemas" / "search"
REPORTS = ROOT / "reports" / "phase5c"
EXAMPLES = ROOT / "examples" / "search"

REQUIRED_DOCS = (
    "architecture.md",
    "determinism.md",
    "exact_tail_integration.md",
    "phase5c_evaluation.md",
    "phase5d_a_handoff.md",
    "phase5d_a_hypotheses.md",
    "phase5d_a_results.md",
    "rollout_security.md",
    "uniform_feasible_pimc.md",
    "utilities.md",
)
REQUIRED_SCHEMAS = (
    "phase5d_a_convergence.schema.json",
    "phase5d_a_decomposition.schema.json",
    "phase5d_a_report.schema.json",
    "phase5c_evaluation.schema.json",
    "pimc_configuration.schema.json",
    "pimc_decision_diagnostics.schema.json",
    "search_benchmark.schema.json",
    "world_set_summary.schema.json",
)
REQUIRED_REPORTS = (
    "phase5c_evaluation.json",
    "pimc_registry.json",
    "search_benchmark.json",
)


def _text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _flat(name: str) -> str:
    """Collapse wrapping so a phrase assertion is not a line-length assertion."""

    return " ".join(_text(name).split())


def _report(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def test_every_required_document_exists_and_is_substantial() -> None:
    assert sorted(path.name for path in DOCS.glob("*.md")) == sorted(REQUIRED_DOCS)
    for name in REQUIRED_DOCS:
        assert len(_text(name)) > 1500, name


def test_every_required_schema_report_and_example_exists() -> None:
    assert sorted(path.name for path in SCHEMAS.glob("*.json")) == sorted(
        REQUIRED_SCHEMAS
    )
    assert sorted(path.name for path in REPORTS.glob("*.json")) == sorted(
        REQUIRED_REPORTS
    )
    assert (EXAMPLES / "README.md").is_file()
    assert len((EXAMPLES / "README.md").read_text(encoding="utf-8")) > 1500


@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_every_schema_is_a_valid_draft_2020_12_schema(name: str) -> None:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_a_live_configuration_validates_against_its_schema() -> None:
    from tuppi_search.registry import REGISTERED_CONFIGURATIONS

    schema = json.loads(
        (SCHEMAS / "pimc_configuration.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    for configuration in REGISTERED_CONFIGURATIONS.values():
        validator.validate(configuration.to_data())


def test_live_diagnostics_validate_against_their_schema(mid_position) -> None:
    from tuppi_search.registry import build_agent

    schema = json.loads(
        (SCHEMAS / "pimc_decision_diagnostics.schema.json").read_text(
            encoding="utf-8"
        )
    )
    agent = build_agent(
        "uniform_feasible_pimc_smoke_v1",
        seat=mid_position.observation.observing_seat,
    )
    jsonschema.Draft202012Validator(schema).validate(
        agent.explain(mid_position.observation).to_data()
    )


def test_a_live_world_set_summary_validates_against_its_schema(mid_position) -> None:
    from tuppi_search.config import PimcConfiguration
    from tuppi_search.random import SearchSeedHierarchy, information_state_digest
    from tuppi_search.worlds import build_world_set

    configuration = PimcConfiguration.build(world_count=2)
    world_set = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=SearchSeedHierarchy(
            pimc_protocol=configuration.pimc_protocol_version,
            information_state=information_state_digest(mid_position.observation),
            decision_seed="schema",
        ),
    )
    schema = json.loads(
        (SCHEMAS / "world_set_summary.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(world_set.to_data())


def test_the_committed_benchmark_validates_against_its_schema() -> None:
    schema = json.loads(
        (SCHEMAS / "search_benchmark.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(_report("search_benchmark.json"))


def test_the_committed_match_comparison_validates_against_its_schema() -> None:
    schema = json.loads(
        (SCHEMAS / "phase5c_evaluation.schema.json").read_text(encoding="utf-8")
    )
    report = _report("phase5c_evaluation.json")
    jsonschema.Draft202012Validator(schema).validate(
        report["primary_complete_match_comparison"]
    )


def test_the_committed_registry_matches_the_live_registry() -> None:
    from tuppi_search.registry import registry_snapshot

    committed = _report("pimc_registry.json")
    live = registry_snapshot()
    assert committed["registry_digest"] == live["registry_digest"]
    assert committed["primary_profile_key"] == live["primary_profile_key"]
    assert {item["agent_id"] for item in committed["agents"]} == {
        item["agent_id"] for item in live["agents"]
    }


def test_the_committed_boundary_report_still_holds() -> None:
    assert _report("pimc_registry.json")["boundary_report"]["holds"] is True


# ------------------------------------------------------------ document claims


def test_the_architecture_document_states_the_one_way_dependency() -> None:
    text = _flat("architecture.md")
    for phrase in (
        "None of them may reference it",
        "retroactively search-assisted",
        "Not an agent",
        "Why ISMCTS is deferred",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_algorithm_document_explains_strategy_fusion() -> None:
    text = _flat("uniform_feasible_pimc.md")
    for phrase in (
        "not an equilibrium solver",
        "strategy fusion",
        "more samples do not fix it",
        "policy mismatch",
        "not information-set-optimal",
    ):
        assert phrase.lower() in text.lower(), phrase
    assert "solving uncertainty" in text.lower()


def test_the_rollout_document_states_the_boundary_and_the_refusals() -> None:
    text = _flat("rollout_security.md")
    for phrase in (
        "The policy is never passed the state",
        "Illegal actions are never repaired",
        "distinct agent object",
        "nowhere to put one",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_exact_tail_document_states_that_it_may_hurt() -> None:
    text = _flat("exact_tail_integration.md")
    for phrase in (
        "The tail is not variance reduction",
        "changes the estimand",
        "puts that clairvoyance back",
        "perfect-information bias",
        "No silent partial exact result",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_utilities_document_names_the_registered_choice() -> None:
    text = _flat("utilities.md")
    for phrase in (
        "match_transition.v1",
        "not exact nonterminal match equity",
        "Overshoot past 52 is worth nothing",
        "Not registerable",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_determinism_document_states_the_candidate_rule() -> None:
    text = _flat("determinism.md")
    for phrase in (
        "World sampling never sees the candidate",
        "prefix-stability",
        "Deterministic budgets, not wall-clock",
        "salted per process",
    ):
        assert phrase.lower() in text.lower(), phrase


# ------------------------------------------------------- results agree exactly


def test_the_results_document_reports_the_recorded_win_probability() -> None:
    inference = _report("phase5c_evaluation.json")[
        "primary_complete_match_comparison"
    ]["primary_match_inference"]
    text = _flat("phase5c_evaluation.md")
    probability = inference["candidate_match_win_probability"]
    assert f"{probability:.3f}" in text
    outcomes = inference["pair_outcomes"]
    assert f"{outcomes['win']} / {outcomes['tie']} / {outcomes['loss']}" in text
    assert str(inference["complete_pair_count"]) in text


def test_the_results_document_reports_the_recorded_interval() -> None:
    inference = _report("phase5c_evaluation.json")[
        "primary_complete_match_comparison"
    ]["primary_match_inference"]
    low, high = inference["win_probability_confidence_interval"]
    text = _flat("phase5c_evaluation.md")
    assert f"[{low:.3f}, {high:.3f}]" in text


def test_the_results_document_reports_the_recorded_action_stability() -> None:
    stability = _report("phase5c_evaluation.json")["action_stability"]["stability"]
    text = _flat("phase5c_evaluation.md")
    for entry in stability:
        assert f"{entry['agreement_rate']:.3f}" in text
        assert f"({entry['agreements']}/{entry['comparisons']})" in text


def test_the_results_document_reports_the_recorded_showing_sensitivity() -> None:
    sensitivity = _report("phase5c_evaluation.json")[
        "showing_contract_sensitivity"
    ]
    text = _flat("phase5c_evaluation.md")
    assert f"{sensitivity['reference_rami_declaration_rate']:.3f}" in text
    for rate in sensitivity["pimc_rami_declaration_rate"].values():
        assert f"{rate:.3f}" in text


def test_the_results_document_preserves_the_negative_finding() -> None:
    text = _flat("phase5c_evaluation.md")
    for phrase in (
        "loses decisively",
        "preserved exactly as measured",
        "Not tuned",
        "was not computationally practical",
        "sealed bank stays closed",
        "Not established",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_results_document_refutes_the_optimism_hypothesis() -> None:
    """The document must say which explanation was tested and ruled out."""

    text = _flat("phase5c_evaluation.md")
    assert "refuted" in text.lower()
    assert "selection optimism" in text.lower()
    assert "rises with the budget" in text.lower()


def test_the_committed_report_disclaims_promotion_and_lists_limits() -> None:
    report = _report("phase5c_evaluation.json")
    assert "promotion evidence" in report["promotion_status"]
    assert "never opened" in report["promotion_status"]
    assert len(report["not_established"]) >= 4
    assert "refuted" in report["interpretation"]


def test_the_results_document_recommends_a_phase5d_decision() -> None:
    text = _flat("phase5c_evaluation.md")
    assert "Recommended Phase 5D decision" in _text("phase5c_evaluation.md")
    assert "ismcts" in text.lower()
    assert "policy mismatch" in text.lower()
