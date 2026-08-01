from __future__ import annotations

from tuppi_eval.config import evaluation_config_to_data
from tuppi_eval.deals import save_deal_bank
from tuppi_eval.runner import main
from tuppi_eval.serialization import atomic_write_canonical_json, strict_json_load_file

from .support import comparison_config, evaluation_inputs


def test_generate_compare_and_summarize_cli_are_finite(tmp_path) -> None:
    generated = tmp_path / "generated.json"
    assert main(
        [
            "generate-deals",
            "--count",
            "1",
            "--seed",
            "1729",
            "--dealer-policy",
            "round_robin",
            "--initial-dealer",
            "0",
            "--starting-score",
            "0-0",
            "--output",
            str(generated),
        ]
    ) == 0
    assert strict_json_load_file(generated)["schema_version"] == "tuppi.eval.deal_bank.v1"

    _, _, _, bank, _, config = evaluation_inputs()
    bank_path = tmp_path / "bank.json"
    config_path = tmp_path / "config.json"
    run_path = tmp_path / "run"
    save_deal_bank(bank_path, bank)
    atomic_write_canonical_json(config_path, evaluation_config_to_data(config))
    assert main(
        [
            "compare",
            "--config",
            str(config_path),
            "--deal-bank",
            str(bank_path),
            "--output-dir",
            str(run_path),
        ]
    ) == 0
    assert main(["summarize", "--run-dir", str(run_path)]) == 0
    assert strict_json_load_file(run_path / "run_status.json")["status"] == "complete"


def test_crossplay_cli_retains_symmetric_matrix(tmp_path) -> None:
    registry, first, second, bank, _, _ = evaluation_inputs()
    left, right = sorted((first, second), key=lambda team: team.team_id)
    _, config = comparison_config(
        bank=bank,
        registry=registry,
        team_a=left,
        team_b=right,
    )
    bank_path = tmp_path / "bank.json"
    request_path = tmp_path / "crossplay.json"
    output = tmp_path / "crossplay"
    save_deal_bank(bank_path, bank)
    atomic_write_canonical_json(
        request_path,
        {
            "comparisons": [evaluation_config_to_data(config)],
            "deal_bank_id": bank.deal_bank_id,
            "include_missing": True,
            "schema_version": "tuppi.eval.crossplay_request.v1",
        },
    )
    assert main(
        [
            "crossplay",
            "--config",
            str(request_path),
            "--deal-bank",
            str(bank_path),
            "--output-dir",
            str(output),
        ]
    ) == 0
    matrix = strict_json_load_file(output / "crossplay_matrix.json")
    assert len(matrix["team_ids"]) == 2
    assert len(matrix["cells"]) == 3
