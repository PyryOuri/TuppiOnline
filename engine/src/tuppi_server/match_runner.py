"""Authoritative in-memory live match runner.

This module contains no network code. It owns the engine state, validates
client action envelopes, records idempotency keys, runs configured AI seats,
and returns projection-safe dictionaries to the transport layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import importlib.util
import os
import re
from typing import Any, Awaitable, Callable

from tuppi_agents import (
    RuleBasedPolicy,
    construct_registered_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_agents.void_lead import (
    BASE_PROFILE_KEY,
    VOID_LEAD_PROFILE_KEY,
    construct_void_lead_agent,
)
from tuppi_agents.sooli import SooliFallbackAgent
from tuppi_engine import (
    Action,
    EngineError,
    EnginePhase,
    ExplicitDeal,
    FirstLegalActionAgent,
    MatchState,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    explicit_deal_from_data,
    explicit_deal_to_data,
    locked_bid_options,
    match_observation_for,
    validate_match_state,
)
from tuppi_engine.serialization import action_from_data, action_to_data
from tuppi_rules import LOCKED_BID_RULESETS, SOOLI_RULESETS, SUPPORTED_RULESETS, MatchScore, RulesetId

from .contract_evaluation import (
    MAXIMUM_SAMPLES,
    evaluate_contract_choice,
    validate_contract_evaluation_record,
)
from .deal_generation import generate_live_deal
from .projection import (
    project_completed_deals,
    project_event_batch,
    project_match_result,
    project_observation,
)
from .training_analysis import generate_training_analysis


PROTOCOL_VERSION = "tuppi.network.v1"
ACK_SCHEMA_VERSION = "tuppi.network.action_acknowledgement.v1"
BIDDING_SCHEMA_VERSION = "tuppi.network.bidding.v1"
#: What a spectator sees besides the public table: every seat's cards.
TABLE_VIEW_SCHEMA_VERSION = "tuppi.network.table_view.v1"
MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v4"
HOSTED_MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v5"
#: v4/v5 plus the bids locked but not yet revealed (and this deal's discarded-
#: bid acknowledgements), so a restart keeps them. Written only while either
#: exists; bot_controllers is present for hosted bots.
BIDS_MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v6"
V3_MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v3"
PREVIOUS_MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v2"
LEGACY_MATCH_RECORD_SCHEMA_VERSION = "tuppi.server.match_record.v1"
#: The live AI. Seats play the strongest policy available, which is the
#: registered baseline plus the void-seeking NOLO lead - measured at -0.69 tricks
#: and +14 points of deal-win rate against the plain baseline, and still ahead
#: when the opponents lead the same way. See docs/valuation/void_seeking_lead.md.
DEFAULT_AI_PROFILE_KEY = VOID_LEAD_PROFILE_KEY
#: The registered profile the live AI is built on. Separate from the reported
#: identity because the Phase 4 registry is frozen by digest.
BASE_AI_PROFILE_KEY = BASE_PROFILE_KEY
#: Still accepted, so a room can deliberately request the plain baseline.
LEGACY_AI_PROFILE_KEY = BASE_PROFILE_KEY
TEST_AI_PROFILE_KEY = "first_legal_action_v1"
#: TuppiAI's best agent (the optional package ``tuppi_ai``): search over
#: sampled worlds with a learned rollout policy; plays sooli itself.
TUPPI_AI_PROFILE_KEY = "tuppi_ai_search_v1"
TUPPI_AI_WORLDS = 1024


def tuppi_ai_available() -> bool:
    return importlib.util.find_spec("tuppi_ai") is not None


def _configured_ai_delay() -> float:
    raw = os.environ.get("TUPPI_SERVER_AI_ACTION_DELAY_SECONDS", "0.5")
    try:
        delay = float(raw)
    except ValueError as exc:
        raise ValueError("TUPPI_SERVER_AI_ACTION_DELAY_SECONDS must be numeric") from exc
    if not 0.0 <= delay <= 60.0:
        raise ValueError("TUPPI_SERVER_AI_ACTION_DELAY_SECONDS must be in 0..60")
    return delay


AI_ACTION_DELAY_SECONDS = _configured_ai_delay()


def _configured_reveal_pause() -> float:
    raw = os.environ.get("TUPPI_SERVER_REVEAL_PAUSE_SECONDS", "2.5")
    try:
        pause = float(raw)
    except ValueError as exc:
        raise ValueError("TUPPI_SERVER_REVEAL_PAUSE_SECONDS must be numeric") from exc
    if not 0.0 <= pause <= 30.0:
        raise ValueError("TUPPI_SERVER_REVEAL_PAUSE_SECONDS must be in 0..30")
    return pause


#: project_target_v3: after the locked bids are revealed, the first AI move
#: waits until the clients have shown the reveal: the bids appear one by one in
#: seat order from the forehand (the first RAMI ends it), then all fade out
#: together. The client takes 0.7 s per further bid, holds 1.8 s and fades in
#: 0.4 s; the pause is REVEAL_PAUSE_SECONDS + REVEAL_STEP_SECONDS per further bid.
REVEAL_PAUSE_SECONDS = _configured_reveal_pause()
REVEAL_STEP_SECONDS = 0.7


def reveal_pause(revealed_bids: int) -> float:
    return REVEAL_PAUSE_SECONDS + REVEAL_STEP_SECONDS * max(0, revealed_bids - 1)


def _for_ruleset(agents: dict[int, object], ruleset_id: RulesetId) -> dict[int, object]:
    """Give agents without their own sooli behaviour the simple fallback.

    An agent that plays sooli itself declares ``handles_sooli = True``.
    """

    if ruleset_id not in SOOLI_RULESETS:
        return agents
    return {
        seat: agent if getattr(agent, "handles_sooli", False) else SooliFallbackAgent(agent)
        for seat, agent in agents.items()
    }


def _construct_ai_agents(
    seats: frozenset[int],
    *,
    profile_key: str,
) -> dict[int, object]:
    if profile_key == TEST_AI_PROFILE_KEY:
        return {seat: FirstLegalActionAgent() for seat in seats}
    if profile_key == TUPPI_AI_PROFILE_KEY:
        if os.environ.get("TUPPI_HOSTED_BOT") == "1":
            from .hosted_bot import hosted_agents
            return hosted_agents(seats)
        try:
            from tuppi_ai.best import best_agents
        except ImportError as exc:
            raise ValueError("the tuppi_ai package is not installed") from exc
        return best_agents(sorted(seats), worlds=TUPPI_AI_WORLDS)
    if profile_key == DEFAULT_AI_PROFILE_KEY:
        return {
            seat: construct_void_lead_agent(seat, profile_key=BASE_AI_PROFILE_KEY)
            for seat in seats
        }
    if profile_key != LEGACY_AI_PROFILE_KEY:
        raise ValueError(f"unsupported live AI profile: {profile_key}")
    specification = phase4_specifications_by_profile_key()[profile_key]
    return {
        seat: construct_registered_agent(specification, seat=seat)
        for seat in seats
    }


#: Forced plays after a concession: concede:<seat>:<tricks>:<deal number>:<n>.
CONCEDE_ID = re.compile(r"concede:([0-3]):(\d{1,2}):(\d{1,4}):(\d{1,2})")


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
    contract_evaluation: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _LockedBid:
    """project_target_v3: a human's bid, held until every human has locked.

    Kept in the private room record until the bids resolve, so a restart
    keeps it; never projected to another seat. Discarded bids are deleted.
    """

    client_action_id: str
    seat: int
    action: Action
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
        contract_rollout_samples: int = 0,
        auto_run_ai: bool = True,
        ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1,
    ) -> None:
        if ruleset_id not in SUPPORTED_RULESETS:
            raise ValueError("unsupported ruleset")
        self.ruleset_id = RulesetId(ruleset_id)
        self.state: MatchState = create_match(
            initial_score=initial_score or MatchScore(0, 0),
            initial_dealer=initial_dealer,
            match_ref=match_ref,
            ruleset_id=self.ruleset_id,
        )
        self.ai_seats = frozenset(ai_seats)
        if any(seat not in range(4) for seat in self.ai_seats):
            raise ValueError("ai_seats must contain only seats 0..3")
        self.ai_profile_key = ai_profile_key
        if (
            type(contract_rollout_samples) is not int
            or not 0 <= contract_rollout_samples <= MAXIMUM_SAMPLES
        ):
            raise ValueError("contract_rollout_samples must be in 0..64")
        self.contract_rollout_samples = contract_rollout_samples
        self._ai_agents = _for_ruleset(
            _construct_ai_agents(self.ai_seats, profile_key=self.ai_profile_key),
            self.ruleset_id,
        )
        self._records: dict[str, AcceptedActionRecord] = {}
        self._accepted_actions: list[AcceptedActionRecord] = []
        self._deals: list[ExplicitDeal] = []
        self._next_action_index = 0
        self._next_ai_action_id = 0
        self._locked_bids: dict[int, _LockedBid] = {}
        self._discarded_bid_acks: dict[str, dict[str, object]] = {}
        #: Bot seats a new player takes over when the next deal starts (the
        #: room's handover_seats), and those handed over since the room last
        #: looked (RoomManager.settle_handovers).
        self.handover_seats: frozenset[int] = frozenset()
        self.handed_over: frozenset[int] = frozenset()
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
        required_v3 = required_v2 | {"contract_rollout_samples"}
        required_v4 = required_v3 | {"ruleset_id"}
        schema_version = record.get("schema_version")
        ruleset_id = RulesetId.PROJECT_TARGET_V1
        if schema_version in {MATCH_RECORD_SCHEMA_VERSION, HOSTED_MATCH_RECORD_SCHEMA_VERSION, BIDS_MATCH_RECORD_SCHEMA_VERSION}:
            required = required_v4 | ({"bot_controllers"} if schema_version == HOSTED_MATCH_RECORD_SCHEMA_VERSION else set())
            if schema_version == BIDS_MATCH_RECORD_SCHEMA_VERSION:
                required = required_v4 | {"locked_bids", "discarded_bid_acks"} | (
                    {"bot_controllers"} if "bot_controllers" in record else set())
            ai_profile_key = record.get("ai_profile_key")
            contract_rollout_samples = record.get("contract_rollout_samples")
            action_record_version = 3
            try:
                ruleset_id = RulesetId(record.get("ruleset_id"))
            except ValueError as exc:
                raise ValueError("persisted ruleset_id is invalid") from exc
        elif schema_version == V3_MATCH_RECORD_SCHEMA_VERSION:
            required = required_v3
            ai_profile_key = record.get("ai_profile_key")
            contract_rollout_samples = record.get("contract_rollout_samples")
            action_record_version = 3
        elif schema_version == PREVIOUS_MATCH_RECORD_SCHEMA_VERSION:
            required = required_v2
            ai_profile_key = record.get("ai_profile_key")
            contract_rollout_samples = 0
            action_record_version = 2
        elif schema_version == LEGACY_MATCH_RECORD_SCHEMA_VERSION:
            required = required_v1
            ai_profile_key = TEST_AI_PROFILE_KEY
            contract_rollout_samples = 0
            action_record_version = 1
        else:
            raise ValueError("unsupported match persistence schema_version")
        if set(record) != required:
            raise ValueError("match persistence record fields are invalid")
        if not isinstance(ai_profile_key, str):
            raise ValueError("persisted ai_profile_key must be a string")
        if (
            type(contract_rollout_samples) is not int
            or not 0 <= contract_rollout_samples <= MAXIMUM_SAMPLES
        ):
            raise ValueError("persisted contract_rollout_samples is invalid")
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
        runner.ruleset_id = ruleset_id
        runner.state = create_match(
            initial_score=initial_score,
            initial_dealer=initial_dealer,
            match_ref=match_ref,
            ruleset_id=ruleset_id,
        )
        runner.ai_seats = frozenset(ai_seats_data)
        if any(seat not in range(4) for seat in runner.ai_seats):
            raise ValueError("persisted ai_seats contains an invalid seat")
        runner.ai_profile_key = ai_profile_key
        runner.contract_rollout_samples = contract_rollout_samples
        runner._ai_agents = _for_ruleset(
            _construct_ai_agents(runner.ai_seats, profile_key=runner.ai_profile_key),
            runner.ruleset_id,
        )
        runner._records = {}
        runner._accepted_actions = []
        runner._deals = deals
        runner._next_action_index = 0
        runner._next_ai_action_id = 0
        runner._locked_bids = {}
        runner._discarded_bid_acks = {}
        # The room restores its handover seats after the replay.
        runner.handover_seats = runner.handed_over = frozenset()
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
            if action_record_version == 3:
                expected_fields.add("contract_evaluation")
            if set(raw_record) != expected_fields:
                raise ValueError("persisted action record fields are invalid")
            action_index = raw_record["action_index"]
            seat = raw_record["seat"]
            expected_event_index = raw_record["expected_event_index"]
            client_action_id = raw_record["client_action_id"]
            accepted_indices = raw_record["accepted_event_indices"]
            event_batch = raw_record["event_batch"]
            acknowledgement = raw_record["acknowledgement"]
            contract_evaluation = (
                raw_record.get("contract_evaluation")
                if action_record_version == 3
                else None
            )
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
            if contract_evaluation is not None:
                contract_evaluation = validate_contract_evaluation_record(
                    contract_evaluation
                )
                declared_contract = getattr(action, "declared_contract", None)
                if (
                    contract_evaluation["seat"] != seat
                    or contract_evaluation["event_index"] != expected_event_index
                    or declared_contract is None
                    or contract_evaluation["selected_contract"]
                    != declared_contract.value
                ):
                    raise ValueError("persisted contract evaluation disagrees with action")
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
                contract_evaluation=contract_evaluation,
            )
            runner._accepted_actions.append(restored)
            if not client_action_id.startswith("ai:"):
                if client_action_id in runner._records:
                    raise ValueError("persisted client_action_id is duplicated")
                runner._records[client_action_id] = restored
            runner._next_action_index += 1
            if client_action_id.startswith("ai:"):
                runner._next_ai_action_id += 1
            if runner.state.phase is EnginePhase.DEAL_COMPLETE and len(runner.state.completed_deals) < len(deals):
                runner._ensure_deal_started()

        if tuple(public_events) != tuple(project_event_batch(runner.state.public_events)):
            raise ValueError("replayed public events differ from persisted events")
        validate_match_state(runner.state)
        if schema_version == BIDS_MATCH_RECORD_SCHEMA_VERSION:
            runner._restore_bids(record["locked_bids"], record["discarded_bid_acks"])
        if "bot_controllers" in required:
            controllers = record["bot_controllers"]
            if type(controllers) is not dict or set(controllers) != {str(s) for s in runner.ai_seats}:
                raise ValueError("persisted bot controllers have invalid seats")
            for seat, agent in runner._ai_agents.items():
                if not hasattr(agent, "restore"):
                    raise ValueError("hosted record requires the hosted bot runtime")
                agent.restore(controllers[str(seat)])
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

    def spectate(self, *, last_applied_event_index: int) -> dict[str, object]:
        """What a spectator sees (feature watch): the public table from seat
        0, as in ``reconnect`` but with no hand or actions of its own, and
        every seat's cards in ``table``. Locked bids stay unrevealed; only
        who has locked is shown."""

        result = self.reconnect(seat=0, last_applied_event_index=last_applied_event_index)
        result["observation"] = {**result["observation"], "own_hand": [], "legal_actions": []}
        result["table"] = {"hands": [self.observation(seat)["own_hand"] for seat in range(4)],
                           "schema_version": TABLE_VIEW_SCHEMA_VERSION}
        if "bidding" in result:
            result["bidding"] = {**result["bidding"], "options": [], "own_bid": None,
                                 "locked_seats": sorted(set(self._locked_bids) | set(self.ai_seats))}
        return result

    def training_analysis(self, seat: int) -> dict[str, object]:
        """Return live suit-split and card-location training odds for ``seat``.

        Built from ``seat``'s own formal observation of the current deal, so
        this is meaningful any time a deal is in progress - the caller
        (``RoomManager.training_analysis_for_session``) rejects the case
        where no deal is active.
        """

        observation = match_observation_for(self.state, seat)
        # The behavioural assumptions describe the old reference bots: off in
        # the real game (humans pick bid cards freely) and wherever TuppiAI plays.
        return generate_training_analysis(
            observation,
            with_assumptions=self.ruleset_id is RulesetId.PROJECT_TARGET_V1
            and self.ai_profile_key != TUPPI_AI_PROFILE_KEY,
        )

    def contract_evaluations_for_deal(
        self, deal_number: int
    ) -> tuple[dict[str, object], ...]:
        if type(deal_number) is not int or deal_number < 0:
            raise ValueError("deal_number must be nonnegative")
        return tuple(
            record.contract_evaluation
            for record in sorted(
                self._accepted_actions, key=lambda item: item.action_index
            )
            if record.contract_evaluation is not None
            and record.contract_evaluation["deal_number"] == deal_number
        )

    def persistence_record(self) -> dict[str, object]:
        """Return private durable material for restart recovery only."""

        record = {
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
                    "contract_evaluation": record.contract_evaluation,
                }
                for record in sorted(
                    self._accepted_actions, key=lambda item: item.action_index
                )
            ],
            "ai_seats": sorted(self.ai_seats),
            "ai_profile_key": self.ai_profile_key,
            "contract_rollout_samples": self.contract_rollout_samples,
            "deals": [explicit_deal_to_data(deal) for deal in self._deals],
            "initial_dealer": self.state.initial_dealer,
            "initial_score": [
                self.state.initial_score.team0,
                self.state.initial_score.team1,
            ],
            "match_ref": self.match_ref,
            "public_events": project_event_batch(self.state.public_events),
            "ruleset_id": self.ruleset_id.value,
            "schema_version": MATCH_RECORD_SCHEMA_VERSION,
        }
        if self._ai_agents and all(hasattr(a, "checkpoint") for a in self._ai_agents.values()):
            record["schema_version"] = HOSTED_MATCH_RECORD_SCHEMA_VERSION
            record["bot_controllers"] = {str(s): a.checkpoint() for s, a in self._ai_agents.items()}
        if self._locked_bids or self._discarded_bid_acks:
            record["schema_version"] = BIDS_MATCH_RECORD_SCHEMA_VERSION
            record["locked_bids"] = [
                {"acknowledgement": bid.acknowledgement, "action": action_to_data(bid.action),
                 "client_action_id": bid.client_action_id, "seat": bid.seat}
                for _, bid in sorted(self._locked_bids.items())
            ]
            record["discarded_bid_acks"] = dict(sorted(self._discarded_bid_acks.items()))
        return record

    def _restore_bids(self, locked: object, discarded: object) -> None:
        """Validate and restore the persisted unrevealed bids after replay."""

        if type(locked) is not list or type(discarded) is not dict:
            raise ValueError("persisted bids are invalid")
        if locked and not self.collecting_bids():
            raise ValueError("persisted locked bids outside a bidding round")
        for item in locked:
            if type(item) is not dict or set(item) != {"acknowledgement", "action", "client_action_id", "seat"}:
                raise ValueError("persisted locked bid fields are invalid")
            seat, client_action_id, ack = item["seat"], item["client_action_id"], item["acknowledgement"]
            # A bot may have taken the seat after its player locked the bid
            # (seat_bot, leave_seat): the bid still stands when bids resolve.
            if type(seat) is not int or seat not in range(4) or seat in self._locked_bids:
                raise ValueError("persisted locked bid seat is invalid")
            if (not isinstance(client_action_id, str) or not client_action_id or client_action_id.startswith("ai:")
                    or client_action_id in self._records
                    or any(bid.client_action_id == client_action_id for bid in self._locked_bids.values())):
                raise ValueError("persisted locked bid client_action_id is invalid")
            action = action_from_data(item["action"])
            if (not isinstance(action, ShowAction) or action.seat != seat
                    or action not in locked_bid_options(self.state.active_deal, seat)):
                raise ValueError("persisted locked bid is not a legal bid")
            if type(ack) is not dict or ack.get("client_action_id") != client_action_id or ack.get("status") != "accepted":
                raise ValueError("persisted locked bid acknowledgement is invalid")
            self._locked_bids[seat] = _LockedBid(client_action_id=client_action_id, seat=seat,
                                                 action=action, acknowledgement=ack)
        for client_action_id, ack in discarded.items():
            if (client_action_id in self._records or type(ack) is not dict
                    or ack.get("client_action_id") != client_action_id):
                raise ValueError("persisted discarded bid acknowledgement is invalid")
            self._discarded_bid_acks[client_action_id] = ack

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
        bidding = self.bidding(seat)
        if bidding is not None:
            result["bidding"] = bidding
        if self.terminal:
            result["match_result"] = project_match_result(self.state)
        conceded = self.conceded_deals()
        if conceded:
            result["conceded_deals"] = conceded
        return result

    # ------------------------------------------------------ locked bids (v3)

    def collecting_bids(self) -> bool:
        """project_target_v3 showing: bids are being locked, none applied yet."""

        return (
            self.ruleset_id in LOCKED_BID_RULESETS
            and not self.terminal
            and self.state.phase is EnginePhase.SHOWING
        )

    def _human_seats(self) -> frozenset[int]:
        return frozenset(range(4)) - self.ai_seats

    def bidding(self, seat: int) -> dict[str, object] | None:
        """What ``seat`` may know while bids are locked: who has locked, its
        own bid and, until it locks, its options. Never another seat's bid.
        AI seats bid blind when showing runs, so they count as locked."""

        if not self.collecting_bids():
            return None
        own = self._locked_bids.get(seat)
        options = (
            ()
            if own is not None or seat in self.ai_seats
            else locked_bid_options(self.state.active_deal, seat)
        )
        return {
            "locked_seats": sorted(set(self._locked_bids) | set(self.ai_seats)),
            "options": [action_to_data(action) for action in options],
            "own_bid": None if own is None else action_to_data(own.action),
            "schema_version": BIDDING_SCHEMA_VERSION,
        }

    def _lock_bid(
        self,
        *,
        seat: int,
        client_action_id: str,
        expected_event_index: int,
        action: Action,
    ) -> dict[str, object]:
        if seat in self.ai_seats:
            return self._rejected(client_action_id, code="ai_seat", seat=seat)
        if action.seat != seat:
            return self._rejected(client_action_id, code="seat_mismatch", seat=seat)
        if expected_event_index != self.event_cursor:
            return self._stale(client_action_id, seat=seat, expected_event_index=expected_event_index)
        if seat in self._locked_bids:
            return self._rejected(client_action_id, code="bid_already_locked", seat=seat)
        if not isinstance(action, ShowAction) or action not in locked_bid_options(self.state.active_deal, seat):
            return self._rejected(client_action_id, code="illegal_action", seat=seat)
        acknowledgement = self._acknowledgement(client_action_id=client_action_id, status="accepted")
        self._locked_bids[seat] = _LockedBid(
            client_action_id=client_action_id, seat=seat, action=action, acknowledgement=acknowledgement
        )
        return acknowledgement

    def _all_bids_locked(self) -> bool:
        return all(seat in self._locked_bids for seat in self._human_seats())

    def _resolve_locked_showing(self) -> None:
        """Apply the bids in seat order, blind, until showing resolves.

        AI seats decide at their turn from an observation that shows no bid.
        Human bids come from the lock buffer. The locked bids after the first
        RAMI are discarded unseen; only their acknowledgements are kept, for
        duplicate retries, until the next deal starts.
        """

        while self.state.phase is EnginePhase.SHOWING:
            actor = self.current_actor
            # A bid its player locked before a bot took the seat over stands.
            if actor in self.ai_seats and actor not in self._locked_bids:
                action, evaluation = self._choose_ai_action(actor)
                self._apply_ai_action(actor, action=action, contract_evaluation=evaluation)
                continue
            locked = self._locked_bids.pop(actor)
            expected_event_index = self.event_cursor
            before_event_count = len(self.state.public_events)
            self.state = apply_match_action(self.state, locked.action)
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
            indices = tuple(item["event_index"] for item in event_batch)
            acknowledgement = self._acknowledgement(
                client_action_id=locked.client_action_id,
                status="accepted",
                accepted_event_indices=indices,
            )
            record = AcceptedActionRecord(
                client_action_id=locked.client_action_id,
                action_index=self._next_action_index,
                seat=actor,
                expected_event_index=expected_event_index,
                action=action_to_data(locked.action),
                accepted_event_indices=indices,
                event_batch=event_batch,
                acknowledgement=acknowledgement,
                contract_evaluation=None,
            )
            self._records[locked.client_action_id] = record
            self._accepted_actions.append(record)
            self._next_action_index += 1
        for locked in self._locked_bids.values():
            self._discarded_bid_acks[locked.client_action_id] = locked.acknowledgement
        self._locked_bids = {}

    def _maybe_resolve_showing(self) -> bool:
        """Run a v3 showing once every human has locked. False while waiting."""

        if not self.collecting_bids():
            return True
        if not self._all_bids_locked():
            return False
        self._resolve_locked_showing()
        return True

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

        locked = self._submit_locked_bid(
            seat=seat,
            client_action_id=client_action_id,
            match_ref=match_ref,
            expected_event_index=expected_event_index,
            action=action,
        )
        if locked is not None:
            if locked.get("status") == "accepted":
                self._run_ai_until_human_or_terminal()
            return locked
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
        paused: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        """Submit an action while allowing the server to pace AI turn starts."""

        locked = self._submit_locked_bid(
            seat=seat,
            client_action_id=client_action_id,
            match_ref=match_ref,
            expected_event_index=expected_event_index,
            action=action,
        )
        if locked is not None:
            if locked.get("status") == "accepted":
                if on_human_action is not None:
                    await on_human_action()
                await self._run_ai_until_human_or_terminal_async(
                    on_state_change=on_state_change,
                    delay_seconds=ai_action_delay_seconds,
                    paused=paused,
                )
            return locked
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
            paused=paused,
        )
        return self._complete_human_submission(pending)

    async def run_ai_async(
        self,
        *,
        on_state_change: Callable[[], Awaitable[None]] | None = None,
        ai_action_delay_seconds: float | None = None,
        paused: Callable[[], bool] | None = None,
    ) -> None:
        """Advance AI seats with the live-action delay between every move."""

        await self._run_ai_until_human_or_terminal_async(
            on_state_change=on_state_change,
            delay_seconds=ai_action_delay_seconds,
            paused=paused,
        )

    def _submit_locked_bid(
        self,
        *,
        seat: int,
        client_action_id: str,
        match_ref: str,
        expected_event_index: int,
        action: Action,
    ) -> dict[str, object] | None:
        """The v3 lock path; None when the submission is not a bid to lock."""

        if not self.collecting_bids() and client_action_id not in self._discarded_bid_acks:
            return None
        self._validate_submission_fields(
            seat=seat,
            client_action_id=client_action_id,
            match_ref=match_ref,
            expected_event_index=expected_event_index,
        )
        existing = self._records.get(client_action_id)
        if existing is not None:
            return {**existing.acknowledgement, "status": "duplicate"}
        if client_action_id in self._discarded_bid_acks:
            return {**self._discarded_bid_acks[client_action_id], "status": "duplicate"}
        pending = next(
            (bid for bid in self._locked_bids.values() if bid.client_action_id == client_action_id),
            None,
        )
        if pending is not None:
            return {**pending.acknowledgement, "status": "duplicate"}
        if match_ref != self.match_ref:
            return self._rejected(client_action_id, code="match_not_found", seat=seat)
        return self._lock_bid(
            seat=seat,
            client_action_id=client_action_id,
            expected_event_index=expected_event_index,
            action=action,
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
            contract_evaluation=None,
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
            contract_evaluation=None,
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
            if not self._maybe_resolve_showing():
                return
            actor = self.current_actor
            if actor is None or actor not in self.ai_seats:
                return
            action, evaluation = self._choose_ai_action(actor)
            self._apply_ai_action(actor, action=action, contract_evaluation=evaluation)

    async def _run_ai_until_human_or_terminal_async(
        self,
        *,
        on_state_change: Callable[[], Awaitable[None]] | None = None,
        delay_seconds: float | None = None,
        paused: Callable[[], bool] | None = None,
    ) -> None:
        delay = AI_ACTION_DELAY_SECONDS if delay_seconds is None else delay_seconds
        if not isinstance(delay, (int, float)) or isinstance(delay, bool) or not 0 <= delay <= 60:
            raise ValueError("AI action delay must be numeric and in 0..60")
        revealed = 0
        while not self.terminal:
            # A host pause stops here, between committed actions: no deal
            # starts, no locked bids resolve and no bot moves until resumed.
            if paused is not None and paused():
                return
            self._ensure_deal_started()
            if self.collecting_bids():
                # All bids are taken at once when every human has locked; the
                # AI bids blind at its turn, with no pacing between bids.
                if not await asyncio.to_thread(self._maybe_resolve_showing):
                    return
                if on_state_change is not None:
                    await on_state_change()
                revealed = len(self.state.active_deal.show_actions) if self.state.active_deal else 1
                continue
            actor = self.current_actor
            if actor is None or actor not in self.ai_seats:
                return
            # The first move after a reveal waits until the revealed bids have
            # been shown, one by one, and have faded out.
            await asyncio.sleep(max(delay, reveal_pause(revealed)) if revealed else delay)
            revealed = 0
            action, evaluation = await asyncio.to_thread(self._choose_ai_action, actor)
            self._apply_ai_action(actor, action=action, contract_evaluation=evaluation)
            if on_state_change is not None:
                await on_state_change()

    def _choose_ai_action(
        self, actor: int
    ) -> tuple[Action, dict[str, object] | None]:
        observation = match_observation_for(self.state, actor)
        agent = self._ai_agents[actor]
        if observation.phase is EnginePhase.SHOWING and isinstance(agent, RuleBasedPolicy):
            decision = evaluate_contract_choice(
                observation,
                policy=agent,
                agents={
                    seat: self._ai_agents.get(seat)
                    or _construct_ai_agents(
                        frozenset({seat}), profile_key=self.ai_profile_key
                    )[seat]
                    for seat in range(4)
                },
                deal_number=len(self.state.completed_deals),
                event_index=self.event_cursor,
                sample_count=self.contract_rollout_samples,
            )
            return decision.action, decision.record
        return agent.choose_action(observation), None

    # ------------------------------------------------------- bot stand-ins

    def set_bot(self, seat: int, bot: bool) -> None:
        """From now on a bot plays this seat (or stops). Recorded moves stay
        as they are; a new bot starts from its seat's initial random state."""

        if bot and seat not in self.ai_seats:
            self._ai_agents.update(_for_ruleset(
                _construct_ai_agents(frozenset({seat}), profile_key=self.ai_profile_key), self.ruleset_id))
            self.ai_seats = frozenset(self.ai_seats | {seat})
        elif not bot and seat in self.ai_seats:
            self.ai_seats = frozenset(self.ai_seats - {seat})
            self._ai_agents.pop(seat, None)

    # ------------------------------------------------------------ concession

    def concede_available(self) -> bool:
        """The deal's result is already 0-0: the team that is behind wins it.

        In the rising score a deal won by the team behind resets the match to
        0-0 whatever its points. That is certain once, in NOLO, the team ahead
        has 7 tricks (the fewer tricks win), or, in RAMI, the team behind has
        7 (it made its RAMI or stole the other's). Normal trick play only, not
        sooli.
        """

        if self.terminal or self.state.phase is not EnginePhase.TRICK_PLAY or self.state.active_deal is None:
            return False
        observation = match_observation_for(self.state, 0)
        up = observation.match_score.up_team
        if up is None or observation.contract is None:
            return False
        ahead, behind = observation.team_tricks[up.value], observation.team_tricks[1 - up.value]
        return (ahead >= 7) if observation.contract.value == "NOLO" else (behind >= 7)

    def conceded_deals(self) -> list[dict[str, object]]:
        """Conceded deals, from the forced plays' action ids (see concede)."""

        found: dict[int, dict[str, object]] = {}
        for record in self._accepted_actions:
            match = CONCEDE_ID.fullmatch(record.client_action_id)
            if match and int(match[3]) not in found:
                found[int(match[3])] = {"after_tricks": int(match[2]), "deal_number": int(match[3]), "seat": int(match[1])}
        return [found[key] for key in sorted(found)]

    def concede(self, *, seat: int) -> bool:
        """Finish a decided deal at once: every seat plays its first legal card.

        Bots are not asked (their random state is untouched), and the plays
        are ordinary accepted actions, so restarts replay them exactly. Their
        ids, concede:<seat>:<tricks so far>:<deal number>:<n>, mark the deal
        as conceded in the history.
        """

        if not self.concede_available():
            return False
        deal_number = len(self.state.completed_deals)  # 0-based, as in DealResult
        tricks = sum(match_observation_for(self.state, 0).team_tricks)
        n = 0
        while self.state.phase is EnginePhase.TRICK_PLAY and len(self.state.completed_deals) == deal_number:
            actor = self.state.current_actor
            action = match_observation_for(self.state, actor).legal_actions[0]
            self._apply_ai_action(actor, action=action, client_action_id=f"concede:{seat}:{tricks}:{deal_number}:{n}")
            n += 1
        return True

    def _apply_ai_action(
        self,
        actor: int,
        *,
        action: Action | None = None,
        contract_evaluation: dict[str, object] | None = None,
        client_action_id: str | None = None,
    ) -> None:
        if action is None:
            action, contract_evaluation = self._choose_ai_action(actor)
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
        forced = client_action_id is not None
        client_action_id = client_action_id or f"ai:{self._next_ai_action_id}"
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
                contract_evaluation=contract_evaluation,
            )
        )
        self._next_action_index += 1
        if forced:
            self._records[client_action_id] = self._accepted_actions[-1]
        else:
            self._next_ai_action_id += 1

    def _ensure_deal_started(self) -> None:
        if self.state.phase not in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
            return
        if self.state.terminal:
            return
        deal_number = len(self.state.completed_deals)
        # A discarded bid's duplicate retry is answered only within its deal.
        self._discarded_bid_acks = {}
        if deal_number < len(self._deals):
            deal = self._deals[deal_number]
        else:
            deal = generate_live_deal(dealer=self.state.dealer)
            self._deals.append(deal)
        self.state = begin_explicit_deal(self.state, deal)
        for seat in self.handover_seats:
            self.set_bot(seat, False)
        self.handed_over |= self.handover_seats
        self.handover_seats = frozenset()

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
