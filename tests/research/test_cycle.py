"""The control cycle must close, and the null control must cancel exactly.

The exact zero is the point of the whole fixture: with candidate and incumbent
identical, the canonical eight-row design is an algebraic identity, so one number
simultaneously checks the design's balance, the sign convention, the mean-of-eight
normalisation and the claim that the candidate really is identical.
"""

from __future__ import annotations

import pytest

from tuppi_eval.qualification import expected_blocks_for
from tuppi_research.cycle import (
    DEAL_POINTS_SCREENING_RULE,
    ENDPOINT,
    REFERENCE_PROFILE,
    analyse,
    build_inputs,
    noop_parity_check,
    null_control_zero_check,
    preflight_legality,
    reference_specification,
    review,
)
from tuppi_research.errors import CycleError
from tuppi_research.ledger import ExecutionState, Ledger, Verdict
from tuppi_research.runner import run_null_control


def test_inputs_keep_the_native_eight_row_design(tmp_path):
    inputs = build_inputs(base_deals=2)
    assert len(inputs.schedule.transformations) == 8
    assert len(inputs.schedule.entries) == 16
    assert inputs.schedule.block_size == 8
    assert {entry.transformation.seat_rotation for entry in inputs.schedule.entries} == {
        0, 1, 2, 3
    }
    assert {
        entry.transformation.team_assignment_exchange
        for entry in inputs.schedule.entries
    } == {False, True}


def test_the_candidate_is_the_imported_incumbent_in_both_partner_seats():
    inputs = build_inputs(base_deals=1)
    specification = reference_specification()
    assert REFERENCE_PROFILE == "partner_aware_lead_v2"
    assert inputs.team_a.team_id == inputs.team_b.team_id
    assert inputs.team_a.component_agent_ids == (
        specification.agent_id, specification.agent_id
    )
    assert inputs.team_a.homogeneous and not inputs.team_a.shared_instances


def test_base_deals_are_bounded():
    with pytest.raises(CycleError, match="base_deals must be"):
        build_inputs(base_deals=0)
    with pytest.raises(CycleError, match="base_deals must be"):
        build_inputs(base_deals=10_000)


def test_preflight_rejects_nothing_legal_and_checks_isolation():
    detail = preflight_legality(build_inputs(base_deals=1))
    assert detail["decisions"] == 56
    assert detail["every_action_within_legal_tuple"]
    assert detail["observation_confined_to_own_hand"]
    assert detail["distinct_instances_per_seat"]


def test_a_pass_through_wrapper_changes_no_action():
    assert noop_parity_check() == {"actions": 56, "trace_identical": True}


def test_the_null_control_cycle_closes_and_cancels_exactly(tmp_path):
    report = run_null_control(
        workspace=tmp_path, base_deals=2, reviewed_by="test-suite"
    )
    assert report.execution_state is ExecutionState.COMPLETE
    assert report.verdict is Verdict.NO_EFFECT
    assert report.finding_id is not None
    assert report.units == 2
    assert report.summary["block_utilities"] == [0.0, 0.0]
    assert report.summary["mean_paired_utility"] == 0.0
    assert report.summary["transformed_games"] == 16
    names = {check["name"] for check in report.control_checks}
    assert {
        "arena_execution",
        "artifact_digests_current",
        "noop_delegation_parity",
        "null_control_exact_zero",
        "preflight_legality",
    } <= names
    assert all(check["passed"] for check in report.control_checks)


def test_the_recorded_finding_never_claims_promotion(tmp_path):
    report = run_null_control(
        workspace=tmp_path, base_deals=2, reviewed_by="test-suite"
    )
    with Ledger(tmp_path / "research.sqlite3") as ledger:
        finding = ledger.finding(report.run_id)
    assert finding["promotion"] == "not_performed"
    assert finding["verdict"] == "no_effect"
    assert finding["endpoint"] == ENDPOINT
    assert finding["decision_rule_id"] == DEAL_POINTS_SCREENING_RULE.rule_id
    assert "establishes nothing about strength" in finding["statement"]
    assert report.to_data()["promotion"] == "not_performed"


def test_missing_capabilities_are_reported_blocked_not_implemented(tmp_path):
    report = run_null_control(
        workspace=tmp_path, base_deals=2, reviewed_by="test-suite"
    )
    blocked = " ".join(report.blocked)
    assert "BLOCKED" in blocked
    # the threshold and the construction gap are now resolved and say so
    assert "RESOLVED" in blocked
    assert "opponent population" in blocked
    assert "endpoint validity" in blocked
    assert "promotion" in blocked
    assert "ten-second" in blocked


def test_the_exact_zero_check_refuses_a_nonzero_unit():
    analysis = {
        "admitted_units": 2,
        "block_utilities": [0.0, 0.25],
        "statistics": {"mean_paired_utility": 0.125},
    }
    with pytest.raises(CycleError, match="did not cancel exactly"):
        null_control_zero_check(analysis)


def test_the_exact_zero_check_refuses_a_nonzero_mean():
    analysis = {
        "admitted_units": 1,
        "block_utilities": [0.0],
        "statistics": {"mean_paired_utility": 1e-18},
    }
    with pytest.raises(CycleError, match="not exactly 0.0"):
        null_control_zero_check(analysis)


def test_analysis_admits_the_planned_manifest_only(tmp_path):
    inputs = build_inputs(base_deals=2)
    run_null_control(workspace=tmp_path, base_deals=2, reviewed_by="test-suite")
    analysis = analyse(inputs, tmp_path / "evaluation")
    assert analysis["admitted_units"] == 2
    assert len(expected_blocks_for(inputs.config, inputs.schedule)) == 2


def test_analysis_before_execution_is_refused(tmp_path):
    with pytest.raises(CycleError, match="run the cycle first"):
        analyse(build_inputs(base_deals=1), tmp_path / "nothing-here")


def test_review_judges_a_real_candidate_under_the_declared_rule():
    """Before a rule existed this returned INCONCLUSIVE for everything real."""
    def analysis(low, high):
        return {
            "admitted_units": 4,
            "block_utilities": [0.0, 0.0, 0.0, 0.0],
            "statistics": {
                "mean_paired_utility": (low + high) / 2,
                "confidence_interval": [low, high],
                "confidence_level": 0.95,
            },
        }

    verdict, statement = review(analysis(0.0, 0.0), is_null_control=True)
    assert verdict is Verdict.NO_EFFECT
    assert "establishes nothing about strength" in statement
    assert "No policy is promoted" in statement

    assert review(analysis(-24.0, -16.0), is_null_control=False)[0] is Verdict.REJECTED
    assert review(analysis(1.5, 3.0), is_null_control=False)[0] is Verdict.ACCEPTED
    assert review(analysis(-0.4, 0.4), is_null_control=False)[0] is Verdict.NO_EFFECT
    assert review(analysis(0.5, 3.0), is_null_control=False)[0] is Verdict.INCONCLUSIVE


def test_a_null_control_judged_anything_but_equivalent_is_an_instrument_fault():
    analysis = {
        "admitted_units": 1,
        "block_utilities": [-20.0],
        "statistics": {
            "mean_paired_utility": -20.0,
            "confidence_interval": [-24.0, -16.0],
            "confidence_level": 0.95,
        },
    }
    with pytest.raises(CycleError, match="not a finding"):
        review(analysis, is_null_control=True)
