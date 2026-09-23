"""Live server under project_target_v3: simultaneous locked bids, sooli, privacy.

Human seats lock bids at any time during showing; nothing reaches the engine
until every human has locked; then the bids are taken in seat order (AI seats
bid blind at their turn) and the ones after the first RAMI are discarded
unseen, never sent and never stored. Every wire payload is checked against
the network schemas and against the other seats' bids.
"""

from __future__ import annotations

import json
import random

from tuppi_engine import EnginePhase, action_from_data
from tuppi_rules import RulesetId
from tuppi_server import LiveMatchRunner
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_server.rooms import RoomManager
from tuppi_ui_fixtures.validation import validate_instance

V3 = RulesetId.PROJECT_TARGET_V3
WS = "https://example.invalid/tuppi/schemas/network/websocket_message.schema.json"


def _runner(ai_seats=(1, 3), dealer=3):
    return LiveMatchRunner(match_ref="locked-server", ai_seats=frozenset(ai_seats), initial_dealer=dealer,
                           ai_profile_key=TEST_AI_PROFILE_KEY, ruleset_id=V3)


def _payload(runner, seat, after=-1):
    payload = runner.reconnect(seat=seat, last_applied_event_index=after)
    validate_instance(payload, f"{WS}#/$defs/reconnectResultPayload")
    return payload


def _bid_text(bid):
    return json.dumps({"declared_contract": bid["declared_contract"], "shown_card": bid["shown_card"]})[1:-1]


def _lock(runner, seat, bid, cid):
    return runner.submit(seat=seat, client_action_id=cid, match_ref=runner.match_ref,
                         expected_event_index=runner.event_cursor, action=action_from_data(bid))


def _assert_blind(runner, locked):
    """No payload to any seat carries another seat's locked bid."""
    for seat in range(4):
        text = json.dumps(_payload(runner, seat), sort_keys=True)
        for other, bid in locked.items():
            if other != seat:
                assert _bid_text(bid) not in text, (seat, other)
        assert '"show_accepted"' not in text.split('"deal_ref"')[-1] or runner.state.phase is not EnginePhase.SHOWING


def test_bids_are_collected_blind_and_applied_together():
    runner = _runner()
    assert runner.state.phase is EnginePhase.SHOWING
    start = runner.event_cursor
    b0, b2 = _payload(runner, 0)["bidding"], _payload(runner, 2)["bidding"]
    assert b0["own_bid"] is None and b0["options"] and b0["locked_seats"] == [1, 3]
    # seat 2 locks first even though seat 0 is the forehand
    bid2 = b2["options"][-1]
    ack = _lock(runner, 2, bid2, "lock-2")
    assert ack["status"] == "accepted" and ack["accepted_event_indices"] == []
    assert runner.event_cursor == start and runner.state.phase is EnginePhase.SHOWING
    assert _payload(runner, 2)["bidding"]["own_bid"] == bid2
    assert _payload(runner, 2)["bidding"]["options"] == []
    assert _payload(runner, 0)["bidding"]["locked_seats"] == [1, 2, 3]
    assert _lock(runner, 2, bid2, "lock-2b")["code"] == "bid_already_locked"
    _assert_blind(runner, {2: bid2})
    bid0 = b0["options"][0]
    _lock(runner, 0, bid0, "lock-0")
    assert runner.state.phase is not EnginePhase.SHOWING
    assert "bidding" not in _payload(runner, 0)
    shows = runner.observation(0)["show_actions"]
    assert shows and shows[0]["seat"] == 0
    assert shows[0]["shown_card"] == bid0["shown_card"]
    # restart recovery replays to the same state
    restored = LiveMatchRunner.from_persistence_record(json.loads(json.dumps(runner.persistence_record())))
    assert restored.persistence_record() == runner.persistence_record()


def test_bid_after_the_first_rami_is_never_revealed_or_stored():
    rng = random.Random("discard")
    for attempt in range(30):
        runner = _runner(dealer=3)  # forehand = seat 0
        options0 = _payload(runner, 0)["bidding"]["options"]
        rami0 = [b for b in options0 if b["declared_contract"] == "RAMI"]
        bid2 = rng.choice(_payload(runner, 2)["bidding"]["options"])
        _lock(runner, 2, bid2, "lock-2")
        _lock(runner, 0, rami0[0], "lock-0")
        # seat 0 declared RAMI at once: seat 2's bid never took effect
        assert [s["seat"] for s in runner.observation(1)["show_actions"]] == [0]
        record = json.dumps(runner.persistence_record(), sort_keys=True)
        assert all(not (item["seat"] == 2 and item["action"]["type"] == "show")
                   for item in runner.persistence_record()["accepted_actions"])
        for seat in range(4):
            text = json.dumps(_payload(runner, seat), sort_keys=True)
            if seat != 2:
                assert '"seat": 2, "shown_card"' not in text and _bid_text(bid2) not in text.replace(
                    json.dumps(runner.observation(seat)["own_hand"]), "")
        assert '"lock-2"' not in record
        # a retry of the discarded lock is answered as a duplicate, not re-applied
        again = runner.submit(seat=2, client_action_id="lock-2", match_ref=runner.match_ref,
                              expected_event_index=runner.event_cursor, action=action_from_data(bid2))
        assert again["status"] == "duplicate"
        return
    raise AssertionError("no deal reached")


def _drive_human_match(runner, rng, deals, prefix="c"):
    """Every seat human: lock bids in random order, answer sooli, exchange, play."""
    n = 0
    done = 0
    while not runner.terminal and done < deals:
        before = len(runner.state.completed_deals)
        if runner.collecting_bids():
            for seat in rng.sample(range(4), 4):
                if not runner.collecting_bids():
                    break
                options = runner.bidding(seat)["options"]
                if options:
                    ack = _lock(runner, seat, rng.choice(options), f"{prefix}{n}")
                    n += 1
                    assert ack["status"] == "accepted"
                    for s in range(4):
                        _payload(runner, s, after=max(-1, runner.event_cursor - 3))
            continue
        seat = runner.current_actor
        obs = runner.observation(seat)
        legal = obs["legal_actions"]
        if obs["phase"] == "SOOLI_OFFER":
            accept = rng.random() < 0.7
            action = next(a for a in legal if a["play_sooli"] is accept)
        else:
            action = rng.choice(legal)
        ack = runner.submit(seat=seat, client_action_id=f"{prefix}{n}", match_ref=runner.match_ref,
                            expected_event_index=runner.event_cursor, action=action_from_data(action))
        n += 1
        assert ack["status"] == "accepted", ack
        state = runner.state.active_deal
        if state is not None and state.soolaaja is not None:
            for s in range(4):
                sooli = runner.observation(s)["sooli"]
                if s not in (state.soolaaja, (state.soolaaja + 2) % 4):
                    assert sooli["given_card"] is None and sooli["returned_card"] is None
        for s in range(4):
            _payload(runner, s, after=max(-1, runner.event_cursor - 3))
        done += len(runner.state.completed_deals) > before
    return runner


def test_all_human_v3_table_plays_sooli_deals_through_the_runner():
    rng = random.Random("humans")
    runner = LiveMatchRunner(match_ref="humans-v3", ruleset_id=V3)
    _drive_human_match(runner, rng, deals=6)
    results = runner.reconnect(seat=0, last_applied_event_index=-1)["completed_deals"]
    assert results
    for result in results:
        validate_instance(result, "https://example.invalid/tuppi/schemas/engine/deal_result.schema.json")
    restored = LiveMatchRunner.from_persistence_record(json.loads(json.dumps(runner.persistence_record())))
    assert restored.persistence_record() == runner.persistence_record()


def test_ai_seats_play_sooli_with_the_fallback():
    runner = LiveMatchRunner(match_ref="ai-v3", ai_seats=frozenset({1, 2, 3}), ruleset_id=V3)
    rng = random.Random("ai")
    _drive_human_match(runner, rng, deals=6)
    assert runner.state.ruleset_id is V3


def test_rooms_carry_the_ruleset(tmp_path):
    manager = RoomManager(tmp_path, ruleset_id=V3)
    room, session = manager.create_room(display_name="Pelaaja", ai_seats=frozenset({1, 2, 3}))
    assert room.snapshot()["ruleset_id"] == "project_target_v3"
    manager.mark_ready(code=room.code, token=session.token)
    assert room.runner.ruleset_id is V3 and room.runner.collecting_bids()
    reloaded = RoomManager(tmp_path, ruleset_id=RulesetId.PROJECT_TARGET_V1).get(room.code)
    assert reloaded.ruleset_id is V3 and reloaded.runner.ruleset_id is V3
    v1_room, _ = RoomManager().create_room(display_name="Pelaaja", ai_seats=frozenset({1, 2, 3}))
    assert "ruleset_id" not in v1_room.snapshot()


def test_websocket_v3_lock_flow_follows_the_schemas(monkeypatch) -> None:
    import asyncio

    from tuppi_server import match_runner
    from tuppi_server.app import TuppiASGIApp

    monkeypatch.setattr(match_runner, "AI_ACTION_DELAY_SECONDS", 0.0)

    def message(message_type, payload):
        return json.dumps({"message_type": message_type, "payload": payload})

    async def scenario():
        manager = RoomManager(ruleset_id=V3)
        app = TuppiASGIApp(manager)
        room, session = manager.create_room(display_name="Pelaaja", ai_seats=frozenset({1, 2, 3}))
        room.ai_action_delay_ms = 0
        manager.mark_ready(code=room.code, token=session.token)
        runner = room.runner
        bid = runner.bidding(0)["options"][0]
        incoming = iter([
            {"type": "websocket.receive", "text": message("hello", {
                "protocol_version": "tuppi.network.v1", "room_code": room.code, "session_token": session.token})},
            {"type": "websocket.receive", "text": message("action_submission", {
                "action": bid, "client_action_id": "ws-lock-1", "expected_event_index": runner.event_cursor,
                "match_ref": runner.match_ref})},
            {"type": "websocket.disconnect"},
        ])
        outgoing = []

        async def receive():
            await asyncio.sleep(0)
            return next(incoming)

        async def send(item):
            outgoing.append(item)

        await app({"type": "websocket", "path": "/v1/ws", "query_string": b""}, receive, send)
        return [json.loads(item["text"]) for item in outgoing if item.get("type") == "websocket.send"], runner

    messages, runner = asyncio.run(scenario())
    for item in messages:
        validate_instance(item, WS)
    updates = [m["payload"] for m in messages if m["message_type"] == "match_update"]
    assert updates[0]["bidding"]["options"] and updates[0]["observation"]["show_actions"] == []
    lobby = next(m for m in messages if m["message_type"] == "lobby_snapshot")["payload"]
    assert lobby["ruleset_id"] == "project_target_v3"
    ack = next(m for m in messages if m["message_type"] == "action_acknowledgement")["payload"]
    assert ack["status"] == "accepted"
    assert runner.state.phase is not EnginePhase.SHOWING


def test_tuppi_ai_profile_plays_a_v3_deal():
    import pytest

    from tuppi_server.match_runner import TUPPI_AI_PROFILE_KEY, tuppi_ai_available
    if not tuppi_ai_available():
        pytest.skip("tuppi_ai is not installed")
    runner = LiveMatchRunner(match_ref="tuppi-ai-v3", ai_seats=frozenset({1, 2, 3}), ruleset_id=V3,
                             ai_profile_key=TUPPI_AI_PROFILE_KEY)
    assert all(getattr(agent, "handles_sooli", False) for agent in runner._ai_agents.values())
    rng = random.Random("tuppi-ai")
    _drive_human_match(runner, rng, deals=2)
    assert len(runner.state.completed_deals) >= 2
    manager = RoomManager(ai_profile_key=TUPPI_AI_PROFILE_KEY, ruleset_id=V3)
    room, _ = manager.create_room(display_name="Pelaaja", ai_seats=frozenset({1, 2, 3}))
    seat = room.snapshot()["seats"][1]
    assert seat["agent_profile"] == TUPPI_AI_PROFILE_KEY and seat["display_name"] == "TuppiAI"
    validate_instance(room.snapshot(), "https://example.invalid/tuppi/schemas/network/http_api.schema.json#/$defs/lobbySnapshot")


def test_restart_mid_bidding_forgets_pending_locks_and_restart_mid_sooli_resumes():
    rng = random.Random("restart")
    runner = LiveMatchRunner(match_ref="restart-v3", ruleset_id=V3)
    bid = runner.bidding(2)["options"][0]
    _lock(runner, 2, bid, "pending-2")
    record = json.loads(json.dumps(runner.persistence_record()))
    assert "pending-2" not in json.dumps(record)
    restored = LiveMatchRunner.from_persistence_record(record)
    assert restored.collecting_bids() and restored.bidding(2)["own_bid"] is None
    assert restored.bidding(2)["options"]  # the seat simply locks again
    # drive to a sooli exchange or sooli play, restart there, and finish the deal
    for attempt in range(60):
        runner = LiveMatchRunner(match_ref=f"restart-s{attempt}", ruleset_id=V3)
        n = 0
        while not runner.terminal and len(runner.state.completed_deals) == 0:
            if runner.collecting_bids():
                for seat in range(4):
                    if runner.collecting_bids() and runner.bidding(seat)["options"]:
                        opts = runner.bidding(seat)["options"]
                        rami = [o for o in opts if o["declared_contract"] == "RAMI"]
                        _lock(runner, seat, (rami or opts)[0], f"c{n}")
                        n += 1
                continue
            phase = runner.state.phase.value
            if phase in ("SOOLI_RETURN", "SOOLI_PLAY"):
                runner = LiveMatchRunner.from_persistence_record(json.loads(json.dumps(runner.persistence_record())))
                assert runner.state.phase.value == phase
                _drive_human_match(runner, rng, deals=1, prefix="after-restart-")
                assert runner.state.completed_deals[-1].public_result.soolaaja is not None
                return
            seat = runner.current_actor
            legal = runner.observation(seat)["legal_actions"]
            action = next((a for a in legal if a.get("play_sooli")), rng.choice(legal))
            runner.submit(seat=seat, client_action_id=f"c{n}", match_ref=runner.match_ref,
                          expected_event_index=runner.event_cursor, action=action_from_data(action))
            n += 1
    raise AssertionError("no sooli reached")


def test_first_ai_move_after_the_reveal_waits_for_the_fade(monkeypatch):
    import asyncio

    from tuppi_server import match_runner

    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(match_runner.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(match_runner, "REVEAL_PAUSE_SECONDS", 3.0)
    for attempt in range(40):
        waits.clear()
        runner = LiveMatchRunner(match_ref=f"reveal-{attempt}", ai_seats=frozenset({1, 2, 3}), ruleset_id=V3,
                                 ai_profile_key=TEST_AI_PROFILE_KEY, initial_dealer=attempt % 4)
        bid = runner.bidding(0)["options"][0]

        async def scenario():
            await runner.submit_async(seat=0, client_action_id="lock-0", match_ref=runner.match_ref,
                                      expected_event_index=runner.event_cursor, action=action_from_data(bid),
                                      ai_action_delay_seconds=0.5)

        asyncio.run(scenario())
        assert not runner.collecting_bids()
        if waits:  # an AI acted after the reveal: its first move waited for the fade
            assert waits[0] == 3.0 and all(w == 0.5 for w in waits[1:])
            return
    raise AssertionError("no deal where an AI moves after the reveal")
