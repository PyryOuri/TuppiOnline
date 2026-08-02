from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tuppi_agents import (
    construct_agent,
    phase4_agent_specifications,
    phase4_specifications_by_profile_key,
    phase4_team_specifications,
    profile_catalogue_to_data,
    registered_profiles,
    rule_catalogue_to_data,
)
from tuppi_agents.benchmark import run_benchmark
from tuppi_agents.evaluation import (
    BASELINE_REPORT_SCHEMA_VERSION,
    ComparisonSpec,
    build_baseline_report,
    read_bank,
    run_comparisons,
)
from tuppi_eval.identities import agent_spec_to_data, team_spec_to_data
from tuppi_engine import strict_json_load_file

from .conftest import acting_observation, build_position, partition_deck
from tuppi_rules import Contract


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRECTORY = ROOT / "schemas" / "agents"
EXAMPLES = ROOT / "examples" / "agents"
BANKS = ROOT / "banks"
MANIFESTS = ROOT / "manifests" / "phase4"
REPORTS = ROOT / "reports" / "phase4"

ALL_NOLO = (Contract.NOLO,) * 4


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIRECTORY / f"{name}.schema.json").read_text("utf-8"))


def _validator(name: str) -> Draft202012Validator:
    schema = _schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_every_agent_schema_is_valid_draft_2020_12() -> None:
    names = sorted(path.name for path in SCHEMA_DIRECTORY.glob("*.schema.json"))
    assert names == [
        "baseline_report.schema.json",
        "decision_diagnostics.schema.json",
        "heuristic_profile.schema.json",
        "strategy_rule_catalogue.schema.json",
    ]
    for name in names:
        schema = json.loads((SCHEMA_DIRECTORY / name).read_text("utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["$id"].endswith(name)


def test_every_registered_profile_validates() -> None:
    validator = _validator("heuristic_profile")
    for profile in registered_profiles().values():
        validator.validate(profile.to_data())


def test_the_committed_profile_catalogue_matches_the_code() -> None:
    committed = strict_json_load_file(EXAMPLES / "heuristic_profiles.json")
    assert committed == profile_catalogue_to_data()
    validator = _validator("heuristic_profile")
    for item in committed["profiles"]:
        validator.validate(item)


def test_the_rule_catalogue_validates_and_matches_the_committed_copy() -> None:
    data = rule_catalogue_to_data()
    _validator("strategy_rule_catalogue").validate(data)
    assert strict_json_load_file(EXAMPLES / "strategy_rule_catalogue.json") == data


def test_a_profile_with_an_unknown_field_is_rejected_by_the_schema() -> None:
    validator = _validator("heuristic_profile")
    data = dict(registered_profiles()["reactive_contract_v1"].to_data())
    data["surprise"] = 1
    with pytest.raises(Exception):
        validator.validate(data)


def test_diagnostics_records_validate() -> None:
    validator = _validator("decision_diagnostics")
    specifications = phase4_specifications_by_profile_key()
    hands = partition_deck({})
    for phase_contracts in ((), ALL_NOLO):
        state = build_position(hands, dealer=0, show_contracts=phase_contracts)
        observation = acting_observation(state)
        for key in ("legacy_heuristic_port_v1", "match_aware_v1"):
            agent = construct_agent(
                specifications[key], seat=observation.observing_seat
            )
            record = agent.decide(observation, diagnostics=True).diagnostics
            assert record is not None
            validator.validate(record.to_data())


def test_the_committed_diagnostics_bundle_validates() -> None:
    validator = _validator("decision_diagnostics")
    bundle = strict_json_load_file(EXAMPLES / "decision_diagnostics.json")
    assert bundle["schema_version"] == "tuppi.agents.decision_diagnostics_bundle.v1"
    assert bundle["decisions"]
    for decision in bundle["decisions"]:
        validator.validate(decision)


def test_committed_agent_and_team_catalogues_use_the_phase3_schemas() -> None:
    evaluation_schemas = ROOT / "schemas" / "evaluation"
    agent_validator = Draft202012Validator(
        json.loads((evaluation_schemas / "agent_spec.schema.json").read_text("utf-8"))
    )
    team_validator = Draft202012Validator(
        json.loads((evaluation_schemas / "team_spec.schema.json").read_text("utf-8"))
    )
    committed = strict_json_load_file(EXAMPLES / "phase4_agents.json")
    assert committed["agents"] == [
        agent_spec_to_data(item) for item in phase4_agent_specifications()
    ]
    for item in committed["agents"]:
        agent_validator.validate(item)
    teams = phase4_team_specifications()
    for item in committed["teams"]:
        payload = {key: value for key, value in item.items() if key != "name"}
        team_validator.validate(payload)
        assert payload == team_spec_to_data(teams[item["name"]])


def test_the_committed_banks_and_manifests_are_reproducible() -> None:
    from tuppi_eval.config import evaluation_config_from_data
    from tuppi_agents.evaluation import ALL_COMPARISONS, build_configuration

    index = strict_json_load_file(MANIFESTS / "index.json")
    names = {item["name"] for item in index["comparisons"]}
    assert names == {item.name for item in ALL_COMPARISONS}
    for specification in ALL_COMPARISONS:
        bank = read_bank(BANKS, specification.bank)
        stored = evaluation_config_from_data(
            strict_json_load_file(MANIFESTS / f"{specification.name}.json")
        )
        rebuilt = build_configuration(specification, bank)
        assert stored.evaluation_id == rebuilt.evaluation_id
        assert stored.configuration_digest == rebuilt.configuration_digest


def test_a_small_report_validates_against_the_baseline_report_schema(
    tmp_path: Path,
) -> None:
    validator = _validator("baseline_report")
    specification = ComparisonSpec(
        name="schema_smoke",
        result_class="development",
        hypothesis="A tiny comparison used only to validate the report schema.",
        team_a="match_aware_v1_clone",
        team_b="reactive_contract_v1_clone",
        bank="crossplay",
    )
    comparisons = run_comparisons(
        bank_directory=BANKS,
        output_directory=tmp_path / "run",
        selected=(specification,),
    )
    performance = run_benchmark(deal_count=1)
    report = build_baseline_report(
        comparisons=comparisons,
        crossplay=None,
        performance=performance,
        bank_identifiers={"crossplay": read_bank(BANKS, "crossplay").deal_bank_id},
    )
    assert report["schema_version"] == BASELINE_REPORT_SCHEMA_VERSION
    validator.validate(report)


@pytest.mark.skipif(
    not (REPORTS / "baseline_report.json").exists(),
    reason="the frozen Phase 4 report has not been generated in this checkout",
)
def test_the_committed_baseline_report_validates() -> None:
    validator = _validator("baseline_report")
    report = strict_json_load_file(REPORTS / "baseline_report.json")
    validator.validate(report)
    assert report["ruleset_id"] == "project_target_v1"
    assert report["interpretation"]["no_expert_claim"]
    ladder = [item for item in report["agents"] if item["in_ladder"]]
    assert len(ladder) == 5
