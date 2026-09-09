"""Four fault fixtures, each injected separately.

The template requires illegal agent output, a timeout, a missing or duplicated
unit, and an interrupted run. Each must be *recorded* rather than absorbed: none
of them may end up inside a result that gets called qualification, and none of
them may lose or duplicate an observation.

Faults are induced only through native configuration and the native Phase 3
fixture agents. No policy is modified and no fault is simulated by hand-writing a
record.
"""

from __future__ import annotations

import pytest

from tuppi_eval.arena import run_evaluation
from tuppi_eval.errors import InterruptedEvaluation
from tuppi_eval.identities import TeamSpecification
from tuppi_eval.qualification import admitted_blocks, expected_blocks_for
from tuppi_eval.records import ExecutionStatus, FailureKind
from tuppi_eval.errors import IncompleteEvidenceError
from tuppi_research.cycle import (
    build_inputs,
    build_inputs_for_teams,
    execute_cycle,
)
from tuppi_research.ledger import ExecutionState, Ledger, Verdict
from tuppi_research.errors import LedgerError
from tuppi_research.runner import run_null_control


# ------------------------------------------------------- 1. illegal output
def test_illegal_agent_output_is_recorded_and_cannot_qualify(tmp_path):
    """A scripted fixture replaying another seat's script emits illegal actions."""

    from tuppi_eval.identities import (
        AgentSpecification,
        DeterminismClass,
        SeedPolicy,
    )
    from tuppi_eval.registry import AgentRegistry, baseline_agent_specifications

    # A scripted fixture told to show a card no seat can be holding at that turn.
    # The engine refuses the action; the arena records the refusal.
    scripted = AgentSpecification.build(
        agent_family="fixed_script",
        configuration_version="1.0.0",
        implementation_reference="tuppi_eval.agents:fixed_script_v1",
        ruleset_compatibility=("project_target_v1",),
        observation_schema_compatibility=("tuppi.engine.player_observation.v1",),
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration={
            "actions": [
                {
                    "type": "show",
                    "seat": seat,
                    "shown_card": "AS",
                    "declared_contract": "RAMI",
                }
                for seat in range(4)
            ]
        },
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description="Fault fixture: every seat shows the same single card.",
    )
    registry = AgentRegistry.build(baseline_agent_specifications() + (scripted,))
    team = TeamSpecification.build(
        component_agent_ids=(scripted.agent_id, scripted.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description="Scripted fixture emitting an action the engine must refuse.",
    )
    inputs = build_inputs_for_teams(
        registry=registry, team_a=team, team_b=team, base_deals=1,
        description="Illegal-output fault fixture.",
    )
    config, schedule = inputs.config, inputs.schedule
    run = run_evaluation(config, inputs.bank, schedule, output_directory=tmp_path / "e")
    failed = [
        record
        for record in run.result.game_records
        if record.execution_status is not ExecutionStatus.SUCCESS
    ]
    assert failed, "expected the scripted fixture to fail"
    assert {record.failure.kind for record in failed} == {
        FailureKind.ILLEGAL_AGENT_ACTION
    }
    assert "must belong to the player's hand" in failed[0].failure.message
    # a failed game leaves its block incomplete, and the gate refuses it
    blocks = run.result.duplicate_blocks
    assert any(not block.complete for block in blocks)
    expected = expected_blocks_for(config, schedule)
    with pytest.raises(IncompleteEvidenceError, match="incomplete"):
        admitted_blocks(blocks, expected)


def test_a_failed_unit_is_recorded_and_blocks_the_finding(tmp_path):
    inputs = build_inputs(base_deals=1)
    with Ledger(tmp_path / "l.sqlite3") as ledger:
        experiment_id = ledger.record_experiment(
            hypothesis="h", endpoint="ep", incumbent_id="agent:sha256:" + "a" * 64,
            candidate_id="agent:sha256:" + "a" * 64, is_null_control=True,
        )
        run_id = ledger.open_run(
            experiment_id=experiment_id, evaluation_id="eval:x", schedule_id="s:x",
            config_digest="sha256:" + "c" * 64, deal_bank_id="b:x",
            output_directory=str(tmp_path), planned_units=((0, "base:0"),),
            games_per_unit=8,
        )
        ledger.fail_unit(run_id=run_id, block_index=0, detail="3 of 8 games failed")
        ledger.set_run_state(run_id=run_id, state=ExecutionState.COMPLETE)
        assert ledger.incomplete_units(run_id) == (0,)
        with pytest.raises(LedgerError, match="requires every planned unit"):
            ledger.record_finding(
                experiment_id=experiment_id, run_id=run_id,
                verdict=Verdict.NO_EFFECT, endpoint="ep",
                decision_rule_id="rule:sha256:" + "e" * 64,
                summary_sha256="d" * 64, statement="s", reviewed_by="t",
            )
        checks = {row["name"]: row for row in ledger.control_checks(run_id)}
        assert checks["unit_0_failure"]["passed"] == 0


# ------------------------------------------------------------- 2. timeout
def test_a_per_action_timeout_is_recorded_as_a_timeout_failure(tmp_path):
    inputs = build_inputs(base_deals=1, per_action_seconds=1e-9)
    config = inputs.config
    run = run_evaluation(
        config, inputs.bank, inputs.schedule, output_directory=tmp_path / "e"
    )
    failed = [
        record
        for record in run.result.game_records
        if record.execution_status is not ExecutionStatus.SUCCESS
    ]
    assert failed, "a one-nanosecond action budget should not be met"
    assert {record.failure.kind for record in failed} == {FailureKind.TIMEOUT}
    expected = expected_blocks_for(config, inputs.schedule)
    with pytest.raises(IncompleteEvidenceError):
        admitted_blocks(run.result.duplicate_blocks, expected)


# ------------------------------------------ 3. missing / duplicated unit
def test_a_missing_planned_unit_is_refused_by_the_gate(tmp_path):
    inputs = build_inputs(base_deals=2)
    run = run_evaluation(
        inputs.config, inputs.bank, inputs.schedule, output_directory=tmp_path / "e"
    )
    blocks = run.result.duplicate_blocks
    expected = expected_blocks_for(inputs.config, inputs.schedule)
    assert len(blocks) == 2
    with pytest.raises(IncompleteEvidenceError, match="missing from the results"):
        admitted_blocks(blocks[:1], expected)


def test_a_duplicated_unit_is_refused_by_the_gate(tmp_path):
    inputs = build_inputs(base_deals=2)
    run = run_evaluation(
        inputs.config, inputs.bank, inputs.schedule, output_directory=tmp_path / "e"
    )
    blocks = run.result.duplicate_blocks
    expected = expected_blocks_for(inputs.config, inputs.schedule)
    with pytest.raises(IncompleteEvidenceError, match="more than once"):
        admitted_blocks(blocks + (blocks[0],), expected)


# --------------------------------------------------------- 4. interruption
def test_an_interrupted_run_resumes_without_losing_or_duplicating_a_unit(tmp_path):
    """Stop mid-unit, resume, and require the uninterrupted result exactly."""

    inputs = build_inputs(base_deals=2)
    workspace = tmp_path / "interrupted"
    output = workspace / "evaluation"
    with Ledger(workspace / "research.sqlite3") as ledger:
        # 12 of 16 games: unit 0 finished, unit 1 only half executed
        experiment_id, run_id, state = execute_cycle(
            ledger, inputs, output_directory=output, max_new_games=12
        )
        assert state is ExecutionState.INTERRUPTED
        assert ledger.run(run_id)["execution_state"] == "interrupted"
        # a partially executed unit is not half-counted
        assert ledger.completed_units(run_id) == frozenset()
        assert ledger.incomplete_units(run_id) == (0, 1)

        resumed_experiment, resumed_run, resumed_state = execute_cycle(
            ledger, inputs, output_directory=output
        )
        assert resumed_run == run_id and resumed_experiment == experiment_id
        assert resumed_state is ExecutionState.COMPLETE
        assert ledger.completed_units(run_id) == frozenset({0, 1})
        assert ledger.incomplete_units(run_id) == ()
        units = ledger.units(run_id)
        assert [unit.observed_games for unit in units] == [8, 8]
        assert len({unit.base_deal_id for unit in units}) == 2
        resumed_ids = [unit.block_record_id for unit in units]

    # the same evaluation run straight through must give identical block records
    straight = run_evaluation(
        inputs.config, inputs.bank, inputs.schedule,
        output_directory=tmp_path / "straight",
    )
    assert [
        block.block_record_id for block in straight.result.duplicate_blocks
    ] == resumed_ids


def test_the_cycle_refuses_to_review_an_interrupted_run(tmp_path):
    report = run_null_control(workspace=tmp_path, base_deals=2, max_new_games=4)
    assert report.execution_state is ExecutionState.INTERRUPTED
    assert report.verdict is None
    assert report.finding_id is None
    assert any("resume before reviewing" in item for item in report.blocked)
    with Ledger(tmp_path / "research.sqlite3") as ledger:
        assert ledger.finding(report.run_id) is None


def test_interruption_raises_from_the_native_arena(tmp_path):
    inputs = build_inputs(base_deals=1)
    with pytest.raises(InterruptedEvaluation):
        run_evaluation(
            inputs.config, inputs.bank, inputs.schedule,
            output_directory=tmp_path / "e", max_new_games=2,
        )
