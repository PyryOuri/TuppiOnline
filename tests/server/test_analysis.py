from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tuppi_engine import action_from_data
from tuppi_server.analysis import (
    AGENT_DIAGNOSTICS_SCHEMA_VERSION,
    AnalysisProjectionError,
    PIMC_DIAGNOSTICS_SCHEMA_VERSION,
    project_post_match_analysis,
    project_post_match_analysis_response,
    validate_post_match_analysis_response,
)
from tuppi_server.app import TuppiASGIApp
from tuppi_server.match_runner import LiveMatchRunner
from tuppi_server.persistence import PersistenceError
from tuppi_server.projection import project_event_batch
from tuppi_server.rooms import RoomManager
from tuppi_ui_fixtures.validation import validate_instance


MATCH_REF = "analysis-test"
RULE_ID = "common.select.deterministic_maximum.v1"


def _action(card: str, *, seat: int = 1) -> dict[str, object]:
    return {"card": card, "seat": seat, "type": "play"}


def _show_action(card: str, *, seat: int = 1) -> dict[str, object]:
    return {
        "declared_contract": "RAMI",
        "seat": seat,
        "shown_card": card,
        "type": "show",
    }


def _candidate(
    action: dict[str, object],
    score: list[float],
    order_index: int,
    *,
    selected: bool,
) -> dict[str, object]:
    return {
        "action": action,
        "action_order_index": order_index,
        "feature_contributions": [{"component": "test_score", "value": score[-1]}],
        "reason_codes": ["test_reason"],
        "rule_ids": [RULE_ID],
        "score_vector": score,
        "selected": selected,
    }


def _diagnostics(*, phase: str = "SHOWING", selected_card: str = "7H") -> dict[str, object]:
    if phase == "SHOWING":
        actions = [
            _show_action("7H"),
            _show_action("8H"),
            _show_action("9H"),
        ]
    else:
        actions = [_action("2C"), _action("3C"), _action("4C")]
    selected_action = actions[0]
    if selected_card != "7H" and phase == "SHOWING":
        selected_action = _show_action(selected_card)
        actions[0] = selected_action
    return {
        "action_ordering_id": "tuppi.agents.engine_legal_action_order.v1",
        "agent_id": "agent:sha256:" + "a" * 64,
        "candidates": [
            _candidate(actions[0], [1.0, 3.0], 0, selected=True),
            _candidate(actions[1], [1.0, 2.0], 1, selected=False),
            _candidate(actions[2], [1.0, 1.0], 2, selected=False),
        ],
        "contract": None if phase == "SHOWING" else "RAMI",
        "invoked_rule_ids": [RULE_ID],
        "legal_action_count": 3,
        "match_role": "table",
        "observation_digest": "sha256:" + "b" * 64,
        "observing_seat": 1,
        "own_hand_size": 13,
        "partner_seat": 3,
        "phase": phase,
        "profile_id": "profile:sha256:" + "c" * 64,
        "profile_key": "test_profile_v1",
        "schema_version": AGENT_DIAGNOSTICS_SCHEMA_VERSION,
        "selected_action": selected_action,
        "selected_action_order_index": 0,
        "tie_break_applied": False,
        "tie_break_id": "lowest_engine_legal_action_index_v1",
    }


def _event(
    *,
    event_index: int = 1,
    phase: str = "SHOWING",
    card: str = "7H",
    match_ref: str = MATCH_REF,
) -> dict[str, object]:
    if phase == "SHOWING":
        payload = {
            "declared_contract": "RAMI",
            "seat": 1,
            "shown_card": card,
            "verbal_required": False,
        }
        event_type = "show_accepted"
    else:
        payload = {"card": card, "position": 0, "seat": 1, "trick_index": 0}
        event_type = "card_played"
    return {
        "deal_ref": f"{match_ref}/deal:0",
        "event_index": event_index,
        "event_type": event_type,
        "match_ref": match_ref,
        "payload": payload,
        "ruleset_id": "project_target_v1",
        "schema_version": "tuppi.engine.public_event.v1",
    }


def _record(
    *,
    phase: str = "SHOWING",
    match_ref: str = MATCH_REF,
) -> dict[str, object]:
    is_showing = phase == "SHOWING"
    action = _show_action("7H") if is_showing else _action("2C")
    return {
        "match_ref": match_ref,
        "event_index": 1,
        "deal_number": 0,
        "trick_index": None if is_showing else 0,
        "seat": 1,
        "played_action": action,
        "title": "Päätösanalyysi",
        "summary": "Esimerkkianalyysi testitapausta varten.",
        "recommendation": "Suositus perustuu analysoituun sallittuun tilanteeseen.",
        "explanation": ["Testi käyttää vain julkista tapahtumaa."],
        "limitations": ["Testidata ei ole pelivahvuusarvio."],
        "source": "server_analysis_test_v1",
        "diagnostics": _diagnostics(phase=phase),
    }


def _record_for_show_event(
    event: dict[str, object], *, match_ref: str
) -> dict[str, object]:
    payload = event["payload"]
    assert isinstance(payload, dict)
    action = {
        "declared_contract": payload["declared_contract"],
        "seat": payload["seat"],
        "shown_card": payload["shown_card"],
        "type": "show",
    }
    record = _record(match_ref=match_ref)
    record["event_index"] = event["event_index"]
    record["played_action"] = action
    diagnostics = record["diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["selected_action"] = action
    candidates = diagnostics["candidates"]
    assert isinstance(candidates, list)
    selected_candidate = candidates[0]
    assert isinstance(selected_candidate, dict)
    selected_candidate["action"] = action
    return record


def _assert_no_key(value: object, forbidden: str) -> None:
    if isinstance(value, dict):
        assert forbidden not in value
        for nested in value.values():
            _assert_no_key(nested, forbidden)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_key(nested, forbidden)


def test_projection_is_schema_valid_and_filters_raw_diagnostics() -> None:
    response = project_post_match_analysis_response(
        [_record()],
        public_events=[_event()],
        visible_card_codes={"7H", "8H", "9H"},
    )
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "schemas"
        / "network"
        / "post_match_analysis.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validate_instance(
        response,
        "https://example.invalid/tuppi/schemas/network/post_match_analysis.schema.json",
    )

    _assert_no_key(response, "observation_digest")
    _assert_no_key(response, "score_vector")
    _assert_no_key(response, "feature_contributions")
    _assert_no_key(response, "agent_id")
    assert response["match_ref"] == MATCH_REF
    analyses = response["analyses"]
    assert isinstance(analyses, list)
    assert analyses[0]["recommended_action"] == _show_action("7H")
    assert [item["title"] for item in analyses[0]["alternatives"]] == [
        "Näytä 8H · RAMI",
        "Näytä 9H · RAMI",
    ]


def test_projection_supports_trick_play_and_matches_public_event() -> None:
    record = _record(phase="TRICK_PLAY")
    result = project_post_match_analysis(
        record,
        public_events=[_event(phase="TRICK_PLAY", card="2C")],
    )
    assert result["decision_kind"] == "TRICK_PLAY"
    assert result["trick_index"] == 0
    assert result["played_action"] == _action("2C")


def test_projection_rejects_search_diagnostics() -> None:
    record = _record()
    diagnostics = record["diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["schema_version"] = PIMC_DIAGNOSTICS_SCHEMA_VERSION
    with pytest.raises(AnalysisProjectionError, match="PIMC/search"):
        project_post_match_analysis(record, public_events=[_event()])


def test_projection_rejects_nested_private_keys_before_copying_fields() -> None:
    record = _record()
    diagnostics = record["diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["private_metadata"] = {"world_set": []}
    with pytest.raises(AnalysisProjectionError, match="world_set"):
        project_post_match_analysis(record, public_events=[_event()])


def test_projection_rejects_cards_outside_authorized_context() -> None:
    record = _record()
    with pytest.raises(AnalysisProjectionError, match="8H"):
        project_post_match_analysis(
            record,
            public_events=[_event()],
            visible_card_codes={"7H"},
        )


def test_projection_rejects_event_and_diagnostics_mismatches() -> None:
    record = _record()
    bad_event_record = deepcopy(record)
    bad_event_record["event_index"] = 99
    with pytest.raises(AnalysisProjectionError, match="event_index"):
        project_post_match_analysis(bad_event_record, public_events=[_event()])

    bad_selected_record = deepcopy(record)
    diagnostics = bad_selected_record["diagnostics"]
    assert isinstance(diagnostics, dict)
    diagnostics["selected_action"] = _show_action("8H")
    with pytest.raises(AnalysisProjectionError, match="selected candidate"):
        project_post_match_analysis(bad_selected_record, public_events=[_event()])


def test_empty_response_requires_match_reference() -> None:
    with pytest.raises(AnalysisProjectionError, match="empty analysis response"):
        project_post_match_analysis_response([], public_events=[])
    response = project_post_match_analysis_response(
        [], public_events=[], match_ref=MATCH_REF
    )
    assert response == {
        "schema_version": "tuppi.analysis.post_match.v1",
        "match_ref": MATCH_REF,
        "analyses": [],
    }


def test_stored_response_is_bound_to_the_authoritative_public_event() -> None:
    response = project_post_match_analysis_response(
        [_record()],
        public_events=[_event()],
    )
    validate_post_match_analysis_response(
        response,
        expected_match_ref=MATCH_REF,
        public_events=[_event()],
    )

    altered = deepcopy(response)
    analyses = altered["analyses"]
    assert isinstance(analyses, list)
    analysis = analyses[0]
    assert isinstance(analysis, dict)
    analysis["played_action"] = _show_action("8H")
    with pytest.raises(AnalysisProjectionError, match="played action"):
        validate_post_match_analysis_response(
            altered,
            expected_match_ref=MATCH_REF,
            public_events=[_event()],
        )


def _http_post(
    app: TuppiASGIApp,
    *,
    path: str,
    payload: dict[str, object],
) -> tuple[int, dict[str, object]]:
    async def scenario() -> tuple[int, dict[str, object]]:
        incoming = iter(
            [
                {
                    "type": "http.request",
                    "body": json.dumps(payload).encode("utf-8"),
                    "more_body": False,
                }
            ]
        )
        outgoing: list[dict[str, object]] = []

        async def receive():
            return next(incoming)

        async def send(message):
            outgoing.append(message)

        await app(
            {"type": "http", "method": "POST", "path": path},
            receive,
            send,
        )
        return outgoing[0]["status"], json.loads(outgoing[1]["body"])

    return asyncio.run(scenario())


@dataclass(slots=True)
class _TerminalRunnerStub:
    match_ref: str
    state: object
    terminal: bool = True


def test_authenticated_http_endpoint_returns_stored_analysis() -> None:
    fixture_runner = LiveMatchRunner(
        match_ref=MATCH_REF,
        ai_seats=frozenset(),
        auto_run_ai=False,
    )
    observation = fixture_runner.observation(1)
    action = action_from_data(observation["legal_actions"][0])
    fixture_runner.submit(
        seat=1,
        client_action_id="analysis-fixture-show",
        match_ref=MATCH_REF,
        expected_event_index=fixture_runner.event_cursor,
        action=action,
    )
    public_events = project_event_batch(fixture_runner.state.public_events)
    show_event = public_events[1]
    record = _record_for_show_event(show_event, match_ref=MATCH_REF)

    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.lifecycle = "completed"
    room.runner = _TerminalRunnerStub(MATCH_REF, fixture_runner.state)  # type: ignore[assignment]
    response = project_post_match_analysis_response(
        [record],
        public_events=public_events,
    )
    assert manager.record_post_match_analyses(
        code=room.code,
        records=[record],
    ) == response

    status, payload = _http_post(
        TuppiASGIApp(manager),
        path=f"/v1/rooms/{room.code}/analysis",
        payload={"session_token": host.token},
    )
    assert status == 200
    assert payload == response
    assert host.token not in json.dumps(payload)

    unauthorized_status, unauthorized_payload = _http_post(
        TuppiASGIApp(manager),
        path=f"/v1/rooms/{room.code}/analysis",
        payload={"session_token": "not-a-session"},
    )
    assert unauthorized_status == 404
    assert unauthorized_payload == {"error": "invalid_session"}


def test_post_match_analysis_survives_room_restart(tmp_path) -> None:
    manager = RoomManager(persistence_dir=tmp_path)
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    runner = LiveMatchRunner(
        match_ref=f"room-{room.code.lower()}",
        ai_seats=frozenset({0, 1, 2, 3}),
        auto_run_ai=True,
    )
    assert runner.terminal
    room.runner = runner
    room.lifecycle = "completed"
    manager.persist(room)

    public_events = project_event_batch(runner.state.public_events)
    event = public_events[1]
    record = _record_for_show_event(event, match_ref=runner.match_ref)
    response = project_post_match_analysis_response(
        [record],
        public_events=public_events,
    )
    manager.set_post_match_analysis(code=room.code, response=response)
    persisted_text = (tmp_path / f"analysis-{room.code}.json").read_text(
        encoding="utf-8"
    )
    assert "observation_digest" not in persisted_text
    assert "score_vector" not in persisted_text

    restored_manager = RoomManager(persistence_dir=tmp_path)
    restored_room, restored_session = restored_manager.session(
        code=room.code,
        token=host.token,
    )
    assert restored_session.seat == 0
    assert restored_room.post_match_analysis == response
    regenerated = restored_manager.post_match_analysis_for_session(
        code=room.code,
        token=host.token,
    )
    assert regenerated["schema_version"] == "tuppi.analysis.post_match.v3"
    assert regenerated["seat"] == host.seat

    analysis_path = tmp_path / f"analysis-{room.code}.json"
    tampered = json.loads(analysis_path.read_text(encoding="utf-8"))
    tampered["analysis"]["analyses"][0]["observation_digest"] = "leak"
    analysis_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(PersistenceError, match="analysis|persisted"):
        RoomManager(persistence_dir=tmp_path)


def test_adapter_has_no_search_package_dependency() -> None:
    source_path = Path(__file__).resolve().parents[2] / "src" / "tuppi_server" / "analysis.py"
    source = source_path.read_text(encoding="utf-8")
    assert "tuppi_search" not in source
