from __future__ import annotations

import os
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

from tuppi_engine.runner import main


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/engine/project_target_v1"


def _first_legal_args(output: Path, *, verbosity: str = "quiet") -> list[str]:
    return [
        "--deal-file",
        str(EXAMPLES / "valid_one_deal_match.json"),
        "--agents",
        "first-legal,first-legal,first-legal,first-legal",
        "--output",
        str(output),
        "--verbosity",
        verbosity,
    ]


def test_cli_runs_one_finite_explicit_deal_without_stdin(tmp_path, monkeypatch) -> None:
    def forbidden_input(*args, **kwargs):
        raise AssertionError("stdin was accessed")

    monkeypatch.setattr("builtins.input", forbidden_input)
    output = tmp_path / "result.json"
    assert main(_first_legal_args(output)) == 0
    data = output.read_text(encoding="utf-8")
    assert '"execution_status":"success"' in data
    assert '"terminal":false' in data
    assert data.endswith("\n")


def test_cli_optional_public_event_log_contains_no_initial_hands(tmp_path) -> None:
    output = tmp_path / "research.json"
    public = tmp_path / "public.json"
    args = _first_legal_args(output) + ["--event-log", str(public)]
    assert main(args) == 0
    public_text = public.read_text(encoding="utf-8")
    assert '"events"' in public_text
    assert '"hands"' not in public_text
    assert '"deal_id"' not in public_text
    assert '"initial_hands"' in output.read_text(encoding="utf-8")


def test_output_path_and_logging_verbosity_do_not_change_content(tmp_path) -> None:
    quiet = tmp_path / "quiet.json"
    debug = tmp_path / "debug.json"
    assert main(_first_legal_args(quiet, verbosity="quiet")) == 0
    assert main(_first_legal_args(debug, verbosity="debug")) == 0
    assert quiet.read_bytes() == debug.read_bytes()


def test_cli_runs_complete_scripted_match(tmp_path) -> None:
    output = tmp_path / "match.json"
    public = tmp_path / "events.json"
    code = main(
        [
            "--deal-file",
            str(EXAMPLES / "exact_52_match.json"),
            "--agents",
            "scripted,scripted,scripted,scripted",
            "--script-file",
            str(EXAMPLES / "exact_52_script.json"),
            "--output",
            str(output),
            "--event-log",
            str(public),
            "--require-complete-match",
            "--verbosity",
            "quiet",
        ]
    )
    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert '"final_score":[0,52]' in text
    assert '"terminal":true' in text
    assert '"winner_team":1' in text


def test_invalid_input_fails_nonzero_without_truncating_existing_output(tmp_path) -> None:
    output = tmp_path / "existing.json"
    output.write_text("preserve-me\n", encoding="utf-8")
    code = main(
        [
            "--deal-file",
            str(EXAMPLES / "invalid_duplicate_card_deal.json"),
            "--agents",
            "first-legal,first-legal,first-legal,first-legal",
            "--output",
            str(output),
            "--verbosity",
            "quiet",
        ]
    )
    assert code != 0
    assert output.read_text(encoding="utf-8") == "preserve-me\n"


def test_stdin_configuration_fails_nonzero(tmp_path) -> None:
    assert (
        main(
            [
                "--deal-file",
                "-",
                "--agents",
                "first-legal,first-legal,first-legal,first-legal",
                "--output",
                str(tmp_path / "result.json"),
            ]
        )
        != 0
    )


def test_device_stdin_path_is_rejected_as_nonregular_input(tmp_path) -> None:
    device = Path("/dev/stdin")
    if not device.exists():
        pytest.skip("platform has no /dev/stdin")
    assert main(_first_legal_args(tmp_path / "result.json")[:0] + [
        "--deal-file", str(device),
        "--agents", "first-legal,first-legal,first-legal,first-legal",
        "--output", str(tmp_path / "result.json"),
        "--verbosity", "quiet",
    ]) != 0


def test_output_cannot_alias_deal_input(tmp_path) -> None:
    copied = tmp_path / "deal.json"
    shutil.copyfile(EXAMPLES / "valid_one_deal_match.json", copied)
    before = copied.read_bytes()
    args = _first_legal_args(copied)
    args[1] = str(copied)
    assert main(args) != 0
    assert copied.read_bytes() == before


def test_event_log_cannot_alias_script_input(tmp_path) -> None:
    deal = tmp_path / "match.json"
    script = tmp_path / "script.json"
    shutil.copyfile(EXAMPLES / "successful_rami_match.json", deal)
    shutil.copyfile(EXAMPLES / "successful_rami_script.json", script)
    before = script.read_bytes()
    assert main([
        "--deal-file", str(deal),
        "--agents", "scripted,scripted,scripted,scripted",
        "--script-file", str(script),
        "--output", str(tmp_path / "research.json"),
        "--event-log", str(script),
        "--verbosity", "quiet",
    ]) != 0
    assert script.read_bytes() == before


def test_output_bundle_preflight_prevents_partial_research_write(tmp_path) -> None:
    research = tmp_path / "research.json"
    args = _first_legal_args(research) + [
        "--event-log", str(tmp_path / "missing" / "events.json")
    ]
    assert main(args) != 0
    assert not research.exists()


def test_reordered_global_fixed_script_is_rejected(tmp_path) -> None:
    script_data = json.loads(
        (EXAMPLES / "successful_rami_script.json").read_text(encoding="utf-8")
    )
    script_data["actions"] = sorted(
        script_data["actions"], key=lambda action: action["seat"]
    )
    script = tmp_path / "reordered.json"
    script.write_text(json.dumps(script_data), encoding="utf-8")
    output = tmp_path / "result.json"
    assert main([
        "--deal-file", str(EXAMPLES / "successful_rami_match.json"),
        "--agents", "scripted,scripted,scripted,scripted",
        "--script-file", str(script),
        "--output", str(output),
        "--verbosity", "quiet",
    ]) != 0
    assert not output.exists()


@pytest.mark.parametrize(
    "agents",
    ["unknown,unknown,unknown,unknown", "first-legal,first-legal"],
)
def test_invalid_agent_configuration_fails_nonzero(tmp_path, agents: str) -> None:
    assert (
        main(
            [
                "--deal-file",
                str(EXAMPLES / "valid_one_deal_match.json"),
                "--agents",
                agents,
                "--output",
                str(tmp_path / "result.json"),
            ]
        )
        != 0
    )


def test_documented_module_command_runs_without_gui_or_network(tmp_path) -> None:
    output = tmp_path / "subprocess.json"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tuppi_engine.runner",
            "--deal-file",
            str(EXAMPLES / "valid_one_deal_match.json"),
            "--agents",
            "first-legal,first-legal,first-legal,first-legal",
            "--output",
            str(output),
            "--verbosity",
            "quiet",
        ],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout == ""
    assert output.exists()
