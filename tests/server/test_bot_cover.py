"""A bot plays for a player who is away during a match (owner request 2026-10-16).

The host lets a bot take a disconnected player's seat; the player keeps their
seat and session and takes it back (or the host does). A bid the player
locked before the bot took over stands; a covered player's own moves are
refused; restarts keep the stand-in; a rematch gives the seat back.
"""
from __future__ import annotations

import asyncio

from tuppi_server.rooms import RoomManager
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY

from .test_concede import V3, Table, setup


def lobby(table, seat_index):
    return [m["payload"] for m in table.sent[seat_index] if m["message_type"] == "lobby_snapshot"][-1]


def test_host_covers_an_absent_player_who_later_takes_the_seat_back(tmp_path, monkeypatch):
    setup(monkeypatch, score=(0, 0), seed=11)

    async def scenario():
        table = Table(tmp_path)
        for seat, connection in table.connections.items():
            await table.send(seat, "ready", {"session_token": connection.token})
        runner, room = table.room.runner, table.room
        # The guest (seat 2) locks a bid, then leaves before the host bids.
        options = runner.bidding(2)["options"]
        await table.send(2, "action_submission", {"action": options[-1], "client_action_id": "guest-bid",
                         "expected_event_index": runner.event_cursor, "match_ref": runner.match_ref})
        locked = options[-1]
        guest = table.app._connections[room.code].pop(table.guest.token)
        assert table.app._lobby(room)["seats"][2]["connected"] is False
        assert table.app._lobby(room)["seats"][0]["connected"] is True

        # Only the host may cover, and only a player who is away.
        table.app._connections[room.code][table.guest.token] = guest
        await table.send(0, "seat_bot", {"seat": 2, "bot": True})
        assert 2 not in room.ai_seats and lobby(table, 0)["seats"][2]["kind"] == "human", "the player is connected"
        await table.send(2, "seat_bot", {"seat": 1, "bot": True})
        assert lobby(table, 2)["seats"][1].get("covering") is None, "a seat that was a bot from the start"
        table.app._connections[room.code].pop(table.guest.token)

        await table.send(0, "seat_bot", {"seat": 2, "bot": True})
        assert 2 in room.ai_seats and 2 in runner.ai_seats
        seat = lobby(table, 0)["seats"][2]
        assert seat["kind"] == "ai" and seat["covering"] == "Aino" and seat["connected"] is False
        # The host bids; showing resolves with the guest's locked bid standing.
        await table.send(0, "action_submission", {"action": runner.bidding(0)["options"][0], "client_action_id": "host-bid",
                         "expected_event_index": runner.event_cursor, "match_ref": runner.match_ref})
        shows = {show["seat"]: show for show in runner.observation(0)["show_actions"]}
        if 2 in shows:
            assert shows[2]["shown_card"] == locked["shown_card"], "the player's locked bid stands"
        # The bot plays seat 2: from now on only the host's turns wait for a person.
        # (During locked bidding the engine's next bidder may be seat 2 while
        # the server waits for the host's bid; that is not seat 2 waiting.)
        waiting_at_2 = lambda: runner.current_actor == 2 and not runner.collecting_bids() and not runner.terminal
        for _ in range(40):
            assert not waiting_at_2(), "the bot does not wait at seat 2"
            if runner.terminal:
                break
            await table.move()

        # Restarts keep the stand-in.
        restored = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY).get(room.code)
        assert 2 in restored.ai_seats and 2 in restored.runner.ai_seats
        assert restored.snapshot()["seats"][2]["covering"] == "Aino"

        # The guest returns; their own move is refused while covered, then they take the seat back.
        table.app._connections[room.code][table.guest.token] = guest
        assert table.app._lobby(room)["seats"][2]["connected"] is True
        await table.send(2, "seat_bot", {"seat": 2, "bot": False})
        assert 2 not in room.ai_seats and 2 not in runner.ai_seats
        assert lobby(table, 2)["seats"][2]["kind"] == "human" and "covering" not in lobby(table, 2)["seats"][2]
        # The guest's seat waits for the guest again.
        for _ in range(80):
            if runner.current_actor == 2 or runner.terminal or runner.collecting_bids():
                break
            await table.move()
        assert runner.current_actor == 2 or runner.collecting_bids() or runner.terminal
    asyncio.run(scenario())


def test_a_covered_players_moves_are_refused_and_a_rematch_gives_the_seat_back(tmp_path, monkeypatch):
    setup(monkeypatch, score=(48, 0), seed=3)

    async def scenario():
        table = Table(tmp_path)
        for seat, connection in table.connections.items():
            await table.send(seat, "ready", {"session_token": connection.token})
        runner, room = table.room.runner, table.room
        guest = table.app._connections[room.code].pop(table.guest.token)
        await table.send(0, "seat_bot", {"seat": 2, "bot": True})
        assert 2 in runner.ai_seats
        table.app._connections[room.code][table.guest.token] = guest
        before = runner.event_cursor
        await table.send(2, "action_submission", {"action": {"type": "show", "seat": 2, "shown_card": "2H",
                         "declared_contract": "NOLO"}, "client_action_id": "covered", "expected_event_index": before,
                         "match_ref": runner.match_ref})
        ack = [m for m in table.sent[2] if m["message_type"] == "action_acknowledgement"][-1]["payload"]
        assert ack["status"] == "rejected" and ack["code"] == "ai_seat"
        # Play out with the bot at seat 2; the covered player is not credited.
        for _ in range(3000):
            if runner.terminal:
                break
            await table.move()
        assert runner.terminal
        names = {entry["name"] for entry in table.rooms.leaderboard.standings()}
        assert "Pyry" in names and "Aino" not in names, "the bot played the match out, not Aino"
        await table.send(0, "rematch")
        assert 2 not in room.ai_seats and room.snapshot()["seats"][2]["kind"] == "human", "the seat returns"
    asyncio.run(scenario())
