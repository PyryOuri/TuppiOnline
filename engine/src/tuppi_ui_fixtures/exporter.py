"""Export privacy-safe deterministic fixtures for the native Tuppi client.

The exporter reads the committed explicit-deal examples and fixed action
scripts, replays them through the authoritative engine, and writes only:

* seat-authorized ``PlayerObservation`` snapshots;
* canonical public events and public deal/match results;
* deterministic action acknowledgements for fixture playback; and
* non-authoritative showing hints derived by the server-side rules.

It deliberately never writes ``ExplicitMatchInput``, research results, full
hands, deal identifiers, or fixed scripts to the UI bundle.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tuppi_engine import (
    Action,
    ExplicitMatchInput,
    action_to_data,
    agent_script_from_data,
    apply_match_action,
    begin_explicit_deal,
    canonical_json_bytes,
    create_match,
    deal_result_to_data,
    event_to_data,
    match_input_from_data,
    match_observation_for,
    match_result_from_state,
    match_result_to_data,
    observation_to_data,
    public_event_log_to_data,
    strict_json_load_file,
)
from tuppi_rules import (
    card_color,
    contract_color,
    is_show_rank_eligible,
    verbal_declaration_required,
)

from .validation import schema_metadata


BUNDLE_SCHEMA_VERSION = "tuppi.ui.fixture_bundle.v1"
NETWORK_PROTOCOL_VERSION = "tuppi.network.v1"
SHOWING_HINTS_SCHEMA_VERSION = "tuppi.ui.showing_hints.v1"
ACTION_ACK_SCHEMA_VERSION = "tuppi.network.action_acknowledgement.v1"
WEBSOCKET_SCHEMA_REF = (
    "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"
)
HTTP_SCHEMA_ROOT = "https://example.invalid/tuppi/schemas/network/http_api.schema.json"


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    name: str
    match_file: str
    script_file: str
    expected_terminal: bool


SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec("full_nolo", "valid_one_deal_match.json", "full_nolo_script.json", False),
    ScenarioSpec("successful_rami", "successful_rami_match.json", "successful_rami_script.json", False),
    ScenarioSpec("stolen_rami", "stolen_rami_match.json", "stolen_rami_script.json", True),
    ScenarioSpec("verbal_fallback", "verbal_fallback_match.json", "verbal_fallback_script.json", True),
    ScenarioSpec("no_eligible_show", "no_eligible_show_match.json", "no_eligible_show_script.json", False),
    ScenarioSpec("exact_52", "exact_52_match.json", "exact_52_script.json", True),
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _examples_dir() -> Path:
    return _repository_root() / "examples/engine/project_target_v1"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _event_cursor(state: Any) -> int:
    return -1 if not state.public_events else state.public_events[-1].event_index


def _showing_hints(observation: Any) -> dict[str, object]:
    """Return display metadata without changing authoritative legality."""

    actions: list[dict[str, object]] = []
    for action in observation.legal_actions:
        if action.__class__.__name__ != "ShowAction":
            continue
        eligible = tuple(card for card in observation.own_hand if is_show_rank_eligible(card))
        matching = tuple(
            card
            for card in eligible
            if card_color(card) is contract_color(action.declared_contract)
        )
        fallback = (
            "none"
            if matching
            else "eligible_rank_fallback"
            if eligible
            else "no_eligible_rank_fallback"
        )
        actions.append(
            {
                "declared_contract": action.declared_contract.value,
                "fallback": fallback,
                "seat": action.seat,
                "shown_card": action.shown_card.to_code(),
                "type": "show",
                "verbal_required": verbal_declaration_required(
                    observation.own_hand,
                    action.shown_card,
                    action.declared_contract,
                ),
            }
        )
    return {
        "actions": actions,
        "current_actor": observation.current_actor,
        "schema_version": SHOWING_HINTS_SCHEMA_VERSION,
    }


def _snapshot(
    state: Any,
    *,
    snapshot_index: int,
    after_action_index: int | None,
    reason: str,
    seat: int,
) -> dict[str, object]:
    observation = match_observation_for(state, seat)
    return {
        "after_action_index": after_action_index,
        "event_index": _event_cursor(state),
        "observation": observation_to_data(observation),
        "reason": reason,
        "showing_ui_hints": _showing_hints(observation),
        "snapshot_index": snapshot_index,
    }


def _load_scenario(spec: ScenarioSpec) -> tuple[ExplicitMatchInput, tuple[Action, ...]]:
    examples = _examples_dir()
    match_input = match_input_from_data(strict_json_load_file(examples / spec.match_file))
    actions = agent_script_from_data(
        strict_json_load_file(examples / spec.script_file),
        expected_match_input_id=match_input.match_input_id,
    )
    return match_input, actions


def _run_scenario(spec: ScenarioSpec) -> dict[str, Any]:
    match_input, actions = _load_scenario(spec)
    state = create_match(
        initial_score=match_input.initial_score,
        initial_dealer=match_input.initial_dealer,
        match_ref=match_input.match_ref,
    )
    snapshots: dict[int, list[dict[str, object]]] = {seat: [] for seat in range(4)}
    accepted_actions: list[dict[str, object]] = []
    snapshot_index = 0
    action_index = 0
    deal_index = 0

    def record(reason: str, after_action_index: int | None) -> None:
        nonlocal snapshot_index
        for seat in range(4):
            snapshots[seat].append(
                _snapshot(
                    state,
                    snapshot_index=snapshot_index,
                    after_action_index=after_action_index,
                    reason=reason,
                    seat=seat,
                )
            )
        snapshot_index += 1

    while not state.terminal:
        if state.active_deal is None or state.phase.value == "DEAL_COMPLETE":
            if deal_index >= len(match_input.deals):
                break
            state = begin_explicit_deal(state, match_input.deals[deal_index])
            deal_index += 1
            record("deal_started", None if action_index == 0 else action_index - 1)

        while state.phase.value in ("SHOWING", "TRICK_PLAY"):
            if action_index >= len(actions):
                raise RuntimeError(f"scenario {spec.name} ended before action {action_index}")
            action = actions[action_index]
            if action.seat != state.current_actor:
                raise RuntimeError(
                    f"scenario {spec.name} action {action_index} has seat {action.seat}, "
                    f"expected {state.current_actor}"
                )
            before_event_count = len(state.public_events)
            before_cursor = _event_cursor(state)
            client_action_id = f"fixture-{spec.name}-{action_index:04d}"
            state = apply_match_action(state, action)
            new_events = state.public_events[before_event_count:]
            event_indices = [event.event_index for event in new_events]
            accepted_actions.append(
                {
                    "accepted_event_indices": event_indices,
                    "action": action_to_data(action),
                    "action_index": action_index,
                    "client_action_id": client_action_id,
                    "expected_event_index": before_cursor,
                    "acknowledgement": {
                        "accepted_event_indices": event_indices,
                        "client_action_id": client_action_id,
                        "last_event_index": _event_cursor(state),
                        "match_ref": state.match_ref,
                        "schema_version": ACTION_ACK_SCHEMA_VERSION,
                        "status": "accepted",
                    },
                    "event_batch": [event_to_data(event) for event in new_events],
                }
            )
            record("after_action", action_index)
            action_index += 1

        if state.terminal:
            break

    if action_index != len(actions):
        raise RuntimeError(f"scenario {spec.name} has {len(actions) - action_index} unused actions")
    if state.terminal is not spec.expected_terminal:
        raise RuntimeError(
            f"scenario {spec.name} terminal={state.terminal}, expected {spec.expected_terminal}"
        )

    return {
        "accepted_actions": accepted_actions,
        "deal_summaries": [
            deal_result_to_data(item.public_result) for item in state.completed_deals
        ],
        "match_input": match_input,
        "public_events": public_event_log_to_data(
            state.public_events,
            match_ref=state.match_ref,
        ),
        "snapshots": snapshots,
        "terminal_result": (
            match_result_to_data(match_result_from_state(state))
            if state.terminal
            else None
        ),
    }


def _find_snapshot(
    snapshots: dict[int, list[dict[str, object]]],
    *,
    after_action_index: int | None = None,
    phase: str | None = None,
    current_trick_minimum: int | None = None,
    match_score: list[int] | None = None,
    deal_ref: str | None = None,
) -> tuple[int, dict[str, object]]:
    for seat in range(4):
        for snapshot in snapshots[seat]:
            observation = snapshot["observation"]
            assert isinstance(observation, dict)
            if after_action_index is not None and snapshot["after_action_index"] != after_action_index:
                continue
            if phase is not None and observation["phase"] != phase:
                continue
            if deal_ref is not None and observation["deal_ref"] != deal_ref:
                continue
            if (
                current_trick_minimum is not None
                and len(observation["current_trick"]) < current_trick_minimum
            ):
                continue
            if match_score is not None and observation["match_score"] != match_score:
                continue
            return seat, snapshot
    raise RuntimeError("required fixture snapshot was not found")


def _snapshot_for_seat(
    snapshots: dict[int, list[dict[str, object]]],
    seat: int,
    snapshot_index: int,
) -> dict[str, object]:
    for snapshot in snapshots[seat]:
        if snapshot["snapshot_index"] == snapshot_index:
            return snapshot
    raise RuntimeError(f"snapshot {snapshot_index} was not found for seat {seat}")


def _transport_cases(recording: dict[str, Any]) -> dict[str, object]:
    snapshots = recording["snapshots"]
    accepted = recording["accepted_actions"]
    match_ref = recording["match_input"].match_ref

    showing_seat, showing = _find_snapshot(snapshots, phase="SHOWING")
    trick_seat, trick = _find_snapshot(
        snapshots,
        phase="TRICK_PLAY",
        current_trick_minimum=1,
    )
    reset_seat, reset = _find_snapshot(
        snapshots,
        match_score=[0, 0],
        phase="SHOWING",
        deal_ref=f"{match_ref}/deal:2",
    )

    stale_action = accepted[1]
    stale_seat, stale_latest = _find_snapshot(snapshots, after_action_index=0)
    stale_action_seat = stale_action["action"]["seat"]
    stale_latest = _snapshot_for_seat(
        snapshots,
        stale_action_seat,
        stale_latest["snapshot_index"],
    )
    stale_response = {
        "message_type": "action_acknowledgement",
        "payload": {
            "accepted_event_indices": [],
            "client_action_id": "fixture-stale-action",
            "last_event_index": stale_latest["event_index"],
            "match_ref": match_ref,
            "schema_version": ACTION_ACK_SCHEMA_VERSION,
            "status": "stale",
        },
    }

    trick_observation = _snapshot_for_seat(
        snapshots,
        trick_observation_seat := trick["observation"]["current_actor"],
        trick["snapshot_index"],
    )["observation"]
    legal_cards = {
        item["card"]
        for item in trick_observation["legal_actions"]
        if item["type"] == "play"
    }
    illegal_card = next(
        card for card in trick_observation["own_hand"] if card not in legal_cards
    )
    rejected_response = {
        "message_type": "action_acknowledgement",
        "payload": {
            "accepted_event_indices": [],
            "client_action_id": "fixture-rejected-action",
            "code": "illegal_action",
            "last_event_index": trick["event_index"],
            "match_ref": match_ref,
            "schema_version": ACTION_ACK_SCHEMA_VERSION,
            "status": "rejected",
        },
    }
    duplicate_ack = dict(accepted[0]["acknowledgement"])
    duplicate_ack["status"] = "duplicate"

    def event_at(index: int) -> list[dict[str, object]]:
        return [
            event
            for event in recording["public_events"]["events"]
            if event["event_index"] == index
        ]

    def completed_deals_at(index: int) -> list[dict[str, object]]:
        terminal_result = recording.get("terminal_result")
        if type(terminal_result) is not dict:
            return []
        return [
            deal
            for deal in terminal_result["deals"]
            if max(event["event_index"] for event in deal["events"]) <= index
        ]

    return {
        "schema_version": "tuppi.ui.transport_cases.v2",
        "protocol_version": NETWORK_PROTOCOL_VERSION,
        "cases": [
            {
                "name": "reconnect_during_showing",
                "request": {
                    "message_type": "reconnect",
                    "payload": {
                        "last_applied_event_index": showing["event_index"],
                    },
                },
                "response": {
                    "message_type": "reconnect_result",
                    "payload": {
                        "completed_deals": completed_deals_at(showing["event_index"]),
                        "event_delta": [],
                        "observation": showing["observation"],
                        "status": "connected",
                    },
                },
            },
            {
                "name": "reconnect_during_trick",
                "request": {
                    "message_type": "reconnect",
                    "payload": {
                        "last_applied_event_index": trick["event_index"] - 1,
                    },
                },
                "response": {
                    "message_type": "reconnect_result",
                    "payload": {
                        "completed_deals": completed_deals_at(trick["event_index"]),
                        "event_delta": event_at(trick["event_index"]),
                        "observation": _snapshot_for_seat(
                            snapshots,
                            trick_seat,
                            trick["snapshot_index"],
                        )["observation"],
                        "status": "connected",
                    },
                },
            },
            {
                "name": "reconnect_after_reset",
                "request": {
                    "message_type": "reconnect",
                    "payload": {
                        "last_applied_event_index": reset["event_index"] - 1,
                    },
                },
                "response": {
                    "message_type": "reconnect_result",
                    "payload": {
                        "completed_deals": completed_deals_at(reset["event_index"]),
                        "event_delta": event_at(reset["event_index"]),
                        "observation": reset["observation"],
                        "status": "connected",
                    },
                },
            },
            {
                "name": "duplicate_submission",
                "request": {
                    "message_type": "action_submission",
                    "payload": {
                        "action": accepted[0]["action"],
                        "client_action_id": accepted[0]["client_action_id"],
                        "expected_event_index": accepted[0]["expected_event_index"],
                        "match_ref": match_ref,
                    },
                },
                "response": {
                    "message_type": "action_acknowledgement",
                    "payload": duplicate_ack,
                },
            },
            {
                "name": "stale_submission",
                "request": {
                    "message_type": "action_submission",
                    "payload": {
                        "action": stale_action["action"],
                        "client_action_id": "fixture-stale-action",
                        "expected_event_index": -1,
                        "match_ref": match_ref,
                    },
                },
                "response": stale_response,
            },
            {
                "name": "server_rejection",
                "request": {
                    "message_type": "action_submission",
                    "payload": {
                        "action": {
                            "card": illegal_card,
                            "seat": trick_observation["current_actor"],
                            "type": "play",
                        },
                        "client_action_id": "fixture-rejected-action",
                        "expected_event_index": trick["event_index"],
                        "match_ref": match_ref,
                    },
                },
                "response": rejected_response,
            },
            {
                "name": "protocol_mismatch",
                "request": {
                    "message_type": "hello",
                    "payload": {
                        "protocol_version": "tuppi.network.unknown",
                        "room_code": "ABC123",
                        "session_token": "fixture_session_token_0123456789",
                    },
                },
                "response": {
                    "message_type": "compatibility_result",
                    "payload": {
                        "compatible": False,
                        "message_key": "update_required",
                        "supported_protocol_versions": [NETWORK_PROTOCOL_VERSION],
                    },
                },
            },
        ],
    }


def _wire_recordings(
    recording: dict[str, Any],
    analysis: dict[str, object],
) -> dict[str, object]:
    """Return representative recordings for every implemented wire DTO."""

    snapshots = recording["snapshots"]
    accepted = recording["accepted_actions"]
    match_ref = recording["match_input"].match_ref
    _, showing = _find_snapshot(snapshots, phase="SHOWING")
    terminal = next(
        snapshot
        for snapshot in snapshots[0]
        if snapshot["observation"]["match_terminal"]
    )
    terminal_result = recording["terminal_result"]
    if terminal_result is None:
        raise RuntimeError("wire recordings require a terminal exact-52 result")

    room_code = "ABC123"
    token = "fixture_session_token_0123456789"
    open_seats = [
        {
            "display_name": "Fixture host" if seat == 0 else None,
            "kind": "human" if seat == 0 else "open",
            "ready": False,
            "seat": seat,
        }
        for seat in range(4)
    ]
    configured_seats = [
        {
            "display_name": "Fixture host" if seat == 0 else "Tuppi AI",
            "kind": "human" if seat == 0 else "ai",
            "ready": seat != 0,
            "seat": seat,
            **({"agent_profile": "partner_aware_v1"} if seat != 0 else {}),
        }
        for seat in range(4)
    ]
    playing_seats = [
        {**seat, "ready": True}
        for seat in configured_seats
    ]
    joined_seats = [
        {
            "display_name": (
                "Fixture host" if seat == 0 else "Fixture guest" if seat == 1 else None
            ),
            "kind": "human" if seat in {0, 1} else "open",
            "ready": False,
            "seat": seat,
        }
        for seat in range(4)
    ]
    waiting_lobby = {
        "ai_action_delay_ms": 5000,
        "lifecycle": "waiting",
        "room_code": room_code,
        "seats": open_seats,
    }
    configured_lobby = {
        "ai_action_delay_ms": 5000,
        "lifecycle": "configured",
        "room_code": room_code,
        "seats": configured_seats,
    }
    joined_lobby = {
        "ai_action_delay_ms": 5000,
        "lifecycle": "waiting",
        "room_code": room_code,
        "seats": joined_seats,
    }
    playing_lobby = {
        "ai_action_delay_ms": 5000,
        "lifecycle": "playing",
        "room_code": room_code,
        "seats": playing_seats,
    }

    http = [
        {
            "name": "compatibility_result",
            "method": "GET",
            "path": "/v1/compatibility",
            "request_schema_ref": None,
            "request": None,
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/compatibilityResult",
            "response": {
                "compatible": True,
                "protocol_version": NETWORK_PROTOCOL_VERSION,
                "status": "ok",
            },
        },
        {
            "name": "create_room",
            "method": "POST",
            "path": "/v1/rooms",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/createRoomRequest",
            "request": {"display_name": "Fixture host", "ai_seats": [1, 2, 3]},
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/roomBootstrap",
            "response": {
                "room_code": room_code,
                "seat": 0,
                "session_token": token,
                "lobby": configured_lobby,
            },
        },
        {
            "name": "join_room",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/join",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/joinRoomRequest",
            "request": {"display_name": "Fixture guest"},
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/roomBootstrap",
            "response": {
                "room_code": room_code,
                "seat": 1,
                "session_token": f"{token}_guest",
                "lobby": joined_lobby,
            },
        },
        {
            "name": "configure_room",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/configure",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/configureRoomRequest",
            "request": {"session_token": token, "ai_seats": [1, 2, 3]},
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/roomStatusResponse",
            "response": {"lobby": configured_lobby},
        },
        {
            "name": "room_settings",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/settings",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/roomSettingsRequest",
            "request": {"session_token": token, "ai_action_delay_ms": 2000},
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/roomStatusResponse",
            "response": {
                "lobby": {**configured_lobby, "ai_action_delay_ms": 2000}
            },
        },
        {
            "name": "ready",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/ready",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/sessionRequest",
            "request": {"session_token": token},
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/roomStatusResponse",
            "response": {"lobby": playing_lobby, "playing": True},
        },
        {
            "name": "analysis",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/analysis",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/sessionRequest",
            "request": {"session_token": token},
            "response_schema_ref": "https://example.invalid/tuppi/schemas/network/post_match_analysis.schema.json",
            "response": analysis,
        },
        {
            "name": "completed_deal_analysis",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/deals/0/analysis",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/sessionRequest",
            "request": {"session_token": token},
            "response_schema_ref": "https://example.invalid/tuppi/schemas/network/completed_deal_analysis.schema.json",
            "response": {
                "schema_version": "tuppi.analysis.completed_deal.v1",
                "match_ref": match_ref,
                "deal_ref": terminal_result["deals"][0]["deal_ref"],
                "deal_number": 0,
                "seat": analysis.get("seat", 0),
                "summary": {
                    "contract": terminal_result["deals"][0]["contract"],
                    "diagnostic_count": 0,
                    "outcome": terminal_result["deals"][0]["outcome"],
                    "points": terminal_result["deals"][0]["deal_score"]["points"],
                    "score_before": terminal_result["deals"][0]["score_before"],
                    "score_after": terminal_result["deals"][0]["score_after"],
                    "team_tricks": terminal_result["deals"][0]["team_tricks"],
                },
                "analyses": [],
            },
        },
        {
            "name": "server_error",
            "method": "POST",
            "path": f"/v1/rooms/{room_code}/join",
            "request_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/joinRoomRequest",
            "request": {"display_name": "Fixture guest"},
            "response_schema_ref": f"{HTTP_SCHEMA_ROOT}#/$defs/serverError",
            "response": {"error": "room_full"},
        },
    ]

    websocket: list[dict[str, object]] = []

    def add(name: str, direction: str, message: dict[str, object]) -> None:
        websocket.append(
            {
                "name": name,
                "direction": direction,
                "schema_ref": WEBSOCKET_SCHEMA_REF,
                "message": message,
            }
        )

    add(
        "hello",
        "client_to_server",
        {
            "message_type": "hello",
            "payload": {
                "protocol_version": NETWORK_PROTOCOL_VERSION,
                "room_code": room_code,
                "session_token": token,
            },
        },
    )
    add(
        "hello_ack",
        "server_to_client",
        {
            "message_type": "hello_ack",
            "payload": {
                "compatible": True,
                "protocol_version": NETWORK_PROTOCOL_VERSION,
                "room_code": room_code,
                "seat": 0,
            },
        },
    )
    add(
        "lobby_snapshot",
        "server_to_client",
        {"message_type": "lobby_snapshot", "payload": waiting_lobby},
    )
    add(
        "ready",
        "client_to_server",
        {"message_type": "ready", "payload": {"session_token": token}},
    )
    add(
        "match_update",
        "server_to_client",
        {
            "message_type": "match_update",
            "payload": {
                "completed_deals": [],
                "event_batch": [],
                "last_event_index": showing["event_index"],
                "match_ref": match_ref,
                "observation": showing["observation"],
            },
        },
    )
    add(
        "action_submission",
        "client_to_server",
        {
            "message_type": "action_submission",
            "payload": {
                "action": accepted[0]["action"],
                "client_action_id": accepted[0]["client_action_id"],
                "expected_event_index": accepted[0]["expected_event_index"],
                "match_ref": match_ref,
            },
        },
    )
    add(
        "action_acknowledgement",
        "server_to_client",
        {
            "message_type": "action_acknowledgement",
            "payload": accepted[0]["acknowledgement"],
        },
    )
    for case in _transport_cases(recording)["cases"]:
        add(f"{case['name']}_request", "client_to_server", case["request"])
        add(f"{case['name']}_response", "server_to_client", case["response"])
    add(
        "protocol_error",
        "server_to_client",
        {"message_type": "protocol_error", "payload": {"code": "invalid_message"}},
    )
    add("ping", "client_to_server", {"message_type": "ping", "payload": {}})
    add("pong", "server_to_client", {"message_type": "pong", "payload": {}})
    add(
        "match_completion",
        "server_to_client",
        {
            "message_type": "match_update",
            "payload": {
                "completed_deals": terminal_result["deals"],
                "event_batch": [],
                "last_event_index": terminal["event_index"],
                "match_ref": match_ref,
                "observation": terminal["observation"],
                "match_result": terminal_result,
            },
        },
    )
    return {
        "schema_version": "tuppi.ui.wire_recordings.v1",
        "protocol_version": NETWORK_PROTOCOL_VERSION,
        "http": http,
        "websocket": websocket,
    }


def export_bundle(output_dir: Path, scenario_names: tuple[str, ...] | None = None) -> Path:
    """Generate the UI-A bundle and return its output directory."""

    selected = set(scenario_names or (spec.name for spec in SCENARIOS))
    specs = tuple(spec for spec in SCENARIOS if spec.name in selected)
    unknown = selected - {spec.name for spec in SCENARIOS}
    if unknown:
        raise ValueError(f"unknown fixture scenario(s): {sorted(unknown)}")
    if not specs:
        raise ValueError("at least one fixture scenario is required")

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files: list[str] = []
    scenario_manifest: list[dict[str, object]] = []
    recordings: dict[str, dict[str, Any]] = {}

    for spec in specs:
        recording = _run_scenario(spec)
        recordings[spec.name] = recording
        scenario_dir = output_dir / "fixtures" / spec.name
        scenario_dir.mkdir(parents=True, exist_ok=True)

        for seat in range(4):
            path = scenario_dir / f"seat-{seat}.json"
            _write_json(
                path,
                {
                    "schema_version": BUNDLE_SCHEMA_VERSION,
                    "scenario": spec.name,
                    "seat": seat,
                    "snapshots": recording["snapshots"][seat],
                },
            )
            generated_files.append(str(path.relative_to(output_dir)))

        public_path = scenario_dir / "public-events.json"
        _write_json(public_path, recording["public_events"])
        generated_files.append(str(public_path.relative_to(output_dir)))

        actions_path = scenario_dir / "accepted-actions.json"
        _write_json(
            actions_path,
            {
                "schema_version": "tuppi.ui.accepted_actions.v1",
                "scenario": spec.name,
                "actions": recording["accepted_actions"],
            },
        )
        generated_files.append(str(actions_path.relative_to(output_dir)))

        deals_path = scenario_dir / "deal-summaries.json"
        _write_json(
            deals_path,
            {
                "schema_version": "tuppi.ui.deal_summaries.v1",
                "scenario": spec.name,
                "deals": recording["deal_summaries"],
            },
        )
        generated_files.append(str(deals_path.relative_to(output_dir)))

        if recording["terminal_result"] is not None:
            result_path = scenario_dir / "match-result.json"
            _write_json(result_path, recording["terminal_result"])
            generated_files.append(str(result_path.relative_to(output_dir)))

        scenario_manifest.append(
            {
                "expected_terminal": spec.expected_terminal,
                "name": spec.name,
                "seat_files": [
                    str((scenario_dir / f"seat-{seat}.json").relative_to(output_dir))
                    for seat in range(4)
                ],
                "snapshot_count": len(recording["snapshots"][0]),
            }
        )

    transport_recording = recordings.get("exact_52")
    if transport_recording is None:
        transport_recording = _run_scenario(
            next(spec for spec in SCENARIOS if spec.name == "exact_52")
        )
    analysis_source = _repository_root() / "examples/ui/phase_a_bundle/analysis/example-exact-52.json"
    analysis = strict_json_load_file(analysis_source)
    analysis_path = output_dir / "analysis" / "example-exact-52.json"
    _write_json(analysis_path, analysis)
    generated_files.append(str(analysis_path.relative_to(output_dir)))

    transport_path = output_dir / "transport" / "cases.json"
    _write_json(transport_path, _transport_cases(transport_recording))
    generated_files.append(str(transport_path.relative_to(output_dir)))

    wire_recordings_path = output_dir / "transport" / "wire-recordings.json"
    _write_json(
        wire_recordings_path,
        _wire_recordings(transport_recording, analysis),
    )
    generated_files.append(str(wire_recordings_path.relative_to(output_dir)))

    protocol_manifest_source = _repository_root() / "schemas/network/protocol_manifest.json"
    protocol_manifest_path = output_dir / "protocol-manifest.json"
    _write_json(
        protocol_manifest_path,
        strict_json_load_file(protocol_manifest_source),
    )
    generated_files.append("protocol-manifest.json")

    schema_digests = schema_metadata(_repository_root())

    compatibility_path = output_dir / "compatibility.json"
    _write_json(
        compatibility_path,
        {
            "canonical_engine_schemas": [
                "tuppi.engine.player_observation.v1",
                "tuppi.engine.public_event.v1",
                "tuppi.engine.deal_result.v1",
                "tuppi.engine.match_result.v1",
            ],
            "protocol_manifest": "protocol-manifest.json",
            "protocol_version": NETWORK_PROTOCOL_VERSION,
            "ruleset_id": "project_target_v1",
            "schema_version": "tuppi.ui.compatibility.v1",
            "ui_language": "fi",
        },
    )
    generated_files.append("compatibility.json")

    manifest_path = output_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
            "canonical_engine_schemas": [
                "tuppi.engine.player_observation.v1",
                "tuppi.engine.public_event.v1",
                "tuppi.engine.deal_result.v1",
                "tuppi.engine.match_result.v1",
            ],
            "compatibility": "compatibility.json",
            "generated_files": sorted(generated_files),
            "generator": "tuppi_ui_fixtures.exporter",
            "protocol_version": NETWORK_PROTOCOL_VERSION,
            "ruleset_id": "project_target_v1",
            "scenarios": scenario_manifest,
            "schema_digests": schema_digests,
            "visibility": "development_fixture_public_projection",
        },
    )
    generated_files.append("manifest.json")

    checksums = {
        relative: _sha256(output_dir / relative)
        for relative in sorted(generated_files)
        if relative != "sha256sums.json"
    }
    _write_json(
        output_dir / "sha256sums.json",
        {
            "schema_version": "tuppi.ui.checksums.v1",
            "files": checksums,
        },
    )
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export privacy-safe deterministic fixtures for TuppiClient"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        choices=tuple(spec.name for spec in SCENARIOS),
        help="export only this scenario; repeat for multiple scenarios",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    export_bundle(args.output_dir, tuple(args.scenarios) if args.scenarios else None)
    print(f"exported Tuppi UI fixture bundle to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
