"""After-deal review endpoint: scoped to the seat's own decisions, validated, pluggable."""

from __future__ import annotations

import asyncio
import json
import random

import pytest

from tuppi_engine import PlayCardAction, ShowAction, action_from_data
from tuppi_rules import RulesetId
from tuppi_server.app import TuppiASGIApp
from tuppi_server.deal_review import ReviewFinding
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_ui_fixtures.validation import validate_instance

SCHEMA = "https://example.invalid/tuppi/schemas/network/deal_review_v1.schema.json"


class FirstLegalReviewer:
    """Flags every decision where the first legal action was not played."""

    reviewer_id = "test.first_legal"

    def __init__(self):
        self.seen = []

    def review_decisions(self, decisions):
        self.seen.append(decisions)
        return [ReviewFinding(d.decision_index, d.observation.legal_actions[0], 0.01, 0.001)
                for d in decisions
                if len(d.observation.legal_actions) > 1 and d.action != d.observation.legal_actions[0]]


class ForeignCardReviewer:
    """Recommends, for the seat's first decision, a card the seat does not hold."""

    reviewer_id = "test.foreign"

    def review_decisions(self, decisions):
        from tuppi_rules import FULL_DECK
        first = decisions[0]
        foreign = next(c for c in FULL_DECK if c not in first.observation.own_hand)
        return [ReviewFinding(first.decision_index, PlayCardAction(seat=first.action.seat, card=foreign), 0.02, 0.0)]


def _play_one_deal(manager, room, rng):
    runner = room.runner
    n = 0
    while len(runner.state.completed_deals) < 1:
        if runner.collecting_bids():
            for seat in range(4):
                bidding = runner.bidding(seat)
                if bidding and bidding["options"]:
                    runner.submit(seat=seat, client_action_id=f"b{n}", match_ref=runner.match_ref,
                                  expected_event_index=runner.event_cursor,
                                  action=action_from_data(rng.choice(bidding["options"])))
                    n += 1
            continue
        seat = runner.current_actor
        legal = runner.observation(seat)["legal_actions"]
        runner.submit(seat=seat, client_action_id=f"a{n}", match_ref=runner.match_ref,
                      expected_event_index=runner.event_cursor, action=action_from_data(rng.choice(legal)))
        n += 1


def _room(ruleset=RulesetId.PROJECT_TARGET_V3):
    manager = RoomManager(ruleset_id=ruleset)
    room, host = manager.create_room(display_name="A", ai_seats=frozenset())
    sessions = [host] + [manager.join_room(code=room.code, display_name=f"P{i}")[1] for i in range(1, 4)]
    for session in sessions:
        manager.mark_ready(code=room.code, token=session.token)
    return manager, room, sessions


@pytest.mark.parametrize("ruleset", [RulesetId.PROJECT_TARGET_V1, RulesetId.PROJECT_TARGET_V3])
def test_review_is_scoped_validated_and_cached(ruleset):
    manager, room, sessions = _room(ruleset)
    reviewer = FirstLegalReviewer()
    manager.deal_reviewer = reviewer
    _play_one_deal(manager, room, random.Random(1))
    for session in sessions:
        review = manager.deal_review_for_session(code=room.code, token=session.token, deal_number=0)
        validate_instance(review, SCHEMA)
        assert review["seat"] == session.seat and review["ruleset_id"] == ruleset.value
        decisions = reviewer.seen[-1]
        assert decisions and all(d.action.seat == session.seat for d in decisions)
        assert all(d.observation.observing_seat == session.seat for d in decisions)
        for finding in review["findings"]:
            assert finding["played_action"]["seat"] == session.seat
            assert finding["recommended_action"]["seat"] == session.seat
        assert review["total_cost"] == pytest.approx(0.01 * len(review["findings"]))
    calls = len(reviewer.seen)
    manager.deal_review_for_session(code=room.code, token=sessions[0].token, deal_number=0)
    assert len(reviewer.seen) == calls  # cached


def test_v3_bid_decisions_are_reviewed_blind():
    manager, room, sessions = _room()
    reviewer = FirstLegalReviewer()
    manager.deal_reviewer = reviewer
    _play_one_deal(manager, room, random.Random(2))
    manager.deal_review_for_session(code=room.code, token=sessions[1].token, deal_number=0)
    bids = [d for d in reviewer.seen[-1] if isinstance(d.action, ShowAction)]
    assert all(d.observation.show_actions == () for d in bids)


def test_review_refuses_a_card_the_seat_did_not_hold():
    manager, room, sessions = _room()
    manager.deal_reviewer = ForeignCardReviewer()
    _play_one_deal(manager, room, random.Random(3))
    with pytest.raises(RoomError, match="review_failed"):
        manager.deal_review_for_session(code=room.code, token=sessions[0].token, deal_number=0)


def test_review_unavailable_and_incomplete_deals():
    manager, room, sessions = _room()
    with pytest.raises(RoomError, match="review_unavailable"):
        manager.deal_review_for_session(code=room.code, token=sessions[0].token, deal_number=0)
    manager.deal_reviewer = FirstLegalReviewer()
    with pytest.raises(RoomError, match="deal_not_complete"):
        manager.deal_review_for_session(code=room.code, token=sessions[0].token, deal_number=0)


def test_http_review_route():
    manager, room, sessions = _room()
    manager.deal_reviewer = FirstLegalReviewer()
    _play_one_deal(manager, room, random.Random(4))
    app = TuppiASGIApp(manager)

    async def scenario():
        incoming = iter([{"type": "http.request", "more_body": False,
                          "body": json.dumps({"session_token": sessions[2].token}).encode()}])
        outgoing = []

        async def receive():
            return next(incoming)

        async def send(message):
            outgoing.append(message)

        await app({"type": "http", "method": "POST", "path": f"/v1/rooms/{room.code}/deals/0/review"},
                  receive, send)
        return outgoing

    outgoing = asyncio.run(scenario())
    assert outgoing[0]["status"] == 200
    body = json.loads(outgoing[1]["body"])
    validate_instance(body, SCHEMA)
    assert body["seat"] == 2
