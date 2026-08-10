from __future__ import annotations

import tuppi_server.match_runner as match_runner_module
from tuppi_engine import action_from_data
from tuppi_server import LiveMatchRunner, generate_live_deal
from tuppi_server.match_runner import DEFAULT_AI_PROFILE_KEY
from tuppi_server.projection import project_event_batch, project_observation
from tuppi_rules import FULL_DECK


def _all_serialized_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _all_serialized_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _all_serialized_strings(item)


def test_live_deal_is_complete_and_uses_no_research_seed() -> None:
    deal = generate_live_deal(dealer=0)
    assert len(deal.hands) == 4
    assert all(len(hand) == 13 for hand in deal.hands)
    assert frozenset(card for hand in deal.hands for card in hand) == frozenset(FULL_DECK)
    assert deal.deal_id.startswith("sha256:")


def test_runner_stops_at_human_turn_and_projects_only_authorized_state() -> None:
    runner = LiveMatchRunner(
        match_ref="server-test",
        ai_seats=frozenset({1, 2, 3}),
    )
    observation = runner.observation(0)
    assert observation["current_actor"] == 0
    assert observation["phase"] in {"SHOWING", "TRICK_PLAY"}
    assert len(observation["own_hand"]) == 13
    assert runner.ai_profile_key == DEFAULT_AI_PROFILE_KEY
    assert {
        agent.identity for agent in runner._ai_agents.values()
    } == {"agent:sha256:d8b426f1263c7ce32bdef82e4971dc2e494950f155e15db9b69fc6334a2ac929"}

    assert "initial_hands" not in observation
    assert "hands" not in observation
    assert "deal_id" not in observation
    assert not any(
        value.startswith("sha256:")
        for value in _all_serialized_strings(observation)
    )


def test_accepted_duplicate_stale_and_rejected_actions() -> None:
    runner = LiveMatchRunner(
        match_ref="server-actions",
        ai_seats=frozenset({1, 2, 3}),
    )
    observation = runner.observation(0)
    action = action_from_data(observation["legal_actions"][0])
    cursor = runner.event_cursor

    accepted = runner.submit(
        seat=0,
        client_action_id="client-action-1",
        match_ref="server-actions",
        expected_event_index=cursor,
        action=action,
    )
    assert accepted["status"] == "accepted"
    assert accepted["event_batch"]
    assert accepted["observation"]["observing_seat"] == 0

    duplicate = runner.submit(
        seat=0,
        client_action_id="client-action-1",
        match_ref="server-actions",
        expected_event_index=-1,
        action=action,
    )
    assert duplicate["status"] == "duplicate"

    stale = runner.submit(
        seat=0,
        client_action_id="client-action-2",
        match_ref="server-actions",
        expected_event_index=-1,
        action=action,
    )
    assert stale["status"] == "stale"
    assert stale["latest_observation"]["observing_seat"] == 0

    wrong_seat_action = action_from_data(observation["legal_actions"][0])
    rejected = runner.submit(
        seat=1,
        client_action_id="client-action-3",
        match_ref="server-actions",
        expected_event_index=runner.event_cursor,
        action=wrong_seat_action,
    )
    assert rejected["status"] == "rejected"
    assert rejected["code"] in {"seat_mismatch", "not_your_turn", "ai_seat"}


def test_projection_contains_public_events_only() -> None:
    runner = LiveMatchRunner(match_ref="server-events", ai_seats=frozenset({1, 2, 3}))
    observation = project_observation(runner.state, seat=0)
    events = project_event_batch(runner.state.public_events)

    assert events[0]["event_type"] == "deal_started"
    serialized = {"observation": observation, "events": events}
    assert "initial_hands" not in serialized
    assert "hands" not in serialized
    assert "deal_id" not in serialized


def test_persistence_record_replays_private_deal_and_human_and_ai_actions() -> None:
    runner = LiveMatchRunner(
        match_ref="server-recovery",
        ai_seats=frozenset({1, 2, 3}),
    )
    observation = runner.observation(0)
    action = action_from_data(observation["legal_actions"][0])
    runner.submit(
        seat=0,
        client_action_id="recovery-human-1",
        match_ref=runner.match_ref,
        expected_event_index=runner.event_cursor,
        action=action,
    )

    record = runner.persistence_record()
    assert len(record["deals"]) == 1
    assert any(
        item["client_action_id"].startswith("ai:")
        for item in record["accepted_actions"]
    )

    restored = LiveMatchRunner.from_persistence_record(record)
    assert restored.persistence_record() == record
    assert restored.observation(0) == runner.observation(0)
    assert restored.event_cursor == runner.event_cursor


def test_persistence_rejects_tampered_replay_event() -> None:
    runner = LiveMatchRunner(match_ref="server-tamper", ai_seats=frozenset({1, 2, 3}))
    observation = runner.observation(0)
    action = action_from_data(observation["legal_actions"][0])
    runner.submit(
        seat=0,
        client_action_id="tamper-human-1",
        match_ref=runner.match_ref,
        expected_event_index=runner.event_cursor,
        action=action,
    )
    record = runner.persistence_record()
    record["public_events"] = list(record["public_events"][:-1])

    import pytest

    with pytest.raises(ValueError, match="replayed public events"):
        LiveMatchRunner.from_persistence_record(record)


def test_async_submission_waits_before_ai_leads_a_new_trick(monkeypatch) -> None:
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(match_runner_module.asyncio, "sleep", fake_sleep)

    async def scenario() -> None:
        runner = LiveMatchRunner(
            match_ref="server-ai-delay",
            ai_seats=frozenset({1, 2, 3}),
        )
        observation = runner.observation(0)
        action = action_from_data(observation["legal_actions"][0])
        await runner.submit_async(
            seat=0,
            client_action_id="ai-delay-human-1",
            match_ref=runner.match_ref,
            expected_event_index=runner.event_cursor,
            action=action,
        )

    import asyncio

    asyncio.run(scenario())
    assert waits
    assert waits == [match_runner_module.AI_ACTION_DELAY_SECONDS] * len(waits)


def test_async_match_start_paces_initial_ai_actions(monkeypatch) -> None:
    waits: list[float] = []
    updates = 0

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    async def record_update() -> None:
        nonlocal updates
        updates += 1

    monkeypatch.setattr(match_runner_module.asyncio, "sleep", fake_sleep)

    async def scenario() -> None:
        runner = LiveMatchRunner(
            match_ref="async-start-delay",
            ai_seats=frozenset({1, 2, 3}),
            auto_run_ai=False,
        )
        assert runner.current_actor == 1
        await runner.run_ai_async(on_state_change=record_update)
        assert runner.current_actor == 0

    import asyncio

    asyncio.run(scenario())
    assert waits
    assert waits == [match_runner_module.AI_ACTION_DELAY_SECONDS] * len(waits)
    assert updates == len(waits)
