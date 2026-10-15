"""Host pause/resume and same-group rematch in private rooms (BE-01)."""
from __future__ import annotations

import asyncio
import json

import pytest
from tuppi_rules import RulesetId
from tuppi_server import match_runner
from tuppi_server.app import Connection, TuppiASGIApp
from tuppi_server.persistence import PersistenceError
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_ui_fixtures.validation import validate_instance

WS_SCHEMA = "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"

V3 = RulesetId.PROJECT_TARGET_V3


@pytest.fixture(autouse=True)
def unpaced(monkeypatch):
    monkeypatch.setattr(match_runner, "REVEAL_PAUSE_SECONDS", 0)
    monkeypatch.setattr(match_runner, "REVEAL_STEP_SECONDS", 0)


def validate(message):
    """The fixture bot's profile is not a protocol profile; validate the rest."""
    text = json.dumps(message).replace(f'"{TEST_AI_PROFILE_KEY}"', '"tuppi_ai_search_v1"')
    validate_instance(json.loads(text), WS_SCHEMA)


def manager(path):
    return RoomManager(path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)


class Table:
    """One room driven through the WebSocket handler, as the server does."""

    def __init__(self, rooms, room, sessions):
        self.rooms, self.room, self.app = rooms, room, TuppiASGIApp(rooms)
        self.sent = {s.seat: [] for s in sessions}
        self.connections, self.checked = {}, {}
        for session in sessions:
            async def send(message, seat=session.seat):
                self.sent[seat].append(json.loads(message["text"]))
            self.connections[session.seat] = Connection(room.code, session.token, session.seat, send)
        self.app._connections[room.code] = {c.token: c for c in self.connections.values()}
        room.ai_action_delay_ms = 0

    async def send(self, seat, message_type, payload=None):
        request = {"message_type": message_type, "payload": payload or {}}
        validate_instance(request, WS_SCHEMA)
        await self.app._handle_message(self.connections[seat], request)
        await self.settle()
        for messages in self.sent.values():  # every server message keeps the protocol schema
            for message in messages[self.checked.get(id(messages), 0):]:
                validate(message)
            self.checked[id(messages)] = len(messages)

    async def settle(self):
        while tasks := [t for t in self.app._ai_tasks.values() if not t.done()]:
            await asyncio.gather(*tasks)

    def options(self, seat):
        runner = self.room.runner
        if runner.collecting_bids():
            return runner.bidding(seat)["options"]
        return runner.observation(seat)["legal_actions"]

    async def move(self, seat, client_action_id):
        runner = self.room.runner
        await self.send(seat, "action_submission", {"action": self.options(seat)[0],
            "client_action_id": client_action_id, "expected_event_index": runner.event_cursor,
            "match_ref": runner.match_ref})
        return next(m["payload"] for m in reversed(self.sent[seat])
                    if m["message_type"] == "action_acknowledgement")

    async def start(self):
        for seat, connection in self.connections.items():
            await self.send(seat, "ready", {"session_token": connection.token})

    async def finish(self):
        runner, moves = self.room.runner, 0
        while not runner.terminal:
            seat = next(s for s in self.connections if self.options(s))
            ack = await self.move(seat, f"m{runner.match_ref}-{moves}")
            assert ack["status"] == "accepted"
            moves += 1

    def lobby(self, seat=0):
        return next(m["payload"] for m in reversed(self.sent[seat]) if m["message_type"] == "lobby_snapshot")


@pytest.fixture
def near_the_end(monkeypatch):
    """Short, repeatable matches: rooms start at 51-0 and deals come from a seed."""
    import random
    from tuppi_rules import MatchScore
    from tuppi_server import deal_generation, rooms as rooms_module

    class NearEnd(match_runner.LiveMatchRunner):
        def __init__(self, **kwargs):
            kwargs.setdefault("initial_score", MatchScore(51, 0))
            super().__init__(**kwargs)
    source = random.Random(20261015)
    monkeypatch.setattr(rooms_module, "LiveMatchRunner", NearEnd)
    monkeypatch.setattr(match_runner, "generate_live_deal",
                        lambda *, dealer: deal_generation.generate_live_deal(dealer=dealer, rng=source))


def test_rematch_keeps_the_room_and_result_and_starts_a_new_match(tmp_path, near_the_end):
    async def scenario():
        rooms = manager(tmp_path)
        room, host = rooms.create_room(display_name="Host", ai_seats=frozenset({1, 2, 3}))
        table = Table(rooms, room, [host])
        await table.start()
        first = room.runner
        with pytest.raises(RoomError, match="match_not_complete"):
            rooms.start_rematch(code=room.code, host_token=host.token)
        await table.finish()
        record = json.loads((tmp_path / f"room-{room.code}.json").read_text())
        assert record["schema_version"] == "tuppi.server.room_record.v3", "single-match rooms keep the old format"
        with pytest.raises(RoomError, match="host_required"):
            rooms.start_rematch(code=room.code, host_token="not-the-host")
        (tmp_path / f"deal-analysis-{room.code}-0-0.json").write_text("{}")
        final_score = first.observation(0)["match_score"]
        assert table.connections[0].last_event_index == first.event_cursor
        await table.send(0, "rematch")

        assert room.runner is None and room.match_index == 1 and room.ai_seats == {1, 2, 3}
        lobby = table.lobby()
        assert lobby["lifecycle"] == "configured" and lobby["match_number"] == 2
        assert [s["ready"] for s in lobby["seats"] if s["kind"] == "human"] == [False]
        summary = lobby["previous_matches"]
        assert len(summary) == 1 and summary[0]["match_ref"] == first.match_ref
        assert summary[0]["deals"] == len(first.state.completed_deals)
        assert summary[0]["final_score"] == final_score and summary[0]["winner_team"] in (0, 1)
        assert table.connections[0].last_event_index == -1, "the next match's events start again"
        assert not list(tmp_path.glob(f"deal-analysis-{room.code}-*.json"))

        # A restart restores the reopened room, then the same seats play again.
        restored = manager(tmp_path).get(room.code)
        assert restored.runner is None and restored.match_index == 1
        assert restored.previous_matches == room.previous_matches
        await table.start()
        second = room.runner
        assert second.match_ref == f"{first.match_ref}-2" and second.event_cursor >= 0
        assert not set(map(id, second._ai_agents.values())) & set(map(id, first._ai_agents.values()))
        record = json.loads((tmp_path / f"room-{room.code}.json").read_text())
        assert record["schema_version"] == "tuppi.server.room_record.v4"
        assert manager(tmp_path).get(room.code).runner.match_ref == second.match_ref
        update = next(m["payload"] for m in table.sent[0]
                      if m["message_type"] == "match_update" and m["payload"]["match_ref"] == second.match_ref)
        assert update["event_batch"][0]["event_index"] == 0, "seats receive the new match from its start"
    asyncio.run(scenario())


def test_pause_stops_bots_and_moves_and_keeps_a_locked_bid(tmp_path):
    async def scenario():
        rooms = manager(tmp_path)
        room, host = rooms.create_room(display_name="Host", ai_seats=frozenset({1, 3}))
        _, guest = rooms.join_room(code=room.code, display_name="Guest")
        table = Table(rooms, room, [host, guest])
        await table.start()
        runner = room.runner
        assert runner.collecting_bids()
        ack = await table.move(0, "host-bid")
        assert ack["status"] == "accepted" and runner.collecting_bids()
        host_bid = runner.bidding(0)["own_bid"]

        with pytest.raises(RoomError, match="host_required"):
            rooms.set_paused(code=room.code, host_token=guest.token, paused=True)
        await table.send(0, "pause")
        assert room.paused and table.lobby(2)["paused"] is True
        cursor = runner.event_cursor
        ack = await table.move(2, "guest-bid-while-paused")
        assert ack["status"] == "rejected" and ack["code"] == "paused"
        assert runner.event_cursor == cursor and 2 not in runner._locked_bids
        assert runner.bidding(0)["own_bid"] == host_bid, "the locked bid is kept"
        table.app._schedule_ai_continuation(room.code)
        await table.settle()
        assert runner.event_cursor == cursor, "no bot moves while paused"
        restored = manager(tmp_path).get(room.code)
        assert restored.paused and json.loads((tmp_path / f"room-{room.code}.json").read_text())["paused"]

        await table.send(0, "resume")
        assert not room.paused and "paused" not in table.lobby(2)
        ack = await table.move(2, "guest-bid")
        assert ack["status"] == "accepted"
        assert not runner.collecting_bids()
        # Applied in seat order, or discarded unseen after an earlier RAMI.
        assert "host-bid" in runner._records or "host-bid" in runner._discarded_bid_acks
        shown = {a["seat"]: a for a in runner.observation(0)["show_actions"]}
        if 0 in shown:
            assert shown[0]["shown_card"] == host_bid["shown_card"]
    asyncio.run(scenario())


def test_pause_at_a_completed_deal_holds_the_next_deal():
    from tuppi_server.match_runner import LiveMatchRunner
    async def scenario():
        runner = LiveMatchRunner(match_ref="pause-deal-boundary", ruleset_id=V3, ai_seats=frozenset({1, 2, 3}),
                                 ai_profile_key=TEST_AI_PROFILE_KEY, auto_run_ai=False)
        paused = {"value": False}
        async def boundary():  # the host's pause lands once the deal is complete
            if runner.state.phase.value == "DEAL_COMPLETE":
                paused["value"] = True
        moves = 0
        while not paused["value"]:
            options = (runner.bidding(0)["options"] if runner.collecting_bids()
                       else runner.observation(0)["legal_actions"])
            from tuppi_engine import action_from_data
            await runner.submit_async(seat=0, client_action_id=f"m{moves}", match_ref=runner.match_ref,
                expected_event_index=runner.event_cursor, action=action_from_data(options[0]),
                on_human_action=boundary, on_state_change=boundary, ai_action_delay_seconds=0,
                paused=lambda: paused["value"])
            moves += 1
        assert runner.state.phase.value == "DEAL_COMPLETE" and len(runner.state.completed_deals) == 1
        cursor = runner.event_cursor
        await runner.run_ai_async(ai_action_delay_seconds=0, paused=lambda: True)
        assert runner.event_cursor == cursor and runner.state.phase.value == "DEAL_COMPLETE"
        await runner.run_ai_async(ai_action_delay_seconds=0, paused=lambda: False)
        assert runner.event_cursor > cursor and runner.collecting_bids(), "resume starts the next deal"
    asyncio.run(scenario())


def test_pause_and_rematch_need_the_right_match_state(tmp_path):
    rooms = manager(tmp_path)
    room, host = rooms.create_room(display_name="Host", ai_seats=frozenset({1, 2, 3}))
    with pytest.raises(RoomError, match="match_not_active"):
        rooms.set_paused(code=room.code, host_token=host.token, paused=True)
    with pytest.raises(RoomError, match="match_not_complete"):
        rooms.start_rematch(code=room.code, host_token=host.token)
    # A stored pause without a match in progress is rejected at load.
    room.paused = True
    rooms.persist(room)
    with pytest.raises(PersistenceError, match="pause"):
        manager(tmp_path)


def test_hello_acknowledgement_lists_the_optional_commands(tmp_path):
    async def scenario():
        rooms = manager(tmp_path)
        room, host = rooms.create_room(display_name="Host", ai_seats=frozenset({1, 2, 3}))
        app, sent = TuppiASGIApp(rooms), []
        async def send(message): sent.append(json.loads(message["text"]))
        await app._authenticate({"message_type": "hello", "payload": {"protocol_version": "tuppi.network.v1",
            "room_code": room.code, "session_token": host.token}}, send)
        assert sent[0]["message_type"] == "hello_ack" and sent[0]["payload"]["features"] == ["pause", "rematch", "leaderboard", "compact_results"]
        for message in sent:
            validate(message)
    asyncio.run(scenario())


def test_compatibility_lists_the_optional_commands():
    async def scenario():
        app = TuppiASGIApp(RoomManager())
        sent = []
        async def send(message): sent.append(message)
        async def receive(): return {"type": "http.request", "body": b""}
        await app({"type": "http", "method": "GET", "path": "/v1/compatibility"}, receive, send)
        assert json.loads(sent[1]["body"])["features"] == ["pause", "rematch", "leaderboard", "compact_results"]
    asyncio.run(scenario())
