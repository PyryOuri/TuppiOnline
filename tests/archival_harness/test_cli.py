from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tuppi_legacy.adapter import RunnerConfig
from tuppi_legacy.errors import ConfigurationError
from tuppi_legacy.run import main, parse_show_banned_ranks

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DEAL = ROOT / "examples/legacy_deal_seed_1729.json"


def _fixed_args(output: Path) -> list[str]:
    return [
        "--deals",
        "1",
        "--deal-file",
        str(EXAMPLE_DEAL),
        "--legacy-rng-seed",
        "2718",
        "--rollouts",
        "1",
        "--scoring",
        "rising",
        "--output",
        str(output),
    ]


def test_changing_only_output_path_does_not_change_result(tmp_path) -> None:
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"
    assert main(_fixed_args(first_path)) == 0
    assert main(_fixed_args(second_path)) == 0
    assert first_path.read_bytes() == second_path.read_bytes()


def test_changing_only_logging_verbosity_does_not_change_result(tmp_path) -> None:
    output = tmp_path / "same-path.jsonl"
    assert main(_fixed_args(output)) == 0
    quiet = output.read_bytes()
    assert main([*_fixed_args(output), "-vv"]) == 0
    assert quiet == output.read_bytes()


def test_cli_executes_exact_requested_finite_deal_count(tmp_path) -> None:
    output = tmp_path / "two.jsonl"
    code = main(
        [
            "--deals",
            "2",
            "--deal-seed",
            "101",
            "--legacy-rng-seed",
            "202",
            "--rollouts",
            "1",
            "--scoring",
            "flat",
            "--output",
            str(output),
        ]
    )
    assert code == 0
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert [record["effective_configuration"]["deal_index"] for record in records] == [0, 1]
    deal_input = records[0]["effective_configuration"]["deal_input"]
    assert deal_input["mode"] == "generated"
    assert deal_input["generation_seed"] == 101
    assert deal_input["initial_dealer"] == 0
    assert deal_input["materialized_deal_set_sha256"].startswith("sha256:")
    assert all(record["execution"]["status"] == "ok" for record in records)


def test_subprocess_replay_is_hash_seed_independent_and_needs_no_stdin(tmp_path) -> None:
    outputs = []
    for hash_seed in ("1", "987654"):
        output = tmp_path / f"hash-{hash_seed}.jsonl"
        command = [sys.executable, "-m", "tuppi_legacy.run", *_fixed_args(output)]
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = hash_seed
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode("utf-8")
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1]


def test_invalid_subprocess_configuration_exits_nonzero(tmp_path) -> None:
    output = tmp_path / "must-not-exist.jsonl"
    args = _fixed_args(output)
    args[args.index("--rollouts") + 1] = "0"
    completed = subprocess.run(
        [sys.executable, "-m", "tuppi_legacy.run", *args],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    assert b"positive integer" in completed.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    ("option", "value"),
    [("--deals", "0"), ("--deals", "-1"), ("--rollouts", "0"), ("--rollouts", "-1")],
)
def test_nonpositive_counts_fail_without_creating_output(tmp_path, option, value) -> None:
    output = tmp_path / f"invalid-{option[2:]}.jsonl"
    args = _fixed_args(output)
    index = args.index(option)
    args[index + 1] = value
    assert main(args) == 2
    assert not output.exists()


def test_deal_file_count_mismatch_fails_loudly(tmp_path) -> None:
    output = tmp_path / "mismatch.jsonl"
    args = _fixed_args(output)
    args[args.index("--deals") + 1] = "2"
    assert main(args) == 2
    assert not output.exists()


def test_dealer_with_explicit_file_is_rejected(tmp_path) -> None:
    output = tmp_path / "dealer.jsonl"
    assert main([*_fixed_args(output), "--dealer", "0"]) == 2
    assert not output.exists()


def test_output_cannot_overwrite_explicit_deal_file(tmp_path) -> None:
    deal_copy = tmp_path / "deal.json"
    original = EXAMPLE_DEAL.read_bytes()
    deal_copy.write_bytes(original)
    args = _fixed_args(deal_copy)
    args[args.index(str(EXAMPLE_DEAL))] = str(deal_copy)
    assert main(args) == 2
    assert deal_copy.read_bytes() == original


def test_output_cannot_write_inside_frozen_archive() -> None:
    target = ROOT / "Archive" / "forbidden-result.jsonl"
    assert main(_fixed_args(target)) == 2
    assert not target.exists()


def test_show_ban_parser_supports_true_empty_and_rejects_bad_values() -> None:
    assert parse_show_banned_ranks("none") == ()
    assert parse_show_banned_ranks("") == ()
    assert parse_show_banned_ranks("2,J,Q,K") == (2, 11, 12, 13)
    with pytest.raises(ConfigurationError, match="unknown rank"):
        parse_show_banned_ranks("X")
    with pytest.raises(ConfigurationError, match="duplicate"):
        parse_show_banned_ranks("2,2")
    with pytest.raises(ConfigurationError, match="empty rank"):
        parse_show_banned_ranks("2,,K")


@pytest.mark.parametrize("rollouts", [0, -1])
def test_adapter_config_rejects_legacy_rollout_fallback_values(rollouts) -> None:
    config = RunnerConfig(
        deal_count=1,
        legacy_rng_seed=1,
        rollouts=rollouts,
        scoring="rising",
    )
    with pytest.raises(ConfigurationError, match="rollout count must be a positive"):
        config.validate()
