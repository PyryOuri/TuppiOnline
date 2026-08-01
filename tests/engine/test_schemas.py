from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from tuppi_engine import (
    ExplicitDeal,
    ExplicitMatchInput,
    FirstLegalActionAgent,
    EnginePhase,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    agent_script_to_data,
    deal_result_to_data,
    explicit_deal_to_data,
    match_input_from_data,
    match_input_to_data,
    match_observation_for,
    match_result_to_data,
    observation_to_data,
    public_event_log_to_data,
    research_run_result_to_data,
    strict_json_load_file,
)
from tuppi_engine.runner import run_match_input
from tuppi_rules import MatchScore

from .conftest import (
    apply_first_legal,
    resolve_all_nolo,
    start_match_deal,
    suit_block_hands,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas/engine"
EXAMPLES = ROOT / "examples/engine/project_target_v1"


@pytest.fixture(scope="module")
def schema_bundle():
    documents = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_ROOT.glob("*.json")
    }
    assert len(documents) == 8
    for schema in documents.values():
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema))
        for schema in documents.values()
    )
    return documents, registry


def _validate(schema_bundle, name: str, value) -> None:
    documents, registry = schema_bundle
    Draft202012Validator(documents[name], registry=registry).validate(value)


def _nonterminal_run():
    deal = ExplicitDeal(dealer=0, hands=suit_block_hands())
    match_input = ExplicitMatchInput(
        match_ref="schema-test",
        initial_score=MatchScore(),
        initial_dealer=0,
        deals=(deal,),
    )
    result = run_match_input(
        match_input, tuple(FirstLegalActionAgent() for _ in range(4))
    )
    return match_input, result


def _terminal_run():
    match_input = match_input_from_data(
        strict_json_load_file(EXAMPLES / "stolen_rami_match.json")
    )
    script = strict_json_load_file(EXAMPLES / "stolen_rami_script.json")
    from tuppi_engine import FixedScriptAgent, agent_script_from_data

    actions = agent_script_from_data(
        script, expected_match_input_id=match_input.match_input_id
    )
    agents = tuple(
        FixedScriptAgent(tuple(action for action in actions if action.seat == seat))
        for seat in range(4)
    )
    return match_input, run_match_input(match_input, agents)


def test_all_serializer_outputs_validate_against_strict_schemas(schema_bundle) -> None:
    match_input, run = _nonterminal_run()
    deal_data = explicit_deal_to_data(match_input.deals[0])
    match_input_data = match_input_to_data(match_input)
    observation_data = observation_to_data(
        match_observation_for(start_match_deal(match_ref="schema-observation"), 1)
    )
    event_data = public_event_log_to_data(
        run.public_events, match_ref=run.match_ref
    )
    deal_result_data = deal_result_to_data(run.deals[0].public_result)
    research_data = research_run_result_to_data(run)

    action = match_observation_for(
        start_match_deal(match_ref="schema-action"), 1
    ).legal_actions[0]
    script_data = agent_script_to_data(
        (action,), match_input_id=match_input.match_input_id
    )

    _validate(schema_bundle, "explicit_deal.schema", deal_data)
    _validate(schema_bundle, "match_input.schema", match_input_data)
    _validate(schema_bundle, "agent_script.schema", script_data)
    _validate(schema_bundle, "player_observation.schema", observation_data)
    _validate(schema_bundle, "public_event_log.schema", event_data)
    _validate(schema_bundle, "deal_result.schema", deal_result_data)
    _validate(schema_bundle, "research_result.schema", research_data)

    _, terminal = _terminal_run()
    _validate(
        schema_bundle,
        "match_result.schema",
        match_result_to_data(terminal.match_result),
    )
    _validate(
        schema_bundle,
        "research_result.schema",
        research_run_result_to_data(terminal),
    )


@pytest.mark.parametrize(
    ("schema_name", "factory"),
    [
        (
            "explicit_deal.schema",
            lambda: explicit_deal_to_data(
                ExplicitDeal(dealer=0, hands=suit_block_hands())
            ),
        ),
        (
            "match_input.schema",
            lambda: match_input_to_data(_nonterminal_run()[0]),
        ),
        (
            "public_event_log.schema",
            lambda: public_event_log_to_data(
                _nonterminal_run()[1].public_events,
                match_ref=_nonterminal_run()[1].match_ref,
            ),
        ),
        (
            "research_result.schema",
            lambda: research_run_result_to_data(_nonterminal_run()[1]),
        ),
    ],
)
def test_unknown_root_fields_are_rejected(schema_bundle, schema_name, factory) -> None:
    value = factory()
    value["unknown"] = True
    with pytest.raises(ValidationError):
        _validate(schema_bundle, schema_name, value)


def test_missing_required_fields_are_rejected(schema_bundle) -> None:
    value = explicit_deal_to_data(ExplicitDeal(dealer=0, hands=suit_block_hands()))
    del value["hands"]
    with pytest.raises(ValidationError):
        _validate(schema_bundle, "explicit_deal.schema", value)


def test_event_type_payload_mismatch_is_rejected(schema_bundle) -> None:
    _, run = _nonterminal_run()
    value = public_event_log_to_data(run.public_events, match_ref=run.match_ref)
    altered = deepcopy(value)
    altered["events"][0]["event_type"] = "card_played"
    with pytest.raises(ValidationError):
        _validate(schema_bundle, "public_event_log.schema", altered)


def test_observation_schema_accepts_every_engine_phase(schema_bundle) -> None:
    showing = start_match_deal(match_ref="schema-phases")
    trick_play = resolve_all_nolo(showing)
    deal_complete = trick_play
    while deal_complete.phase is EnginePhase.TRICK_PLAY:
        deal_complete = apply_first_legal(deal_complete)

    terminal_input = match_input_from_data(
        strict_json_load_file(EXAMPLES / "stolen_rami_match.json")
    )
    script = strict_json_load_file(EXAMPLES / "stolen_rami_script.json")
    from tuppi_engine import agent_script_from_data

    terminal_actions = agent_script_from_data(
        script, expected_match_input_id=terminal_input.match_input_id
    )
    terminal = create_match(
        initial_score=terminal_input.initial_score,
        initial_dealer=terminal_input.initial_dealer,
        match_ref=terminal_input.match_ref,
    )
    terminal = begin_explicit_deal(terminal, terminal_input.deals[0])
    for action in terminal_actions:
        terminal = apply_match_action(terminal, action)
    assert terminal.phase is EnginePhase.MATCH_COMPLETE

    for state in (showing, trick_play, deal_complete, terminal):
        observation = match_observation_for(state, 0)
        _validate(
            schema_bundle,
            "player_observation.schema",
            observation_to_data(observation),
        )
