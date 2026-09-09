"""The ledger must keep execution status and scientific verdict apart.

Everything else it does is bookkeeping; this is the property the layer exists
for. A run that finished is not a result, an unplanned unit is not an extra
observation, and a null control is not promotable.
"""

from __future__ import annotations

import sqlite3

import pytest

from tuppi_research.errors import LedgerError
from tuppi_research.ledger import (
    LEDGER_SCHEMA_VERSION,
    ExecutionState,
    Ledger,
    Verdict,
    digest_file,
)


@pytest.fixture()
def ledger(tmp_path):
    with Ledger(tmp_path / "research.sqlite3") as opened:
        yield opened


def register(ledger, *, null_control: bool = True) -> str:
    return ledger.record_experiment(
        hypothesis="an identical candidate changes nothing",
        endpoint="mean_signed_deal_points_per_eight_game_block",
        incumbent_id="agent:sha256:" + "a" * 64,
        candidate_id="agent:sha256:" + "a" * 64,
        is_null_control=null_control,
    )


def open_run(ledger, experiment_id: str, units: int = 2) -> str:
    return ledger.open_run(
        experiment_id=experiment_id,
        evaluation_id="eval:one",
        schedule_id="schedule:one",
        config_digest="sha256:" + "c" * 64,
        deal_bank_id="bank:one",
        output_directory="/tmp/does-not-need-to-exist",
        planned_units=tuple((index, f"base:deal-{index}") for index in range(units)),
        games_per_unit=8,
    )


def complete_all(ledger, run_id: str, units: int = 2) -> None:
    for index in range(units):
        ledger.complete_unit(
            run_id=run_id,
            block_index=index,
            observed_games=8,
            block_record_id=f"block:{index}",
            paired_utility=0.0,
        )


def test_identities_are_content_addressed_so_registering_twice_is_idempotent(ledger):
    first = register(ledger)
    second = register(ledger)
    assert first == second
    assert first.startswith("experiment:sha256:")


def test_reopening_a_run_is_resume_not_replanning(ledger):
    experiment_id = register(ledger)
    first = open_run(ledger, experiment_id)
    complete_all(ledger, first, units=1)
    second = open_run(ledger, experiment_id)
    assert second == first
    assert ledger.completed_units(first) == frozenset({0})


def test_reopening_with_a_different_plan_is_refused(ledger):
    experiment_id = register(ledger)
    open_run(ledger, experiment_id, units=2)
    with pytest.raises(LedgerError, match="different planned manifest"):
        ledger.open_run(
            experiment_id=experiment_id,
            evaluation_id="eval:one",
            schedule_id="schedule:one",
            config_digest="sha256:" + "c" * 64,
            deal_bank_id="bank:one",
            output_directory="/tmp/does-not-need-to-exist",
            planned_units=((0, "base:deal-0"), (1, "base:deal-CHANGED")),
            games_per_unit=8,
        )


def test_an_unplanned_unit_cannot_smuggle_in_an_observation(ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    with pytest.raises(LedgerError, match="was not planned"):
        ledger.complete_unit(
            run_id=run_id, block_index=7, observed_games=8,
            block_record_id="block:7", paired_utility=1.0,
        )


def test_a_short_unit_cannot_be_marked_complete(ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    with pytest.raises(LedgerError, match="observed 7 games, planned 8"):
        ledger.complete_unit(
            run_id=run_id, block_index=0, observed_games=7,
            block_record_id="block:0", paired_utility=1.0,
        )


def test_a_unit_is_recorded_once_so_resume_cannot_duplicate_it(ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    for _ in range(3):
        ledger.complete_unit(
            run_id=run_id, block_index=0, observed_games=8,
            block_record_id="block:0", paired_utility=2.5,
        )
    rows = [unit for unit in ledger.units(run_id) if unit.block_index == 0]
    assert len(rows) == 1
    assert rows[0].paired_utility == 2.5


def test_a_finding_needs_a_completed_run(ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    complete_all(ledger, run_id)
    with pytest.raises(LedgerError, match="requires a completed run"):
        ledger.record_finding(
            experiment_id=experiment_id, run_id=run_id, verdict=Verdict.NO_EFFECT,
            endpoint="ep", decision_rule_id="rule:sha256:" + "e" * 64,
                summary_sha256="d" * 64, statement="s", reviewed_by="t",
        )


def test_a_finding_needs_every_planned_unit(ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    complete_all(ledger, run_id, units=1)
    ledger.set_run_state(run_id=run_id, state=ExecutionState.COMPLETE)
    with pytest.raises(LedgerError, match="requires every planned unit"):
        ledger.record_finding(
            experiment_id=experiment_id, run_id=run_id, verdict=Verdict.NO_EFFECT,
            endpoint="ep", decision_rule_id="rule:sha256:" + "e" * 64,
                summary_sha256="d" * 64, statement="s", reviewed_by="t",
        )


def test_a_completed_run_is_not_a_finding(ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    complete_all(ledger, run_id)
    ledger.set_run_state(run_id=run_id, state=ExecutionState.COMPLETE)
    assert ledger.run(run_id)["execution_state"] == "complete"
    assert ledger.finding(run_id) is None


def test_a_null_control_can_never_be_accepted(ledger):
    experiment_id = register(ledger, null_control=True)
    run_id = open_run(ledger, experiment_id)
    complete_all(ledger, run_id)
    ledger.set_run_state(run_id=run_id, state=ExecutionState.COMPLETE)
    with pytest.raises(LedgerError, match="never be accepted"):
        ledger.record_finding(
            experiment_id=experiment_id, run_id=run_id, verdict=Verdict.ACCEPTED,
            endpoint="ep", decision_rule_id="rule:sha256:" + "e" * 64,
                summary_sha256="d" * 64, statement="s", reviewed_by="t",
        )
    finding_id = ledger.record_finding(
        experiment_id=experiment_id, run_id=run_id, verdict=Verdict.NO_EFFECT,
        endpoint="ep", decision_rule_id="rule:sha256:" + "e" * 64,
                summary_sha256="d" * 64, statement="s", reviewed_by="t",
    )
    assert ledger.finding(run_id)["verdict"] == "no_effect"
    assert ledger.finding(run_id)["promotion"] == "not_performed"
    assert finding_id.startswith("finding:sha256:")


def test_artifacts_are_referenced_by_digest_not_copied(tmp_path, ledger):
    experiment_id = register(ledger)
    run_id = open_run(ledger, experiment_id)
    artifact = tmp_path / "summary.json"
    artifact.write_text('{"a": 1}')
    recorded = ledger.record_artifact(
        run_id=run_id, kind="summary", path=artifact, root=tmp_path
    )
    expected, size = digest_file(artifact)
    assert recorded == expected
    row = ledger.artifacts(run_id)[0]
    assert row["relative_path"] == "summary.json" and row["bytes"] == size
    assert ledger.stale_artifacts(run_id, tmp_path) == ()
    artifact.write_text('{"a": 2}')
    assert ledger.stale_artifacts(run_id, tmp_path) == ("summary.json (changed)",)
    artifact.unlink()
    assert ledger.stale_artifacts(run_id, tmp_path) == ("summary.json (missing)",)


def test_a_foreign_schema_version_is_refused_rather_than_migrated(tmp_path):
    path = tmp_path / "old.sqlite3"
    with Ledger(path):
        pass
    connection = sqlite3.connect(path)
    connection.execute(
        "UPDATE ledger_meta SET value = 'tuppi.research.ledger.v0'"
        " WHERE key = 'schema_version'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(LedgerError, match="migrate explicitly"):
        Ledger(path)


def test_the_schema_version_is_recorded(tmp_path):
    with Ledger(tmp_path / "l.sqlite3") as opened:
        row = opened._connection.execute(
            "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
        ).fetchone()
    assert row["value"] == LEDGER_SCHEMA_VERSION
