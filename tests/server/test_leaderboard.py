"""Per-nickname leaderboard and compact end-of-match updates."""
from __future__ import annotations

import asyncio
import json
import random

import pytest
from tuppi_rules import MatchScore, RulesetId
from tuppi_server import deal_generation, match_runner, rooms as rooms_module
from tuppi_server.app import Connection, TuppiASGIApp
from tuppi_server.hosted import HostedBoundary
from tuppi_server.leaderboard import Leaderboard, name_key
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_server.persistence import PersistenceError
from tuppi_server.rooms import RoomManager
from tuppi_ui_fixtures.validation import validate_instance

V3 = RulesetId.PROJECT_TARGET_V3
WS_SCHEMA = "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"
HTTP_SCHEMA = "https://example.invalid/tuppi/schemas/network/http_api.schema.json"


@pytest.fixture(autouse=True)
def short_matches(monkeypatch):
    """Unpaced, seeded, starting at 51-0 so a whole match is a few deals."""
    monkeypatch.setattr(match_runner, "REVEAL_PAUSE_SECONDS", 0)
    monkeypatch.setattr(match_runner, "REVEAL_STEP_SECONDS", 0)

    class NearEnd(match_runner.LiveMatchRunner):
        def __init__(self, **kwargs):
            kwargs.setdefault("initial_score", MatchScore(51, 0))
            super().__init__(**kwargs)
    source = random.Random(20261016)
    monkeypatch.setattr(rooms_module, "LiveMatchRunner", NearEnd)
    monkeypatch.setattr(match_runner, "generate_live_deal",
                        lambda *, dealer: deal_generation.generate_live_deal(dealer=dealer, rng=source))


def test_counting_rules_and_order(tmp_path):
    board = Leaderboard(tmp_path / "leaderboard.json")
    assert board.record(match_key="m1", seats={0: "Pyry", 2: "Aino"}, winner_team=0)
    assert not board.record(match_key="m1", seats={0: "Pyry", 2: "Aino"}, winner_team=0), "counted once"
    assert board.record(match_key="m2", seats={0: " pyry ", 1: "Leevi"}, winner_team=1)
    assert board.record(match_key="m3", seats={0: "Leevi", 1: "Aino"}, winner_team=0)
    assert board.record(match_key="m4", seats={0: "Pelaaja", 1: "pelaaja", 2: "Aino"}, winner_team=0)
    assert not board.record(match_key="bots-only", seats={}, winner_team=0)
    standings = {e["name"]: e for e in board.standings()}
    assert standings["pyry"] == {"losses": 1, "matches": 2, "name": "pyry", "wins": 1, "win_percent": 50}, \
        "case and spaces are one name; the latest spelling is shown"
    assert (standings["Aino"]["wins"], standings["Aino"]["losses"]) == (2, 1)
    assert (standings["Leevi"]["wins"], standings["Leevi"]["losses"]) == (2, 0)
    assert "Pelaaja" not in standings, "a name on both teams is not credited"
    assert [e["name"] for e in board.standings()][:2] == ["Leevi", "Aino"], "wins, then win rate"
    restored = Leaderboard(tmp_path / "leaderboard.json")
    assert restored.standings() == board.standings() and restored.counted == board.counted
    assert name_key("  Pyry   Ouri ") == "pyry ouri"


def test_damaged_leaderboard_file_is_refused(tmp_path):
    path = tmp_path / "leaderboard.json"
    path.write_text('{"schema_version": "tuppi.server.leaderboard.v1", "players": {"x": {}}, "counted": []}')
    with pytest.raises(PersistenceError):
        Leaderboard(path)


class Room:
    """Host and friend as partners against two bots, driven through the server."""

    def __init__(self, path):
        self.rooms = RoomManager(path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
        self.room, self.host = self.rooms.create_room(display_name="Pyry", ai_seats=frozenset({1, 3}))
        _, self.guest = self.rooms.join_room(code=self.room.code, display_name="Aino")
        self.room.ai_action_delay_ms = 0
        self.boundary = HostedBoundary(TuppiASGIApp(self.rooms), origins={"https://tuppi.example"}, max_bot_rooms=8)
        self.app = self.boundary.game
        self.sent = {0: [], 2: []}
        self.connections = {}
        for session in (self.host, self.guest):
            async def send(message, seat=session.seat):
                self.sent[seat].append(json.loads(message["text"]))
            self.connections[session.seat] = Connection(self.room.code, session.token, session.seat, send)
        self.app._connections[self.room.code] = {c.token: c for c in self.connections.values()}

    async def send(self, seat, message_type, payload=None):
        request = {"message_type": message_type, "payload": payload or {}}
        validate_instance(request, WS_SCHEMA)
        await self.app._handle_message(self.connections[seat], request)
        while tasks := [t for t in self.app._ai_tasks.values() if not t.done()]:
            await asyncio.gather(*tasks)

    async def play_out(self):
        for seat, connection in self.connections.items():
            await self.send(seat, "ready", {"session_token": connection.token})
        runner, n = self.room.runner, 0
        while not runner.terminal:
            seat = next(s for s in (0, 2) if (runner.bidding(s)["options"] if runner.collecting_bids()
                                              else runner.observation(s)["legal_actions"]))
            options = runner.bidding(seat)["options"] if runner.collecting_bids() else runner.observation(seat)["legal_actions"]
            await self.send(seat, "action_submission", {"action": options[0], "client_action_id": f"a{n}",
                "expected_event_index": runner.event_cursor, "match_ref": runner.match_ref})
            n += 1

    async def leaderboard(self, token):
        out = []
        async def receive():
            return {"type": "http.request", "body": json.dumps({"session_token": token}).encode(), "more_body": False}
        async def send(message): out.append(message)
        await self.boundary({"type": "http", "method": "POST", "path": f"/v1/rooms/{self.room.code}/leaderboard",
                             "headers": []}, receive, send)
        return out[0]["status"], json.loads(out[1]["body"])


def test_a_finished_room_match_is_credited_once_and_served_to_seat_holders(tmp_path):
    async def scenario():
        table = Room(tmp_path)
        await table.send(2, "client_options", {"omit_match_result": True})
        await table.play_out()
        runner = table.room.runner
        winners = runner.observation(0)["match_score"]
        won = winners[0] > winners[1]
        status, body = await table.leaderboard(table.guest.token)
        assert status == 200
        validate_instance(body, f"{HTTP_SCHEMA}#/$defs/leaderboardResult")
        entries = {e["name"]: e for e in body["entries"]}
        assert set(entries) == {"Pyry", "Aino"} and entries["Pyry"]["wins"] == int(won) == entries["Aino"]["wins"]
        assert entries["Pyry"]["matches"] == 1, "two terminal broadcasts still count one match"
        status, body = await table.leaderboard("not-a-seat-token")
        assert status == 404, "only seat holders see names"
        # Compact results: only the opted-in connection omits the full match result.
        host_final = [m for m in table.sent[0] if m["message_type"] == "match_update" and "match_result" in m["payload"]]
        guest_final = [m for m in table.sent[2] if m["message_type"] == "match_update" and "match_result" in m["payload"]]
        assert host_final and not guest_final
        await table.send(2, "reconnect", {"last_applied_event_index": -1})
        result = table.sent[2][-1]
        assert result["message_type"] == "reconnect_result" and "match_result" not in result["payload"]
        for message in table.sent[2]:
            validate_instance(json.loads(json.dumps(message).replace(TEST_AI_PROFILE_KEY, "tuppi_ai_search_v1")), WS_SCHEMA)
        # A restart keeps the standings and does not count the match again.
        again = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
        assert again.leaderboard.standings() == table.rooms.leaderboard.standings()
        # A rematch is a new match.
        await table.send(0, "rematch")
        await table.play_out()
        assert {e["name"]: e["matches"] for e in table.rooms.leaderboard.standings()} == {"Pyry": 2, "Aino": 2}
    asyncio.run(scenario())


def test_startup_credits_a_match_that_finished_just_before_a_crash(tmp_path):
    async def scenario():
        table = Room(tmp_path)
        await table.play_out()
        (tmp_path / "leaderboard.json").unlink()  # the crash came before the leaderboard save
        restarted = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
        assert {e["name"] for e in restarted.leaderboard.standings()} == {"Pyry", "Aino"}
    asyncio.run(scenario())


def test_client_options_are_validated(tmp_path):
    async def scenario():
        table = Room(tmp_path)
        from tuppi_server.app import ProtocolError
        with pytest.raises(ProtocolError):
            await table.app._handle_message(table.connections[0], {"message_type": "client_options",
                                                                   "payload": {"omit_match_result": "yes"}})
    asyncio.run(scenario())
