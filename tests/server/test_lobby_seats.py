"""Renaming your own seat and the host freeing a seat, before a match starts.

The friend-test case (2026-10-16): a friend joined under the wrong name,
left and joined again under the right one. The first seat stayed a human
seat nobody would ever ready, so the room could not start.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from tuppi_rules import RulesetId
from tuppi_server.app import SEAT_RELEASED_CLOSE_CODE, Connection, TuppiASGIApp
from tuppi_server.hosted import HostedBoundary
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_ui_fixtures.validation import validate_instance

V3 = RulesetId.PROJECT_TARGET_V3
HTTP_SCHEMA = "https://example.invalid/tuppi/schemas/network/http_api.schema.json"


def manager(path=None):
    return RoomManager(path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)


def test_rename_own_seat_only_before_the_match(tmp_path):
    rooms = manager(tmp_path)
    room, host = rooms.create_room(display_name="Pyry", ai_seats=frozenset({1, 3}))
    _, guest = rooms.join_room(code=room.code, display_name="Aiin")
    rooms.mark_ready(code=room.code, token=host.token, auto_run_ai=False)
    rooms.rename(code=room.code, token=guest.token, display_name="  Aino ")
    seat = next(s for s in room.snapshot()["seats"] if s["seat"] == guest.seat)
    assert seat["display_name"] == "Aino"
    assert next(s for s in room.snapshot()["seats"] if s["seat"] == 0)["ready"], "renaming keeps readiness"
    with pytest.raises(RoomError, match="invalid_display_name"):
        rooms.rename(code=room.code, token=guest.token, display_name="   ")
    with pytest.raises(RoomError, match="invalid_session"):
        rooms.rename(code=room.code, token="not-a-session-token-at-all", display_name="X")
    assert manager(tmp_path).get(room.code).session_for_seat(guest.seat).display_name == "Aino", "persisted"
    rooms.mark_ready(code=room.code, token=guest.token, auto_run_ai=False)
    assert room.runner is not None
    with pytest.raises(RoomError, match="settings_locked"):
        rooms.rename(code=room.code, token=guest.token, display_name="Late")


def test_host_frees_a_seat_left_behind_and_the_room_can_start(tmp_path):
    rooms = manager(tmp_path)
    room, host = rooms.create_room(display_name="Pyry")
    _, wrong = rooms.join_room(code=room.code, display_name="Aiin")
    _, right = rooms.join_room(code=room.code, display_name="Aino")
    rooms.set_ai_seats(code=room.code, host_token=host.token, ai_seats=frozenset({3}))
    for session in (host, right):
        rooms.mark_ready(code=room.code, token=session.token, auto_run_ai=False)
    assert room.runner is None, "the left-behind seat blocks the start"
    with pytest.raises(RoomError, match="host_required"):
        rooms.release_seat(code=room.code, host_token=right.token, seat=wrong.seat)
    for seat in (0, 3, 7, "1"):
        with pytest.raises(RoomError, match="seat_not_releasable"):
            rooms.release_seat(code=room.code, host_token=host.token, seat=seat)
    _, released = rooms.release_seat(code=room.code, host_token=host.token, seat=wrong.seat)
    assert released == wrong.token
    with pytest.raises(RoomError, match="invalid_session"):
        rooms.session(code=room.code, token=wrong.token)
    snapshot = {s["seat"]: s for s in room.snapshot()["seats"]}
    assert snapshot[wrong.seat]["kind"] == "open" and not any(s["ready"] for s in snapshot.values() if s["kind"] == "human")
    assert manager(tmp_path).get(room.code).session_for_seat(wrong.seat) is None, "persisted"
    # The freed seat can take a bot, and the room starts.
    rooms.set_ai_seats(code=room.code, host_token=host.token, ai_seats=frozenset({wrong.seat, 3}))
    for session in (host, right):
        rooms.mark_ready(code=room.code, token=session.token, auto_run_ai=False)
    assert room.runner is not None
    with pytest.raises(RoomError, match="settings_locked"):
        rooms.release_seat(code=room.code, host_token=host.token, seat=right.seat)


def test_http_commands_broadcast_and_close_the_released_socket():
    async def scenario():
        rooms = manager()
        room, host = rooms.create_room(display_name="Pyry")
        _, wrong = rooms.join_room(code=room.code, display_name="Aiin")
        _, right = rooms.join_room(code=room.code, display_name="Aino")
        boundary = HostedBoundary(TuppiASGIApp(rooms), origins={"https://tuppi.example"}, max_bot_rooms=8)
        sent = {wrong.token: [], right.token: [], host.token: []}
        for session in (host, wrong, right):
            async def send(message, token=session.token):
                sent[token].append(message)
            boundary.game._connections.setdefault(room.code, {})[session.token] = Connection(
                room.code, session.token, session.seat, send)

        async def post(command, body):
            output = []
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            async def send(message): output.append(message)
            await boundary({"type": "http", "method": "POST", "path": f"/v1/rooms/{room.code}/{command}",
                            "headers": [(b"origin", b"https://tuppi.example")]}, receive, send)
            return output[0]["status"], json.loads(output[1]["body"])

        request = {"session_token": right.token, "display_name": "Aino O."}
        validate_instance(request, f"{HTTP_SCHEMA}#/$defs/renameRequest")
        status, body = await post("name", request)
        assert status == 200 and any(s["display_name"] == "Aino O." for s in body["lobby"]["seats"])
        validate_instance(body["lobby"], f"{HTTP_SCHEMA}#/$defs/lobbySnapshot")
        lobby = [json.loads(m["text"]) for m in sent[host.token] if m["type"] == "websocket.send"]
        assert lobby[-1]["message_type"] == "lobby_snapshot", "others see the new name"

        status, body = await post("release", {"session_token": right.token, "seat": wrong.seat})
        assert (status, body) == (409, {"error": "host_required"})
        request = {"session_token": host.token, "seat": wrong.seat}
        validate_instance(request, f"{HTTP_SCHEMA}#/$defs/releaseSeatRequest")
        status, body = await post("release", request)
        assert status == 200
        assert sent[wrong.token][-1] == {"type": "websocket.close", "code": SEAT_RELEASED_CLOSE_CODE}
        assert wrong.token not in boundary.game._connections[room.code]
        for token in (host.token, right.token):
            assert json.loads(sent[token][-1]["text"])["message_type"] == "lobby_snapshot"
        assert {"rename", "release_seat"} <= set((await compatibility(boundary))["features"])
    asyncio.run(scenario())


async def compatibility(app):
    output = []
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message): output.append(message)
    await app({"type": "http", "method": "GET", "path": "/v1/compatibility", "headers": []}, receive, send)
    body = json.loads(output[1]["body"])
    validate_instance({"compatible": True, "features": body["features"], "protocol_version": "tuppi.network.v1",
                       "room_code": "ABC123", "seat": 0},
                      "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"
                      "#/$defs/helloAcknowledgementPayload")
    return body
