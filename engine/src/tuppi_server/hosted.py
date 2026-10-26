"""Single-authority private alpha with an explicit browser boundary.

One ASGI process owns rooms. Two admission threads feed one spawned, serial
native bot process; authoritative room mutations are ordered by per-room locks.
Use ``uvicorn tuppi_server.hosted:create_hosted_app --factory --workers 1``.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import re
import time
import threading
from urllib.parse import urlsplit

from .limits import WindowLimit, client_address, client_header_from_environment
from .persistence import PersistenceError
from .usage import USAGE_INTERVAL_SECONDS, Usage, resident_megabytes

ROOM_ROUTE = re.compile(r"^/v1/rooms/([A-Z0-9]{6})/(join|configure|settings|ready|leaderboard|name|release|seats|swap|leave|watch|records)$", re.I)
# Each limit below holds for all clients together; the *_PER_CLIENT limits
# hold for one client address (limits.py), so one address cannot use up the
# shared allowance alone.
#: Wrong room-creation passcodes accepted per minute before refusing tries.
MAX_PASSCODE_FAILURES_PER_MINUTE = 30
PASSCODE_FAILURES_PER_CLIENT = 5
#: Rooms created per minute.
MAX_ROOMS_PER_MINUTE = 12
ROOMS_PER_CLIENT = 4
#: Offline match reports accepted per minute.
MAX_RESULTS_PER_MINUTE = 30
RESULTS_PER_CLIENT = 10
#: Offline match records (with every card) accepted per minute; each is
#: checked by replaying it, one at a time.
MAX_RECORDS_PER_MINUTE = 10
RECORDS_PER_CLIENT = 4
#: Wrong research download keys accepted per minute before refusing tries.
MAX_RESEARCH_KEY_FAILURES_PER_MINUTE = 10
RESEARCH_KEY_FAILURES_PER_CLIENT = 5
#: Open WebSocket connections from one client address (max_connections in all).
CONNECTIONS_PER_CLIENT = 16
#: Browser security policy reports counted per minute (see _csp_report).
MAX_CSP_REPORTS_PER_MINUTE = 60
CSP_REPORTS_PER_CLIENT = 10
#: How often idle rooms are archived and old archives pruned.
MAINTENANCE_INTERVAL_SECONDS = 3600
#: An unfinished room nobody is connected to stops counting towards the
#: active-room and bot-room limits after this long without activity. It stays
#: resumable; abandoned lobbies and matches must not lock others out.
IDLE_ROOM_SECONDS = 1800
#: A search table needs actual player activity to keep its scarce slot.
#: Heartbeats, reconnects, spectators and bot moves do not renew it.
HEIDI_IDLE_SECONDS = 15 * 60
HEIDI_MAINTENANCE_SECONDS = 30


def admin_key_from_environment() -> str | None:
    value = os.environ.get("TUPPI_ADMIN_KEY") or None
    if value is not None and (not 16 <= len(value) <= 256 or value != value.strip()):
        raise ValueError("TUPPI_ADMIN_KEY must be 16-256 characters without surrounding spaces")
    return value


def storage_limits_from_environment() -> dict:
    """Archive retention and the free-space floor for new rooms."""
    def number(key, default, low, high):
        raw = os.environ.get(key, str(default))
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{key} must be a number") from exc
        if not low <= value <= high:
            raise ValueError(f"{key} must be in {low}..{high}")
        return value
    return {"archive_days": number("TUPPI_ARCHIVE_DAYS", 30, 1, 3650),
            "archive_max_bytes": int(number("TUPPI_ARCHIVE_MAX_MB", 200, 1, 100000) * 2**20),
            "min_free_bytes": int(number("TUPPI_MIN_FREE_MB", 50, 1, 100000) * 2**20)}


def room_passcode_from_environment() -> str | None:
    """TUPPI_ROOM_PASSCODE: when set, creating a room requires it (joining by
    invitation does not). A public deployment sets it as a provider secret."""
    value = os.environ.get("TUPPI_ROOM_PASSCODE") or None
    if value is not None and (len(value) < 8 or len(value) > 128 or value != value.strip()):
        raise ValueError("TUPPI_ROOM_PASSCODE must be 8-128 characters without surrounding spaces")
    return value


def validate_origins(raw: str) -> frozenset[str]:
    origins = frozenset(value.strip() for value in raw.split(",") if value.strip())
    if not origins:
        raise ValueError("TUPPI_BROWSER_ORIGINS must list exact HTTPS origins")
    for origin in origins:
        url = urlsplit(origin)
        local = url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme != "https" and not (local and url.scheme == "http")) or not url.netloc \
                or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError("invalid browser origin")
    return origins


def _verified_model_manifest(root: Path, level: str) -> dict:
    if level not in {"lite", "full"}:
        raise ValueError("TUPPI_HOSTED_BOT_LEVEL must be lite or full")
    models = root / "models"
    lite = models / "hosted-models.lite.json"
    full = models / "hosted-models.json"
    if level == "lite" and lite.is_file():
        # The d1 options also read the equity table (TUPPI_HOSTED_LITE_OPTIONS).
        # Nelli 1.1 (tuppi_ai_lite_c1h_v2) plays vrpo4_final.lite.npz, so every
        # lite package lists and verifies it: no network is loaded unverified.
        from .hosted_bot import lite_options
        path = lite
        names = set(json.loads(lite.read_text()))
        expected = {"vrpo3_final.lite.npz", "vrpo4_final.lite.npz", "equity_incumbent.json"} if (
            lite_options() != "off" or "equity_incumbent.json" in names) else {"vrpo3_final.lite.npz",
                                                                               "vrpo4_final.lite.npz"}
    else:
        if level == "full" and not full.is_file() and lite.is_file():
            raise RuntimeError("this runtime contains only the lite bot; use the full image for TUPPI_HOSTED_BOT_LEVEL=full")
        path = full
        expected = {"vrpo1_actor_0504.pt", "vrpo3_final.pt", "equity_incumbent.json", "vrpo3_final.lite.npz",
                    "vrpo4_final.pt", "vrpo4_final.lite.npz"}
    manifest = json.loads(path.read_text())
    if type(manifest) is not dict or set(manifest) != expected:
        raise RuntimeError("hosted model manifest fields are invalid")
    for name, digest in manifest.items():
        if (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or hashlib.sha256((models / name).read_bytes()).hexdigest() != digest):
            raise RuntimeError(f"hosted model identity mismatch: {name}")
    return manifest


def verify_bot_identity(level: str = "full") -> dict:
    spec = importlib.util.find_spec("tuppi_ai")
    if spec is None or spec.origin is None:
        raise RuntimeError("the trained bot package is required")
    root = Path(spec.origin).resolve().parents[1]
    manifest = _verified_model_manifest(root, level)
    from tuppi_ai import native
    from .hosted_bot import lite_options, heidi_enabled, heidi_identity, dan_enabled
    options = lite_options() if level == "lite" else "off"
    bot = ({"profile": "tuppi_ai_lite_v1" if options == "off" else f"tuppi_ai_lite_{options}_v1", "level": "lite",
            "search": None} if level == "lite" else {"profile": "tuppi_ai_search_v1", "level": "full", "worlds": 1024})
    return {**bot,
        **({"dan11": {"worlds": 64}} if level == "lite" and dan_enabled() else {}),
        **({"heidi10": {"worlds": 1024, "inference": 8, "max_active_tables": 1,
                        "models_sha256": heidi_identity()}} if level == "lite" and heidi_enabled() else {}),
        "models_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "native_sha256": hashlib.sha256(Path(native.lib._name).read_bytes()).hexdigest()}


def bot_options(identity: dict) -> list[dict]:
    """The bots new rooms may choose. Nelli 1.0 and Heidi 1.1 are no longer
    offered; rooms that chose them keep them (match_runner.py). Heidi 1.2
    needs the hosted compact worker (TUPPI_HOSTED_HEIDI10=1, the identity's
    ``heidi10`` entry), which serves both search profiles one table at a time."""
    from .match_runner import BOT_DISPLAY_NAMES, HEIDI12_PROFILE_KEY, NELLI11_PROFILE_KEY, TUPPI_AI_PROFILE_KEY, DAN11_PROFILE_KEY
    if identity.get("level") != "lite":
        return []
    return ([{"profile": key, "name": BOT_DISPLAY_NAMES[key]} for key in (TUPPI_AI_PROFILE_KEY, NELLI11_PROFILE_KEY)] +
            ([{"profile": HEIDI12_PROFILE_KEY, "name": BOT_DISPLAY_NAMES[HEIDI12_PROFILE_KEY], "max_active_tables": 1}]
             if identity.get("heidi10") else []) +
            ([{"profile": DAN11_PROFILE_KEY, "name": BOT_DISPLAY_NAMES[DAN11_PROFILE_KEY]}]
             if identity.get("dan11") else []))


def bot_room_limit(level: str, max_rooms: int) -> int:
    """Active bot-filled matches. The full bot qualified one per CPU; the lite
    bot costs about 1 ms of CPU per seat and deal, so every room may use bots."""
    return max_rooms if level == "lite" else 1


def create_hosted_app():
    origins = validate_origins(os.environ.get("TUPPI_BROWSER_ORIGINS") or os.environ.get("RENDER_EXTERNAL_URL", ""))
    if not os.environ.get("TUPPI_SERVER_DATA_DIR"):
        raise ValueError("TUPPI_SERVER_DATA_DIR must name the private persistent volume")
    for key, expected in {"TUPPI_SERVER_AI_PROFILE": "tuppi_ai_search_v1",
            "TUPPI_SERVER_RULESET": "project_target_v3", "TUPPI_HOSTED_BOT": "1",
            "TUPPI_SERVER_REVIEW": "0", "TUPPI_SERVER_SOOLI_ODDS": "0",
            "TUPPI_CONTRACT_ROLLOUT_SAMPLES": "0"}.items():
        if os.environ.get(key) != expected:
            raise ValueError(f"hosted deployment requires {key}={expected}")
    from .hosted_bot import level as bot_level
    level = bot_level()
    identity = verify_bot_identity(level)
    # Import only after the hosted configuration and weights have been checked.
    from .app import app
    return HostedBoundary(app, origins=origins, bot_identity=identity, max_bot_rooms=bot_room_limit(level, 8),
                          room_passcode=room_passcode_from_environment(), client_header=client_header_from_environment(),
                          admin_key=admin_key_from_environment(),
                          **storage_limits_from_environment())


class PasscodeRefused(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.status = status


class HostedBoundary:
    def __init__(self, game, *, origins, bot_identity=None, max_rooms=8, max_connections=32, max_bot_rooms=1,
                 max_retained_rooms=32, room_passcode=None, archive_days=30, archive_max_bytes=200 * 2**20,
                 min_free_bytes=50 * 2**20, client_header=None, admin_key=None):
        self.game = game
        self.archive_days, self.archive_max_bytes = archive_days, archive_max_bytes
        self.min_free_bytes = min_free_bytes
        self.maintenance_task = None
        self.usage_task = None
        self.heidi_maintenance_task = None
        self.admin_key = admin_key
        self.admin_failures = WindowLimit(5, 30)
        #: The served browser release, set by HostedSite; logged at startup.
        self.release = None
        self.room_passcode = room_passcode
        #: The proxy header naming the client address (limits.py); None: the peer.
        self.client_header = client_header
        self.passcode_failures = WindowLimit(PASSCODE_FAILURES_PER_CLIENT, MAX_PASSCODE_FAILURES_PER_MINUTE)
        self.created = WindowLimit(ROOMS_PER_CLIENT, MAX_ROOMS_PER_MINUTE)
        self.result_posts = WindowLimit(RESULTS_PER_CLIENT, MAX_RESULTS_PER_MINUTE)
        self.record_posts = WindowLimit(RECORDS_PER_CLIENT, MAX_RECORDS_PER_MINUTE)
        self.research_key_failures = WindowLimit(RESEARCH_KEY_FAILURES_PER_CLIENT, MAX_RESEARCH_KEY_FAILURES_PER_MINUTE)
        self.csp_reports = WindowLimit(CSP_REPORTS_PER_CLIENT, MAX_CSP_REPORTS_PER_MINUTE)
        self.client_connections: dict[str, int] = {}
        self.record_check = asyncio.Lock()
        #: The owner's download key for the match records (research.py); no
        #: key, no download.
        self.research_key = os.environ.get("TUPPI_RESEARCH_KEY") or None
        self.origins = frozenset(origins)
        self.bot_identity = bot_identity or {"profile": "test"}
        if bot_identity and bot_identity.get("models_sha256"):
            game.rooms.bot_version = f"{bot_identity['profile']}:{bot_identity['models_sha256'][:12]}"
        self.max_rooms, self.max_connections = max_rooms, max_connections
        self.max_bot_rooms = max_bot_rooms
        self.max_retained_rooms = max_retained_rooms
        self.connections = 0
        self.room_locks = {}
        self.creation_lock = asyncio.Lock()
        self.executor = None
        # One thread writes every room record: each room is saved under its
        # lock (below), so the loop serves the others during a long save.
        self.save_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="room-save")
        game.rooms.save_executor = self.save_executor
        self.activity = {code: self._mtime(code) for code in game.rooms._rooms}
        self.heidi_activity = dict(self.activity)
        self.usage = Usage()
        self.usage.baseline(game.rooms._rooms)
        store = game.rooms._store
        if store is not None:
            original_save = store.save
            def timed_save(record):
                started = time.perf_counter()
                original_save(record)
                try:
                    size = (store.root / f"room-{record['room_code']}.json").stat().st_size
                except OSError:
                    size = 0
                self.usage.saved(time.perf_counter() - started, size)
            store.save = timed_save
        original_error = game._send_error
        async def counted_error(send, code):
            self.usage.error(code)
            await original_error(send, code)
        game._send_error = counted_error
        # Core authentication and client commands share the same room lock as
        # HTTP configuration and continuation. A long native bid cannot allow
        # a second connection to observe a half-applied reveal.
        original_auth = game._authenticate
        original_message = game._handle_message
        original_continue = game._continue_ai
        original_ready = game.rooms.mark_ready
        heidi_admission = threading.Lock()
        def ready(*, code, token, auto_run_ai=True):
            # Until a table is closed/archived it keeps its slot, including
            # while paused or temporarily human-only. Expiry never merely
            # discounts a resumable table and admits a second search table.
            with heidi_admission:
                # Heidi 1.1 and Heidi 1.2 share the one compact worker: at most
                # one unfinished search table of either kind.
                from .match_runner import HEIDI_SEARCH_PROFILE_KEYS
                from .rooms import RoomError
                room, _ = game.rooms.session(code=code, token=token)
                others = [r for r in game.rooms._rooms.values() if r.code != room.code
                          and r.runner is not None and not r.runner.terminal]
                if room.runner is None and room.ai_profile_key in HEIDI_SEARCH_PROFILE_KEYS and any(
                        r.ai_profile_key in HEIDI_SEARCH_PROFILE_KEYS for r in others):
                    raise RoomError("heidi_busy")
                active = sum(bool(r.ai_seats) and self.in_use(r.code) for r in others)
                if room.runner is None and room.ai_seats and active >= self.max_bot_rooms:
                    raise RoomError("server_busy")
                result = original_ready(code=code, token=token, auto_run_ai=auto_run_ai)
                self.heidi_activity[code] = time.time()
                return result
        game.rooms.mark_ready = ready

        async def auth(request, send):
            if game.rooms.storage_failed:
                from .rooms import RoomError
                raise RoomError("storage_unavailable")
            code = str(request.get("payload", {}).get("room_code", "")).upper()
            await self.expire_idle_heidi_rooms()
            self.game.rooms.get(code)
            async with self._lock(code):
                connection = await original_auth(request, send)
                self.activity[code] = time.time()
                self.usage.counts["opens"] += 1
                return connection

        async def message(connection, request):
            if game.rooms.storage_failed and request.get("message_type") != "ping":
                from .rooms import RoomError
                raise RoomError("storage_unavailable")
            if request.get("message_type") == "action_submission":
                self.usage.counts["moves"] += 1
            if request.get("message_type") == "ready":
                await self.expire_idle_heidi_rooms(exclude_code=connection.room_code)
            async with self._lock(connection.room_code):
                room = game.rooms._rooms.get(connection.room_code)
                cursor = room.runner.event_cursor if room is not None and room.runner is not None else None
                await original_message(connection, request)
                self.activity[connection.room_code] = time.time()
                changed = (request.get("message_type") != "action_submission" or
                           (room is not None and room.runner is not None and room.runner.event_cursor != cursor))
                if changed and not connection.watching and request.get("message_type") not in {"ping", "reconnect"}:
                    self.heidi_activity[connection.room_code] = time.time()

        async def continuation(code):
            async with self._lock(code):
                await original_continue(code)
                self.activity[code] = time.time()

        game._authenticate, game._handle_message, game._continue_ai = auth, message, continuation

    def heidi_tables(self) -> list[dict]:
        from .match_runner import HEIDI_SEARCH_PROFILE_KEYS
        now = time.time()
        return [{"room_code": room.code, "paused": room.paused,
                 "idle_seconds": max(0, int(now - self.heidi_activity.get(room.code, now))),
                 "connected_players": sum(token in self.game._connections.get(room.code, {})
                                          for token in room.sessions)}
                for room in self.game.rooms._rooms.values()
                if room.ai_profile_key in HEIDI_SEARCH_PROFILE_KEYS
                and room.runner is not None and not room.runner.terminal]

    async def release_heidi_table(self, code: str, *, idle_only=False) -> bool:
        """Close one search table under its mutation lock; retain its archive.

        Wait for an in-flight native decision/save instead of cancelling its
        thread and allowing it to write after the room has been archived.
        """
        from .match_runner import HEIDI_SEARCH_PROFILE_KEYS
        async with self._lock(code):
            room = self.game.rooms._rooms.get(code)
            if (room is None or room.ai_profile_key not in HEIDI_SEARCH_PROFILE_KEYS
                    or room.runner is None or room.runner.terminal):
                return False
            if idle_only and time.time() - self.heidi_activity.get(code, time.time()) < HEIDI_IDLE_SECONDS:
                return False
            connections = tuple(self.game._connections.get(code, {}).values())
            # Archive first: a storage failure must not free the slot.
            try:
                self._archive(code)
            except PersistenceError:
                self.game.rooms.storage_failed = True
                raise
            task = self.game._ai_tasks.pop(code, None)
            if task is not None:
                task.cancel()
            async def close(connection):
                try:
                    await asyncio.wait_for(connection.send({"type": "websocket.close", "code": 4004}), 1)
                except Exception:
                    pass
            await asyncio.gather(*(close(connection) for connection in connections))
            self.usage.counts["heidi_releases"] += 1
            return True

    async def expire_idle_heidi_rooms(self, *, exclude_code=None):
        if self.game.rooms.storage_failed:
            return
        for table in self.heidi_tables():
            code = table["room_code"]
            # A running decision holds this lock. Check again on the next tick.
            if code != exclude_code and table["idle_seconds"] >= HEIDI_IDLE_SECONDS and not self._lock(code).locked():
                await self.release_heidi_table(code, idle_only=True)

    async def _heidi_maintenance_loop(self):
        while True:
            await asyncio.sleep(HEIDI_MAINTENANCE_SECONDS)
            try:
                await self.expire_idle_heidi_rooms()
            except Exception:
                self.usage.error("heidi_release_failed")

    async def _heidi_admin(self, scope, receive, send, client):
        from .heidi_admin import ASSETS
        path, method = scope.get("path"), scope.get("method")
        if self.admin_key is None:
            await self.game._json_response(send, 404, {"error": "unknown_endpoint"})
            return
        if method == "GET" and path in ASSETS:
            mime, body = ASSETS[path]
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", mime.encode()), (b"x-content-type-options", b"nosniff"),
                (b"referrer-policy", b"no-referrer"),
                (b"content-security-policy", b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")]})
            await send({"type": "http.response.body", "body": body.encode()})
            return
        offered = dict(scope.get("headers", [])).get(b"authorization", b"")
        if not self.admin_failures.allows(client) or not hmac.compare_digest(
                offered, b"Bearer " + self.admin_key.encode()):
            self.admin_failures.add(client)
            await self.game._json_response(send, 403, {"error": "admin_required"})
            return
        if path == "/v1/admin/heidi/status" and method == "GET":
            await self.game._json_response(send, 200, {"tables": self.heidi_tables(), "idle_timeout_seconds": HEIDI_IDLE_SECONDS})
            return
        if path == "/v1/admin/heidi/release" and method == "POST":
            if self.game.rooms.storage_failed:
                await self.game._json_response(send, 503, {"error": "storage_unavailable"})
                return
            try:
                body = b""
                while True:
                    message = await asyncio.wait_for(receive(), 10)
                    if message["type"] != "http.request":
                        raise ValueError("invalid_request")
                    body += message.get("body", b"")
                    if len(body) > 1024:
                        raise ValueError("request_too_large")
                    if not message.get("more_body", False):
                        break
                payload = json.loads(body)
                if (type(payload) is not dict or set(payload) != {"room_code"}
                        or not isinstance(payload["room_code"], str)
                        or re.fullmatch(r"[A-Z0-9]{6}", payload["room_code"]) is None):
                    raise ValueError("invalid_request")
                code = payload["room_code"]
                if code not in self.game.rooms._rooms:
                    released = False
                else:
                    released = await self.release_heidi_table(code)
                await self.game._json_response(send, 200 if released else 409,
                                               {"released": True, "room_code": code} if released else {"error": "heidi_table_not_active"})
            except (ValueError, UnicodeError, asyncio.TimeoutError):
                await self.game._json_response(send, 400, {"error": "invalid_request"})
            except PersistenceError:
                await self.game._json_response(send, 503, {"error": "storage_unavailable"})
            return
        await self.game._json_response(send, 404, {"error": "unknown_endpoint"})

    async def _room_creation_body(self, receive, client=None) -> bytes:
        """Read a create-room body, check and remove its room_passcode.

        The passcode is a hosting concern; the game sees the request without it.
        Malformed bodies pass through for the game's own validation.
        """
        chunks = []
        while True:
            message = await receive()
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        try:
            payload = json.loads(body) if body else {}
        except (ValueError, UnicodeError):
            payload = None
        offered = payload.pop("room_passcode", None) if type(payload) is dict else None
        if self.room_passcode is not None:
            if not self.passcode_failures.allows(client):
                raise PasscodeRefused("too_many_attempts", 429)
            if not isinstance(offered, str) or not offered:
                raise PasscodeRefused("room_passcode_required", 403)
            if not hmac.compare_digest(offered.encode(), self.room_passcode.encode()):
                self.passcode_failures.add(client)
                raise PasscodeRefused("invalid_room_passcode", 403)
        return json.dumps(payload).encode() if type(payload) is dict else body

    async def _offline_result(self, receive, send, client=None) -> None:
        """A browser reports a finished offline match (anonymous; see results.py)."""

        from .results import ResultRejected, offline_row, today
        if not self.result_posts.take(client):
            await self.game._json_response(send, 429, {"error": "too_many_attempts"})
            return
        body, size = b"", 0
        try:
            while True:
                message = await asyncio.wait_for(receive(), timeout=10)
                body += message.get("body", b""); size = len(body)
                if size > 2048:
                    raise ResultRejected("request_too_large")
                if not message.get("more_body", False):
                    break
            recorded = self.game.rooms.results.record(offline_row(json.loads(body or b"null"), day=today()))
        except (ResultRejected, ValueError, asyncio.TimeoutError) as exc:
            code = str(exc) if isinstance(exc, ResultRejected) else "invalid_result"
            await self.game._json_response(send, 507 if code == "results_full" else 400, {"error": code})
            return
        except PersistenceError:
            await self.game._json_response(send, 503, {"error": "storage_unavailable"})
            return
        self.usage.counts["results"] += 1
        await self.game._json_response(send, 200, {"recorded": recorded})

    async def _offline_record(self, receive, send, client=None) -> None:
        """A browser sends a finished offline match with every card (research.py)."""

        from .research import MAX_OFFLINE_BODY_BYTES, RecordRejected, offline_record
        from .results import today
        if not self.record_posts.take(client):
            await self.game._json_response(send, 429, {"error": "too_many_attempts"})
            return
        body = b""
        try:
            while True:
                message = await asyncio.wait_for(receive(), timeout=10)
                body += message.get("body", b"")
                if len(body) > MAX_OFFLINE_BODY_BYTES:
                    raise RecordRejected("request_too_large")
                if not message.get("more_body", False):
                    break
            payload = json.loads(body or b"null")
            async with self.record_check:  # one replay at a time, off the event loop
                record = await asyncio.to_thread(offline_record, payload, day=today())
            recorded = self.game.rooms.records.save(record)
        except (RecordRejected, ValueError, asyncio.TimeoutError) as exc:
            code = str(exc) if isinstance(exc, RecordRejected) else "invalid_record"
            await self.game._json_response(send, 413 if code == "request_too_large" else 400, {"error": code})
            return
        except PersistenceError:
            await self.game._json_response(send, 503, {"error": "storage_unavailable"})
            return
        self.usage.counts["records"] += 1
        await self.game._json_response(send, 200, {"recorded": recorded})

    async def _research_download(self, scope, send, client=None) -> None:
        """The owner downloads every match record as one gzip file of JSON
        lines: GET /v1/research/matches?key=<TUPPI_RESEARCH_KEY>. Without the
        key configured this endpoint does not exist."""

        from urllib.parse import parse_qs
        offered = (parse_qs((scope.get("query_string") or b"").decode("ascii", errors="replace")).get("key") or [""])[0]
        if self.research_key is None or not self.research_key_failures.allows(client) or not (
                offered and hmac.compare_digest(offered.encode(), self.research_key.encode())):
            if self.research_key is not None:
                self.research_key_failures.add(client)
            await self.game._json_response(send, 404, {"error": "unknown_endpoint"})
            return
        records = self.game.rooms.records
        day = time.strftime("%Y-%m-%d", time.gmtime())
        await send({"type": "http.response.start", "status": 200, "headers": [
            (b"content-type", b"application/gzip"), (b"cache-control", b"no-store"),
            (b"content-disposition", f'attachment; filename="tuppi-matches-{day}.jsonl.gz"'.encode())]})
        for chunk in records.download():
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _csp_report(self, receive, send, client=None) -> None:
        """A browser reports something the Content-Security-Policy blocked
        (hosted_site.py). Only the directive and the kind of blocked source
        are counted for the usage line; no addresses, paths or room codes."""

        accepted = self.csp_reports.take(client)
        body = b""
        try:
            while True:
                message = await asyncio.wait_for(receive(), timeout=10)
                body += message.get("body", b"")
                if len(body) > 16384:
                    raise ValueError("request_too_large")
                if not message.get("more_body", False):
                    break
            reports = json.loads(body) if accepted else []
        except (ValueError, asyncio.TimeoutError):
            reports = []
        # report-uri sends {"csp-report": {...}}; report-to a list of reports.
        for report in (reports if type(reports) is list else [reports])[:8]:
            if type(report) is not dict:
                continue
            fields = report.get("csp-report") if "csp-report" in report else report.get("body")
            if type(fields) is not dict:
                continue
            directive = str(fields.get("effective-directive") or fields.get("effectiveDirective")
                            or fields.get("violated-directive") or "").split(" ")[0]
            blocked = str(fields.get("blocked-uri") or fields.get("blockedURL") or "")
            scheme = blocked.split(":", 1)[0]  # report-uri sends a bare "data" or "blob"
            kind = blocked if blocked in {"inline", "eval", "wasm-eval", "trusted-types-sink"} else \
                scheme if scheme in {"data", "blob"} else "url" if blocked else "none"
            self.usage.csp_violation(directive, kind)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    def storage_state(self) -> str:
        """failed: a save failed, so changes stop until a restart recovers the
        last durable state. low: free space below the floor for new rooms."""
        if self.game.rooms.storage_failed:
            return "failed"
        store = self.game.rooms._store
        try:
            if store is not None and store.free_bytes() < self.min_free_bytes:
                return "low"
        except OSError:
            return "low"
        return "ok"

    def maintain(self) -> dict:
        """Archive idle rooms and prune the archive (hourly and at startup)."""
        self.expire_idle_rooms()
        store = self.game.rooms._store
        if store is None:
            return {"removed": 0}
        return store.prune_archive(max_age_days=self.archive_days, max_bytes=self.archive_max_bytes)

    async def _maintenance_loop(self):
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
            try:
                self.maintain()
            except Exception:  # never let housekeeping stop the authority
                pass

    def usage_gauges(self) -> dict[str, object]:
        rooms = self.game.rooms._rooms
        in_use = {code for code in rooms if self.in_use(code)}
        try:
            free = self.game.rooms._store.free_bytes() // 2**20 if self.game.rooms._store is not None else None
        except OSError:
            free = None
        return {"in_play": sum(rooms[code].runner is not None and not rooms[code].runner.terminal for code in in_use),
                # Distinct client addresses among the connections: 0 while
                # people are connected means the client header is not arriving.
                "connections": self.connections, "clients": len(self.client_connections),
                "rooms": len(rooms), "in_use": len(in_use),
                "rss_mb": resident_megabytes(), "disk_free_mb": free, "storage": self.storage_state()}

    def usage_line(self, *, force: bool = False) -> str | None:
        self.usage.observe_matches(self.game.rooms._rooms)
        return self.usage.line(self.usage_gauges(), force=force)

    async def _usage_loop(self):
        while True:
            await asyncio.sleep(USAGE_INTERVAL_SECONDS)
            try:
                line = self.usage_line()
                if line:
                    print(line, flush=True)
            except Exception:  # never let reporting stop the authority
                pass

    async def _http_game(self, scope, receive, send):
        started = False
        status = None
        async def tracked(message):
            nonlocal started, status
            started = started or message["type"] == "http.response.start"
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
        try:
            await self.game(scope, receive, tracked)
        except PersistenceError:
            if not started:
                await self.game._json_response(send, 503, {"error": "storage_unavailable"})
        return status

    def _lock(self, code):
        return self.room_locks.setdefault(code, asyncio.Lock())

    def in_use(self, code) -> bool:
        """Someone is connected, or the room was active within IDLE_ROOM_SECONDS
        (a room whose activity is unknown counts as in use)."""
        return bool(self.game._connections.get(code)) or time.time() - self.activity.get(code, time.time()) < IDLE_ROOM_SECONDS

    def _mtime(self, code):
        store = self.game.rooms._store
        if store is not None:
            return (store.root / f"room-{code}.json").stat().st_mtime
        return time.time()

    def expire_idle_rooms(self):
        """Archive idle records; never prune a connected room or a running job."""
        now = time.time()
        for code, room in tuple(self.game.rooms._rooms.items()):
            deadline = 7 * 86400 if room.runner is not None else 86400
            task = self.game._ai_tasks.get(code)
            if (self.game._connections.get(code) or (task is not None and not task.done())
                    or self.room_locks.get(code, asyncio.Lock()).locked()
                    or now - self.activity.get(code, now) < deadline):
                continue
            self._archive(code)

    def _archive(self, code):
        room = self.game.rooms._rooms[code]
        if room.runner is not None and not room.runner.terminal:
            self.game.rooms.record_match(room)  # an unfinished match: the deals played so far
        store = self.game.rooms._store
        if store is not None:
            store.archive_room(code)
        del self.game.rooms._rooms[code]
        self.activity.pop(code, None)
        self.heidi_activity.pop(code, None)
        self.room_locks.pop(code, None)
        self.game._connections.pop(code, None)
        self.game.forget_chat(code)

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    try:
                        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bot-admission")
                        asyncio.get_running_loop().set_default_executor(self.executor)
                        from .hosted_bot import warm
                        await asyncio.to_thread(warm)
                        self.maintain()
                        await self.expire_idle_heidi_rooms()
                        self.maintenance_task = asyncio.create_task(self._maintenance_loop())
                        self.heidi_maintenance_task = asyncio.create_task(self._heidi_maintenance_loop())
                        self.usage_task = asyncio.create_task(self._usage_loop())
                        client = self.client_header.decode() if self.client_header else "peer"
                        print(f"tuppi started release={str(self.release)[:12]} rooms={len(self.game.rooms._rooms)} "
                              f"client_address={client}", flush=True)
                        await send({"type": "lifespan.startup.complete"})
                    except Exception as exc:
                        await send({"type": "lifespan.startup.failed", "message": str(exc)})
                elif message["type"] == "lifespan.shutdown":
                    for task in (self.maintenance_task, self.usage_task, self.heidi_maintenance_task):
                        if task is not None:
                            task.cancel()
                    try:
                        print(f"tuppi stopping {self.usage_line(force=True)}", flush=True)
                    except Exception:
                        pass
                    for task in self.game._ai_tasks.values():
                        task.cancel()
                    await asyncio.gather(*self.game._ai_tasks.values(), return_exceptions=True)
                    # A save already started finishes before the process exits.
                    await asyncio.to_thread(self.save_executor.shutdown, wait=True)
                    from .hosted_bot import shutdown
                    await asyncio.to_thread(shutdown)
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("ascii", errors="replace")
        if origin and origin not in self.origins:
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await self.game._json_response(send, 403, {"error": "origin_not_allowed"})
            return
        path = scope.get("path", "")
        client = client_address(scope, self.client_header)
        if kind == "websocket":
            if (path != "/v1/ws" or self.connections >= self.max_connections or self.game.rooms.storage_failed
                    or self.client_connections.get(client, 0) >= CONNECTIONS_PER_CLIENT):
                await send({"type": "websocket.close", "code": 1013})
                return
            self.connections += 1
            if client is not None:
                self.client_connections[client] = self.client_connections.get(client, 0) + 1
            first = True
            async def limited_receive():
                nonlocal first
                message = await asyncio.wait_for(receive(), timeout=20 if first else 70)
                if message["type"] == "websocket.receive":
                    first = False
                    if len((message.get("text") or "").encode()) + len(message.get("bytes") or b"") > 32768:
                        return {"type": "websocket.disconnect", "code": 1009}
                return message
            try:
                await self.game(scope, limited_receive, send)
            except asyncio.TimeoutError:
                await send({"type": "websocket.close", "code": 1001})
            except PersistenceError:
                # The move was not saved and was not acknowledged; the client
                # retries it after the restart that recovers durable state.
                await send({"type": "websocket.close", "code": 1011})
            finally:
                self.connections -= 1
                if client is not None:
                    remaining = self.client_connections.pop(client) - 1
                    if remaining:
                        self.client_connections[client] = remaining
            return
        if kind != "http":
            return
        async def cors_send(message):
            if message["type"] == "http.response.start":
                message["headers"] += [(b"cache-control", b"no-store"), (b"vary", b"Origin")]
                if origin:
                    message["headers"] += [(b"access-control-allow-origin", origin.encode()),
                        (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                        (b"access-control-allow-headers", b"Content-Type")]
            await send(message)
        if scope.get("method") == "OPTIONS":
            await self.game._json_response(cors_send, 200, {})
            return
        if path.startswith("/v1/admin/heidi"):
            await self._heidi_admin(scope, receive, cors_send, client)
            return
        if scope.get("method") == "GET" and path in {"/healthz", "/v1/compatibility"}:
            from .app import FEATURES
            storage = self.storage_state()
            await self.game._json_response(cors_send, 503 if storage == "failed" else 200, {
                "compatible": True, "features": list(FEATURES),
                "create_passcode_required": self.room_passcode is not None,
                "protocol_version": "tuppi.network.v1", "ruleset_id": "project_target_v3",
                "status": "storage_failed" if storage == "failed" else "ok", "storage": storage,
                "bot": self.bot_identity,
                "bot_options": bot_options(self.bot_identity)})
            return
        if path == "/v1/results/summary" and scope.get("method") == "GET":
            await self.game._json_response(cors_send, 200, self.game.rooms.results.summary())
            return
        if path == "/v1/results" and scope.get("method") == "POST":
            await self._offline_result(receive, cors_send, client)
            return
        if path == "/v1/research/matches" and scope.get("method") == "POST":
            await self._offline_record(receive, cors_send, client)
            return
        if path == "/v1/research/matches" and scope.get("method") == "GET":
            await self._research_download(scope, send, client)
            return
        if path == "/v1/csp-report" and scope.get("method") == "POST":
            await self._csp_report(receive, cors_send, client)
            return
        if scope.get("method") == "POST" and self.game.rooms.storage_failed:
            await self.game._json_response(cors_send, 503, {"error": "storage_unavailable"})
            return
        route = ROOM_ROUTE.fullmatch(path)
        if scope.get("method") != "POST" or (path != "/v1/rooms" and route is None):
            await self.game._json_response(cors_send, 404, {"error": "unknown_endpoint"})
            return
        body_size = 0
        async def limited_body():
            nonlocal body_size
            message = await asyncio.wait_for(receive(), timeout=10)
            if message["type"] == "http.disconnect":
                raise ValueError("request_disconnected")
            body_size += len(message.get("body", b""))
            if body_size > 16384:
                raise ValueError("request_too_large")
            return message
        if path == "/v1/rooms":
            try:
                body = await self._room_creation_body(limited_body, client)
            except PasscodeRefused as refusal:
                await self.game._json_response(cors_send, refusal.status, {"error": str(refusal)})
                return
            except (ValueError, asyncio.TimeoutError) as exc:
                await self.game._json_response(cors_send, 400, {"error": str(exc) or "invalid_request"})
                return
            async def creation_body():
                return {"type": "http.request", "body": body, "more_body": False}
            if self.storage_state() == "low":
                await self.game._json_response(cors_send, 503, {"error": "storage_low"})
                return
            async with self.creation_lock:
                self.expire_idle_rooms()
                active_rooms = sum((r.runner is None or not r.runner.terminal) and self.in_use(code)
                                   for code, r in self.game.rooms._rooms.items())
                if active_rooms >= self.max_rooms or not self.created.allows(client):
                    await self.game._json_response(cors_send, 503, {"error": "server_busy"})
                    return
                if len(self.game.rooms._rooms) >= self.max_retained_rooms:
                    # Archive the longest-idle finished room, else the longest-idle
                    # room nobody is using; never one with a running bot task.
                    def idle(code, room):
                        task = self.game._ai_tasks.get(code)
                        return not self.in_use(code) and (task is None or task.done()) and not self.room_locks.get(code, asyncio.Lock()).locked()
                    finished = [code for code, room in self.game.rooms._rooms.items()
                                if room.runner is not None and room.runner.terminal and not self.game._connections.get(code)]
                    candidates = sorted(finished or [code for code, room in self.game.rooms._rooms.items() if idle(code, room)],
                                        key=lambda code: self.activity.get(code, 0))
                    if not candidates:
                        await self.game._json_response(cors_send, 503, {"error": "server_busy"})
                        return
                    self._archive(candidates[0])
                self.created.add(client)
                before = set(self.game.rooms._rooms)
                await self._http_game(scope, creation_body, cors_send)
                for code in set(self.game.rooms._rooms) - before:
                    self.activity[code] = time.time()
                    self.usage.counts["created"] += 1
        else:
            if route[2] == "ready":
                try:
                    await self.expire_idle_heidi_rooms()
                except PersistenceError:
                    await self.game._json_response(cors_send, 503, {"error": "storage_unavailable"})
                    return
            if route[1].upper() not in self.game.rooms._rooms:
                await self.game._json_response(cors_send, 404, {"error": "room_not_found"})
                return
            async with self._lock(route[1].upper()):
                status = await self._http_game(scope, limited_body, cors_send)
                if route[1].upper() in self.game.rooms._rooms:
                    self.activity[route[1].upper()] = time.time()
                    if status == 200 and route[2] in {"join", "configure", "settings", "name", "release", "swap", "leave"}:
                        self.heidi_activity[route[1].upper()] = time.time()
