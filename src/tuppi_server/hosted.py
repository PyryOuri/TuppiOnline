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
from urllib.parse import urlsplit

from .persistence import PersistenceError

ROOM_ROUTE = re.compile(r"^/v1/rooms/([A-Z0-9]{6})/(join|configure|settings|ready|leaderboard)$", re.I)
#: Wrong room-creation passcodes accepted per minute before refusing all tries.
MAX_PASSCODE_FAILURES_PER_MINUTE = 20
#: How often idle rooms are archived and old archives pruned.
MAINTENANCE_INTERVAL_SECONDS = 3600
#: An unfinished room nobody is connected to stops counting towards the
#: active-room and bot-room limits after this long without activity. It stays
#: resumable; abandoned lobbies and matches must not lock others out.
IDLE_ROOM_SECONDS = 1800


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
        path, expected = lite, {"vrpo3_final.lite.npz"}
    else:
        if level == "full" and not full.is_file() and lite.is_file():
            raise RuntimeError("this runtime contains only the lite bot; use the full image for TUPPI_HOSTED_BOT_LEVEL=full")
        path = full
        expected = {"vrpo1_actor_0504.pt", "vrpo3_final.pt", "equity_incumbent.json", "vrpo3_final.lite.npz"}
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
    bot = ({"profile": "tuppi_ai_lite_v1", "level": "lite", "search": None} if level == "lite"
           else {"profile": "tuppi_ai_search_v1", "level": "full", "worlds": 1024})
    return {**bot,
        "models_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        "native_sha256": hashlib.sha256(Path(native.lib._name).read_bytes()).hexdigest()}


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
                          room_passcode=room_passcode_from_environment(), **storage_limits_from_environment())


class PasscodeRefused(Exception):
    def __init__(self, code: str, status: int):
        super().__init__(code)
        self.status = status


class HostedBoundary:
    def __init__(self, game, *, origins, bot_identity=None, max_rooms=8, max_connections=32, max_bot_rooms=1,
                 max_retained_rooms=32, room_passcode=None, archive_days=30, archive_max_bytes=200 * 2**20,
                 min_free_bytes=50 * 2**20):
        self.game = game
        self.archive_days, self.archive_max_bytes = archive_days, archive_max_bytes
        self.min_free_bytes = min_free_bytes
        self.maintenance_task = None
        self.room_passcode = room_passcode
        self.passcode_failures = []
        self.origins = frozenset(origins)
        self.bot_identity = bot_identity or {"profile": "test"}
        self.max_rooms, self.max_connections = max_rooms, max_connections
        self.max_bot_rooms = max_bot_rooms
        self.max_retained_rooms = max_retained_rooms
        self.connections = 0
        self.created = []
        self.room_locks = {}
        self.creation_lock = asyncio.Lock()
        self.executor = None
        self.activity = {code: self._mtime(code) for code in game.rooms._rooms}
        # Core authentication and client commands share the same room lock as
        # HTTP configuration and continuation. A long native bid cannot allow
        # a second connection to observe a half-applied reveal.
        original_auth = game._authenticate
        original_message = game._handle_message
        original_continue = game._continue_ai
        original_ready = game.rooms.mark_ready
        def ready(*, code, token, auto_run_ai=True):
            room, _ = game.rooms.session(code=code, token=token)
            active = sum(other.runner is not None and not other.runner.terminal and bool(other.ai_seats)
                and self.in_use(other.code) for other in game.rooms._rooms.values() if other.code != room.code)
            if room.runner is None and room.ai_seats and active >= self.max_bot_rooms:
                from .rooms import RoomError
                raise RoomError("server_busy")
            return original_ready(code=code, token=token, auto_run_ai=auto_run_ai)
        game.rooms.mark_ready = ready

        async def auth(request, send):
            if game.rooms.storage_failed:
                from .rooms import RoomError
                raise RoomError("storage_unavailable")
            code = str(request.get("payload", {}).get("room_code", "")).upper()
            self.game.rooms.get(code)
            async with self._lock(code):
                connection = await original_auth(request, send)
                self.activity[code] = time.time()
                return connection

        async def message(connection, request):
            if game.rooms.storage_failed and request.get("message_type") != "ping":
                from .rooms import RoomError
                raise RoomError("storage_unavailable")
            async with self._lock(connection.room_code):
                await original_message(connection, request)
                self.activity[connection.room_code] = time.time()

        async def continuation(code):
            async with self._lock(code):
                await original_continue(code)
                self.activity[code] = time.time()

        game._authenticate, game._handle_message, game._continue_ai = auth, message, continuation

    async def _room_creation_body(self, receive) -> bytes:
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
            now = time.time()
            self.passcode_failures = [t for t in self.passcode_failures if now - t < 60]
            if len(self.passcode_failures) >= MAX_PASSCODE_FAILURES_PER_MINUTE:
                raise PasscodeRefused("too_many_attempts", 429)
            if not isinstance(offered, str) or not offered:
                raise PasscodeRefused("room_passcode_required", 403)
            if not hmac.compare_digest(offered.encode(), self.room_passcode.encode()):
                self.passcode_failures.append(now)
                raise PasscodeRefused("invalid_room_passcode", 403)
        return json.dumps(payload).encode() if type(payload) is dict else body

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

    async def _http_game(self, scope, receive, send):
        started = False
        async def tracked(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)
        try:
            await self.game(scope, receive, tracked)
        except PersistenceError:
            if not started:
                await self.game._json_response(send, 503, {"error": "storage_unavailable"})

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
        store = self.game.rooms._store
        if store is not None:
            source = store.root / f"room-{code}.json"
            if source.is_symlink():
                raise RuntimeError("invalid private room file")
            archive = store.root / "expired"
            archive.mkdir(mode=0o700, exist_ok=True)
            source.rename(archive / f"room-{code}-{time.time_ns()}.json")
        del self.game.rooms._rooms[code]
        self.activity.pop(code, None)
        self.room_locks.pop(code, None)
        self.game._connections.pop(code, None)

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
                        self.maintenance_task = asyncio.create_task(self._maintenance_loop())
                        await send({"type": "lifespan.startup.complete"})
                    except Exception as exc:
                        await send({"type": "lifespan.startup.failed", "message": str(exc)})
                elif message["type"] == "lifespan.shutdown":
                    if self.maintenance_task is not None:
                        self.maintenance_task.cancel()
                    for task in self.game._ai_tasks.values():
                        task.cancel()
                    await asyncio.gather(*self.game._ai_tasks.values(), return_exceptions=True)
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
        if kind == "websocket":
            if path != "/v1/ws" or self.connections >= self.max_connections or self.game.rooms.storage_failed:
                await send({"type": "websocket.close", "code": 1013})
                return
            self.connections += 1
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
        if scope.get("method") == "GET" and path in {"/healthz", "/v1/compatibility"}:
            from .app import FEATURES
            storage = self.storage_state()
            await self.game._json_response(cors_send, 503 if storage == "failed" else 200, {
                "compatible": True, "features": list(FEATURES),
                "create_passcode_required": self.room_passcode is not None,
                "protocol_version": "tuppi.network.v1", "ruleset_id": "project_target_v3",
                "status": "storage_failed" if storage == "failed" else "ok", "storage": storage,
                "bot": self.bot_identity})
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
                body = await self._room_creation_body(limited_body)
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
                self.created = [t for t in self.created if time.time() - t < 60]
                active_rooms = sum((r.runner is None or not r.runner.terminal) and self.in_use(code)
                                   for code, r in self.game.rooms._rooms.items())
                if active_rooms >= self.max_rooms or len(self.created) >= 12:
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
                self.created.append(time.time())
                before = set(self.game.rooms._rooms)
                await self._http_game(scope, creation_body, cors_send)
                for code in set(self.game.rooms._rooms) - before:
                    self.activity[code] = time.time()
        else:
            if route[1].upper() not in self.game.rooms._rooms:
                await self.game._json_response(cors_send, 404, {"error": "room_not_found"})
                return
            async with self._lock(route[1].upper()):
                await self._http_game(scope, limited_body, cors_send)
                if route[1].upper() in self.game.rooms._rooms:
                    self.activity[route[1].upper()] = time.time()
