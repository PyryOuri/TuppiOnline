"""Private-room lifecycle with optional restart-safe match persistence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import string

from .analysis import (
    AnalysisProjectionError,
    POST_MATCH_ANALYSIS_SCHEMA_VERSION,
    project_post_match_analysis,
    RecordedDecisionAnalysis,
    validate_post_match_analysis_response,
)
from .match_runner import DEFAULT_AI_PROFILE_KEY, LiveMatchRunner
from .persistence import (
    ROOM_RECORD_SCHEMA_VERSION,
    FileRoomStore,
    PersistenceError,
)
from .projection import project_event_batch


class RoomError(Exception):
    """A user-facing room operation failed."""


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

    def session_for_seat(self, seat: int) -> Session | None:
        return next((item for item in self.sessions.values() if item.seat == seat), None)

    def snapshot(self) -> dict[str, object]:
        seats: list[dict[str, object]] = []
        for seat in range(4):
            if seat in self.ai_seats:
                profile_key = (
                    DEFAULT_AI_PROFILE_KEY
                    if self.runner is None
                    else self.runner.ai_profile_key
                )
                seats.append(
                    {
                        "agent_profile": profile_key,
                        "display_name": "Tuppi partner AI",
                        "kind": "ai",
                        "ready": True,
                        "seat": seat,
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
        return {
            "lifecycle": self.lifecycle,
            "room_code": self.code,
            "seats": seats,
        }

    def persistence_record(self) -> dict[str, object]:
        """Return private room/session/match material for the file store."""

        return {
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


class RoomManager:
    """Own rooms and opaque reconnect credentials.

    ``RoomManager()`` remains in-memory for tests and fixture usage.  The
    running server uses ``from_environment()`` to enable the local durable
    store without requiring PostgreSQL or Redis.
    """

    def __init__(self, persistence_dir: str | Path | None = None) -> None:
        self._rooms: dict[str, Room] = {}
        self._store = (
            None if persistence_dir is None else FileRoomStore(persistence_dir)
        )
        if self._store is not None:
            self._load_persisted_rooms()

    @classmethod
    def from_environment(cls) -> "RoomManager":
        configured = os.environ.get("TUPPI_SERVER_DATA_DIR")
        root = (
            Path(configured).expanduser()
            if configured
            else Path.home() / "Library" / "Application Support" / "Tuppi" / "server"
        )
        return cls(root)

    def create_room(
        self,
        *,
        display_name: str,
        ai_seats: frozenset[int] = frozenset(),
    ) -> tuple[Room, Session]:
        name = self._validate_name(display_name)
        self._validate_ai_seats(ai_seats)
        code = self._new_code()
        host_token = self._new_token()
        room = Room(code=code, host_token=host_token, ai_seats=set(ai_seats))
        session = Session(token=host_token, seat=0, display_name=name)
        room.sessions[host_token] = session
        room.lifecycle = "configured" if ai_seats else "waiting"
        self._rooms[code] = room
        self.persist(room)
        return room, session

    def join_room(self, *, code: str, display_name: str) -> tuple[Room, Session]:
        room = self.get(code)
        name = self._validate_name(display_name)
        open_seats = [
            seat
            for seat in range(4)
            if seat not in room.ai_seats and room.session_for_seat(seat) is None
        ]
        if not open_seats:
            raise RoomError("room_full")
        token = self._new_token()
        session = Session(token=token, seat=open_seats[0], display_name=name)
        room.sessions[token] = session
        room.lifecycle = "waiting"
        self.persist(room)
        return room, session

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
        self._validate_ai_seats(ai_seats)
        for seat in ai_seats:
            if seat != 0 and room.session_for_seat(seat) is not None:
                raise RoomError("seat_occupied")
        room.ai_seats = set(ai_seats)
        room.lifecycle = "configured"
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
        session.ready = True
        if self._ready_to_start(room):
            room.runner = LiveMatchRunner(
                match_ref=f"room-{room.code.lower()}",
                ai_seats=frozenset(room.ai_seats),
                auto_run_ai=auto_run_ai,
            )
            room.lifecycle = "playing"
        else:
            room.lifecycle = "ready"
        self.persist(room)
        return room

    def persist(self, room: Room) -> None:
        if self._store is not None:
            self._store.save(room.persistence_record())

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

        room, _ = self.session(code=code, token=token)
        if room.runner is None or not room.runner.terminal:
            raise RoomError("match_not_complete")
        if room.post_match_analysis is None:
            raise RoomError("analysis_not_available")
        return validate_post_match_analysis_response(
            room.post_match_analysis,
            expected_match_ref=room.runner.match_ref,
            public_events=project_event_batch(room.runner.state.public_events),
        )

    def get(self, code: str) -> Room:
        normalized = code.strip().upper()
        if normalized not in self._rooms:
            raise RoomError("room_not_found")
        return self._rooms[normalized]

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
    def _validate_ai_seats(ai_seats: frozenset[int]) -> None:
        if any(type(seat) is not int or seat not in range(1, 4) for seat in ai_seats):
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
                room = self._room_from_record(record)
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
    def _room_from_record(record: dict[str, object]) -> Room:
        expected = {
            "ai_seats",
            "host_token",
            "lifecycle",
            "room_code",
            "schema_version",
            "sessions",
            "runner",
        }
        if set(record) != expected:
            raise PersistenceError("persisted room fields are invalid")
        if record["schema_version"] != ROOM_RECORD_SCHEMA_VERSION:
            raise PersistenceError("unsupported room record schema_version")
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
            type(seat) is not int or seat not in range(1, 4)
            for seat in ai_seats_data
        ):
            raise PersistenceError("persisted ai_seats are invalid")
        if type(sessions_data) is not list:
            raise PersistenceError("persisted sessions must be an array")
        room = Room(
            code=code,
            host_token=host_token,
            ai_seats=set(ai_seats_data),
            lifecycle=lifecycle,
        )
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
        if host_session is None or host_session.seat != 0:
            raise PersistenceError("persisted host session is invalid")
        runner_record = record["runner"]
        if runner_record is not None:
            if type(runner_record) is not dict:
                raise PersistenceError("persisted runner must be an object or null")
            room.runner = LiveMatchRunner.from_persistence_record(runner_record)
            if room.runner.match_ref != f"room-{room.code.lower()}":
                raise PersistenceError("persisted runner match_ref disagrees with room")
            room.lifecycle = "playing" if not room.runner.terminal else "completed"
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
