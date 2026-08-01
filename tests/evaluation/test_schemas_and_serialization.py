from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tuppi_eval.arena import run_evaluation
from tuppi_eval.config import evaluation_config_to_data
from tuppi_eval.deals import deal_bank_to_data
from tuppi_eval.identities import agent_spec_to_data, team_spec_to_data
from tuppi_eval.records import (
    PromotionDecision,
    PromotionOutcome,
    duplicate_block_to_data,
    evaluation_result_to_data,
    game_record_to_data,
    promotion_decision_from_data,
    promotion_decision_to_data,
)
from tuppi_eval.crossplay import crossplay_matrix_from_data
from tuppi_eval.deals import deal_bank_from_data
from tuppi_eval.config import evaluation_config_from_data
from tuppi_eval.schedules import schedule_to_data
from tuppi_eval.serialization import (
    canonical_json_bytes,
    content_digest,
    strict_json_loads,
)

from .support import evaluation_inputs


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRECTORY = ROOT / "schemas" / "evaluation"


def _schemas():
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SCHEMA_DIRECTORY.glob("*.schema.json"))
    }


def _registry(schemas):
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in schemas.values()
    )


def test_all_evaluation_schemas_are_valid_draft_2020_12() -> None:
    schemas = _schemas()
    assert set(schemas) == {
        "agent_spec.schema.json",
        "crossplay_matrix.schema.json",
        "deal_bank.schema.json",
        "duplicate_block_record.schema.json",
        "evaluation_config.schema.json",
        "evaluation_result.schema.json",
        "game_record.schema.json",
        "promotion_decision.schema.json",
        "schedule.schema.json",
        "team_spec.schema.json",
    }
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)


def test_representative_runtime_artifacts_validate_against_schemas(tmp_path) -> None:
    registry, team_a, team_b, bank, schedule, config = evaluation_inputs()
    arena = run_evaluation(config, bank, schedule, output_directory=tmp_path / "run")
    promotion = PromotionDecision.build(
        candidate_team_id=team_b.team_id,
        champion_team_id=team_a.team_id,
        evaluation_result_ids=(arena.result.result_id,),
        primary_metric="paired_duplicate_utility_points_v1",
        confidence_interval=None,
        historical_agent_results={"status": "baseline_only"},
        contract_regressions={"status": "insufficient_sample"},
        score_state_regressions={"status": "insufficient_sample"},
        failure_rate=0.0,
        latency_budget_seconds=1.0,
        reproducible=True,
        outcome=PromotionOutcome.INCONCLUSIVE,
        rationale="Baseline fixture only; no strategic-strength claim.",
    )
    artifacts = {
        "agent_spec.schema.json": agent_spec_to_data(registry.specifications[0]),
        "team_spec.schema.json": team_spec_to_data(team_a),
        "deal_bank.schema.json": deal_bank_to_data(bank),
        "evaluation_config.schema.json": evaluation_config_to_data(config),
        "schedule.schema.json": schedule_to_data(schedule),
        "game_record.schema.json": game_record_to_data(arena.result.game_records[0]),
        "duplicate_block_record.schema.json": duplicate_block_to_data(
            arena.result.duplicate_blocks[0]
        ),
        "evaluation_result.schema.json": evaluation_result_to_data(arena.result),
        "promotion_decision.schema.json": promotion_decision_to_data(promotion),
    }
    schemas = _schemas()
    registry_of_schemas = _registry(schemas)
    for name, artifact in artifacts.items():
        Draft202012Validator(
            schemas[name], registry=registry_of_schemas
        ).validate(artifact)
    assert promotion_decision_from_data(promotion_decision_to_data(promotion)) == promotion


def test_unknown_fields_and_noncanonical_json_are_rejected() -> None:
    with pytest.raises(Exception, match="duplicate JSON object key"):
        strict_json_loads('{"same":1,"same":2}')
    with pytest.raises(Exception, match="non-finite"):
        strict_json_loads('{"bad":NaN}')
    assert canonical_json_bytes({"z": 1, "a": 2}) == b'{"a":2,"z":1}'


def test_operational_durations_do_not_change_semantic_game_digest(tmp_path) -> None:
    _, _, _, bank, schedule, config = evaluation_inputs()
    arena = run_evaluation(config, bank, schedule, output_directory=tmp_path / "run")
    data = game_record_to_data(arena.result.game_records[0])
    original = data["record_id"]
    data["duration_seconds"] = 999.0
    data["action_durations_seconds"] = [999.0]
    from tuppi_eval.records import game_record_from_data

    assert game_record_from_data(data).record_id == original


def test_checked_in_fixtures_validate_and_reconstruct() -> None:
    schemas = _schemas()
    schema_registry = _registry(schemas)
    example_directory = ROOT / "examples" / "evaluation"
    mapping = {
        "small_deal_bank.json": "deal_bank.schema.json",
        "baseline_comparison.json": "evaluation_config.schema.json",
        "duplicate_block.json": "duplicate_block_record.schema.json",
        "small_crossplay_matrix.json": "crossplay_matrix.schema.json",
        "structured_failure.json": "game_record.schema.json",
        "promotion_decision.json": "promotion_decision.schema.json",
    }
    for filename, schema_name in mapping.items():
        artifact = json.loads(
            (example_directory / filename).read_text(encoding="utf-8")
        )
        Draft202012Validator(
            schemas[schema_name], registry=schema_registry
        ).validate(artifact)

    deal_bank_from_data(
        json.loads((example_directory / "small_deal_bank.json").read_text())
    )
    evaluation_config_from_data(
        json.loads((example_directory / "baseline_comparison.json").read_text())
    )
    crossplay_matrix_from_data(
        json.loads((example_directory / "small_crossplay_matrix.json").read_text())
    )
    promotion_decision_from_data(
        json.loads((example_directory / "promotion_decision.json").read_text())
    )
