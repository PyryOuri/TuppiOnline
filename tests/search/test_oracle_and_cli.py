"""The restricted oracle diagnostic, and the Phase 5C CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuppi_engine import EnginePhase

from tuppi_search.errors import OracleError
from tuppi_search.oracle import (
    OracleComparison,
    OracleDiagnostic,
    summarize_comparisons,
)
from tuppi_search.registry import PRIMARY_PROFILE_KEY, configuration_for
from tuppi_search.runner import build_parser, main

from .conftest import walk_deal


ROOT = Path(__file__).resolve().parents[2]
MATCH_INPUT = (
    ROOT / "examples" / "engine" / "project_target_v1" / "valid_one_deal_match.json"
)


# ------------------------------------------------------------------- oracle


def test_the_oracle_is_not_an_agent():
    """It must be impossible to hand the oracle to the engine or the arena."""

    from tuppi_agents import ObservationOnlyAgent

    oracle = OracleDiagnostic(
        configuration=configuration_for(PRIMARY_PROFILE_KEY),
        decision_seed="oracle",
    )
    assert not hasattr(oracle, "identity")
    assert not hasattr(oracle, "choose_action")
    assert not isinstance(oracle, ObservationOnlyAgent)


def test_the_oracle_is_not_registerable():
    """No Phase 5C registry entry may reference the oracle."""

    from tuppi_search.registry import phase5c_specifications

    for specification in phase5c_specifications().values():
        assert "oracle" not in specification.implementation_reference
        assert "oracle" not in json.dumps(specification.configuration)


def test_the_oracle_compares_against_the_full_information_optimum(late_position):
    oracle = OracleDiagnostic(
        configuration=configuration_for(PRIMARY_PROFILE_KEY),
        decision_seed="oracle",
        maximum_tricks_remaining=4,
    )
    comparison = oracle.compare(late_position.deal_state)
    if comparison is None:
        pytest.skip("this position is outside the exact solver's range")
    assert comparison.label == "perfect_information_diagnostic"
    assert comparison.legal_action_count >= 2
    assert comparison.perfect_information_optimal_actions
    assert isinstance(comparison.pimc_action_is_optimal, bool)
    assert isinstance(comparison.true_world_in_sample, bool)
    data = comparison.to_data()
    assert data["label"] == "perfect_information_diagnostic"


def test_the_oracle_refuses_positions_outside_its_exact_range(mid_position):
    oracle = OracleDiagnostic(
        configuration=configuration_for(PRIMARY_PROFILE_KEY),
        decision_seed="oracle",
        maximum_tricks_remaining=2,
    )
    assert oracle.compare(mid_position.deal_state) is None


def test_the_oracle_skips_showing_and_forced_positions(showing_position):
    oracle = OracleDiagnostic(
        configuration=configuration_for(PRIMARY_PROFILE_KEY),
        decision_seed="oracle",
    )
    assert showing_position.deal_state.phase is EnginePhase.SHOWING
    assert oracle.compare(showing_position.deal_state) is None


def test_oracle_summaries_are_labelled_perfect_information(late_position):
    oracle = OracleDiagnostic(
        configuration=configuration_for(PRIMARY_PROFILE_KEY),
        decision_seed="oracle",
        maximum_tricks_remaining=4,
    )
    collected = []
    for position in walk_deal(stream_index=1):
        comparison = oracle.compare(position.deal_state)
        if comparison is not None:
            collected.append(comparison)
    if not collected:
        pytest.skip("no comparable position was reached")
    summary = summarize_comparisons(tuple(collected))
    assert summary["label"] == "perfect_information_diagnostic"
    assert 0.0 <= summary["agreement_rate"] <= 1.0
    assert 0.0 <= summary["true_world_coverage_rate"] <= 1.0
    assert "clairvoyant" in summary["interpretation"]
    del late_position


def test_the_oracle_validates_its_arguments():
    with pytest.raises(OracleError):
        OracleDiagnostic(configuration="not a config", decision_seed="x")
    with pytest.raises(OracleError):
        OracleDiagnostic(
            configuration=configuration_for(PRIMARY_PROFILE_KEY), decision_seed=""
        )
    oracle = OracleDiagnostic(
        configuration=configuration_for(PRIMARY_PROFILE_KEY), decision_seed="x"
    )
    with pytest.raises(OracleError):
        oracle.compare("not a state")
    with pytest.raises(OracleError):
        summarize_comparisons(())


def test_an_oracle_comparison_record_is_canonical():
    comparison = OracleComparison(
        root_seat=1,
        phase="TRICK_PLAY",
        tricks_remaining=3,
        legal_action_count=4,
        pimc_action="play:1:5H",
        perfect_information_optimal_actions=("play:1:5H",),
        pimc_action_is_optimal=True,
        true_world_in_sample=False,
        sampled_world_count=4,
        unique_world_count=4,
        exact_feasible_assignment_count=120,
    )
    data = comparison.to_data()
    assert data["schema_version"] == (
        "tuppi.search.perfect_information_diagnostic.v1"
    )
    assert data["pimc_action_is_optimal"] is True


# ---------------------------------------------------------------------- CLI


def test_every_subcommand_is_registered():
    parser = build_parser()
    actions = parser._subparsers._group_actions  # type: ignore[union-attr]
    names = set(actions[0].choices)
    assert names == {
        "ablate",
        "agents",
        "benchmark",
        "compare",
        "explain",
        "heterogeneous",
        "showing-sensitivity",
        "stability",
        "utilities",
        "validate",
    }


def test_a_missing_subcommand_fails_rather_than_defaulting():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_validate_exits_zero(capsys):
    assert main(["validate"]) == 0
    assert "holds" in capsys.readouterr().out


def test_agents_lists_distinct_identities(capsys):
    assert main(["agents"]) == 0
    output = capsys.readouterr().out
    lines = [line for line in output.splitlines() if line.startswith("uniform")]
    assert len(lines) >= 6
    assert len({line.split()[-1] for line in lines}) == len(lines)
    assert "primary:" in output


def test_utilities_lists_every_adapter(capsys):
    assert main(["utilities"]) == 0
    output = capsys.readouterr().out
    assert "match_transition" in output
    assert "registerable=False" in output


def test_agents_writes_a_canonical_snapshot(tmp_path):
    path = tmp_path / "registry.json"
    assert main(["agents", "--output", str(path)]) == 0
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "tuppi.search.phase5c_registry.v1"
    first = path.read_bytes()
    assert main(["agents", "--output", str(path)]) == 0
    assert path.read_bytes() == first


def test_explain_produces_privacy_safe_diagnostics(tmp_path, capsys):
    path = tmp_path / "decision.json"
    assert (
        main(
            [
                "explain",
                "--deal-file",
                str(MATCH_INPUT),
                "--profile",
                "uniform_feasible_pimc_smoke_v1",
                "--seat",
                "1",
                "--tricks",
                "9",
                "--output",
                str(path),
            ]
        )
        == 0
    )
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == (
        "tuppi.search.pimc_decision_diagnostics.v1"
    )
    assert payload["candidates"]
    assert "operational_timing" in payload
    from tuppi_search.diagnostics import FORBIDDEN_KEYS

    serialized = json.dumps(payload)
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in serialized
    del capsys


def test_explain_refuses_a_non_acting_seat(capsys):
    assert (
        main(
            [
                "explain",
                "--deal-file",
                str(MATCH_INPUT),
                "--profile",
                "uniform_feasible_pimc_smoke_v1",
                "--seat",
                "0",
                "--tricks",
                "9",
            ]
        )
        == 2
    )
    assert "not the acting seat" in capsys.readouterr().err


def test_explain_refuses_an_unknown_profile(capsys):
    assert (
        main(
            [
                "explain",
                "--deal-file",
                str(MATCH_INPUT),
                "--profile",
                "not_a_profile",
                "--seat",
                "1",
            ]
        )
        == 2
    )
    assert "tuppi-search:" in capsys.readouterr().err


def test_explain_refuses_an_invalid_deal_file(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"schema_version": "nonsense"}')
    assert (
        main(["explain", "--deal-file", str(path), "--seat", "1"]) == 2
    )
    assert "tuppi-search:" in capsys.readouterr().err


def test_output_path_does_not_change_the_selected_action(tmp_path):
    """The recorded decision must not depend on where it was written."""

    first = tmp_path / "a.json"
    second = tmp_path / "nested" / "b.json"
    second.parent.mkdir()
    arguments = [
        "explain",
        "--deal-file",
        str(MATCH_INPUT),
        "--profile",
        "uniform_feasible_pimc_smoke_v1",
        "--seat",
        "1",
        "--tricks",
        "9",
    ]
    assert main(arguments + ["--output", str(first)]) == 0
    assert main(arguments + ["--output", str(second)]) == 0
    left = json.loads(first.read_text())
    right = json.loads(second.read_text())
    left.pop("operational_timing")
    right.pop("operational_timing")
    assert left == right
