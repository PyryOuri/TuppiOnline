"""Storage safety for the hosted authority (BE-04): a failed save is never
acknowledged, changes stop until a restart, archives are pruned, a low disk
refuses new rooms, and a copied data directory restores the same games."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time

import pytest
from tuppi_engine import action_from_data
from tuppi_engine.errors import SerializationError
from tuppi_rules import RulesetId
from tuppi_server import match_runner, persistence
from tuppi_server.app import Connection, TuppiASGIApp
from tuppi_server.hosted import HostedBoundary, storage_limits_from_environment
from tuppi_server.persistence import FileRoomStore, PersistenceError
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY

V3 = RulesetId.PROJECT_TARGET_V3
ORIGIN = "https://tuppi.example"


@pytest.fixture(autouse=True)
def unpaced(monkeypatch):
    monkeypatch.setattr(match_runner, "REVEAL_PAUSE_SECONDS", 0)
    monkeypatch.setattr(match_runner, "REVEAL_STEP_SECONDS", 0)


def manager(path):
    return RoomManager(path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)


async def http(app, path, body=None, method="POST"):
    output = []
    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"", "more_body": False}
    async def send(message): output.append(message)
    await app({"type": "http", "path": path, "method": method, "headers": []}, receive, send)
    return output[0]["status"], json.loads(output[1]["body"])


def started_room(path):
    """A room with the host against three bots, at the host's first bid."""
    rooms = manager(path)
    room, host = rooms.create_room(display_name="Host", ai_seats=frozenset({1, 2, 3}))
    boundary = HostedBoundary(TuppiASGIApp(rooms), origins={ORIGIN}, max_bot_rooms=8)
    sent = []
    async def send(message): sent.append(json.loads(message["text"]))
    connection = Connection(room.code, host.token, 0, send)
    boundary.game._connections[room.code] = {host.token: connection}
    room.ai_action_delay_ms = 0
    return rooms, room, host, boundary, connection, sent


async def submit(boundary, connection, room, client_action_id):
    runner = room.runner
    options = runner.bidding(0)["options"] if runner.collecting_bids() else runner.observation(0)["legal_actions"]
    await boundary.game._handle_message(connection, {"message_type": "action_submission", "payload": {
        "action": options[0], "client_action_id": client_action_id,
        "expected_event_index": runner.event_cursor, "match_ref": runner.match_ref}})


def test_a_failed_save_is_never_acknowledged_and_stops_changes(tmp_path, monkeypatch):
    async def scenario():
        rooms, room, host, boundary, connection, sent = started_room(tmp_path)
        await boundary.game._handle_message(connection, {"message_type": "ready", "payload": {"session_token": host.token}})
        await asyncio.gather(*boundary.game._ai_tasks.values())
        durable_cursor = room.runner.event_cursor
        def full_disk(path, value):
            raise SerializationError(f"cannot write output bundle: [Errno 28] No space left on device: '{path}'")
        monkeypatch.setattr(persistence, "atomic_write_canonical_json", full_disk)
        before = len(sent)
        with pytest.raises(PersistenceError) as raised:
            await submit(boundary, connection, room, "move-on-full-disk")
        assert str(tmp_path) not in str(raised.value), "no private path in the error"
        assert not [m for m in sent[before:] if m["message_type"] == "action_acknowledgement"], "never acknowledged"
        assert rooms.storage_failed and boundary.storage_state() == "failed"
        status, body = await http(boundary, "/healthz", method="GET")
        assert status == 503 and body["status"] == "storage_failed"
        status, body = await http(boundary, "/v1/rooms", {"display_name": "Late", "ai_seats": []})
        assert status == 503 and body["error"] == "storage_unavailable"
        with pytest.raises(RoomError, match="storage_unavailable"):
            await boundary.game._handle_message(connection, {"message_type": "reconnect",
                                                             "payload": {"last_applied_event_index": -1}})
        # A restart recovers the last durable state; the same move is then applied once.
        monkeypatch.undo()
        match_runner.REVEAL_PAUSE_SECONDS = match_runner.REVEAL_STEP_SECONDS = 0
        recovered = manager(tmp_path).get(room.code)
        assert recovered.runner.event_cursor == durable_cursor and not manager(tmp_path).storage_failed
        action = action_from_data(recovered.runner.bidding(0)["options"][0] if recovered.runner.collecting_bids()
                                  else recovered.runner.observation(0)["legal_actions"][0])
        retried = recovered.runner.submit(seat=0, client_action_id="move-on-full-disk", match_ref=recovered.runner.match_ref,
                                          expected_event_index=recovered.runner.event_cursor, action=action)
        assert retried["status"] == "accepted", "the unacknowledged move is applied once after recovery"
    asyncio.run(scenario())


def test_a_failed_save_closes_the_socket_cleanly(tmp_path, monkeypatch):
    async def scenario():
        rooms = manager(tmp_path)
        boundary = HostedBoundary(TuppiASGIApp(rooms), origins={ORIGIN})
        async def failing(self, scope, receive, send):
            raise PersistenceError("cannot persist room ABC123")
        monkeypatch.setattr(TuppiASGIApp, "__call__", failing)
        sent = []
        async def send(message): sent.append(message)
        async def receive(): return {"type": "websocket.connect"}
        await boundary({"type": "websocket", "path": "/v1/ws", "headers": []}, receive, send)
        assert sent[-1] == {"type": "websocket.close", "code": 1011} and boundary.connections == 0
    asyncio.run(scenario())


def test_startup_removes_half_written_records_and_a_copy_restores_the_games(tmp_path):
    async def scenario():
        rooms, room, host, boundary, connection, sent = started_room(tmp_path / "live")
        await boundary.game._handle_message(connection, {"message_type": "ready", "payload": {"session_token": host.token}})
        await asyncio.gather(*boundary.game._ai_tasks.values())
        for move in range(6):
            await submit(boundary, connection, room, f"m{move}")
        snapshot = tmp_path / "snapshot"
        shutil.copytree(tmp_path / "live", snapshot)
        stray = snapshot / f".room-{room.code}.json.k3j2.tmp"
        stray.write_text('{"half": ')
        (snapshot / "expired").mkdir(exist_ok=True)
        (snapshot / "expired" / "room-OLD000-1.json").write_text("{}")
        restored = manager(snapshot).get(room.code)
        assert not stray.exists(), "a half-written record is removed at startup"
        for seat in range(4):
            assert restored.runner.observation(seat) == room.runner.observation(seat)
        assert restored.runner.reconnect(seat=0, last_applied_event_index=-1) == room.runner.reconnect(
            seat=0, last_applied_event_index=-1)
        # Both continue identically from the restored point.
        action = action_from_data((room.runner.bidding(0)["options"] if room.runner.collecting_bids()
                                   else room.runner.observation(0)["legal_actions"])[0])
        results = [r.runner.submit(seat=0, client_action_id="next", match_ref=r.runner.match_ref,
                                   expected_event_index=r.runner.event_cursor, action=action) for r in (room, restored)]
        assert results[0]["accepted_event_indices"] == results[1]["accepted_event_indices"]
    asyncio.run(scenario())


def test_archive_is_pruned_by_age_then_size(tmp_path):
    store = FileRoomStore(tmp_path)
    archive = tmp_path / "expired"
    archive.mkdir(parents=True)
    now = time.time()
    for name, age_days, size in [("room-AAAAAA-1.json", 40, 10), ("room-BBBBBB-2.json", 5, 600),
                                 ("room-CCCCCC-3.json", 3, 600), ("room-DDDDDD-4.json", 1, 600)]:
        path = archive / name
        path.write_bytes(b"x" * size)
        os.utime(path, (now - age_days * 86400, now - age_days * 86400))
    result = store.prune_archive(max_age_days=30, max_bytes=1300)
    assert sorted(p.name for p in archive.iterdir()) == ["room-CCCCCC-3.json", "room-DDDDDD-4.json"]
    assert result == {"removed": 2, "kept": 2, "bytes": 1200}


def test_low_disk_refuses_new_rooms_but_games_continue(tmp_path, monkeypatch):
    async def scenario():
        rooms = manager(tmp_path)
        room, _ = rooms.create_room(display_name="Existing", ai_seats=frozenset({1, 3}))
        boundary = HostedBoundary(TuppiASGIApp(rooms), origins={ORIGIN}, min_free_bytes=50 * 2**20)
        monkeypatch.setattr(FileRoomStore, "free_bytes", lambda self: 10 * 2**20)
        status, body = await http(boundary, "/healthz", method="GET")
        assert status == 200 and body["storage"] == "low"
        status, body = await http(boundary, "/v1/rooms", {"display_name": "New", "ai_seats": []})
        assert status == 503 and body["error"] == "storage_low"
        status, body = await http(boundary, f"/v1/rooms/{room.code}/join", {"display_name": "Friend"})
        assert status == 200, "existing rooms keep working"
    asyncio.run(scenario())


def test_maintenance_archives_idle_rooms_and_prunes(tmp_path):
    rooms = manager(tmp_path)
    room, _ = rooms.create_room(display_name="Idle", ai_seats=frozenset({1, 2, 3}))
    boundary = HostedBoundary(TuppiASGIApp(rooms), origins={ORIGIN}, archive_days=30, archive_max_bytes=2**20)
    boundary.activity[room.code] = time.time() - 2 * 86400
    old = tmp_path / "expired" / "room-ZZZZZZ-1.json"
    old.parent.mkdir(exist_ok=True)
    old.write_text("{}")
    os.utime(old, (time.time() - 90 * 86400,) * 2)
    result = boundary.maintain()
    assert room.code not in rooms._rooms and not old.exists()
    assert result["kept"] == 1 and len(list((tmp_path / "expired").glob(f"room-{room.code}-*.json"))) == 1


def test_storage_limits_are_validated(monkeypatch):
    for key in ("TUPPI_ARCHIVE_DAYS", "TUPPI_ARCHIVE_MAX_MB", "TUPPI_MIN_FREE_MB"):
        monkeypatch.delenv(key, raising=False)
    assert storage_limits_from_environment() == {"archive_days": 30, "archive_max_bytes": 200 * 2**20,
                                                 "min_free_bytes": 50 * 2**20}
    monkeypatch.setenv("TUPPI_ARCHIVE_DAYS", "0")
    with pytest.raises(ValueError):
        storage_limits_from_environment()
    monkeypatch.setenv("TUPPI_ARCHIVE_DAYS", "many")
    with pytest.raises(ValueError):
        storage_limits_from_environment()
