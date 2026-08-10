from __future__ import annotations

import asyncio
import json

from tuppi_server.app import TuppiASGIApp
from tuppi_server.rooms import RoomManager
from tuppi_ui_fixtures.validation import validate_instance


WS_SCHEMA = "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"
HTTP_SCHEMA = "https://example.invalid/tuppi/schemas/network/http_api.schema.json"


def _message(message_type: str, payload: dict[str, object]) -> str:
    return json.dumps({"message_type": message_type, "payload": payload})


def test_http_bootstrap_creates_a_private_solo_room() -> None:
    async def scenario() -> list[dict[str, object]]:
        app = TuppiASGIApp(RoomManager())
        incoming = iter(
            [
                {
                    "type": "http.request",
                    "body": json.dumps(
                        {"display_name": "Pelaaja", "ai_seats": [1, 2, 3]}
                    ).encode("utf-8"),
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
            {"type": "http", "method": "POST", "path": "/v1/rooms"},
            receive,
            send,
        )
        return outgoing

    outgoing = asyncio.run(scenario())
    assert outgoing[0]["status"] == 200
    response = json.loads(outgoing[1]["body"])
    validate_instance(response, f"{HTTP_SCHEMA}#/$defs/roomBootstrap")
    assert response["seat"] == 0
    assert len(response["session_token"]) > 20
    assert response["lobby"]["seats"][1]["kind"] == "ai"


def test_http_create_room_and_websocket_action_flow() -> None:
    async def scenario() -> list[dict[str, object]]:
        manager = RoomManager()
        app = TuppiASGIApp(manager)
        room, session = manager.create_room(
            display_name="Pelaaja",
            ai_seats=frozenset({1, 2, 3}),
        )
        manager.mark_ready(code=room.code, token=session.token)

        observation = room.runner.observation(0)  # type: ignore[union-attr]
        action = observation["legal_actions"][0]
        incoming = iter(
            [
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "hello",
                        {
                            "protocol_version": "tuppi.network.v1",
                            "room_code": room.code,
                            "session_token": session.token,
                        },
                    ),
                },
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "action_submission",
                        {
                            "action": action,
                            "client_action_id": "ws-action-1",
                            "expected_event_index": room.runner.event_cursor,  # type: ignore[union-attr]
                            "match_ref": room.runner.match_ref,  # type: ignore[union-attr]
                        },
                    ),
                },
                {"type": "websocket.disconnect"},
            ]
        )
        outgoing: list[dict[str, object]] = []

        async def receive():
            return next(incoming)

        async def send(message):
            outgoing.append(message)

        await app(
            {
                "type": "websocket",
                "path": "/v1/ws",
                "query_string": b"",
            },
            receive,
            send,
        )
        return [
            json.loads(item["text"])
            for item in outgoing
            if item.get("type") == "websocket.send"
        ]

    messages = asyncio.run(scenario())
    for message in messages:
        validate_instance(message, WS_SCHEMA)
    message_types = [item["message_type"] for item in messages]
    assert "hello_ack" in message_types
    assert "lobby_snapshot" in message_types
    assert "action_acknowledgement" in message_types
    assert "match_update" in message_types

    encoded = json.dumps(messages)
    assert "initial_hands" not in encoded
    assert '"hands"' not in encoded
    assert "deal_id" not in encoded


def test_stale_action_is_followed_by_authorized_reconnect_payload() -> None:
    async def scenario() -> list[dict[str, object]]:
        manager = RoomManager()
        app = TuppiASGIApp(manager)
        room, session = manager.create_room(
            display_name="Pelaaja",
            ai_seats=frozenset({1, 2, 3}),
        )
        manager.mark_ready(code=room.code, token=session.token)
        observation = room.runner.observation(0)  # type: ignore[union-attr]
        incoming = iter(
            [
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "hello",
                        {
                            "protocol_version": "tuppi.network.v1",
                            "room_code": room.code,
                            "session_token": session.token,
                        },
                    ),
                },
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "action_submission",
                        {
                            "action": observation["legal_actions"][0],
                            "client_action_id": "ws-stale-1",
                            "expected_event_index": -1,
                            "match_ref": room.runner.match_ref,  # type: ignore[union-attr]
                        },
                    ),
                },
                {"type": "websocket.disconnect"},
            ]
        )
        outgoing: list[dict[str, object]] = []

        async def receive():
            return next(incoming)

        async def send(message):
            if message.get("type") == "websocket.send":
                outgoing.append(json.loads(message["text"]))

        await app({"type": "websocket", "path": "/v1/ws"}, receive, send)
        return outgoing

    messages = asyncio.run(scenario())
    for message in messages:
        validate_instance(message, WS_SCHEMA)
    acknowledgements = [
        item for item in messages if item["message_type"] == "action_acknowledgement"
    ]
    assert acknowledgements[0]["payload"]["status"] == "stale"
    reconnects = [item for item in messages if item["message_type"] == "reconnect_result"]
    assert reconnects
    assert reconnects[-1]["payload"]["observation"]["observing_seat"] == 0


def test_websocket_ready_ping_and_protocol_error_messages_follow_schema() -> None:
    async def scenario() -> list[dict[str, object]]:
        manager = RoomManager()
        app = TuppiASGIApp(manager)
        room, session = manager.create_room(
            display_name="Pelaaja",
            ai_seats=frozenset({1, 2, 3}),
        )
        incoming = iter(
            [
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "hello",
                        {
                            "protocol_version": "tuppi.network.v1",
                            "room_code": room.code,
                            "session_token": session.token,
                        },
                    ),
                },
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "ready",
                        {"session_token": session.token},
                    ),
                },
                {
                    "type": "websocket.receive",
                    "text": _message("ping", {}),
                },
                {
                    "type": "websocket.receive",
                    "text": _message("unknown", {}),
                },
                {"type": "websocket.disconnect"},
            ]
        )
        outgoing: list[dict[str, object]] = []

        async def receive():
            return next(incoming)

        async def send(message):
            if message.get("type") == "websocket.send":
                outgoing.append(json.loads(message["text"]))

        await app({"type": "websocket", "path": "/v1/ws"}, receive, send)
        return outgoing

    messages = asyncio.run(scenario())
    assert {item["message_type"] for item in messages} >= {
        "hello_ack",
        "lobby_snapshot",
        "pong",
        "protocol_error",
    }
    for message in messages:
        validate_instance(message, WS_SCHEMA)


def test_websocket_protocol_mismatch_uses_the_authoritative_envelope() -> None:
    async def scenario() -> list[dict[str, object]]:
        app = TuppiASGIApp(RoomManager())
        incoming = iter(
            [
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "hello",
                        {
                            "protocol_version": "tuppi.network.v0",
                            "room_code": "ABC123",
                            "session_token": "fixture_session_token_0123456789",
                        },
                    ),
                }
            ]
        )
        outgoing: list[dict[str, object]] = []

        async def receive():
            return next(incoming)

        async def send(message):
            if message.get("type") == "websocket.send":
                outgoing.append(json.loads(message["text"]))

        await app({"type": "websocket", "path": "/v1/ws"}, receive, send)
        return outgoing

    messages = asyncio.run(scenario())
    assert [item["message_type"] for item in messages] == ["compatibility_result"]
    validate_instance(messages[0], WS_SCHEMA)


def test_accepted_websocket_action_is_durable_before_ack(tmp_path) -> None:
    async def scenario() -> tuple[str, str, dict[str, object]]:
        manager = RoomManager(persistence_dir=tmp_path)
        app = TuppiASGIApp(manager)
        room, session = manager.create_room(
            display_name="Pelaaja",
            ai_seats=frozenset({1, 2, 3}),
        )
        manager.mark_ready(code=room.code, token=session.token)
        runner = room.runner
        assert runner is not None
        observation = runner.observation(0)
        incoming = iter(
            [
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "hello",
                        {
                            "protocol_version": "tuppi.network.v1",
                            "room_code": room.code,
                            "session_token": session.token,
                        },
                    ),
                },
                {
                    "type": "websocket.receive",
                    "text": _message(
                        "action_submission",
                        {
                            "action": observation["legal_actions"][0],
                            "client_action_id": "durable-ws-action-1",
                            "expected_event_index": runner.event_cursor,
                            "match_ref": runner.match_ref,
                        },
                    ),
                },
                {"type": "websocket.disconnect"},
            ]
        )

        async def receive():
            return next(incoming)

        async def send(message):
            return None

        await app({"type": "websocket", "path": "/v1/ws"}, receive, send)
        return room.code, session.token, runner.observation(0)

    room_code, token, expected_observation = asyncio.run(scenario())
    restored_manager = RoomManager(persistence_dir=tmp_path)
    restored_room, restored_session = restored_manager.session(
        code=room_code,
        token=token,
    )
    assert restored_session.seat == 0
    assert restored_room.runner is not None
    assert restored_room.runner.observation(0) == expected_observation
