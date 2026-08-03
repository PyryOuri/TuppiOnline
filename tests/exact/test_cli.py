"""The Phase 5B CLI is finite, deterministic, and writes canonical JSON only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuppi_exact.runner import build_parser, main


ROOT = Path(__file__).resolve().parents[2]
MATCH_INPUT = (
    ROOT / "examples" / "engine" / "project_target_v1" / "valid_one_deal_match.json"
)


def test_every_subcommand_is_registered() -> None:
    parser = build_parser()
    actions = [
        action
        for action in parser._subparsers._group_actions  # type: ignore[union-attr]
    ]
    assert actions
    names = set(actions[0].choices)
    assert names == {
        "ablate",
        "diagnose",
        "inspect",
        "integrity",
        "monotonicity",
        "show-census",
        "solve",
        "variants",
    }


def test_a_missing_subcommand_fails_rather_than_defaulting() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_integrity_report_exits_zero(capsys) -> None:
    assert main(["integrity", "--report"]) == 0
    assert "holds" in capsys.readouterr().out


def test_integrity_verify_accepts_the_committed_baseline(capsys) -> None:
    path = ROOT / "reports" / "phase5b" / "frozen_baseline.json"
    assert main(["integrity", "--verify", str(path)]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_integrity_verify_reports_drift_with_a_nonzero_exit(tmp_path, capsys) -> None:
    recorded = json.loads(
        (ROOT / "reports" / "phase5b" / "frozen_baseline.json").read_text()
    )
    recorded["ruleset_config_digest"] = "sha256:" + "0" * 64
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(recorded))
    assert main(["integrity", "--verify", str(path)]) == 3
    assert "DRIFT" in capsys.readouterr().err


def test_integrity_writes_a_canonical_baseline(tmp_path) -> None:
    path = tmp_path / "baseline.json"
    assert main(["integrity", "--output", str(path)]) == 0
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == "tuppi.exact.frozen_baseline.v1"
    # Canonical means byte-stable: writing twice must produce identical bytes.
    first = path.read_bytes()
    assert main(["integrity", "--output", str(path)]) == 0
    assert path.read_bytes() == first


def test_monotonicity_writes_the_certificate(tmp_path) -> None:
    path = tmp_path / "certificate.json"
    assert main(["monotonicity", "--output", str(path)]) == 0
    payload = json.loads(path.read_text())
    assert payload["holds"] is True
    assert payload["failures"] == []


def test_variants_lists_distinct_identities(capsys) -> None:
    assert main(["variants"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) >= 8
    identities = {line.split()[-1] for line in lines}
    assert len(identities) == len(lines)


def test_inspect_accepts_a_match_input_and_reports_an_exact_count(capsys) -> None:
    assert main(
        [
            "inspect",
            "--deal-file",
            str(MATCH_INPUT),
            "--seat",
            "1",
            "--tricks",
            "9",
            "--samples",
            "3",
        ]
    ) == 0
    out = capsys.readouterr().out
    assert "unknown=" in out and "feasible=" in out


def test_inspect_writes_exact_marginals_as_rationals(tmp_path) -> None:
    path = tmp_path / "inspection.json"
    assert main(
        [
            "inspect",
            "--deal-file",
            str(MATCH_INPUT),
            "--seat",
            "2",
            "--tricks",
            "8",
            "--samples",
            "2",
            "--output",
            str(path),
        ]
    ) == 0
    payload = json.loads(path.read_text())
    assert payload["counting"]["feasible_assignment_count"] >= 1
    for values in payload["uniform_marginals"].values():
        assert all(isinstance(value, str) for value in values)
    assert payload["continuations_validated"] == 2


def test_solve_reports_the_exact_optimum(capsys) -> None:
    assert main(
        ["solve", "--deal-file", str(MATCH_INPUT), "--tricks", "10"]
    ) == 0
    out = capsys.readouterr().out
    assert "optimal_own_tricks=" in out
    assert "nodes=" in out


def test_solve_refuses_a_position_outside_the_budget(capsys) -> None:
    """The CLI reports the refusal and exits nonzero; it never estimates."""

    assert (
        main(
            [
                "solve",
                "--deal-file",
                str(MATCH_INPUT),
                "--tricks",
                "0",
                "--max-tricks-remaining",
                "2",
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "above the exact budget" in captured.err
    assert captured.out == ""


def test_an_invalid_deal_file_fails_with_a_typed_error(tmp_path, capsys) -> None:
    path = tmp_path / "not-a-deal.json"
    path.write_text('{"schema_version": "nonsense"}')
    assert main(["solve", "--deal-file", str(path), "--tricks", "1"]) == 2
    assert "tuppi-exact:" in capsys.readouterr().err


def test_an_out_of_range_seat_fails_with_a_typed_error(capsys) -> None:
    assert (
        main(
            ["inspect", "--deal-file", str(MATCH_INPUT), "--seat", "7", "--tricks", "5"]
        )
        == 2
    )
    assert "tuppi-exact:" in capsys.readouterr().err


def test_diagnose_writes_a_report_without_the_expensive_instrument(tmp_path) -> None:
    path = tmp_path / "diagnosis.json"
    assert (
        main(
            [
                "diagnose",
                "--census-deals",
                "1",
                "--samples-per-decision",
                "0",
                "--output",
                str(path),
            ]
        )
        == 0
    )
    payload = json.loads(path.read_text())
    assert payload["monotonicity_certificate"]["holds"] is True
    assert "rule_ablation" not in payload


def test_show_census_reports_contract_flips(capsys) -> None:
    assert main(["show-census", "--deals", "4"]) == 0
    out = capsys.readouterr().out
    assert "showing decisions:" in out
    assert "contract_flips=" in out
