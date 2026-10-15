"""Single-authority private alpha with an explicit browser boundary.

One ASGI process owns rooms. Two admission threads feed one spawned, serial
native bot process; authoritative room mutations are ordered by per-room locks.
Use ``uvicorn tuppi_server.hosted:create_hosted_app --factory --workers 1``.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

ROOM_ROUTE = re.compile(r"^/v1/rooms/([A-Z0-9]{6})/(join|configure|settings|ready)$", re.I)


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


def verify_bot_identity(level: str = "full") -> dict:
    spec = importlib.util.find_spec("tuppi_ai")
    if spec is None or spec.origin is None:
        raise RuntimeError("the trained bot package is required")
    root = Path(spec.origin).resolve().parents[1]
    manifest = json.loads((root / "models/hosted-models.json").read_text())
    expected = {"vrpo1_actor_0504.pt", "vrpo3_final.pt", "equity_incumbent.json", "vrpo3_final.lite.npz"}
    if set(manifest) != expected:
        raise RuntimeError("hosted model manifest fields are invalid")
    for name, digest in manifest.items():
        if hashlib.sha256((root / "models" / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"hosted model identity mismatch: {name}")
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
    return HostedBoundary(app, origins=origins, bot_identity=identity, max_bot_rooms=bot_room_limit(level, 8))


class HostedBoundary:
    def __init__(self, game, *, origins, bot_identity=None, max_rooms=8, max_connections=32, max_bot_rooms=1, max_retained_rooms=32):
        self.game = game
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
                for other in game.rooms._rooms.values() if other.code != room.code)
            if room.runner is None and room.ai_seats and active >= self.max_bot_rooms:
                from .rooms import RoomError
                raise RoomError("server_busy")
            return original_ready(code=code, token=token, auto_run_ai=auto_run_ai)
        game.rooms.mark_ready = ready

        async def auth(request, send):
            code = str(request.get("payload", {}).get("room_code", "")).upper()
            self.game.rooms.get(code)
            async with self._lock(code):
                connection = await original_auth(request, send)
                self.activity[code] = time.time()
                return connection

        async def message(connection, request):
            async with self._lock(connection.room_code):
                await original_message(connection, request)
                self.activity[connection.room_code] = time.time()

        async def continuation(code):
            async with self._lock(code):
                await original_continue(code)
                self.activity[code] = time.time()

        game._authenticate, game._handle_message, game._continue_ai = auth, message, continuation

    def _lock(self, code):
        return self.room_locks.setdefault(code, asyncio.Lock())

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
                        await send({"type": "lifespan.startup.complete"})
                    except Exception as exc:
                        await send({"type": "lifespan.startup.failed", "message": str(exc)})
                elif message["type"] == "lifespan.shutdown":
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
            if path != "/v1/ws" or self.connections >= self.max_connections:
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
            await self.game._json_response(cors_send, 200, {"compatible": True,
                "protocol_version": "tuppi.network.v1", "ruleset_id": "project_target_v3",
                "status": "ok", "bot": self.bot_identity})
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
            async with self.creation_lock:
                self.expire_idle_rooms()
                self.created = [t for t in self.created if time.time() - t < 60]
                active_rooms = sum(r.runner is None or not r.runner.terminal for r in self.game.rooms._rooms.values())
                if active_rooms >= self.max_rooms or len(self.created) >= 12:
                    await self.game._json_response(cors_send, 503, {"error": "server_busy"})
                    return
                if len(self.game.rooms._rooms) >= self.max_retained_rooms:
                    candidates = sorted((code for code, room in self.game.rooms._rooms.items()
                        if room.runner is not None and room.runner.terminal and not self.game._connections.get(code)),
                        key=lambda code: self.activity.get(code, 0))
                    if not candidates:
                        await self.game._json_response(cors_send, 503, {"error": "server_busy"})
                        return
                    self._archive(candidates[0])
                self.created.append(time.time())
                before = set(self.game.rooms._rooms)
                await self.game(scope, limited_body, cors_send)
                for code in set(self.game.rooms._rooms) - before:
                    self.activity[code] = time.time()
        else:
            if route[1].upper() not in self.game.rooms._rooms:
                await self.game._json_response(cors_send, 404, {"error": "room_not_found"})
                return
            async with self._lock(route[1].upper()):
                await self.game(scope, limited_body, cors_send)
