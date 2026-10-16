"""Conceding a deal whose result is already 0-0 (owner request 2026-10-16).

In the rising score, a deal won by the team behind resets the match to 0-0.
Once that is certain (NOLO: the team ahead has 7 tricks; RAMI: the team
behind has 7), any player may concede: the remaining cards are played at
once and the deal is marked as conceded in the history.
"""
from __future__ import annotations

import asyncio
import json
import random

from tuppi_rules import MatchScore, RulesetId
from tuppi_server import deal_generation, match_runner, rooms as rooms_module
from tuppi_server.app import Connection, TuppiASGIApp
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_server.rooms import RoomManager
from tuppi_ui_fixtures.validation import validate_instance

V3 = RulesetId.PROJECT_TARGET_V3
WS_SCHEMA = "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"


def setup(monkeypatch, score=(20, 0), seed=7):
    monkeypatch.setattr(match_runner, "REVEAL_PAUSE_SECONDS", 0)
    monkeypatch.setattr(match_runner, "REVEAL_STEP_SECONDS", 0)

    class Ahead(match_runner.LiveMatchRunner):
        def __init__(self, **kwargs):
            kwargs.setdefault("initial_score", MatchScore(*score))
            super().__init__(**kwargs)
    source = random.Random(seed)
    monkeypatch.setattr(rooms_module, "LiveMatchRunner", Ahead)
    monkeypatch.setattr(match_runner, "generate_live_deal",
                        lambda *, dealer: deal_generation.generate_live_deal(dealer=dealer, rng=source))


class Table:
    def __init__(self, path):
        self.rooms = RoomManager(path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
        self.room, self.host = self.rooms.create_room(display_name="Pyry", ai_seats=frozenset({1, 3}))
        _, self.guest = self.rooms.join_room(code=self.room.code, display_name="Aino")
        self.room.ai_action_delay_ms = 0
        self.app = TuppiASGIApp(self.rooms)
        self.sent = {0: [], 2: []}
        self.connections = {}
        for session in (self.host, self.guest):
            async def send(message, seat=session.seat):
                self.sent[seat].append(json.loads(message["text"]))
            self.connections[session.seat] = Connection(self.room.code, session.token, session.seat, send)
        self.app._connections[self.room.code] = {c.token: c for c in self.connections.values()}
        self.moves = 0

    async def send(self, seat, message_type, payload=None):
        request = {"message_type": message_type, "payload": payload or {}}
        validate_instance(request, WS_SCHEMA)
        await self.app._handle_message(self.connections[seat], request)
        while tasks := [t for t in self.app._ai_tasks.values() if not t.done()]:
            await asyncio.gather(*tasks)

    async def move(self):
        runner = self.room.runner
        seat = next(s for s in (0, 2) if (runner.bidding(s)["options"] if runner.collecting_bids()
                                          else runner.observation(s)["legal_actions"]))
        options = runner.bidding(seat)["options"] if runner.collecting_bids() else runner.observation(seat)["legal_actions"]
        await self.send(seat, "action_submission", {"action": options[0], "client_action_id": f"m{self.moves}",
                        "expected_event_index": runner.event_cursor, "match_ref": runner.match_ref})
        self.moves += 1

    async def until_concession(self, limit=3000):
        for _ in range(limit):
            if self.room.runner.concede_available():
                return True
            if self.room.runner.terminal:
                return False
            await self.move()
        return False


def test_a_decided_deal_is_conceded_to_0_0_and_marked(tmp_path, monkeypatch):
    setup(monkeypatch)

    async def scenario():
        table = Table(tmp_path)
        for seat, connection in table.connections.items():
            await table.send(seat, "ready", {"session_token": connection.token})
        runner = table.room.runner
        assert not runner.concede_available(), "showing is never conceded"
        assert await table.until_concession(), "the seeded match reaches a decided deal"
        observation = runner.observation(0)
        deal = len(runner.state.completed_deals)
        tricks = sum(observation["team_tricks"])
        assert observation["match_score"] != [0, 0] and tricks < 13
        before = len(table.sent[2])
        await table.send(2, "concede")
        # The deal finished with every remaining card, the score is 0-0 and it is marked.
        finished = runner.state.completed_deals[deal].public_result
        assert sum(finished.team_tricks) == 13
        assert (finished.score_after.team0, finished.score_after.team1) == (0, 0)
        assert runner.conceded_deals() == [{"after_tricks": tricks, "deal_number": deal, "seat": 2}]
        updates = [m for m in table.sent[0] if m["message_type"] == "match_update"]
        assert updates[-1]["payload"]["conceded_deals"] == runner.conceded_deals()
        for message in table.sent[0] + table.sent[2][before:]:
            validate_instance(json.loads(json.dumps(message).replace(TEST_AI_PROFILE_KEY, "tuppi_ai_search_v1")), WS_SCHEMA)
        # A concession that is no longer available changes nothing.
        cursor = runner.event_cursor
        await table.send(0, "concede")
        assert table.sent[0][-1]["message_type"] == "match_update" and runner.conceded_deals()[0]["deal_number"] == deal
        assert len(runner.conceded_deals()) == 1 and runner.event_cursor >= cursor
        # A restart replays the forced plays exactly and keeps the marker.
        restored = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY).get(table.room.code).runner
        assert restored.conceded_deals() == runner.conceded_deals()
        assert restored.state.public_events == runner.state.public_events
        # Play continues normally into the next deal.
        assert not runner.terminal
        assert runner.state.active_deal.deal_number == deal + 1 and runner.collecting_bids()
        await table.move()  # a locked bid: private until every seat has bid
        assert not runner.concede_available()
    asyncio.run(scenario())


def test_concession_needs_a_lead_and_a_decided_deal(tmp_path, monkeypatch):
    setup(monkeypatch, score=(0, 0))

    async def scenario():
        table = Table(tmp_path)
        for seat, connection in table.connections.items():
            await table.send(seat, "ready", {"session_token": connection.token})
        runner = table.room.runner
        checked = 0
        while not runner.terminal and len(runner.state.completed_deals) < 1:
            observation = runner.observation(0)
            if observation["phase"] == "TRICK_PLAY":
                checked += 1
                assert not runner.concede_available(), "never at 0-0: there is no lead to lose"
            await table.move()
        assert checked > 0
        events = runner.event_cursor
        await table.send(0, "concede")
        assert runner.event_cursor == events and runner.conceded_deals() == []
    asyncio.run(scenario())


def test_the_rule_for_nolo_and_rami():
    from types import SimpleNamespace
    from tuppi_engine.state import EnginePhase
    from tuppi_rules.model import Contract

    def runner(contract, team_tricks, score):
        fake = match_runner.LiveMatchRunner.__new__(match_runner.LiveMatchRunner)
        fake.state = SimpleNamespace(phase=EnginePhase.TRICK_PLAY, active_deal=object(), terminal=False)
        observation = SimpleNamespace(match_score=MatchScore(*score), contract=contract, team_tricks=team_tricks)
        return fake, observation

    cases = [  # contract, tricks (team 0, team 1), score, decided
        (Contract.NOLO, (7, 2), (12, 0), True),    # the team ahead took 7: it loses the NOLO
        (Contract.NOLO, (6, 3), (12, 0), False),
        (Contract.NOLO, (2, 7), (12, 0), False),   # the team behind took 7: it loses; the lead grows
        (Contract.NOLO, (2, 7), (0, 12), True),
        (Contract.RAMI, (2, 7), (12, 0), True),    # the team behind has 7: it wins the RAMI either way
        (Contract.RAMI, (7, 2), (12, 0), False),
        (Contract.RAMI, (3, 6), (12, 0), False),
        (Contract.NOLO, (7, 2), (0, 0), False),    # no lead
    ]
    original = match_runner.match_observation_for
    try:
        for contract, tricks, score, decided in cases:
            fake, observation = runner(contract, tricks, score)
            match_runner.match_observation_for = lambda state, seat, o=observation: o
            assert fake.concede_available() is decided, (contract, tricks, score)
    finally:
        match_runner.match_observation_for = original
