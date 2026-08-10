"""Authoritative in-memory live match runner.

This module contains no network code. It owns the engine state, validates
client action envelopes, records idempotency keys, runs configured AI seats,
and returns projection-safe dictionaries to the transport layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from typing import Any, Awaitable, Callable

from tuppi_agents import (
    construct_registered_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_engine import (
    Action,
    EngineError,
    EnginePhase,
    ExplicitDeal,
    FirstLegalActionAgent,
    MatchState,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    explicit_deal_from_data,
    explicit_deal_to_data,
    match_observation_for,
    validate_match_state,
)
from tuppi_engine.serialization import action_from_data, action_to_data
from tuppi_rules import MatchScore

from .deal_generation import generate_live_deal
from .projection import (
    project_completed_deals,
    project_event_batch,
    project_match_result,
    project_observation,
)


PROTOCOL_VERSION = "tuppi.network.v1"
ACK_SCHEMA_VERSION = "tuppi.network.action_acknowledgement.v1"
MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v2"
LEGACY_MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v1"
DEFAULT_AI_PROFILE_KEY = "partner_aware_v1"
TEST_AI_PROFILE_KEY = "first_legal_action_v1"


def _configured_ai_delay() -> float:
    raw = os.environ.get("TUPPI_SERVER_AI_ACTION_DELAY_SECONDS", "5.0")
    try:
        delay = float(raw)
    except ValueError as exc:
        raise ValueError("TUPPI_SERVER_AI_ACTION_DELAY_SECONDS must be numeric") from exc
    if not 0.0 <= delay <= 60.0:
        raise ValueError("TUPPI_SERVER_AI_ACTION_DELAY_SECONDS must be in 0..60")
    return delay


AI_ACTION_DELAY_SECONDS = _configured_ai_delay()


def _construct_ai_agents(
    seats: frozenset[int],
    *,
    profile_key: str,
) -> dict[int, object]:
    if profile_key == TEST_AI_PROFILE_KEY:
        return {seat: FirstLegalActionAgent() for seat in seats}
    if profile_key != DEFAULT_AI_PROFILE_KEY:
        raise ValueError(f"unsupported live AI profile: {profile_key}")
    specification = phase4_specifications_by_profile_key()[profile_key]
    return {
        seat: construct_registered_agent(specification, seat=seat)
        for seat in seats
    }


@dataclass(frozen=True, slots=True)
class AcceptedActionRecord:
    client_action_id: str
    action_index: int
    seat: int
    expected_event_index: int
    action: dict[str, object]
    accepted_event_indices: tuple[int, ...]
    event_batch: tuple[dict[str, object], ...]
    acknowledgement: dict[str, object]


@dataclass(frozen=True, slots=True)
class _PendingHumanSubmission:
    client_action_id: str
    action_index: int
    seat: int
    expected_event_index: int
    action: Action
    before_event_count: int
    direct_event_batch: tuple[dict[str, object], ...]


class LiveMatchRunner:
    """Advance one live match while keeping all private hands server-side."""

    def __init__(
        self,
        *,
        match_ref: str,
        initial_dealer: int = 0,
        initial_score: MatchScore | None = None,
        ai_seats: frozenset[int] = frozenset(),
        ai_profile_key: str = DEFAULT_AI_PROFILE_KEY,
        auto_run_ai: bool = True,
    ) -> None:
        self.state: MatchState = create_match(
            initial_score=initial_score or MatchScore(0, 0),
            initial_dealer=initial_dealer,
            match_ref=match_ref,
        )
        self.ai_seats = frozenset(ai_seats)
        if any(seat not in range(4) for seat in self.ai_seats):
            raise ValueError("ai_seats must contain only seats 0..3")
        self.ai_profile_key = ai_profile_key
        self._ai_agents = _construct_ai_agents(
            self.ai_seats,
            profile_key=self.ai_profile_key,
        )
        self._records: dict[str, AcceptedActionRecord] = {}
        self._accepted_actions: list[AcceptedActionRecord] = []
        self._deals: list[ExplicitDeal] = []
        self._next_action_index = 0
        self._next_ai_action_id = 0
        self._ensure_deal_started()
        if auto_run_ai:
            self._run_ai_until_human_or_terminal()

    @classmethod
    def from_persistence_record(cls, record: dict[str, object]) -> "LiveMatchRunner":
        """Rebuild a runner by replaying its durable explicit deals and actions."""

        if type(record) is not dict:
            raise ValueError("match persistence record must be an object")
        required_v1 = {
            "accepted_actions",
            "ai_seats",
            "deals",
            "initial_dealer",
            "initial_score",
            "match_ref",
            "public_events",
            "schema_version",
        }
        required_v2 = required_v1 | {"ai_profile_key"}
        schema_version = record.get("schema_version")
        if schema_version == MATCH_RECORD_SCHEMA_VERSION:
            required = required_v2
            ai_profile_key = record.get("ai_profile_key")
        elif schema_version == LEGACY_MATCH_RECORD_SCHEMA_VERSION:
            required = required_v1
            ai_profile_key = TEST_AI_PROFILE_KEY
        else:
            raise ValueError("unsupported match persistence schema_version")
        if set(record) != required:
            raise ValueError("match persistence record fields are invalid")
        if not isinstance(ai_profile_key, str):
            raise ValueError("persisted ai_profile_key must be a string")
        match_ref = record["match_ref"]
        initial_score_data = record["initial_score"]
        initial_dealer = record["initial_dealer"]
        ai_seats_data = record["ai_seats"]
        deals_data = record["deals"]
        actions_data = record["accepted_actions"]
        public_events = record["public_events"]
        if not isinstance(match_ref, str):
            raise ValueError("persisted match_ref must be a string")
        if type(initial_score_data) is not list or len(initial_score_data) != 2:
            raise ValueError("persisted initial_score must contain two values")
        if any(type(value) is not int for value in initial_score_data):
            raise ValueError("persisted initial_score must contain integers")
        if type(initial_dealer) is not int:
            raise ValueError("persisted initial_dealer must be an integer")
        if type(ai_seats_data) is not list or any(
            type(seat) is not int for seat in ai_seats_data
        ):
            raise ValueError("persisted ai_seats must be an integer array")
        if type(deals_data) is not list or not deals_data:
            raise ValueError("persisted deals must be a nonempty array")
        if type(actions_data) is not list:
            raise ValueError("persisted accepted_actions must be an array")
        if type(public_events) is not list:
            raise ValueError("persisted public_events must be an array")

        initial_score = MatchScore(initial_score_data[0], initial_score_data[1])
        deals = [explicit_deal_from_data(item) for item in deals_data]
        if any(deal.dealer != (initial_dealer + index) % 4 for index, deal in enumerate(deals)):
            raise ValueError("persisted deal dealer sequence is invalid")

        runner = cls.__new__(cls)
        runner.state = create_match(
            initial_score=initial_score,
            initial_dealer=initial_dealer,
            match_ref=match_ref,
        )
        runner.ai_seats = frozenset(ai_seats_data)
        if any(seat not in range(4) for seat in runner.ai_seats):
            raise ValueError("persisted ai_seats contains an invalid seat")
        runner.ai_profile_key = ai_profile_key
        runner._ai_agents = _construct_ai_agents(
            runner.ai_seats,
            profile_key=runner.ai_profile_key,
        )
        runner._records = {}
        runner._accepted_actions = []
        runner._deals = deals
        runner._next_action_index = 0
        runner._next_ai_action_id = 0
        runner._ensure_deal_started()

        for raw_record in actions_data:
            if type(raw_record) is not dict:
                raise ValueError("persisted action record must be an object")
            expected_fields = {
                "accepted_event_indices",
                "action",
                "action_index",
                "acknowledgement",
                "client_action_id",
                "event_batch",
                "expected_event_index",
                "seat",
            }
            if set(raw_record) != expected_fields:
                raise ValueError("persisted action record fields are invalid")
            action_index = raw_record["action_index"]
            seat = raw_record["seat"]
            expected_event_index = raw_record["expected_event_index"]
            client_action_id = raw_record["client_action_id"]
            accepted_indices = raw_record["accepted_event_indices"]
            event_batch = raw_record["event_batch"]
            acknowledgement = raw_record["acknowledgement"]
            if action_index != runner._next_action_index:
                raise ValueError("persisted action indices are not contiguous")
            if type(seat) is not int or seat not in range(4):
                raise ValueError("persisted action seat is invalid")
            if type(expected_event_index) is not int:
                raise ValueError("persisted expected_event_index is invalid")
            if not isinstance(client_action_id, str) or not client_action_id:
                raise ValueError("persisted client_action_id is invalid")
            if type(accepted_indices) is not list or any(
                type(index) is not int for index in accepted_indices
            ):
                raise ValueError("persisted accepted_event_indices are invalid")
            if type(event_batch) is not list:
                raise ValueError("persisted event_batch must be an array")
            if type(acknowledgement) is not dict:
                raise ValueError("persisted acknowledgement must be an object")
            if runner.state.phase is EnginePhase.DEAL_COMPLETE:
                runner._ensure_deal_started()
            if expected_event_index != runner.event_cursor:
                raise ValueError("persisted action cursor does not match replay state")
            action = action_from_data(raw_record["action"])
            if action.seat != seat:
                raise ValueError("persisted action seat disagrees with action")
            before_event_count = len(runner.state.public_events)
            try:
                runner.state = apply_match_action(runner.state, action)
            except EngineError as exc:
                raise ValueError("persisted action cannot be replayed") from exc
            direct_event_batch = tuple(
                project_event_batch(
                    runner.state.public_events,
                    after_event_index=(
                        runner.state.public_events[before_event_count - 1].event_index
                        if before_event_count
                        else -1
                    ),
                )
            )
            if direct_event_batch != tuple(event_batch):
                raise ValueError("replayed action events differ from persisted events")
            restored = AcceptedActionRecord(
                client_action_id=client_action_id,
                action_index=action_index,
                seat=seat,
                expected_event_index=expected_event_index,
                action=raw_record["action"],  # type: ignore[arg-type]
                accepted_event_indices=tuple(accepted_indices),
                event_batch=direct_event_batch,
                acknowledgement=acknowledgement,
            )
            runner._accepted_actions.append(restored)
            if not client_action_id.startswith("ai:"):
                if client_action_id in runner._records:
                    raise ValueError("persisted client_action_id is duplicated")
                runner._records[client_action_id] = restored
            runner._next_action_index += 1
            if client_action_id.startswith("ai:"):
                runner._next_ai_action_id += 1
            if runner.state.phase is EnginePhase.DEAL_COMPLETE:
                runner._ensure_deal_started()

        if tuple(public_events) != tuple(project_event_batch(runner.state.public_events)):
            raise ValueError("replayed public events differ from persisted events")
        validate_match_state(runner.state)
        return runner

    @property
    def match_ref(self) -> str:
        return self.state.match_ref

    @property
    def event_cursor(self) -> int:
        return self.state.public_events[-1].event_index if self.state.public_events else -1

    @property
    def terminal(self) -> bool:
        return self.state.terminal

    @property
    def current_actor(self) -> int | None:
        return self.state.current_actor

    def observation(self, seat: int) -> dict[str, object]:
        return project_observation(self.state, seat=seat)

    def persistence_record(self) -> dict[str, object]:
        """Return private durable material for restart recovery only."""

        return {
            "accepted_actions": [
                {
                    "accepted_event_indices": list(record.accepted_event_indices),
                    "action": record.action,
                    "action_index": record.action_index,
                    "acknowledgement": record.acknowledgement,
                    "client_action_id": record.client_action_id,
                    "event_batch": list(record.event_batch),
                    "expected_event_index": record.expected_event_index,
                    "seat": record.seat,
                }
                for record in sorted(
                    self._accepted_actions, key=lambda item: item.action_index
                )
            ],
            "ai_seats": sorted(self.ai_seats),
            "ai_profile_key": self.ai_profile_key,
            "deals": [explicit_deal_to_data(deal) for deal in self._deals],
            "initial_dealer": self.state.initial_dealer,
            "initial_score": [
                self.state.initial_score.team0,
                self.state.initial_score.team1,
            ],
            "match_ref": self.match_ref,
            "public_events": project_event_batch(self.state.public_events),
            "schema_version": MATCH_RECORD_SCHEMA_VERSION,
        }

    def reconnect(self, *, seat: int, last_applied_event_index: int) -> dict[str, object]:
        if type(last_applied_event_index) is not int or last_applied_event_index < -1:
            raise ValueError("last_applied_event_index must be an integer >= -1")
        result = {
            "status": "connected",
            "completed_deals": project_completed_deals(
                self.state,
                after_event_index=last_applied_event_index,
            ),
            "event_delta": project_event_batch(
                self.state.public_events,
                after_event_index=last_applied_event_index,
            ),
            "observation": self.observation(seat),
        }
        if self.terminal:
            result["match_result"] = project_match_result(self.state)
        return result

    def submit(
        self,
        *,
        seat: int,
        client_action_id: str,
        match_ref: str,
        expected_event_index: int,
        action: Action,
    ) -> dict[str, object]:
        """Submit one client action and return an acknowledgement payload."""

        pending, immediate = self._prepare_human_submission(
            seat=seat,
            client_action_id=client_action_id,
            match_ref=match_ref,
            expected_event_index=expected_event_index,
            action=action,
        )
        if immediate is not None:
            return immediate
        if pending is None:
            raise RuntimeError("accepted action did not produce a pending submission")
        self._run_ai_until_human_or_terminal()
        return self._complete_human_submission(pending)

    async def submit_async(
        self,
        *,
        seat: int,
        client_action_id: str,
        match_ref: str,
        expected_event_index: int,
        action: Action,
        on_human_action: Callable[[], Awaitable[None]] | None = None,
        on_state_change: Callable[[], Awaitable[None]] | None = None,
        ai_action_delay_seconds: float | None = None,
    ) -> dict[str, object]:
        """Submit an action while allowing the server to pace AI turn starts."""

        pending, immediate = self._prepare_human_submission(
            seat=seat,
            client_action_id=client_action_id,
            match_ref=match_ref,
            expected_event_index=expected_event_index,
            action=action,
        )
        if immediate is not None:
            return immediate
        if pending is None:
            raise RuntimeError("accepted action did not produce a pending submission")
        if on_human_action is not None:
            await on_human_action()
        await self._run_ai_until_human_or_terminal_async(
            on_state_change=on_state_change,
            delay_seconds=ai_action_delay_seconds,
        )
        return self._complete_human_submission(pending)

    async def run_ai_async(
        self,
        *,
        on_state_change: Callable[[], Awaitable[None]] | None = None,
        ai_action_delay_seconds: float | None = None,
    ) -> None:
        """Advance AI seats with the live-action delay between every move."""

        await self._run_ai_until_human_or_terminal_async(
            on_state_change=on_state_change,
            delay_seconds=ai_action_delay_seconds,
        )

    def _prepare_human_submission(
        self,
        *,
        seat: int,
        client_action_id: str,
        match_ref: str,
        expected_event_index: int,
        action: Action,
    ) -> tuple[_PendingHumanSubmission | None, dict[str, object] | None]:
        """Validate and apply only the human action before AI continuation."""

        self._validate_submission_fields(
            seat=seat,
            client_action_id=client_action_id,
            match_ref=match_ref,
            expected_event_index=expected_event_index,
        )
        existing = self._records.get(client_action_id)
        if existing is not None:
            return None, {
                **existing.acknowledgement,
                "status": "duplicate",
                "event_batch": project_event_batch(
                    self.state.public_events,
                    after_event_index=expected_event_index,
                ),
            }

        if match_ref != self.match_ref:
            return None, self._rejected(
                client_action_id,
                code="match_not_found",
                seat=seat,
            )
        if expected_event_index != self.event_cursor:
            return None, self._stale(
                client_action_id,
                seat=seat,
                expected_event_index=expected_event_index,
            )
        if action.seat != seat:
            return None, self._rejected(
                client_action_id,
                code="seat_mismatch",
                seat=seat,
            )
        if self.terminal:
            return None, self._rejected(client_action_id, code="match_complete", seat=seat)
        if self.current_actor != seat:
            return None, self._rejected(client_action_id, code="not_your_turn", seat=seat)
        if seat in self.ai_seats:
            return None, self._rejected(client_action_id, code="ai_seat", seat=seat)

        before_event_count = len(self.state.public_events)
        action_index = self._next_action_index
        try:
            self.state = apply_match_action(self.state, action)
        except EngineError:
            return None, self._rejected(
                client_action_id,
                code="illegal_action",
                seat=seat,
            )

        self._next_action_index += 1
        direct_event_batch = tuple(
            project_event_batch(
                self.state.public_events,
                after_event_index=(
                    self.state.public_events[before_event_count - 1].event_index
                    if before_event_count
                    else -1
                ),
            )
        )
        provisional_acknowledgement = self._acknowledgement(
            client_action_id=client_action_id,
            status="accepted",
            accepted_event_indices=tuple(
                item["event_index"] for item in direct_event_batch
            ),
        )
        provisional_record = AcceptedActionRecord(
            client_action_id=client_action_id,
            action_index=action_index,
            seat=seat,
            expected_event_index=expected_event_index,
            action=action_to_data(action),
            accepted_event_indices=tuple(
                item["event_index"] for item in direct_event_batch
            ),
            event_batch=direct_event_batch,
            acknowledgement=provisional_acknowledgement,
        )
        self._records[client_action_id] = provisional_record
        self._accepted_actions.append(provisional_record)
        return (
            _PendingHumanSubmission(
                client_action_id=client_action_id,
                action_index=action_index,
                seat=seat,
                expected_event_index=expected_event_index,
                action=action,
                before_event_count=before_event_count,
                direct_event_batch=direct_event_batch,
            ),
            None,
        )

    def _complete_human_submission(
        self,
        pending: _PendingHumanSubmission,
    ) -> dict[str, object]:
        event_batch = project_event_batch(
            self.state.public_events,
            after_event_index=(
                self.state.public_events[pending.before_event_count - 1].event_index
                if pending.before_event_count
                else -1
            ),
        )
        accepted_event_indices = tuple(item["event_index"] for item in event_batch)
        acknowledgement = self._acknowledgement(
            client_action_id=pending.client_action_id,
            status="accepted",
            accepted_event_indices=accepted_event_indices,
        )
        record = AcceptedActionRecord(
            client_action_id=pending.client_action_id,
            action_index=pending.action_index,
            seat=pending.seat,
            expected_event_index=pending.expected_event_index,
            action=action_to_data(pending.action),
            accepted_event_indices=accepted_event_indices,
            event_batch=pending.direct_event_batch,
            acknowledgement=acknowledgement,
        )
        self._records[pending.client_action_id] = record
        self._accepted_actions = [
            record if item.action_index == pending.action_index else item
            for item in self._accepted_actions
        ]
        return {
            **acknowledgement,
            "event_batch": event_batch,
            "observation": self.observation(pending.seat),
            **({"match_result": project_match_result(self.state)} if self.terminal else {}),
        }

    def _run_ai_until_human_or_terminal(self) -> None:
        while not self.terminal:
            self._ensure_deal_started()
            actor = self.current_actor
            if actor is None or actor not in self.ai_seats:
                return
            self._apply_ai_action(actor)

    async def _run_ai_until_human_or_terminal_async(
        self,
        *,
        on_state_change: Callable[[], Awaitable[None]] | None = None,
        delay_seconds: float | None = None,
    ) -> None:
        delay = AI_ACTION_DELAY_SECONDS if delay_seconds is None else delay_seconds
        if not isinstance(delay, (int, float)) or isinstance(delay, bool) or not 0 <= delay <= 60:
            raise ValueError("AI action delay must be numeric and in 0..60")
        while not self.terminal:
            self._ensure_deal_started()
            actor = self.current_actor
            if actor is None or actor not in self.ai_seats:
                return
            await asyncio.sleep(delay)
            self._apply_ai_action(actor)
            if on_state_change is not None:
                await on_state_change()

    def _apply_ai_action(self, actor: int) -> None:
        observation = match_observation_for(self.state, actor)
        action = self._ai_agents[actor].choose_action(observation)
        before_event_count = len(self.state.public_events)
        expected_event_index = self.event_cursor
        self.state = apply_match_action(self.state, action)
        event_batch = tuple(
            project_event_batch(
                self.state.public_events,
                after_event_index=(
                    self.state.public_events[before_event_count - 1].event_index
                    if before_event_count
                    else -1
                ),
            )
        )
        client_action_id = f"ai:{self._next_ai_action_id}"
        acknowledgement = self._acknowledgement(
            client_action_id=client_action_id,
            status="accepted",
            accepted_event_indices=tuple(
                item["event_index"] for item in event_batch
            ),
        )
        self._accepted_actions.append(
            AcceptedActionRecord(
                client_action_id=client_action_id,
                action_index=self._next_action_index,
                seat=actor,
                expected_event_index=expected_event_index,
                action=action_to_data(action),
                accepted_event_indices=tuple(
                    item["event_index"] for item in event_batch
                ),
                event_batch=event_batch,
                acknowledgement=acknowledgement,
            )
        )
        self._next_action_index += 1
        self._next_ai_action_id += 1

    def _ensure_deal_started(self) -> None:
        if self.state.phase not in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
            return
        if self.state.terminal:
            return
        deal_number = len(self.state.completed_deals)
        if deal_number < len(self._deals):
            deal = self._deals[deal_number]
        else:
            deal = generate_live_deal(dealer=self.state.dealer)
            self._deals.append(deal)
        self.state = begin_explicit_deal(self.state, deal)

    def _validate_submission_fields(
        self,
        *,
        seat: int,
        client_action_id: str,
        match_ref: str,
        expected_event_index: int,
    ) -> None:
        if type(seat) is not int or seat not in range(4):
            raise ValueError("seat must be an integer in 0..3")
        if type(client_action_id) is not str or not client_action_id.strip():
            raise ValueError("client_action_id must be a nonempty string")
        if client_action_id.startswith("ai:"):
            raise ValueError("client_action_id uses a reserved prefix")
        if type(match_ref) is not str or not match_ref:
            raise ValueError("match_ref must be a nonempty string")
        if type(expected_event_index) is not int or expected_event_index < -1:
            raise ValueError("expected_event_index must be an integer >= -1")

    def _acknowledgement(
        self,
        *,
        client_action_id: str,
        status: str,
        accepted_event_indices: tuple[int, ...] = (),
        code: str | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "accepted_event_indices": list(accepted_event_indices),
            "client_action_id": client_action_id,
            "last_event_index": self.event_cursor,
            "match_ref": self.match_ref,
            "schema_version": ACK_SCHEMA_VERSION,
            "status": status,
        }
        if code is not None:
            payload["code"] = code
        return payload

    def _rejected(self, client_action_id: str, *, code: str, seat: int) -> dict[str, object]:
        return {
            **self._acknowledgement(
                client_action_id=client_action_id,
                status="rejected",
                code=code,
            ),
            "latest_observation": self.observation(seat),
        }

    def _stale(
        self,
        client_action_id: str,
        *,
        seat: int,
        expected_event_index: int,
    ) -> dict[str, object]:
        return {
            **self._acknowledgement(
                client_action_id=client_action_id,
                status="stale",
            ),
            "latest_observation": self.observation(seat),
            "event_delta": project_event_batch(
                self.state.public_events,
                after_event_index=expected_event_index,
            ),
        }
