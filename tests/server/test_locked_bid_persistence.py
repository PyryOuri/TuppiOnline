"""Unrevealed locked bids survive a restart and stay private (project_target_v3)."""
from __future__ import annotations

import json

import pytest
from tuppi_engine import action_from_data
from tuppi_rules import RulesetId
from tuppi_server import match_runner
from tuppi_server.match_runner import BIDS_MATCH_RECORD_SCHEMA_VERSION, LiveMatchRunner, TEST_AI_PROFILE_KEY
from tuppi_server.rooms import RoomManager

V3 = RulesetId.PROJECT_TARGET_V3


@pytest.fixture(autouse=True)
def unpaced(monkeypatch):
    monkeypatch.setattr(match_runner, "REVEAL_PAUSE_SECONDS", 0)
    monkeypatch.setattr(match_runner, "REVEAL_STEP_SECONDS", 0)


def partners_against_bots():
    return LiveMatchRunner(match_ref="locked-bids", ruleset_id=V3, ai_seats=frozenset({1, 3}),
                           ai_profile_key=TEST_AI_PROFILE_KEY)


def lock(runner, seat, client_action_id, option=0, action=None):
    action = action or action_from_data(runner.bidding(seat)["options"][option])
    return runner.submit(seat=seat, client_action_id=client_action_id, match_ref=runner.match_ref,
                         expected_event_index=runner.event_cursor, action=action)


def restart(runner):
    return LiveMatchRunner.from_persistence_record(json.loads(json.dumps(runner.persistence_record())))


def test_a_locked_bid_survives_a_restart_without_being_revealed():
    runner = partners_against_bots()
    assert runner.persistence_record()["schema_version"] == "tuppi.server.match_record.v4"
    assert lock(runner, 0, "host-bid")["status"] == "accepted"
    own = runner.bidding(0)["own_bid"]
    record = runner.persistence_record()
    assert record["schema_version"] == BIDS_MATCH_RECORD_SCHEMA_VERSION
    assert [item["seat"] for item in record["locked_bids"]] == [0]

    restored = restart(runner)
    assert restored.collecting_bids() and restored.bidding(0)["own_bid"] == own
    partner = restored.bidding(2)
    assert partner["own_bid"] is None and partner["locked_seats"] == [0, 1, 3] and partner["options"]
    seen = json.dumps(restored.reconnect(seat=2, last_applied_event_index=-1))
    assert own["shown_card"] not in seen and restored.observation(2)["show_actions"] == []
    assert lock(restored, 0, "host-bid", action=action_from_data(own))["status"] == "duplicate", \
        "a retried envelope stays a duplicate"
    assert lock(restored, 0, "another-bid", action=action_from_data(own))["code"] == "bid_already_locked"

    assert lock(restored, 2, "partner-bid")["status"] == "accepted"
    assert not restored.collecting_bids()
    applied = {a["seat"]: a for a in restored.observation(0)["show_actions"]}
    assert "host-bid" in restored._records or "host-bid" in restored._discarded_bid_acks
    if 0 in applied:
        assert applied[0]["shown_card"] == own["shown_card"], "the restored bid is the one played"
    after = restored.persistence_record()
    assert "locked_bids" not in after or after["locked_bids"] == []
    assert own["shown_card"] not in json.dumps(after.get("discarded_bid_acks", {})), "discarded bids are not kept"


def test_discarded_bid_acknowledgements_last_until_the_next_deal():
    runner = partners_against_bots()
    for attempt in range(40):  # find a deal where a bid is discarded after an earlier RAMI
        rami = next((i for i, o in enumerate(runner.bidding(0)["options"]) if o["declared_contract"] == "RAMI"), 0)
        lock(runner, 0, f"host-{attempt}", rami)
        lock(runner, 2, f"partner-{attempt}")
        if runner._discarded_bid_acks:
            break
        while not runner.collecting_bids() and not runner.terminal:
            seat = runner.current_actor
            runner.submit(seat=seat, client_action_id=f"play-{attempt}-{runner.event_cursor}", match_ref=runner.match_ref,
                          expected_event_index=runner.event_cursor,
                          action=action_from_data(runner.observation(seat)["legal_actions"][0]))
    assert runner._discarded_bid_acks, "a discarded bid occurs within 40 deals"
    restored = restart(runner)
    discarded = next(iter(runner._discarded_bid_acks))
    assert restored._discarded_bid_acks == runner._discarded_bid_acks
    seat = 2 if discarded.startswith("partner") else 0
    retry = restored.submit(seat=seat, client_action_id=discarded, match_ref=restored.match_ref,
                            expected_event_index=0, action=action_from_data(runner.observation(seat)["legal_actions"][0])
                            if runner.observation(seat)["legal_actions"] else None)
    assert retry["status"] == "duplicate"
    while not restored.collecting_bids() and not restored.terminal:
        actor = restored.current_actor
        restored.submit(seat=actor, client_action_id=f"rest-{restored.event_cursor}", match_ref=restored.match_ref,
                        expected_event_index=restored.event_cursor,
                        action=action_from_data(restored.observation(actor)["legal_actions"][0]))
    assert restored._discarded_bid_acks == {}, "cleared when the next deal starts"
    assert restored.persistence_record()["schema_version"] == "tuppi.server.match_record.v4"


def test_restored_bids_are_validated():
    runner = partners_against_bots()
    lock(runner, 0, "host-bid")
    good = json.loads(json.dumps(runner.persistence_record()))
    for change, message in [
        (lambda r: r["locked_bids"][0].update(seat=1), "seat"),
        (lambda r: r["locked_bids"][0]["action"].update(seat=2), "seat|legal"),
        (lambda r: r["locked_bids"][0]["action"].update(shown_card="2C" if r["locked_bids"][0]["action"]["shown_card"] != "2C" else "3C"), "legal"),
        (lambda r: r["locked_bids"][0]["acknowledgement"].update(client_action_id="other"), "acknowledgement"),
        (lambda r: r["locked_bids"].append(dict(r["locked_bids"][0])), "seat"),
    ]:
        record = json.loads(json.dumps(good))
        change(record)
        with pytest.raises(ValueError, match=message):
            LiveMatchRunner.from_persistence_record(record)


def test_a_room_restart_keeps_the_hosts_locked_bid(tmp_path):
    rooms = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, host = rooms.create_room(display_name="Host", ai_seats=frozenset({1, 3}))
    _, guest = rooms.join_room(code=room.code, display_name="Guest")
    rooms.mark_ready(code=room.code, token=host.token, auto_run_ai=False)
    rooms.mark_ready(code=room.code, token=guest.token, auto_run_ai=False)
    lock(room.runner, 0, "host-bid")
    rooms.persist(room)
    restored = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY).get(room.code)
    assert restored.runner.bidding(0)["own_bid"] == room.runner.bidding(0)["own_bid"]
    assert restored.runner.bidding(2)["own_bid"] is None


def test_hosted_lite_bots_keep_their_cursors_with_locked_bids(monkeypatch):
    monkeypatch.setenv("TUPPI_HOSTED_BOT", "1")
    monkeypatch.setenv("TUPPI_HOSTED_BOT_LEVEL", "lite")
    from tuppi_server.match_runner import TUPPI_AI_PROFILE_KEY
    runner = LiveMatchRunner(match_ref="hosted-bids", ruleset_id=V3, ai_seats=frozenset({1, 3}),
                             ai_profile_key=TUPPI_AI_PROFILE_KEY)
    lock(runner, 0, "host-bid")
    record = runner.persistence_record()
    assert record["schema_version"] == BIDS_MATCH_RECORD_SCHEMA_VERSION and "bot_controllers" in record
    restored = restart(runner)
    assert {s: a.checkpoint() for s, a in restored._ai_agents.items()} == {s: a.checkpoint() for s, a in runner._ai_agents.items()}
    assert restored.bidding(0)["own_bid"] == runner.bidding(0)["own_bid"]
