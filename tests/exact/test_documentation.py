"""The Phase 5B documentation, schemas, and committed reports must agree.

These tests exist so a claim cannot drift away from the code that produced it. The
strongest of them check that a *number* in the results document still matches the
committed report, not merely that a paragraph exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "exact"
SCHEMAS = ROOT / "schemas" / "exact"
REPORTS = ROOT / "reports" / "phase5b"

REQUIRED_DOCS = (
    "architecture.md",
    "constraint_model.md",
    "continuation.md",
    "counting_and_sampling.md",
    "integrity.md",
    "phase5b_results.md",
    "solver.md",
)
REQUIRED_SCHEMAS = (
    "frozen_baseline.schema.json",
    "hidden_hand_sampling.schema.json",
    "late_game_solution.schema.json",
    "match_rule_diagnosis.schema.json",
)
REQUIRED_REPORTS = (
    "frozen_baseline.json",
    "match_rule_diagnosis.json",
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


def test_every_required_schema_and_report_exists() -> None:
    assert sorted(path.name for path in SCHEMAS.glob("*.json")) == sorted(
        REQUIRED_SCHEMAS
    )
    assert sorted(path.name for path in REPORTS.glob("*.json")) == sorted(
        REQUIRED_REPORTS
    )


@pytest.mark.parametrize("name", REQUIRED_SCHEMAS)
def test_every_schema_is_a_valid_draft_2020_12_schema(name: str) -> None:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_the_committed_baseline_validates_and_verifies() -> None:
    from tuppi_exact.integrity import verify_baseline

    baseline = _report("frozen_baseline.json")
    schema = json.loads(
        (SCHEMAS / "frozen_baseline.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(baseline)
    assert verify_baseline(baseline) == []


def test_the_committed_diagnosis_validates_against_its_schema() -> None:
    schema = json.loads(
        (SCHEMAS / "match_rule_diagnosis.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(_report("match_rule_diagnosis.json"))


def test_a_live_solution_validates_against_its_schema(late_positions) -> None:
    from tuppi_exact.solver import solve_late_game

    schema = json.loads(
        (SCHEMAS / "late_game_solution.schema.json").read_text(encoding="utf-8")
    )
    validator = jsonschema.Draft202012Validator(schema)
    for position in late_positions[:10]:
        validator.validate(
            solve_late_game(
                position.deal_state, maximum_tricks_remaining=4
            ).to_data()
        )


def test_a_live_sampling_summary_validates_against_its_schema(
    small_model_position,
) -> None:
    from tuppi_exact.sampling import uniform_sampling_summary

    schema = json.loads(
        (SCHEMAS / "hidden_hand_sampling.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(
        uniform_sampling_summary(
            small_model_position.observation, seed="schema-check", count=4
        )
    )


def test_the_architecture_document_states_the_one_way_dependency() -> None:
    text = _flat("architecture.md")
    for phrase in (
        "None of them may reference it",
        "exact or an error",
        "retroactively search-assisted",
        "capability_containment",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_constraint_document_states_all_three_show_priorities() -> None:
    text = _flat("constraint_model.md")
    for phrase in (
        "no eligible card of the contract's normal colour",
        "no eligible card of either colour",
        "Priority 3 can never show an eligible card",
        "may never exclude the truth",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_sampling_document_states_the_posterior_caveat() -> None:
    text = _flat("counting_and_sampling.md")
    assert "not a posterior" in text.lower()
    assert "neutral reference measure" in text.lower()
    assert "negligible\" is not \"none" in text.lower()


def test_the_continuation_document_explains_engine_refereeing() -> None:
    text = _flat("continuation.md")
    for phrase in (
        "the engine is the referee",
        "necessary rather than merely nice",
        "equal the real deal's",
        "`deal_id`",
        "negative controls",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_solver_document_states_the_theorem_and_its_scope() -> None:
    text = _flat("solver.md")
    for phrase in (
        "Every trick-optimal card is also match-optimal",
        "Overshoot past 52 is worth nothing",
        "cards already in the current trick",
        "out of scope",
        "Perfect information",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_results_document_reports_the_recorded_monotonicity_case_count() -> None:
    report = _report("match_rule_diagnosis.json")
    cases = report["monotonicity_certificate"]["cases_checked"]
    assert report["monotonicity_certificate"]["holds"] is True
    assert f"{cases} cases" in _flat("phase5b_results.md")


def test_the_results_document_reports_the_recorded_census_totals() -> None:
    census = _report("match_rule_diagnosis.json")["census"]
    text = _flat("phase5b_results.md")
    assert f"{census['deals_played']} deals" in text
    assert f"{census['decisions_by_phase']['SHOWING']} showing decisions" in text
    trick = census["decisions_by_phase"]["TRICK_PLAY"]
    assert f"{trick:,}".replace(",", " ") in text


def test_the_results_document_reports_the_recorded_rule_statuses() -> None:
    per_rule = _report("match_rule_diagnosis.json")["census"]["per_rule"]
    text = _flat("phase5b_results.md")
    assert per_rule["match.play.secure_decisive_trick.v1"]["status"] == "redundant"
    assert per_rule["match.play.coast_when_margin_worthless.v1"]["status"] == "active"
    held = per_rule["match.play.secure_decisive_trick.v1"]["precondition_held"]
    assert f"held **{held} times**" in text or f"{held}" in text
    coasting = per_rule["match.play.coast_when_margin_worthless.v1"][
        "exact_verdicts"
    ]
    assert coasting["rule_helps"] == 0 and coasting["rule_hurts"] == 0
    assert f"{coasting['total']} verdicts, {coasting['neutral']} neutral" in text


def test_the_results_document_reports_the_recorded_ablation_win_probabilities() -> None:
    report = _report("match_rule_diagnosis.json")
    text = _flat("phase5b_results.md")
    for comparison in report["rule_ablation"]["comparisons"]:
        probability = comparison["primary_match_inference"][
            "candidate_match_win_probability"
        ]
        assert f"{probability:.3f}" in text, comparison["name"]


def test_the_results_document_states_what_is_not_established() -> None:
    text = _flat("phase5b_results.md")
    for phrase in (
        "Not established",
        "Every interval contains 0.5",
        "sealed bank has still never been opened",
        "belongs to a later experiment",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_results_document_records_the_relocation_timings() -> None:
    text = _flat("phase5b_results.md")
    for phrase in (
        "0.22 s",
        "20 s limit",
        "was **not** raised",
        "901 passed",
        "1 049 passed",
        "documents-readonly-fallback",
        "7186032",
        "~/Developer/TuppiProject",
        "~/.venvs/tuppi-research",
        "~/TuppiRuns/phase5b",
        "~/Library/Caches/TuppiResearch",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_protect_lattice_is_documented_with_its_recorded_classes() -> None:
    lattice = _report("match_rule_diagnosis.json")["protect_threshold_lattice"]
    text = _flat("phase5b_results.md")
    assert lattice["distinct_behaviours"] >= 3
    for entry in lattice["equivalence_classes"]:
        if entry["is_equivalent_to_rule_off"]:
            assert "rule off" in text.lower()
    assert "multiples of four from 4 to 48" in text
    assert "reachable_positive_scores()" in text


def test_the_results_document_makes_recommendations_reversible() -> None:
    text = _flat("phase5b_results.md")
    assert "stated as a recommendation" in text.lower()
    assert "licensed to be applied silently" in text.lower()
