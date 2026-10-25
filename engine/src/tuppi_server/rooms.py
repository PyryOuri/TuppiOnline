"""Private-room lifecycle with optional restart-safe match persistence."""

from __future__ import annotations

import asyncio
import hashlib

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import string

from .analysis import (
    AnalysisProjectionError,
    COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
    POST_MATCH_ANALYSIS_SCHEMA_VERSION,
    project_post_match_analysis,
    RecordedDecisionAnalysis,
    validate_post_match_analysis_response,
)
from .completed_deal_review import (
    BOT_REPLAY_POLICY_ID,
    generate_completed_deal_review,
    validate_completed_deal_review_against_runner,
)
from .match_runner import (
    AI_ACTION_DELAY_SECONDS,
    DEFAULT_AI_PROFILE_KEY,
    TUPPI_AI_PROFILE_KEY,
    BOT_DISPLAY_NAMES,
    HEIDI_LITE_PROFILE_KEY,
    HEIDI_LITE_PROFILE_KEYS,
    HEIDI_SEARCH_PROFILE_KEY,
    HEIDI_SEARCH_PROFILE_KEYS,
    HEIDI12_PROFILE_KEY,
    NELLI11_PROFILE_KEY,
    LiveMatchRunner,
    tuppi_ai_available,
)
from .deal_review import DealReviewError, generate_deal_review
from .sooli_training_analysis import (
    SooliTrainingAnalysisError,
    generate_sooli_training_analysis,
)
from .real_game_deal_analysis import (
    REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION,
    REAL_GAME_RULESETS,
    RealGameAnalysisError,
    bot_policy_for,
    generate_real_game_deal_analysis,
    validate_real_game_deal_analysis,
)
from .post_match_diagnostics import generate_post_match_diagnostics
from .persistence import (
    LEGACY_ROOM_RECORD_SCHEMA_VERSION,
    MULTI_MATCH_ROOM_RECORD_SCHEMA_VERSION,
    OPEN_SEATS_ROOM_RECORD_SCHEMA_VERSION,
    HEIDI_ROOM_RECORD_SCHEMA_VERSION,
    HEIDI_SEARCH_ROOM_RECORD_SCHEMA_VERSION,
    ROOM_RECORD_SCHEMA_VERSION,
    RULESET_ROOM_RECORD_SCHEMA_VERSION,
    FileRoomStore,
    PersistenceError,
)
from .results import ResultRejected, Results, today as results_today
from .research import DEFAULT_MAX_RECORD_BYTES, MatchRecords, finished_deal_records, online_record
from .leaderboard import LEADERBOARD_RESPONSE_SCHEMA_VERSION, Leaderboard
from .projection import project_event_batch, project_match_result
from tuppi_engine import match_observation_for
from tuppi_rules import SUPPORTED_RULESETS, RulesetId

#: The analysis endpoints are built for project_target_v1 deals.
ANALYSIS_RULESETS = frozenset({RulesetId.PROJECT_TARGET_V1})
SOOLI_PHASE_NAMES = frozenset({"SOOLI_OFFER", "SOOLI_GIVE", "SOOLI_RETURN", "SOOLI_PLAY"})


def configured_ruleset() -> RulesetId:
    """The live server's ruleset for new rooms: ``TUPPI_SERVER_RULESET``,
    default ``project_target_v3`` (the real game). ``RoomManager()`` itself
    defaults to v1 for tests and embedded use."""

    raw = os.environ.get("TUPPI_SERVER_RULESET", RulesetId.PROJECT_TARGET_V3.value)
    try:
        ruleset = RulesetId(raw)
    except ValueError as exc:
        raise ValueError(f"TUPPI_SERVER_RULESET is not a ruleset: {raw!r}") from exc
    if ruleset not in SUPPORTED_RULESETS:
        raise ValueError(f"unsupported ruleset {raw!r}")
    return ruleset


class RoomError(Exception):
    """A user-facing room operation failed."""


AI_ACTION_DELAY_OPTIONS_MS = (
    0,
    500,
    1000,
    1500,
    2000,
    2500,
    3000,
    4000,
    5000,
)
DEFAULT_AI_ACTION_DELAY_MS = min(
    AI_ACTION_DELAY_OPTIONS_MS,
    key=lambda value: abs(value - round(AI_ACTION_DELAY_SECONDS * 1000)),
)
#: People watching one room at most (feature watch).
MAX_SPECTATORS = 8
#: Earlier results a room keeps after rematches (summaries only).
MAX_PREVIOUS_MATCHES = 10
_PREVIOUS_MATCH_FIELDS = frozenset({"deals", "final_score", "match_ref", "winner_team"})
#: Profiles a room records and shows by key (room records v6 and v7).
HEIDI_PROFILE_KEYS = HEIDI_LITE_PROFILE_KEYS | HEIDI_SEARCH_PROFILE_KEYS
#: The bot named in research results and match records (the browser's bot ids;
#: the online Nelli 1.0 and Heidi 1.1 keep their earlier ids heidi05 and heidi10).
RESEARCH_BOT_IDS = {HEIDI_LITE_PROFILE_KEY: "heidi05", HEIDI_SEARCH_PROFILE_KEY: "heidi10",
                    NELLI11_PROFILE_KEY: "nelli11", HEIDI12_PROFILE_KEY: "heidi12"}


@dataclass(slots=True)
class Session:
    token: str
    seat: int
    display_name: str
    ready: bool = False


@dataclass(slots=True)
class Room:
    code: str
    host_token: str
    sessions: dict[str, Session] = field(default_factory=dict)
    ai_seats: set[int] = field(default_factory=set)
    runner: LiveMatchRunner | None = None
    lifecycle: str = "created"
    post_match_analysis: dict[str, object] | None = None
    completed_deal_analyses: dict[tuple[int, int], dict[str, object]] = field(
        default_factory=dict
    )
    deal_reviews: dict[tuple[int, int], dict[str, object]] = field(default_factory=dict)
    ai_action_delay_ms: int = DEFAULT_AI_ACTION_DELAY_MS
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1
    ai_profile_key: str = DEFAULT_AI_PROFILE_KEY
    #: 0 for the room's first match; each rematch increments it.
    match_index: int = 0
    #: Host pause: no bot moves, deal starts or human moves until resumed.
    paused: bool = False
    previous_matches: list[dict[str, object]] = field(default_factory=list)
    #: During a match: seats a player left, a bot plays them and anyone may
    #: join them (taking over when the next deal starts).
    open_seats: set[int] = field(default_factory=set)
    #: People watching (feature watch): credential -> name, in arrival order.
    #: Memory only: after a restart a spectator's app asks to watch again.
    spectators: dict[str, str] = field(default_factory=dict)

    def match_ref(self) -> str:
        """The current match's identity; a rematch gets a new one."""

        base = f"room-{self.code.lower()}"
        return base if self.match_index == 0 else f"{base}-{self.match_index + 1}"

    def multi_match(self) -> bool:
        return bool(self.match_index or self.paused or self.previous_matches)

    def session_for_seat(self, seat: int) -> Session | None:
        return next((item for item in self.sessions.values() if item.seat == seat), None)

    def host_seat(self) -> int:
        return self.sessions[self.host_token].seat

    def handover_seats(self) -> frozenset[int]:
        return frozenset() if self.runner is None else self.runner.handover_seats

    def open_seats_record(self) -> bool:
        """The room needs record v5: a seat left in a match, or another host."""

        return bool(self.open_seats or self.handover_seats() or self.host_seat() != 0 or 0 in self.ai_seats)

    def snapshot(self) -> dict[str, object]:
        seats: list[dict[str, object]] = []
        for seat in range(4):
            if seat in self.ai_seats:
                covered = self.session_for_seat(seat)
                profile_key = (
                    self.ai_profile_key
                    if self.runner is None
                    else self.runner.ai_profile_key
                )
                seats.append(
                    {
                        "agent_profile": profile_key,
                        # Display names only; profile keys stay as stored (Nelli 1.0 was
                        # Heidi 0.5, Heidi 1.1 was Heidi 1.0; the same bots). Nelli 1.1
                        # and Heidi 1.2 are the same bots on the new base network.
                        "display_name": BOT_DISPLAY_NAMES.get(profile_key, "Tuppi partner AI"),
                        "kind": "ai",
                        "ready": True,
                        "seat": seat,
                        # A bot standing in for a player who is away, or
                        # for one who joins when the next deal starts.
                        **({"covering": covered.display_name} if covered is not None else {}),
                        **({"joining": True} if seat in self.handover_seats() else {}),
                        # A seat its player left during the match: free to join.
                        **({"vacant": True} if seat in self.open_seats else {}),
                    }
                )
                continue
            session = self.session_for_seat(seat)
            seats.append(
                {
                    "display_name": None if session is None else session.display_name,
                    "kind": "human" if session is not None else "open",
                    "ready": False if session is None else session.ready,
                    "seat": seat,
                }
            )
        snapshot: dict[str, object] = {
            "ai_action_delay_ms": self.ai_action_delay_ms,
            "host_seat": self.host_seat(),
            "lifecycle": self.lifecycle,
            "room_code": self.code,
            "seats": seats,
        }
        if self.ruleset_id is not RulesetId.PROJECT_TARGET_V1:
            snapshot["ruleset_id"] = self.ruleset_id.value
        if self.ai_profile_key in HEIDI_PROFILE_KEYS:
            snapshot["bot_profile"] = self.ai_profile_key
        if self.paused:
            snapshot["paused"] = True
        if self.match_index:
            snapshot["match_number"] = self.match_index + 1
        if self.previous_matches:
            snapshot["previous_matches"] = deepcopy(self.previous_matches)
        return snapshot

    def persistence_record(self) -> dict[str, object]:
        """Return private room/session/match material for the file store."""

        record: dict[str, object] = {
            "ai_action_delay_ms": self.ai_action_delay_ms,
            "ai_seats": sorted(self.ai_seats),
            "host_token": self.host_token,
            "lifecycle": self.lifecycle,
            "room_code": self.code,
            "schema_version": ROOM_RECORD_SCHEMA_VERSION,
            "sessions": [
                {
                    "display_name": session.display_name,
                    "ready": session.ready,
                    "seat": session.seat,
                    "token": session.token,
                }
                for session in sorted(self.sessions.values(), key=lambda item: item.seat)
            ],
            "runner": (
                None if self.runner is None else self.runner.persistence_record()
            ),
        }
        if self.ruleset_id is not RulesetId.PROJECT_TARGET_V1:
            record["schema_version"] = RULESET_ROOM_RECORD_SCHEMA_VERSION
            record["ruleset_id"] = self.ruleset_id.value
        if self.multi_match() or self.open_seats_record():
            record.update(schema_version=MULTI_MATCH_ROOM_RECORD_SCHEMA_VERSION,
                ruleset_id=self.ruleset_id.value, match_index=self.match_index,
                paused=self.paused, previous_matches=deepcopy(self.previous_matches))
        if self.open_seats_record():
            record.update(schema_version=OPEN_SEATS_ROOM_RECORD_SCHEMA_VERSION,
                open_seats=sorted(self.open_seats), handover_seats=sorted(self.handover_seats()))
        if self.ai_profile_key in HEIDI_PROFILE_KEYS:
            # v6 binds a lite C1H profile (Nelli 1.0 or 1.1), v7 a search profile
            # (Heidi 1.1 or 1.2); the fields are the same for both keys of each.
            schema = HEIDI_ROOM_RECORD_SCHEMA_VERSION if self.ai_profile_key in HEIDI_LITE_PROFILE_KEYS else HEIDI_SEARCH_ROOM_RECORD_SCHEMA_VERSION
            record.update(schema_version=schema, ai_profile_key=self.ai_profile_key,
                ruleset_id=self.ruleset_id.value, match_index=self.match_index, paused=self.paused,
                previous_matches=deepcopy(self.previous_matches), open_seats=sorted(self.open_seats),
                handover_seats=sorted(self.handover_seats()))
        return record


class RoomManager:
    """Own rooms and opaque reconnect credentials.

    ``RoomManager()`` remains in-memory for tests and fixture usage.  The
    running server uses ``from_environment()`` to enable the local durable
    store without requiring PostgreSQL or Redis.
    """

    def __init__(
        self,
        persistence_dir: str | Path | None = None,
        *,
        contract_rollout_samples: int = 0,
        ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1,
        ai_profile_key: str = DEFAULT_AI_PROFILE_KEY,
    ) -> None:
        self._rooms: dict[str, Room] = {}
        self._ai_profile_key = ai_profile_key
        #: Optional after-deal reviewer (``tuppi_server.deal_review.DealReviewer``),
        #: installed by a deployment that has a bot able to re-decide positions.
        self.deal_reviewer = None
        #: Optional sooli layout sampler (``tuppi_server.sooli_training_analysis``)
        #: for the live odds tool during a sooli deal.
        self.sooli_odds = None
        if ruleset_id not in SUPPORTED_RULESETS:
            raise ValueError("unsupported ruleset")
        self._ruleset_id = RulesetId(ruleset_id)
        if (
            type(contract_rollout_samples) is not int
            or not 0 <= contract_rollout_samples <= 64
        ):
            raise ValueError("contract_rollout_samples must be in 0..64")
        self._contract_rollout_samples = contract_rollout_samples
        self._store = (
            None if persistence_dir is None else FileRoomStore(persistence_dir)
        )
        #: Set when a room could not be saved: the server must stop accepting
        #: changes, because in-memory state is ahead of what is durable.
        self.storage_failed = False
        #: Executor for persist_async (see there); None saves on the caller.
        self.save_executor = None
        self.leaderboard = Leaderboard(None if self._store is None else self._store.root / "leaderboard.json")
        self.results = Results(None if self._store is None else self._store.root)
        # Anonymous match records for developing the bots (research.py).
        self.records = MatchRecords(None if self._store is None else self._store.root,
                                    int(float(os.environ.get("TUPPI_RESEARCH_MAX_MB") or 0) * 2**20) or DEFAULT_MAX_RECORD_BYTES)
        #: Which trained bot played (set by the hosted server), for the records.
        self.bot_version: str | None = None
        if self._store is not None:
            self._store.remove_stale_temporaries()
            self._load_persisted_rooms()
            # Count matches that finished just before a crash (idempotent).
            for room in self._rooms.values():
                self.record_finished_match(room)

    @classmethod
    def from_environment(cls) -> "RoomManager":
        configured = os.environ.get("TUPPI_SERVER_DATA_DIR")
        root = (
            Path(configured).expanduser()
            if configured
            else Path.home() / "Library" / "Application Support" / "Tuppi" / "server"
        )
        raw_samples = os.environ.get("TUPPI_CONTRACT_ROLLOUT_SAMPLES", "8")
        try:
            samples = int(raw_samples)
        except ValueError as exc:
            raise ValueError("TUPPI_CONTRACT_ROLLOUT_SAMPLES must be an integer") from exc
        profile = os.environ.get(
            "TUPPI_SERVER_AI_PROFILE",
            TUPPI_AI_PROFILE_KEY if tuppi_ai_available() else DEFAULT_AI_PROFILE_KEY,
        )
        manager = cls(root, contract_rollout_samples=samples, ruleset_id=configured_ruleset(),
                      ai_profile_key=profile)
        if profile == TUPPI_AI_PROFILE_KEY and os.environ.get("TUPPI_SERVER_REVIEW", "1") == "1":
            # The after-deal review uses the same bot's search.
            from tuppi_ai.review import ServerReviewer

            manager.deal_reviewer = ServerReviewer()
        if profile == TUPPI_AI_PROFILE_KEY and os.environ.get("TUPPI_SERVER_SOOLI_ODDS", "1") == "1":
            # Live odds during sooli use the same bot's sooli sampler.
            from tuppi_ai.sooli_odds import SooliOdds

            manager.sooli_odds = SooliOdds()
        return manager

    def create_room(
        self,
        *,
        display_name: str,
        ai_seats: frozenset[int] = frozenset(),
        bot_profile: str | None = None,
    ) -> tuple[Room, Session]:
        name = self._validate_name(display_name)
        self._validate_ai_seats(ai_seats)
        # Nelli 1.0 and Heidi 1.1 stay accepted (an older client may still ask
        # for them); new clients are offered Nelli 1.1 and Heidi 1.2.
        if bot_profile is not None and (self._ai_profile_key != TUPPI_AI_PROFILE_KEY or
                bot_profile not in {TUPPI_AI_PROFILE_KEY, *HEIDI_PROFILE_KEYS}):
            raise RoomError("invalid_bot_profile")
        if bot_profile in HEIDI_SEARCH_PROFILE_KEYS:
            from .hosted_bot import heidi_enabled
            if not heidi_enabled():
                raise RoomError("invalid_bot_profile")
        code = self._new_code()
        host_token = self._new_token()
        room = Room(code=code, host_token=host_token, ai_seats=set(ai_seats), ruleset_id=self._ruleset_id,
                    ai_profile_key=self._ai_profile_key if bot_profile is None else bot_profile)
        session = Session(token=host_token, seat=0, display_name=name)
        room.sessions[host_token] = session
        room.lifecycle = "configured" if ai_seats else "waiting"
        self._rooms[code] = room
        self.persist(room)
        return room, session

    def join_room(self, *, code: str, display_name: str, seat: object = None) -> tuple[Room, Session]:
        """Join the chosen free seat, or the lowest free one.

        During a match only a seat its player left can be joined: the bot
        finishes the current deal and the newcomer plays from the next one.
        """

        room = self.get(code)
        playing = room.runner is not None
        if playing and (room.runner.terminal or not room.open_seats):
            raise RoomError("settings_locked")
        name = self._validate_name(display_name)
        open_seats = sorted(room.open_seats) if playing else [
            seat
            for seat in range(4)
            if seat not in room.ai_seats and room.session_for_seat(seat) is None
        ]
        if not open_seats:
            raise RoomError("room_full")
        if seat is not None and (type(seat) is not int or seat not in open_seats):
            raise RoomError("seat_taken")
        token = self._new_token()
        session = Session(token=token, seat=open_seats[0] if seat is None else seat, display_name=name)
        room.sessions[token] = session
        if playing:
            room.open_seats.discard(session.seat)
            room.runner.handover_seats |= {session.seat}
        else:
            for item in room.sessions.values():
                item.ready = False
            room.lifecycle = "waiting"
        self.persist(room)
        return room, session

    def watch_room(self, *, code: str, display_name: str, connected=lambda token: True) -> tuple[Room, str]:
        """Watch a room (feature watch), before or during a match: everyone's
        cards and the chat, no seat. Returns the room and a credential. A
        full room first forgets spectators who are not connected (their app
        asks to watch again when it comes back)."""

        room = self.get(code)
        name = self._validate_name(display_name)
        if len(room.spectators) >= MAX_SPECTATORS:
            for token in [token for token in room.spectators if not connected(token)]:
                del room.spectators[token]
        if len(room.spectators) >= MAX_SPECTATORS:
            raise RoomError("watchers_full")
        token = self._new_token()
        room.spectators[token] = name
        return room, token

    def spectator(self, *, code: str, token: str) -> tuple[Room, str]:
        room = self.get(code)
        name = room.spectators.get(token)
        if name is None:
            raise RoomError("invalid_session")
        return room, name

    def stop_watching(self, *, code: str, token: str) -> Room:
        room, _ = self.spectator(code=code, token=token)
        del room.spectators[token]
        return room

    def set_ai_seats(
        self,
        *,
        code: str,
        host_token: str,
        ai_seats: frozenset[int],
    ) -> Room:
        room = self.get(code)
        if room.host_token != host_token:
            raise RoomError("host_required")
        if room.runner is not None:
            raise RoomError("settings_locked")
        self._validate_ai_seats(ai_seats, host_seat=room.host_seat())
        for seat in ai_seats:
            if room.session_for_seat(seat) is not None:
                raise RoomError("seat_occupied")
        room.ai_seats = set(ai_seats)
        for item in room.sessions.values():
            item.ready = False
        room.lifecycle = "configured"
        self.persist(room)
        return room

    def seat_preview(self, code: str) -> dict[str, object]:
        """Before joining: who sits where (names and kinds only), to choose a seat."""

        room = self.get(code)
        playing = room.runner is not None
        # During a match the seats players left are the free ones.
        seats = [{"display_name": seat["display_name"] if seat["kind"] == "human" else None,
                  "kind": "open" if seat["seat"] in room.open_seats else seat["kind"], "seat": seat["seat"]}
                 for seat in room.snapshot()["seats"]]
        joinable = not playing or (not room.runner.terminal and bool(room.open_seats))
        return {"host_seat": room.host_seat(), "joinable": joinable, "room_code": room.code, "seats": seats}

    def swap_seats(self, *, code: str, host_token: str, seats: object, movable) -> tuple[Room, dict[str, int]]:
        """The host swaps two of the other seats before a match: players, bots
        or free seats. A player can be moved only if `movable(token)` (their app
        takes the new seat). Readiness is cleared. Returns the moved players'
        new seats.
        """

        room = self.get(code)
        if room.host_token != host_token:
            raise RoomError("host_required")
        if room.runner is not None:
            raise RoomError("settings_locked")
        if (type(seats) is not list or len(seats) != 2 or any(
                type(s) is not int or not 0 <= s <= 3 or s == room.host_seat() for s in seats)
                or seats[0] == seats[1]):
            raise RoomError("invalid_seats")
        a, b = seats
        players = {s: room.session_for_seat(s) for s in (a, b)}
        if any(p is not None and not movable(p.token) for p in players.values()):
            raise RoomError("player_cannot_move")
        moved = {}
        for here, there in ((a, b), (b, a)):
            if players[here] is not None:
                players[here].seat = there
                moved[players[here].token] = there
        bots = {s for s in (a, b) if s in room.ai_seats}
        room.ai_seats -= bots
        room.ai_seats |= {b if s == a else a for s in bots}
        for item in room.sessions.values():
            item.ready = False
        room.lifecycle = "configured" if room.ai_seats else "waiting"
        self.persist(room)
        return room, moved

    def rename(self, *, code: str, token: str, display_name: str) -> Room:
        """A player changes their own nickname before the match starts.

        Names are fixed while a match is played: the leaderboard credits the
        names seated when it finishes.
        """

        room = self.get(code)
        session = self._session(room, token)
        if room.runner is not None:
            raise RoomError("settings_locked")
        session.display_name = self._validate_name(display_name)
        self.persist(room)
        return room

    def release_seat(self, *, code: str, host_token: str, seat: object) -> tuple[Room, str]:
        """The host frees another player's seat before the match starts.

        For a seat its player has left for good, e.g. after rejoining under a
        new name or from another device, which would otherwise never be ready.
        Returns the room and the released session token (no longer valid).
        """

        room = self.get(code)
        if room.host_token != host_token:
            raise RoomError("host_required")
        if room.runner is not None:
            raise RoomError("settings_locked")
        session = room.session_for_seat(seat) if type(seat) is int and 0 <= seat <= 3 else None
        if session is None or session.token == room.host_token:
            raise RoomError("seat_not_releasable")
        del room.sessions[session.token]
        for item in room.sessions.values():
            item.ready = False
        room.lifecycle = "waiting"
        self.persist(room)
        return room, session.token

    def set_seat_bot(self, *, code: str, token: str, seat: object, bot: bool, connected) -> Room:
        """During a match, a bot plays for a player who is away (the host
        asks, only while that player is not connected); the player or the
        host takes the seat back. The player keeps their seat and session.
        """

        room = self.get(code)
        self._session(room, token)
        runner = room.runner
        if runner is None or runner.terminal:
            raise RoomError("match_not_active")
        player = room.session_for_seat(seat) if type(seat) is int and 0 <= seat <= 3 else None
        if player is None or type(bot) is not bool:
            raise RoomError("seat_not_coverable")
        if bot:
            if token != room.host_token:
                raise RoomError("host_required")
            if player.token == room.host_token:
                raise RoomError("seat_not_coverable")
            if seat in room.ai_seats:
                return room
            if connected(player.token):
                raise RoomError("player_connected")
            runner.set_bot(seat, True)
            room.ai_seats.add(seat)
        else:
            if token not in (room.host_token, player.token):
                raise RoomError("host_required")
            if seat not in room.ai_seats:
                return room
            if seat in runner.handover_seats:
                # A newcomer plays from the next deal; the bot finishes this one.
                raise RoomError("seat_not_coverable")
            runner.set_bot(seat, False)
            room.ai_seats.discard(seat)
        self.persist(room)
        return room

    def leave_seat(self, *, code: str, token: str, connected) -> tuple[Room, bool]:
        """A player leaves the room for good; their credential stops working.

        Before a match the seat becomes free. During a match a bot plays it
        from now on and anyone may join it, playing from the next deal. If
        the host leaves, the next player hosts (a connected one first). The
        last player to leave closes the room. Returns the room and whether
        it closed.
        """

        room = self.get(code)
        session = self._session(room, token)
        others = sorted((item for item in room.sessions.values() if item.token != token),
                        key=lambda item: (not connected(item.token), item.seat in room.ai_seats, item.seat))
        if not others:
            if room.runner is not None and not room.runner.terminal:
                self.record_match(room)  # the deals played so far
            del self._rooms[room.code]
            if self._store is not None:
                try:
                    self._store.archive_room(room.code)
                except PersistenceError:
                    self.storage_failed = True
            return room, True
        del room.sessions[token]
        if room.host_token == token:
            room.host_token = others[0].token
        runner = room.runner
        if runner is None:
            for item in room.sessions.values():
                item.ready = False
            room.lifecycle = "waiting"
        else:
            runner.handover_seats -= {session.seat}
            if not runner.terminal and session.seat not in room.ai_seats:
                runner.set_bot(session.seat, True)
                room.ai_seats.add(session.seat)
            if session.seat in room.ai_seats:
                room.open_seats.add(session.seat)
        self.persist(room)
        return room, False

    def settle_handovers(self, room: Room) -> bool:
        """Seats the runner handed to their new players at a deal start stop
        being bot seats in the room too. Returns whether any did."""

        runner = room.runner
        if runner is None or not runner.handed_over:
            return False
        room.ai_seats -= runner.handed_over
        runner.handed_over = frozenset()
        self.persist(room)
        return True

    def set_ai_action_delay(
        self,
        *,
        code: str,
        host_token: str,
        ai_action_delay_ms: int,
    ) -> Room:
        """Update host-controlled AI pacing before the match starts."""

        room = self.get(code)
        if room.host_token != host_token:
            raise RoomError("host_required")
        if room.runner is not None:
            raise RoomError("settings_locked")
        if (
            type(ai_action_delay_ms) is not int
            or ai_action_delay_ms not in AI_ACTION_DELAY_OPTIONS_MS
        ):
            raise RoomError("invalid_ai_action_delay")
        room.ai_action_delay_ms = ai_action_delay_ms
        self.persist(room)
        return room

    def mark_ready(
        self,
        *,
        code: str,
        token: str,
        auto_run_ai: bool = True,
    ) -> Room:
        room = self.get(code)
        session = self._session(room, token)
        if room.runner is not None:
            return room
        session.ready = True
        if self._ready_to_start(room):
            room.runner = LiveMatchRunner(
                match_ref=room.match_ref(),
                ai_seats=frozenset(room.ai_seats),
                contract_rollout_samples=self._contract_rollout_samples,
                auto_run_ai=auto_run_ai,
                ruleset_id=room.ruleset_id,
                ai_profile_key=room.ai_profile_key,
            )
            room.lifecycle = "playing"
        else:
            room.lifecycle = "ready"
        self.persist(room)
        return room

    def set_paused(self, *, code: str, host_token: str, paused: bool) -> Room:
        """Host pause/resume of a match in progress. Idempotent.

        Callers hold the room's lock, so a pause lands between committed
        actions: bots finish the replies already running, then nothing moves
        (no bot move, deal start or human move) until the host resumes.
        Locked but unrevealed bids stay locked.
        """

        room = self.get(code)
        if room.host_token != host_token:
            raise RoomError("host_required")
        if room.runner is None or room.runner.terminal:
            raise RoomError("match_not_active")
        if room.paused != paused:
            room.paused = paused
            self.persist(room)
        return room

    def record_finished_match(self, room: Room) -> bool:
        """Credit a finished match's human seats on the leaderboard, once."""

        runner = room.runner
        if runner is None or not runner.terminal or not runner._deals:
            return False
        seats = {s.seat: s.display_name for s in room.sessions.values() if s.seat not in room.ai_seats}
        key = f"{runner.match_ref}:{runner._deals[0].deal_id}"
        result = project_match_result(runner.state)
        if seats:
            # Research row (no names or codes); best effort, never stops play.
            people = [sum(1 for seat in seats if seat % 2 == team) for team in (0, 1)]
            try:
                self.results.record({"bot": RESEARCH_BOT_IDS.get(
                    runner.ai_profile_key, os.environ.get("TUPPI_HOSTED_BOT_LEVEL") or "server"),
                    "conceded": len(runner.conceded_deals()), "day": results_today(),
                    "deals": len(runner.state.completed_deals), "final_score": list(result["final_score"]),
                    "id": "online-" + hashlib.sha256(key.encode()).hexdigest()[:32], "source": "online",
                    "team_humans": people, "winner_team": result["winner_team"]})
            except (ResultRejected, PersistenceError):
                pass
        self.record_match(room)
        try:
            return self.leaderboard.record(match_key=key, seats=seats, winner_team=result["winner_team"])
        except PersistenceError:
            self.storage_failed = True
            raise

    def record_match(self, room: Room) -> None:
        """Save the match's anonymous record (research.py): when it finishes,
        or when the room closes or expires unfinished. Best effort; a failure
        never stops play."""

        if room.runner is None:
            return
        try:
            profile = room.runner.ai_profile_key
            heidi = RESEARCH_BOT_IDS.get(profile)
            version = (profile + ":" + self.bot_version.split(":", 1)[-1]) if heidi and self.bot_version else self.bot_version
            if profile in HEIDI_SEARCH_PROFILE_KEYS:
                from .hosted_bot import heidi_identity
                version = profile + ":" + heidi_identity()[:12]
            record = online_record(room.runner, bot=heidi or os.environ.get("TUPPI_HOSTED_BOT_LEVEL") or "server",
                                   day=results_today(), bot_version=version)
            if record is not None:
                self.records.save(record, replace=True)
        except (PersistenceError, ValueError, KeyError, IndexError, TypeError):
            pass

    def leaderboard_for_session(self, *, code: str, token: str) -> dict[str, object]:
        """The server's standings, for anyone holding a seat in one of its rooms."""

        self.session(code=code, token=token)
        return {"entries": self.leaderboard.standings(), "schema_version": LEADERBOARD_RESPONSE_SCHEMA_VERSION}

    def start_rematch(self, *, code: str, host_token: str) -> Room:
        """Reopen a finished room for a new match with the same seats.

        The finished match's result is kept as a summary. Readiness is
        cleared so everyone confirms the (editable) bot seats again; the next
        match gets a new identity and new bot controllers when it starts.
        """

        room = self.get(code)
        if room.host_token != host_token:
            raise RoomError("host_required")
        if room.runner is None or not room.runner.terminal:
            raise RoomError("match_not_complete")
        result = project_match_result(room.runner.state)
        room.previous_matches = [*room.previous_matches, {
            "deals": len(room.runner.state.completed_deals),
            "final_score": result["final_score"],
            "match_ref": room.runner.match_ref,
            "winner_team": result["winner_team"],
        }][-MAX_PREVIOUS_MATCHES:]
        room.match_index += 1
        # Seats a bot covered return to their players for the next match, and
        # the seats players left are free again.
        room.ai_seats = {seat for seat in room.ai_seats
                         if room.session_for_seat(seat) is None and seat not in room.open_seats}
        room.open_seats.clear()
        room.runner = None
        room.paused = False
        room.post_match_analysis = None
        room.completed_deal_analyses.clear()
        room.deal_reviews.clear()
        for item in room.sessions.values():
            item.ready = False
        room.lifecycle = "configured" if room.ai_seats else "waiting"
        if self._store is not None:
            self._store.discard_match_analyses(room.code)
        self.persist(room)
        return room

    def persist(self, room: Room) -> None:
        if self._store is not None:
            try:
                self._store.save(room.persistence_record())
            except PersistenceError:
                self.storage_failed = True
                raise

    async def persist_async(self, room: Room) -> None:
        """persist() from the event loop, in ``save_executor`` when one is set.

        The hosted boundary sets it: it holds a room's lock across every change
        to that room, so the room cannot change while the record is built and
        written, and the move is acknowledged only after the save. Meanwhile
        the loop serves the other rooms instead of waiting for a long match's
        record and its fsync.
        """
        if self.save_executor is None or self._store is None:
            self.persist(room)
            return
        await asyncio.get_running_loop().run_in_executor(self.save_executor, self.persist, room)

    def set_post_match_analysis(
        self,
        *,
        code: str,
        response: Mapping[str, object],
    ) -> dict[str, object]:
        """Store a validated analysis envelope for a completed match.

        This is an internal server operation.  There is deliberately no HTTP
        write endpoint for analysis: a future analysis runner must produce the
        envelope through ``validate_post_match_analysis_response`` first.
        """

        room = self.get(code)
        if room.runner is None or not room.runner.terminal:
            raise RoomError("match_not_complete")
        try:
            validated = validate_post_match_analysis_response(
                response,
                expected_match_ref=room.runner.match_ref,
                public_events=project_event_batch(room.runner.state.public_events),
            )
        except AnalysisProjectionError:
            raise
        if self._store is not None:
            self._store.save_post_match_analysis(
                room_code=room.code,
                response=validated,
            )
        room.post_match_analysis = validated
        return validated

    def record_post_match_analyses(
        self,
        *,
        code: str,
        records: Iterable[RecordedDecisionAnalysis | Mapping[str, object]],
        visible_card_codes_by_seat: Mapping[int, Iterable[str]] | None = None,
    ) -> dict[str, object]:
        """Project approved decision records and persist the safe envelope.

        This is the intended future hook for an analysis-capable server-side
        agent.  Each record may receive its own authorized card set because
        the observations of four seats are different; the resulting envelope
        is then validated and bound to the public match history before write.
        """

        room = self.get(code)
        if room.runner is None or not room.runner.terminal:
            raise RoomError("match_not_complete")
        public_events = project_event_batch(room.runner.state.public_events)
        projected: list[dict[str, object]] = []
        for record in records:
            parsed = (
                record
                if isinstance(record, RecordedDecisionAnalysis)
                else RecordedDecisionAnalysis.from_data(record)
            )
            visible = None
            if visible_card_codes_by_seat is not None:
                visible = visible_card_codes_by_seat.get(parsed.seat)
            projected.append(
                project_post_match_analysis(
                    parsed,
                    public_events=public_events,
                    visible_card_codes=visible,
                )
            )
        response = {
            "schema_version": POST_MATCH_ANALYSIS_SCHEMA_VERSION,
            "match_ref": room.runner.match_ref,
            "analyses": projected,
        }
        return self.set_post_match_analysis(code=room.code, response=response)

    def post_match_analysis_for_session(
        self,
        *,
        code: str,
        token: str,
    ) -> dict[str, object]:
        """Return stored analysis only to an authenticated room participant."""

        room, session = self.session(code=code, token=token)
        if room.runner is None or not room.runner.terminal:
            raise RoomError("match_not_complete")
        if room.ruleset_id not in ANALYSIS_RULESETS:
            raise RoomError("analysis_unavailable_for_ruleset")
        # A stored v1 envelope is retained only for compatibility with the
        # historical fixture/demo hook.  Real completed rooms reconstruct a
        # fresh seat-scoped v3 response from their durable match record.  This
        # also makes diagnostics available after a server restart without
        # persisting raw AI or exact-solver internals.
        if not isinstance(room.runner, LiveMatchRunner) and room.post_match_analysis is not None:
            return validate_post_match_analysis_response(
                room.post_match_analysis,
                expected_match_ref=room.runner.match_ref,
                public_events=project_event_batch(room.runner.state.public_events),
            )
        if not isinstance(room.runner, LiveMatchRunner):
            raise RoomError("analysis_not_available")
        return generate_post_match_diagnostics(room.runner, seat=session.seat)

    def training_analysis_for_session(
        self,
        *,
        code: str,
        token: str,
    ) -> dict[str, object]:
        """Return this session's own live suit-split and card-location odds.

        Valid only while a deal is in progress. The response is derived
        entirely from the requesting seat's own formal observation (own hand
        plus public history), the same information already available to that
        player, so it carries no more privacy risk than the observation
        itself. There is deliberately no seat parameter: the seat is always
        the authenticated session's own.
        """

        room, session = self.session(code=code, token=token)
        if room.runner is None or room.runner.terminal:
            raise RoomError("no_active_deal")
        deal = room.runner.state.active_deal
        if deal is not None and (deal.soolaaja is not None or deal.phase.value in SOOLI_PHASE_NAMES):
            # The exact odds model is the four-hand one; a sooli deal has a dead
            # hand and a private exchange, so a sampler (the bot's) answers.
            if self.sooli_odds is None:
                raise RoomError("analysis_unavailable_in_sooli")
            observation = match_observation_for(room.runner.state, session.seat)
            try:
                return generate_sooli_training_analysis(observation, self.sooli_odds)
            except (SooliTrainingAnalysisError, ValueError) as exc:
                raise RoomError("analysis_unavailable_in_sooli") from exc
        return room.runner.training_analysis(session.seat)

    def completed_deal_analysis_for_session(
        self,
        *,
        code: str,
        token: str,
        deal_number: int,
    ) -> dict[str, object]:
        """Return one completed-deal diagnostic envelope when disclosure is safe.

        A *completed* deal is analysable by any authenticated participant, in any
        room, without waiting for 52.  Disclosure is safe because the deal is
        over: all 52 of its cards were played publicly, the response is scoped to
        the requesting seat's own decisions, and the next deal is an independent
        shuffle, so nothing about current or future hidden play is revealed.

        The remaining cost is social rather than informational: a player can
        consult a review aid between deals while the table remains usable. It is
        symmetric, because every participant has the same endpoint. A deal that
        is still in progress stays closed.
        """

        room, session = self.session(code=code, token=token)
        if room.runner is None:
            raise RoomError("match_not_started")
        if room.ruleset_id in REAL_GAME_RULESETS:
            return self._real_game_deal_analysis(room, session.seat, deal_number)
        if room.ruleset_id not in ANALYSIS_RULESETS:
            raise RoomError("analysis_unavailable_for_ruleset")
        if (
            type(deal_number) is not int
            or deal_number < 0
            or deal_number >= len(room.runner.state.completed_deals)
        ):
            raise RoomError("deal_not_complete")
        cache_key = (deal_number, session.seat)
        cached = room.completed_deal_analyses.get(cache_key)
        if cached is None and self._store is not None:
            cached = self._store.load_completed_deal_analysis(
                room_code=room.code,
                deal_number=deal_number,
                seat=session.seat,
                analysis_schema_version=COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
                bot_policy_id=BOT_REPLAY_POLICY_ID,
            )
        if cached is not None:
            validated = validate_completed_deal_review_against_runner(
                cached,
                runner=room.runner,
                seat=session.seat,
                deal_number=deal_number,
            )
            room.completed_deal_analyses[cache_key] = validated
            return deepcopy(validated)

        generated = generate_completed_deal_review(
            room.runner,
            seat=session.seat,
            deal_number=deal_number,
        )
        room.completed_deal_analyses[cache_key] = generated
        if self._store is not None:
            self._store.save_completed_deal_analysis(
                room_code=room.code,
                deal_number=deal_number,
                seat=session.seat,
                response=generated,
                analysis_schema_version=COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
                bot_policy_id=BOT_REPLAY_POLICY_ID,
            )
        return deepcopy(generated)

    def _real_game_deal_analysis(
        self, room: Room, seat: int, deal_number: int
    ) -> dict[str, object]:
        """The real game's completed-deal analysis: the dealt hands, the sooli
        exchange, a same-cards replay by the room's own bots and the seat's
        after-deal review. Cached in memory and in the store per deal and seat.
        """

        runner = room.runner
        if not isinstance(runner, LiveMatchRunner):
            raise RoomError("analysis_not_available")
        if (
            type(deal_number) is not int
            or deal_number < 0
            or deal_number >= len(runner.state.completed_deals)
        ):
            raise RoomError("deal_not_complete")
        cache_key = (deal_number, seat)
        policy_id = bot_policy_for(runner)["policy_id"]
        cached = room.completed_deal_analyses.get(cache_key)
        if cached is None and self._store is not None:
            cached = self._store.load_completed_deal_analysis(
                room_code=room.code,
                deal_number=deal_number,
                seat=seat,
                analysis_schema_version=REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION,
                bot_policy_id=policy_id,
            )
        if cached is not None:
            try:
                validated = validate_real_game_deal_analysis(
                    cached, runner=runner, seat=seat, deal_number=deal_number
                )
            except RealGameAnalysisError:
                validated = None  # stale: regenerate below
            if validated is not None:
                room.completed_deal_analyses[cache_key] = validated
                return deepcopy(validated)
        try:
            generated = generate_real_game_deal_analysis(
                runner,
                seat=seat,
                deal_number=deal_number,
                review=self._review_or_none(room, seat, deal_number),
            )
        except RealGameAnalysisError as exc:
            raise RoomError("analysis_not_available") from exc
        room.completed_deal_analyses[cache_key] = generated
        if self._store is not None:
            self._store.save_completed_deal_analysis(
                room_code=room.code,
                deal_number=deal_number,
                seat=seat,
                response=generated,
                analysis_schema_version=REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION,
                bot_policy_id=policy_id,
            )
        return deepcopy(generated)

    def _review_or_none(
        self, room: Room, seat: int, deal_number: int
    ) -> dict[str, object] | None:
        """The seat's after-deal review, or None when this server has no reviewer."""

        if self.deal_reviewer is None or room.runner is None:
            return None
        key = (deal_number, seat)
        cached = room.deal_reviews.get(key)
        if cached is None:
            try:
                cached = generate_deal_review(
                    room.runner, seat=seat, deal_number=deal_number, reviewer=self.deal_reviewer
                )
            except DealReviewError:
                return None
            room.deal_reviews[key] = cached
        return deepcopy(cached)

    def deal_review_for_session(
        self,
        *,
        code: str,
        token: str,
        deal_number: int,
    ) -> dict[str, object]:
        """This session's own decisions in a completed deal, re-decided by the reviewer.

        Available once the deal is complete, to its participants only, and
        scoped to the requesting seat. Cached per deal and seat.
        """

        room, session = self.session(code=code, token=token)
        if self.deal_reviewer is None:
            raise RoomError("review_unavailable")
        if room.runner is None:
            raise RoomError("match_not_started")
        if (
            type(deal_number) is not int
            or deal_number < 0
            or deal_number >= len(room.runner.state.completed_deals)
        ):
            raise RoomError("deal_not_complete")
        key = (deal_number, session.seat)
        cached = room.deal_reviews.get(key)
        if cached is None:
            try:
                cached = generate_deal_review(
                    room.runner, seat=session.seat, deal_number=deal_number, reviewer=self.deal_reviewer
                )
            except DealReviewError as exc:
                raise RoomError("review_failed") from exc
            room.deal_reviews[key] = cached
        return deepcopy(cached)

    def get(self, code: str) -> Room:
        normalized = code.strip().upper()
        if normalized not in self._rooms:
            raise RoomError("room_not_found")
        return self._rooms[normalized]

    def deal_records_for_session(self, *, code: str, token: str) -> dict[str, object]:
        """The finished deals of the current match in full (feature
        deal_records), for the game viewer: to a player or a spectator of the
        room. The deal in play stays private."""

        room = self.get(code)
        if token not in room.spectators:
            self._session(room, token)
        if room.runner is None:
            raise RoomError("match_not_started")
        return {"match_ref": room.runner.match_ref, "deals": finished_deal_records(room.runner)}

    def session(self, *, code: str, token: str) -> tuple[Room, Session]:
        room = self.get(code)
        return room, self._session(room, token)

    def _ready_to_start(self, room: Room) -> bool:
        if room.runner is not None:
            return False
        if any(
            seat not in room.ai_seats and room.session_for_seat(seat) is None
            for seat in range(4)
        ):
            return False
        return all(
            session.ready for session in room.sessions.values()
        )

    @staticmethod
    def _validate_name(display_name: str) -> str:
        if type(display_name) is not str:
            raise RoomError("invalid_display_name")
        name = display_name.strip()
        if not 1 <= len(name) <= 40:
            raise RoomError("invalid_display_name")
        return name

    @staticmethod
    def _validate_ai_seats(ai_seats: frozenset[int], host_seat: int = 0) -> None:
        if any(type(seat) is not int or seat not in range(4) or seat == host_seat for seat in ai_seats):
            raise RoomError("invalid_ai_seats")

    @staticmethod
    def _session(room: Room, token: str) -> Session:
        session = room.sessions.get(token)
        if session is None:
            raise RoomError("invalid_session")
        return session

    def _load_persisted_rooms(self) -> None:
        assert self._store is not None
        try:
            records = self._store.load_all()
            for record in records:
                room = self._room_from_record(record, default_profile=self._ai_profile_key)
                if room.code in self._rooms:
                    raise PersistenceError("duplicate persisted room code")
                self._rooms[room.code] = room
            for code in self._store.post_match_analysis_codes():
                if code not in self._rooms:
                    raise PersistenceError(
                        "persisted analysis has no corresponding room"
                    )
                room = self._rooms[code]
                response = self._store.load_post_match_analysis(code)
                if response is None:
                    raise PersistenceError("persisted analysis disappeared during load")
                if room.runner is None or not room.runner.terminal:
                    raise PersistenceError(
                        "persisted analysis belongs to a non-terminal room"
                    )
                room.post_match_analysis = validate_post_match_analysis_response(
                    response,
                    expected_match_ref=room.runner.match_ref,
                    public_events=project_event_batch(room.runner.state.public_events),
                )
        except PersistenceError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise PersistenceError("persisted room recovery failed") from exc

    @staticmethod
    def _room_from_record(record: dict[str, object], *, default_profile: str = DEFAULT_AI_PROFILE_KEY) -> Room:
        expected_v1 = {
            "ai_seats",
            "host_token",
            "lifecycle",
            "room_code",
            "schema_version",
            "sessions",
            "runner",
        }
        expected_v2 = expected_v1 | {"ai_action_delay_ms"}
        schema_version = record.get("schema_version")
        ruleset_id = RulesetId.PROJECT_TARGET_V1
        heidi_record = schema_version in (HEIDI_ROOM_RECORD_SCHEMA_VERSION, HEIDI_SEARCH_ROOM_RECORD_SCHEMA_VERSION)
        heidi_profiles = HEIDI_SEARCH_PROFILE_KEYS if schema_version == HEIDI_SEARCH_ROOM_RECORD_SCHEMA_VERSION else HEIDI_LITE_PROFILE_KEYS
        heidi_profile = record.get("ai_profile_key")
        multi_match = schema_version in (MULTI_MATCH_ROOM_RECORD_SCHEMA_VERSION, OPEN_SEATS_ROOM_RECORD_SCHEMA_VERSION,
                                        HEIDI_ROOM_RECORD_SCHEMA_VERSION, HEIDI_SEARCH_ROOM_RECORD_SCHEMA_VERSION)
        open_seats_record = schema_version in (OPEN_SEATS_ROOM_RECORD_SCHEMA_VERSION, HEIDI_ROOM_RECORD_SCHEMA_VERSION,
                                              HEIDI_SEARCH_ROOM_RECORD_SCHEMA_VERSION)
        if multi_match:
            expected = expected_v2 | {"ruleset_id", "match_index", "paused", "previous_matches"}
            if open_seats_record:
                expected |= {"open_seats", "handover_seats"}
            if heidi_record:
                expected |= {"ai_profile_key"}
                if not isinstance(heidi_profile, str) or heidi_profile not in heidi_profiles:
                    raise PersistenceError("persisted bot profile is invalid")
            ai_action_delay_ms = record.get("ai_action_delay_ms")
            try:
                ruleset_id = RulesetId(record.get("ruleset_id"))
            except ValueError as exc:
                raise PersistenceError("persisted ruleset_id is invalid") from exc
        elif schema_version == RULESET_ROOM_RECORD_SCHEMA_VERSION:
            expected = expected_v2 | {"ruleset_id"}
            ai_action_delay_ms = record.get("ai_action_delay_ms")
            try:
                ruleset_id = RulesetId(record.get("ruleset_id"))
            except ValueError as exc:
                raise PersistenceError("persisted ruleset_id is invalid") from exc
        elif schema_version == ROOM_RECORD_SCHEMA_VERSION:
            expected = expected_v2
            ai_action_delay_ms = record.get("ai_action_delay_ms")
        elif schema_version == LEGACY_ROOM_RECORD_SCHEMA_VERSION:
            expected = expected_v1
            ai_action_delay_ms = DEFAULT_AI_ACTION_DELAY_MS
        else:
            raise PersistenceError("unsupported room record schema_version")
        if set(record) != expected:
            raise PersistenceError("persisted room fields are invalid")
        code = record["room_code"]
        host_token = record["host_token"]
        lifecycle = record["lifecycle"]
        ai_seats_data = record["ai_seats"]
        sessions_data = record["sessions"]
        if not isinstance(code, str) or len(code) != 6 or not code.isalnum() or code != code.upper():
            raise PersistenceError("persisted room_code is invalid")
        if not isinstance(host_token, str) or not host_token:
            raise PersistenceError("persisted host_token is invalid")
        if not isinstance(lifecycle, str):
            raise PersistenceError("persisted lifecycle is invalid")
        if type(ai_seats_data) is not list or any(
            type(seat) is not int or seat not in (range(4) if open_seats_record else range(1, 4))
            for seat in ai_seats_data
        ):
            raise PersistenceError("persisted ai_seats are invalid")
        if type(sessions_data) is not list:
            raise PersistenceError("persisted sessions must be an array")
        if (
            type(ai_action_delay_ms) is not int
            or ai_action_delay_ms not in AI_ACTION_DELAY_OPTIONS_MS
        ):
            raise PersistenceError("persisted ai_action_delay_ms is invalid")
        room = Room(
            code=code,
            host_token=host_token,
            ai_seats=set(ai_seats_data),
            lifecycle=lifecycle,
            ai_action_delay_ms=ai_action_delay_ms,
            ruleset_id=ruleset_id,
            ai_profile_key=heidi_profile if heidi_record else default_profile,
        )
        if multi_match:
            match_index, paused, previous = record["match_index"], record["paused"], record["previous_matches"]
            if type(match_index) is not int or match_index < 0 or not isinstance(paused, bool):
                raise PersistenceError("persisted match_index or paused is invalid")
            if (type(previous) is not list or len(previous) > MAX_PREVIOUS_MATCHES or any(
                    type(item) is not dict or set(item) != _PREVIOUS_MATCH_FIELDS
                    or type(item["deals"]) is not int or not isinstance(item["match_ref"], str)
                    or type(item["winner_team"]) is not int or type(item["final_score"]) is not list
                    or len(item["final_score"]) != 2 or any(type(v) is not int for v in item["final_score"])
                    for item in previous)):
                raise PersistenceError("persisted previous_matches are invalid")
            room.match_index, room.paused, room.previous_matches = match_index, paused, previous
        for raw_session in sessions_data:
            if type(raw_session) is not dict or set(raw_session) != {
                "display_name", "ready", "seat", "token"
            }:
                raise PersistenceError("persisted session fields are invalid")
            token = raw_session["token"]
            seat = raw_session["seat"]
            display_name = raw_session["display_name"]
            ready = raw_session["ready"]
            if (
                not isinstance(token, str)
                or not token
                or type(seat) is not int
                or seat not in range(4)
                or not isinstance(display_name, str)
                or not isinstance(ready, bool)
            ):
                raise PersistenceError("persisted session contains invalid values")
            if token in room.sessions or room.session_for_seat(seat) is not None:
                raise PersistenceError("persisted sessions contain a duplicate")
            room.sessions[token] = Session(
                token=token,
                seat=seat,
                display_name=display_name,
                ready=ready,
            )
        host_session = room.sessions.get(host_token)
        if host_session is None or (host_session.seat != 0 and not open_seats_record):
            raise PersistenceError("persisted host session is invalid")
        handover: list[int] = []
        if open_seats_record:
            open_seats, handover = record["open_seats"], record["handover_seats"]
            if any(type(seats) is not list or any(type(s) is not int or s not in room.ai_seats for s in seats)
                   or len(set(seats)) != len(seats) for seats in (open_seats, handover)):
                raise PersistenceError("persisted open or handover seats are invalid")
            if (any(room.session_for_seat(s) is not None for s in open_seats)
                    or any(room.session_for_seat(s) is None for s in handover)
                    or (open_seats or handover) and record["runner"] is None):
                raise PersistenceError("persisted open or handover seats are invalid")
            room.open_seats = set(open_seats)
        runner_record = record["runner"]
        if runner_record is not None:
            if type(runner_record) is not dict:
                raise PersistenceError("persisted runner must be an object or null")
            room.runner = LiveMatchRunner.from_persistence_record(runner_record)
            if heidi_record and room.runner.ai_profile_key != room.ai_profile_key:
                raise PersistenceError("persisted runner bot disagrees with room")
            if room.runner.match_ref != room.match_ref():
                raise PersistenceError("persisted runner match_ref disagrees with room")
            if room.runner.ruleset_id is not room.ruleset_id:
                raise PersistenceError("persisted runner ruleset disagrees with room")
            room.lifecycle = "playing" if not room.runner.terminal else "completed"
            # The runner's bot seats are the current ones (a deal start may have
            # handed seats over just before the record was written).
            room.ai_seats = set(room.runner.ai_seats)
            room.runner.handover_seats = frozenset(handover)
        if room.paused and (room.runner is None or room.runner.terminal):
            raise PersistenceError("persisted pause has no match in progress")
        return room

    def _new_code(self) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            if code not in self._rooms:
                return code

    @staticmethod
    def _new_token() -> str:
        return secrets.token_urlsafe(32)
