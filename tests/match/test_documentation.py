from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "match"
REPORTS = ROOT / "reports" / "phase5a"
REQUIRED_DOCS = (
    "bank_lifecycle.md",
    "calibration.md",
    "censoring.md",
    "complete_match_protocol.md",
    "endpoints.md",
    "phase5a_results.md",
)


def _text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def _flat(name: str) -> str:
    """Collapse wrapping so a phrase assertion is not a line-length assertion."""

    return " ".join(_text(name).split())


def test_every_required_document_exists_and_is_substantial() -> None:
    assert sorted(path.name for path in DOCS.glob("*.md")) == sorted(REQUIRED_DOCS)
    for name in REQUIRED_DOCS:
        assert len(_text(name)) > 1500, name


def test_the_protocol_document_states_the_definitive_design() -> None:
    text = _flat("complete_match_protocol.md")
    for phrase in (
        "Leg E",
        "Leg O",
        "D_match = (Y_E - Y_O) / 2",
        "natural termination",
        "Nothing is truncated to the shorter one",
        "random access",
        "worker count",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_documentation_explains_why_deal_points_are_insufficient() -> None:
    text = _flat("endpoints.md")
    assert "cannot score match-aware strategy" in text
    assert "scores it nothing" in text
    assert "discarded" in text
    assert "-1.03" in text


def test_the_censoring_policy_is_documented_as_infrastructure() -> None:
    text = _flat("censoring.md")
    assert "censored_infrastructure" in text
    assert "never" in text.lower()
    for phrase in ("a draw", "a policy win", "a policy loss"):
        assert phrase in text, phrase
    assert "227" in text
    assert "27.1" in text


def test_the_bank_lifecycle_documents_all_three_roles() -> None:
    text = _flat("bank_lifecycle.md")
    for role in ("development", "calibration", "promotion_sealed"):
        assert role in text, role
    assert "outside the repository" in text
    assert "unopened" in text.lower()


def test_the_calibration_document_gives_a_recalculation_procedure() -> None:
    text = _flat("calibration.md")
    assert "n = (1.96 * sd(D) / h)^2" in text
    assert "sample-size recalculation" in text.lower()
    assert "Formal sequential testing remains deferred" in text


def test_the_results_document_reports_the_ladder_and_its_null() -> None:
    text = _flat("phase5a_results.md")
    for phrase in (
        "0.896",
        "0.621",
        "0.557",
        "0.498",
        "Monotonicity is not forced",
        "development_reference_v1",
        "Deferred to Phase 5B",
    ):
        assert phrase in text, phrase
    assert "no measurable benefit" in text
    assert "is a promotion claim, and none designates a champion" in text


# --------------------------------------------------------- committed artifacts


def test_the_committed_reports_exist_and_are_consistent() -> None:
    for name in (
        "phase4_frozen_agents.json",
        "calibration_report.json",
        "score_state_diagnostics.json",
        "match_length_calibration.json",
        "sealed_commitment.json",
    ):
        assert (REPORTS / name).exists(), name


def test_the_calibration_report_records_zero_censoring() -> None:
    report = json.loads((REPORTS / "calibration_report.json").read_text("utf-8"))
    assert report["schema_version"] == "tuppi.match.experiment_result.v1"
    assert report["bank"]["role"] == "calibration"
    assert report["bank"]["supports_promotion"] is False
    assert "cannot support a promotion claim" in report["interpretation"]["bank_role"]
    assert len(report["comparisons"]) == 5
    for comparison in report["comparisons"]:
        inference = comparison["primary_match_inference"]
        assert inference["complete_pair_count"] == 256
        assert inference["censored_pair_count"] == 0
        assert inference["failed_pair_count"] == 0
        assert inference["unit_of_inference"] == "complete_complementary_match_pair"


def test_the_score_state_report_covers_every_required_state() -> None:
    report = json.loads((REPORTS / "score_state_diagnostics.json").read_text("utf-8"))
    scores = {tuple(item["starting_score"]) for item in report["comparisons"]}
    assert scores == {
        (0, 0), (16, 0), (0, 16), (32, 0), (0, 32),
        (44, 0), (0, 44), (48, 0), (0, 48),
    }
    for comparison in report["comparisons"]:
        assert comparison["primary_match_inference"]["censored_pair_count"] == 0
        assert comparison["primary_match_inference"]["complete_pair_count"] == 64
    assert "score_state_summary" in report
    assert "never replace the 0-0 primary endpoint" in (
        report["score_state_summary"]["note"]
    )


def test_the_length_calibration_justifies_the_cap() -> None:
    data = json.loads((REPORTS / "match_length_calibration.json").read_text("utf-8"))
    assert data["pooled"]["maximum"] == 227
    assert data["censored_legs_at_cap_used"] == 0
    assert data["fraction_over_phase4_cap_of_40"] > 0.25
    assert data["recommended_operational_cap"] >= data["pooled"]["maximum"] * 3
    assert data["safety_cap_calibration"]["observed_over_proposed_cap"] == 0


def test_the_sealed_commitment_carries_no_seed_material() -> None:
    data = json.loads((REPORTS / "sealed_commitment.json").read_text("utf-8"))
    assert data["role"] == "promotion_sealed"
    assert data["schema_version"] == "tuppi.match.sealed_commitment.v1"
    assert "seed" not in data
    assert data["seed_digest"].startswith("sha256:")
    assert data["bank_commitment"].startswith("sha256:")
    assert "outside the repository" in data["seed_location"]
    assert "explicit recorded act" in data["usage_rule"]


def test_no_sealed_seed_material_is_committed() -> None:
    """A seed file must never appear anywhere inside the repository tree."""

    suspicious = [
        path
        for path in ROOT.rglob("*sealed_seed*")
        if ".venv" not in path.parts and ".git" not in path.parts
    ]
    assert suspicious == [], suspicious


def test_the_root_readme_documents_the_match_protocol() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "tuppi_match" in readme
    assert "D_match" in readme
    assert "censored_infrastructure" in readme
    assert "docs/match/" in readme
