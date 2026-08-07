"""Phase 5D-A documents, schemas, and committed findings must agree.

The load-bearing tests here are the cross-checks: a number written in
``phase5d_a_results.md`` must still equal the number in
``reports/phase5d_a/phase5d_a_findings.json``, and the quoted Phase 5C figures must
still equal the ones in ``reports/phase5c/``. A prose claim that has drifted from
the artifact that produced it is the failure these catch.

The hypotheses document is checked for the properties it must have *because* it was
written first: it names all six candidate causes, states the four decision paths, and
states the inferential limits. If a later edit quietly dropped a limitation after the
numbers came in, that is exactly the retrofit the pre-registration exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "search"
SCHEMAS = ROOT / "schemas" / "search"
REPORTS = ROOT / "reports" / "phase5d_a"
PHASE5C = ROOT / "reports" / "phase5c"

REQUIRED_DOCS = ("phase5d_a_hypotheses.md", "phase5d_a_results.md")
REQUIRED_SCHEMAS = (
    "phase5d_a_convergence.schema.json",
    "phase5d_a_decomposition.schema.json",
    "phase5d_a_report.schema.json",
)
REQUIRED_REPORTS = ("phase5d_a_findings.json", "phase5d_a_registry.json")


def _flat(name: str) -> str:
    """Collapse wrapping so a phrase assertion is not a line-length assertion."""

    return " ".join((DOCS / name).read_text(encoding="utf-8").split())


def _report(name: str) -> dict:
    path = REPORTS / name
    if not path.exists():
        pytest.skip("Phase 5D-A reports have not been written yet")
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_required_phase5d_a_document_exists_and_is_substantial() -> None:
    for name in REQUIRED_DOCS:
        path = DOCS / name
        assert path.is_file(), name
        assert len(path.read_text(encoding="utf-8")) > 2_000, name


def test_every_required_phase5d_a_schema_is_valid_json_schema() -> None:
    for name in REQUIRED_SCHEMAS:
        schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)


def test_the_findings_report_validates_against_its_schema() -> None:
    schema = json.loads(
        (SCHEMAS / "phase5d_a_report.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(_report("phase5d_a_findings.json"), schema)


def test_the_hypotheses_document_names_all_six_candidate_causes() -> None:
    text = _flat("phase5d_a_hypotheses.md").lower()
    for phrase in (
        "showing and contract selection",
        "card-play pimc",
        "partnership policy mismatch",
        "insufficient world count",
        "rollout-policy mismatch",
        "strategy fusion",
    ):
        assert phrase in text, phrase


def test_the_hypotheses_document_states_the_four_decision_paths() -> None:
    text = _flat("phase5d_a_hypotheses.md").lower()
    for phrase in (
        "showing is primary",
        "partnership mismatch is primary",
        "world-count instability is primary",
        "structural pimc failure",
    ):
        assert phrase in text, phrase


def test_the_hypotheses_document_keeps_its_inferential_limits() -> None:
    """These limits bound every conclusion; a later edit must not drop them."""

    text = _flat("phase5d_a_hypotheses.md").lower()
    for phrase in (
        "decomposition is not additive",
        "disagreement is not error",
        "divergence is not causation",
        "convergence is not strength",
    ):
        assert phrase in text, phrase


def test_the_hypotheses_document_forbids_recursive_pimc_in_prose_too() -> None:
    text = _flat("phase5d_a_hypotheses.md").lower()
    assert "no recursive pimc" in text
    assert "does not terminate at any principled depth" in text


def test_the_results_document_quotes_phase5c_without_recomputing_it() -> None:
    text = _flat("phase5d_a_results.md")
    committed = json.loads((PHASE5C / "phase5c_evaluation.json").read_text())
    inference = committed["primary_complete_match_comparison"][
        "primary_match_inference"
    ]
    probability = inference["candidate_match_win_probability"]
    assert f"{probability:.3f}" in text, probability
    outcomes = inference["pair_outcomes"]
    assert (
        f"{outcomes['win']} / {outcomes['tie']} / {outcomes['loss']}" in text
    ), outcomes
    assert "quoted" in text.lower()


def test_the_results_document_records_the_selected_path() -> None:
    findings = _report("phase5d_a_findings.json")
    selected = findings["selected_path"]
    assert selected["path"] in {"A", "B", "C", "D", "unresolved"}
    text = _flat("phase5d_a_results.md")
    assert selected["path"] in text
    assert len(selected["justification"]) > 80
    assert len(selected["licenses_next"]) > 40


def test_the_results_document_states_the_safety_cap_deviation() -> None:
    """The reduced per-leg cap induces censoring, so it must be declared."""

    findings = _report("phase5d_a_findings.json")
    deviation = findings["safety_cap_deviation"]
    assert deviation["phase5d_a_safety_cap"] < deviation["phase5c_safety_cap"]
    text = _flat("phase5d_a_results.md")
    assert str(deviation["phase5d_a_safety_cap"]) in text
    assert "censor" in text.lower()


def test_the_results_document_reports_every_comparison_it_ran() -> None:
    findings = _report("phase5d_a_findings.json")
    text = _flat("phase5d_a_results.md").lower()
    for key, phrase in (
        ("play_only_complete_match", "play-only"),
        ("show_only_complete_match", "show-only"),
        ("heterogeneous_full_pimc", "heterogeneous"),
    ):
        if key in findings:
            assert phrase in text, key
    for name in findings.get("not_run", []):
        assert "not run" in text or "not produced" in text, name


def test_the_findings_keep_the_phase5c_identity_and_digest_unchanged() -> None:
    findings = _report("phase5d_a_findings.json")
    committed = json.loads((PHASE5C / "pimc_registry.json").read_text())
    assert findings["phase5c_registry_digest_unchanged"] == committed["registry_digest"]
    baseline = findings["phase5c_negative_baseline"]
    by_key = {item["profile_key"]: item for item in committed["agents"]}
    recorded = by_key["uniform_feasible_pimc_small_v1"]
    assert baseline["agent_id"] == recorded["agent_id"]
    assert baseline["designation"].startswith("uniform_feasible_pimc_small_v1")


def test_no_phase5d_a_document_calls_pimc_optimal() -> None:
    for name in REQUIRED_DOCS:
        text = _flat(name).lower()
        assert "optimal imperfect-information" not in text, name
        assert "solves uncertainty" not in text, name


def test_the_results_document_declares_the_development_bank_status() -> None:
    text = _flat("phase5d_a_results.md").lower()
    assert "development" in text
    assert "promotion evidence" in text
    assert "promotion-sealed bank was not opened" in text
    findings = _report("phase5d_a_findings.json")
    assert "development bank" in findings["promotion_status"]
