from __future__ import annotations

import asyncio
import json
import logging

from tuppi_engine import action_from_data
from tuppi_server import LiveMatchRunner
from tuppi_server.app import TuppiASGIApp
from tuppi_server.projection import project_event_batch, project_match_result
from tuppi_server.rooms import RoomManager
from tuppi_rules import FULL_DECK


CARD_CODES = {card.to_code() for card in FULL_DECK}
BANNED_WIRE_KEYS = {
    "accepted_actions",
    "ai_profile_key",
    "deal_id",
    "hands",
    "host_token",
    "initial_hands",
    "research_result",
    "rng_state",
    "session_token",
}


def _keys(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _keys(item)


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _assert_seat_projection_safe(
    runner: LiveMatchRunner,
    *,
    seat: int,
    wire_value: object,
) -> None:
    assert not (set(_keys(wire_value)) & BANNED_WIRE_KEYS)
    observation = runner.observation(seat)
    public_events = project_event_batch(runner.state.public_events)
    visible_codes = {
        value
        for value in _strings({"observation": observation, "events": public_events})
        if value in CARD_CODES
    }
    current_deal = runner._deals[-1]
    foreign_codes = {
        card.to_code()
        for other_seat, hand in enumerate(current_deal.hands)
        if other_seat != seat
        for card in hand
    }
    hidden_sentinels = foreign_codes - visible_codes
    serialized = json.dumps(wire_value, sort_keys=True)
    assert hidden_sentinels
    assert not {code for code in hidden_sentinels if code in serialized}


def _submit_first_legal(runner: LiveMatchRunner, client_action_id: str) -> None:
    actor = runner.current_actor
    assert actor is not None
    observation = runner.observation(actor)
    runner.submit(
        seat=actor,
        client_action_id=client_action_id,
        match_ref=runner.match_ref,
        expected_event_index=runner.event_cursor,
        action=action_from_data(observation["legal_actions"][0]),
    )


def test_hidden_card_sentinels_never_cross_initial_showing_or_trick_projections() -> None:
    runner = LiveMatchRunner(match_ref="privacy-sentinels", auto_run_ai=False)

    for seat in range(4):
        _assert_seat_projection_safe(
            runner,
            seat=seat,
            wire_value={
                "observation": runner.observation(seat),
                "event_batch": project_event_batch(runner.state.public_events),
            },
        )

    action_index = 0
    while runner.state.phase.value == "SHOWING":
        _submit_first_legal(runner, f"privacy-show-{action_index}")
        action_index += 1
        for seat in range(4):
            _assert_seat_projection_safe(
                runner,
                seat=seat,
                wire_value={
                    "observation": runner.observation(seat),
                    "event_batch": project_event_batch(runner.state.public_events),
                },
            )

    while not runner.state.active_deal.current_trick:
        _submit_first_legal(runner, f"privacy-play-{action_index}")
        action_index += 1
    for seat in range(4):
        _assert_seat_projection_safe(
            runner,
            seat=seat,
            wire_value={
                "observation": runner.observation(seat),
                "event_batch": project_event_batch(runner.state.public_events),
            },
        )


def test_stale_reconnect_rejection_and_error_payloads_remain_seat_safe() -> None:
    runner = LiveMatchRunner(match_ref="privacy-errors", auto_run_ai=False)
    actor = runner.current_actor
    assert actor is not None
    observation = runner.observation(actor)
    action = action_from_data(observation["legal_actions"][0])
    stale = runner.submit(
        seat=actor,
        client_action_id="privacy-stale",
        match_ref=runner.match_ref,
        expected_event_index=-1,
        action=action,
    )
    assert stale["status"] == "stale"
    _assert_seat_projection_safe(runner, seat=actor, wire_value=stale)
    _assert_seat_projection_safe(
        runner,
        seat=actor,
        wire_value=runner.reconnect(seat=actor, last_applied_event_index=-1),
    )
    _assert_seat_projection_safe(
        runner,
        seat=actor,
        wire_value={"message_type": "protocol_error", "payload": {"code": "invalid_message"}},
    )


def test_terminal_server_result_contains_no_private_state_keys() -> None:
    runner = LiveMatchRunner(
        match_ref="privacy-terminal",
        ai_seats=frozenset(range(4)),
    )
    assert runner.terminal
    result = project_match_result(runner.state)
    assert not (set(_keys(result)) & BANNED_WIRE_KEYS)


def test_ordinary_server_logging_does_not_emit_tokens_or_hidden_hands(caplog) -> None:
    async def scenario() -> str:
        app = TuppiASGIApp(RoomManager())
        payload = json.dumps(
            {"display_name": "Privacy", "ai_seats": [1, 2, 3]}
        ).encode("utf-8")
        incoming = iter(
            [{"type": "http.request", "body": payload, "more_body": False}]
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
        response = json.loads(outgoing[-1]["body"])
        return response["session_token"]

    caplog.set_level(logging.DEBUG)
    token = asyncio.run(scenario())
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in log_text
    assert "initial_hands" not in log_text
    assert '"hands"' not in log_text
