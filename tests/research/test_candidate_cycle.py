"""A declared candidate must run the whole cycle without acquiring a verdict.

The point of these tests is the pair of outcomes: a pass-through candidate with a
distinct identity must still cancel to exactly zero, and a candidate that really
differs must be detected and still refused a scientific verdict, because no
useful-effect threshold exists.
"""

from __future__ import annotations

import pytest

from tuppi_research.cycle import (
    build_candidate_inputs,
    candidate_declaration,
    candidate_specification,
    null_control_zero_check,
    reference_specification,
)
from tuppi_research.errors import CycleError
from tuppi_research.errors import LedgerError
from tuppi_research.ledger import ExecutionState, Ledger, Verdict
from tuppi_research.runner import run_candidate_cycle


def test_a_candidate_is_evaluated_against_the_incumbent_with_distinct_teams():
    inputs = build_candidate_inputs("research_noop_v1", base_deals=1)
    assert inputs.team_a.team_id != inputs.team_b.team_id
    assert inputs.team_a.component_agent_ids == (
        candidate_specification("research_noop_v1").agent_id,
    ) * 2
    assert inputs.team_b.component_agent_ids == (
        reference_specification().agent_id,
    ) * 2


def test_an_undeclared_candidate_is_refused():
    with pytest.raises(CycleError, match="undeclared research candidate"):
        build_candidate_inputs("not_a_candidate", base_deals=1)


def test_a_passthrough_candidate_with_its_own_identity_still_cancels(tmp_path):
    report = run_candidate_cycle(
        "research_noop_v1", workspace=tmp_path, base_deals=2,
        reviewed_by="test-suite",
    )
    assert report.execution_state is ExecutionState.COMPLETE
    assert report.verdict is Verdict.NO_EFFECT
    assert report.summary["block_utilities"] == [0.0, 0.0]
    assert report.summary["mean_paired_utility"] == 0.0
    assert report.summary["candidate_id"] != report.summary["incumbent_id"]
    names = {check["name"] for check in report.control_checks}
    assert "null_control_exact_zero" in names
    assert all(check["passed"] for check in report.control_checks)


def test_a_genuinely_different_candidate_is_detected_but_not_judged(tmp_path):
    report = run_candidate_cycle(
        "research_legal_shift_v1", workspace=tmp_path, base_deals=4,
        reviewed_by="test-suite",
    )
    assert report.execution_state is ExecutionState.COMPLETE
    # detected: the endpoint moves, and not by zero
    assert report.summary["mean_paired_utility"] != 0.0
    assert any(value != 0.0 for value in report.summary["block_utilities"])
    # not judged: no threshold exists, so no effect claim is made
    assert report.verdict is Verdict.INCONCLUSIVE
    assert report.summary["is_null_control"] is False
    # and the exact-zero identity is correctly NOT asserted for it
    names = {check["name"] for check in report.control_checks}
    assert "null_control_exact_zero" not in names
    with Ledger(tmp_path / "research.sqlite3") as ledger:
        finding = ledger.finding(report.run_id)
    assert finding["verdict"] == "inconclusive"
    assert finding["promotion"] == "not_performed"
    assert "threshold" in finding["statement"]


def test_a_declared_control_can_never_be_accepted(tmp_path):
    report = run_candidate_cycle(
        "research_noop_v1", workspace=tmp_path, base_deals=1,
        reviewed_by="test-suite",
    )
    with Ledger(tmp_path / "research.sqlite3") as ledger:
        with pytest.raises(LedgerError, match="never be accepted"):
            ledger.record_finding(
                experiment_id=report.experiment_id, run_id=report.run_id,
                verdict=Verdict.ACCEPTED, endpoint="ep",
                summary_sha256="d" * 64, statement="s", reviewed_by="t",
            )


def test_the_exact_zero_check_would_have_caught_a_perturbed_passthrough():
    """Guard against the pass-through silently ceasing to be one."""
    with pytest.raises(CycleError, match="did not cancel exactly"):
        null_control_zero_check(
            {
                "admitted_units": 2,
                "block_utilities": [0.0, -2.0],
                "statistics": {"mean_paired_utility": -1.0},
            }
        )


def test_declarations_mark_only_the_passthrough_as_a_control():
    assert candidate_declaration("research_noop_v1").is_null_control is True
    assert candidate_declaration("research_legal_shift_v1").is_null_control is False
