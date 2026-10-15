"""Dependency-light ASGI transport for the private online alpha.

The app deliberately uses only the ASGI call contract. ``uvicorn`` is an
optional runtime dependency, so core server and privacy tests do not require a
web framework or a paid hosting service.
"""

from __future__ import annotations

import asyncio
import argparse
from dataclasses import dataclass
import json
import os
import socket
from typing import Any, Awaitable, Callable, Sequence
from urllib.parse import parse_qs

from tuppi_engine import action_from_data, canonical_json_bytes, strict_json_loads

from .match_runner import PROTOCOL_VERSION
from .rooms import RoomError, RoomManager


Send = Callable[[dict[str, Any]], Awaitable[None]]
#: Optional commands this server accepts; clients show their controls only
#: when the server lists them.
FEATURES = ("pause", "rematch")
Receive = Callable[[], Awaitable[dict[str, Any]]]


class ProtocolError(Exception):
    """A client message failed the network envelope contract."""


@dataclass(slots=True)
class Connection:
    room_code: str
    token: str
    seat: int
    send: Send
    last_event_index: int = -1


class TuppiASGIApp:
    """HTTP bootstrap plus authenticated WebSocket live sessions."""

    def __init__(self, rooms: RoomManager | None = None) -> None:
        self.rooms = rooms or RoomManager()
        self._connections: dict[str, dict[str, Connection]] = {}
        self._ai_tasks: dict[str, asyncio.Task[None]] = {}

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "http":
            await self._http(scope, receive, send)
        elif scope_type == "websocket":
            await self._websocket(scope, receive, send)
        else:
            raise RuntimeError(f"unsupported ASGI scope type: {scope_type}")

    async def _http(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method == "GET" and path in {"/healthz", "/v1/compatibility"}:
            await self._json_response(
                send,
                200,
                {
                    "compatible": True,
                    "features": list(FEATURES),
                    "protocol_version": PROTOCOL_VERSION,
                    "status": "ok",
                },
            )
            return
        if method != "POST":
            await self._json_response(send, 405, {"error": "method_not_allowed"})
            return
        try:
            body = await self._read_body(receive)
            payload = strict_json_loads(body.decode("utf-8")) if body else {}
            if type(payload) is not dict:
                raise ProtocolError("request body must be an object")
            if (
                path.endswith("/review")
                or path.endswith("/training_analysis")
                or ("/deals/" in path and path.endswith("/analysis"))
            ):
                # A review searches for seconds, a real-game deal analysis
                # replays the deal with four searching bots, and the sooli odds
                # sample thousands of layouts: keep the event loop (and the
                # other seats' play) moving while they run.
                response = await asyncio.to_thread(self._http_command, path, payload)
            else:
                response = self._http_command(path, payload)
        except RoomError as exc:
            status = 404 if str(exc) in {"room_not_found", "invalid_session"} else 409
            await self._json_response(send, status, {"error": str(exc)})
            return
        except (ProtocolError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            await self._json_response(send, 400, {"error": str(exc) or "invalid_request"})
            return
        await self._json_response(send, 200, response)
        if path.endswith(("/settings", "/configure", "/join", "/ready")):
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4:
                await self._broadcast_lobby(parts[2].upper())
                room = self.rooms.get(parts[2].upper())
                if room.runner is not None:
                    await self._broadcast_match(room.code)
                    self._schedule_ai_continuation(room.code)

    def _http_command(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        if path == "/v1/rooms":
            self._require_fields(payload, required={"display_name", "ai_seats"})
            display_name = payload.get("display_name")
            ai_seats = self._ai_seats(payload.get("ai_seats", []))
            room, session = self.rooms.create_room(
                display_name=display_name,  # type: ignore[arg-type]
                ai_seats=ai_seats,
            )
            return {
                "room_code": room.code,
                "seat": session.seat,
                "session_token": session.token,
                "lobby": room.snapshot(),
            }

        parts = [part for part in path.split("/") if part]
        if (
            len(parts) == 6
            and parts[0:2] == ["v1", "rooms"]
            and parts[3] == "deals"
            and parts[5] == "review"
        ):
            self._require_fields(payload, required={"session_token"})
            try:
                deal_number = int(parts[4])
            except ValueError as exc:
                raise ProtocolError("invalid_deal_number") from exc
            if str(deal_number) != parts[4]:
                raise ProtocolError("invalid_deal_number")
            return self.rooms.deal_review_for_session(
                code=parts[2].upper(),
                token=self._string(payload, "session_token"),
                deal_number=deal_number,
            )
        if (
            len(parts) == 6
            and parts[0:2] == ["v1", "rooms"]
            and parts[3] == "deals"
            and parts[5] == "analysis"
        ):
            self._require_fields(payload, required={"session_token"})
            try:
                deal_number = int(parts[4])
            except ValueError as exc:
                raise ProtocolError("invalid_deal_number") from exc
            if str(deal_number) != parts[4]:
                raise ProtocolError("invalid_deal_number")
            return self.rooms.completed_deal_analysis_for_session(
                code=parts[2].upper(),
                token=self._string(payload, "session_token"),
                deal_number=deal_number,
            )
        if len(parts) == 4 and parts[0:2] == ["v1", "rooms"]:
            code = parts[2].upper()
            command = parts[3]
            if command == "join":
                self._require_fields(payload, required={"display_name"})
                room, session = self.rooms.join_room(
                    code=code,
                    display_name=payload.get("display_name"),  # type: ignore[arg-type]
                )
                return {
                    "room_code": room.code,
                    "seat": session.seat,
                    "session_token": session.token,
                    "lobby": room.snapshot(),
                }
            if command == "analysis":
                self._require_fields(payload, required={"session_token"})
                return self.rooms.post_match_analysis_for_session(
                    code=code,
                    token=self._string(payload, "session_token"),
                )
            if command == "training_analysis":
                self._require_fields(payload, required={"session_token"})
                return self.rooms.training_analysis_for_session(
                    code=code,
                    token=self._string(payload, "session_token"),
                )
            if command == "configure":
                self._require_fields(
                    payload,
                    required={"session_token", "ai_seats"},
                )
                room = self.rooms.set_ai_seats(
                    code=code,
                    host_token=self._string(payload, "session_token"),
                    ai_seats=self._ai_seats(payload.get("ai_seats", [])),
                )
                return {"lobby": room.snapshot()}
            if command == "settings":
                self._require_fields(
                    payload,
                    required={"session_token", "ai_action_delay_ms"},
                )
                room = self.rooms.set_ai_action_delay(
                    code=code,
                    host_token=self._string(payload, "session_token"),
                    ai_action_delay_ms=self._integer(payload, "ai_action_delay_ms"),
                )
                return {"lobby": room.snapshot()}
            if command == "ready":
                self._require_fields(payload, required={"session_token"})
                room = self.rooms.mark_ready(
                    code=code,
                    token=self._string(payload, "session_token"),
                    auto_run_ai=False,
                )
                return {
                    "lobby": room.snapshot(),
                    "playing": room.runner is not None,
                }
        raise ProtocolError("unknown_endpoint")

    async def _websocket(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        await send({"type": "websocket.accept"})
        connection: Connection | None = None
        try:
            while True:
                message = await receive()
                message_type = message.get("type")
                if message_type == "websocket.disconnect":
                    return
                if message_type != "websocket.receive":
                    continue
                raw = message.get("text")
                if raw is None and message.get("bytes") is not None:
                    raw = message["bytes"].decode("utf-8")
                if not isinstance(raw, str):
                    await self._send_error(send, "invalid_message")
                    continue
                try:
                    request = self._parse_message(raw)
                    if connection is None:
                        connection = await self._authenticate(request, send)
                    else:
                        await self._handle_message(connection, request)
                except RoomError as exc:
                    await self._send_error(send, str(exc))
                except ProtocolError as exc:
                    if connection is None and str(exc) == "protocol_mismatch":
                        return
                    await self._send_error(send, str(exc) or "invalid_message")
                except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                    await self._send_error(send, str(exc) or "invalid_message")
        finally:
            if connection is not None:
                current = self._connections.get(connection.room_code, {}).get(connection.token)
                if current is connection:
                    self._connections[connection.room_code].pop(connection.token, None)

    async def _authenticate(self, request: dict[str, object], send: Send) -> Connection:
        if request.get("message_type") != "hello":
            raise ProtocolError("first_message_must_be_hello")
        payload = self._payload(request)
        self._require_fields(
            payload,
            required={"protocol_version", "room_code", "session_token"},
        )
        if payload.get("protocol_version") != PROTOCOL_VERSION:
            await self._send_message(
                send,
                "compatibility_result",
                {
                    "compatible": False,
                    "supported_protocol_versions": [PROTOCOL_VERSION],
                    "message_key": "update_required",
                },
            )
            await send({"type": "websocket.close", "code": 1002})
            raise ProtocolError("protocol_mismatch")
        room_code = self._string(payload, "room_code").upper()
        token = self._string(payload, "session_token")
        room, session = self.rooms.session(code=room_code, token=token)
        connection = Connection(
            room_code=room.code,
            token=token,
            seat=session.seat,
            send=send,
        )
        previous = self._connections.setdefault(room.code, {}).get(token)
        self._connections[room.code][token] = connection
        if previous is not None:
            try:
                await previous.send({"type": "websocket.close", "code": 4001})
            except (OSError, RuntimeError):
                pass
        await self._send_message(
            send,
            "hello_ack",
            {
                "compatible": True,
                "features": list(FEATURES),
                "protocol_version": PROTOCOL_VERSION,
                "room_code": room.code,
                "seat": session.seat,
            },
        )
        await self._send_message(send, "lobby_snapshot", room.snapshot())
        if room.runner is not None:
            await self._send_match_update(connection)
            if (room.runner.current_actor in room.runner.ai_seats
                    or (not room.runner.terminal and room.runner.state.phase.value == "DEAL_COMPLETE")):
                self._schedule_ai_continuation(room.code)
        return connection

    async def _handle_message(
        self,
        connection: Connection,
        request: dict[str, object],
    ) -> None:
        if self._connections.get(connection.room_code, {}).get(connection.token) is not connection:
            raise RoomError("session_replaced")
        message_type = request.get("message_type")
        payload = self._payload(request)
        room, session = self.rooms.session(
            code=connection.room_code,
            token=connection.token,
        )
        if message_type == "ping":
            self._require_fields(payload, required=set())
            await self._send_message(connection.send, "pong", {})
            return
        if message_type == "ready":
            self._require_fields(payload, required={"session_token"})
            if self._string(payload, "session_token") != session.token:
                raise RoomError("invalid_session")
            was_playing = room.runner is not None
            room = self.rooms.mark_ready(
                code=room.code,
                token=session.token,
                auto_run_ai=False,
            )
            await self._broadcast_lobby(room.code)
            if room.runner is not None:
                await self._broadcast_match(room.code)
                if not was_playing:
                    self._schedule_ai_continuation(room.code)
            return
        if message_type in {"pause", "resume"}:
            self._require_fields(payload, required=set())
            room = self.rooms.set_paused(code=room.code, host_token=session.token,
                                         paused=message_type == "pause")
            await self._broadcast_lobby(room.code)
            if not room.paused:
                self._schedule_ai_continuation(room.code)
            return
        if message_type == "rematch":
            self._require_fields(payload, required=set())
            room = self.rooms.start_rematch(code=room.code, host_token=session.token)
            # The next match's events start again from 0 for every seat.
            for other in self._connections.get(room.code, {}).values():
                other.last_event_index = -1
            await self._broadcast_lobby(room.code)
            return
        if message_type == "reconnect":
            self._require_fields(payload, required={"last_applied_event_index"})
            runner = self._require_runner(room)
            last_index = payload.get("last_applied_event_index", -1)
            result = runner.reconnect(
                seat=session.seat,
                last_applied_event_index=last_index,  # type: ignore[arg-type]
            )
            connection.last_event_index = runner.event_cursor
            await self._send_message(connection.send, "reconnect_result", result)
            return
        if message_type == "action_submission":
            self._require_fields(
                payload,
                required={
                    "action",
                    "client_action_id",
                    "expected_event_index",
                    "match_ref",
                },
            )
            runner = self._require_runner(room)
            try:
                action = action_from_data(payload.get("action"))
            except Exception:
                await self._reject_submission(connection, payload, runner, "malformed_action")
                return
            if room.paused:
                # Not recorded: the player chooses again after the resume.
                await self._reject_submission(connection, payload, runner, "paused")
                return
            async def publish_ai_action() -> None:
                self.rooms.persist(room)
                await self._broadcast_match(room.code)

            async def publish_human_action() -> None:
                self.rooms.persist(room)
                await self._broadcast_match(room.code)

            result = await runner.submit_async(
                seat=session.seat,
                client_action_id=self._string(payload, "client_action_id"),
                match_ref=self._string(payload, "match_ref"),
                expected_event_index=payload.get("expected_event_index"),  # type: ignore[arg-type]
                action=action,
                on_human_action=publish_human_action,
                on_state_change=publish_ai_action,
                ai_action_delay_seconds=room.ai_action_delay_ms / 1000,
                paused=lambda: room.paused,
            )
            if result.get("status") == "accepted":
                if runner.terminal:
                    room.lifecycle = "completed"
                self.rooms.persist(room)
            acknowledgement = {
                key: value
                for key, value in result.items()
                if key
                not in {
                    "event_batch",
                    "event_delta",
                    "observation",
                    "latest_observation",
                    "match_result",
                }
            }
            await self._send_message(
                connection.send,
                "action_acknowledgement",
                acknowledgement,
            )
            if result.get("status") == "accepted":
                await self._broadcast_match(room.code)
            elif result.get("status") == "stale":
                connection.last_event_index = runner.event_cursor
                await self._send_message(
                    connection.send,
                    "reconnect_result",
                    {
                        "event_delta": result["event_delta"],
                        "completed_deals": runner.reconnect(
                            seat=session.seat,
                            last_applied_event_index=runner.event_cursor,
                        )["completed_deals"],
                        "observation": result["latest_observation"],
                        "status": "connected",
                        **({"bidding": runner.bidding(session.seat)} if runner.bidding(session.seat) is not None else {}),
                    },
                )
            elif result.get("status") == "duplicate":
                await self._send_match_update(connection)
            return
        raise ProtocolError("unknown_message_type")

    async def _reject_submission(self, connection: Connection, payload: dict[str, object],
                                 runner, code: str) -> None:
        await self._send_message(
            connection.send,
            "action_acknowledgement",
            {
                "accepted_event_indices": [],
                "client_action_id": (
                    payload.get("client_action_id")
                    if isinstance(payload.get("client_action_id"), str)
                    else "malformed-action"
                ),
                "last_event_index": runner.event_cursor,
                "match_ref": runner.match_ref,
                "schema_version": "tuppi.network.action_acknowledgement.v1",
                "status": "rejected",
                "code": code,
            },
        )

    async def _broadcast_lobby(self, room_code: str) -> None:
        room = self.rooms.get(room_code)
        for connection in tuple(self._connections.get(room.code, {}).values()):
            try:
                await self._send_message(connection.send, "lobby_snapshot", room.snapshot())
            except (OSError, RuntimeError):
                if self._connections.get(room.code, {}).get(connection.token) is connection:
                    self._connections[room.code].pop(connection.token, None)

    async def _broadcast_match(self, room_code: str) -> None:
        for connection in tuple(self._connections.get(room_code, {}).values()):
            try:
                await self._send_match_update(connection)
            except (OSError, RuntimeError):
                if self._connections.get(room_code, {}).get(connection.token) is connection:
                    self._connections[room_code].pop(connection.token, None)

    def _schedule_ai_continuation(self, room_code: str) -> None:
        current = self._ai_tasks.get(room_code)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self._continue_ai(room_code))
        self._ai_tasks[room_code] = task

        def clear_task(completed: asyncio.Task[None]) -> None:
            if self._ai_tasks.get(room_code) is completed:
                self._ai_tasks.pop(room_code, None)

        task.add_done_callback(clear_task)

    async def _continue_ai(self, room_code: str) -> None:
        room = self.rooms.get(room_code)
        runner = self._require_runner(room)

        async def publish_ai_action() -> None:
            self.rooms.persist(room)
            await self._broadcast_match(room.code)

        await runner.run_ai_async(
            on_state_change=publish_ai_action,
            ai_action_delay_seconds=room.ai_action_delay_ms / 1000,
            paused=lambda: room.paused,
        )
        self.rooms.persist(room)
        await self._broadcast_match(room.code)
        if runner.terminal:
            room.lifecycle = "completed"
            self.rooms.persist(room)

    async def _send_match_update(self, connection: Connection) -> None:
        room, session = self.rooms.session(
            code=connection.room_code,
            token=connection.token,
        )
        runner = self._require_runner(room)
        # One authenticated reconnect supplies every part of this update: the
        # seat's observation and, at termination, its match result. Nothing
        # awaits in between, so no cross-seat state can be shared here.
        reconnect = runner.reconnect(
            seat=session.seat,
            last_applied_event_index=connection.last_event_index,
        )
        payload = {
            "completed_deals": reconnect["completed_deals"],
            "event_batch": reconnect["event_delta"],
            "last_event_index": runner.event_cursor,
            "match_ref": runner.match_ref,
            "observation": reconnect["observation"],
        }
        if "bidding" in reconnect:
            # project_target_v3 showing: lock status and this seat's own bid only.
            payload["bidding"] = reconnect["bidding"]
        if runner.terminal:
            payload["match_result"] = reconnect.get("match_result")
        connection.last_event_index = runner.event_cursor
        await self._send_message(connection.send, "match_update", payload)

    @staticmethod
    def _require_runner(room):
        if room.runner is None:
            raise RoomError("match_not_started")
        return room.runner

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                return b"".join(chunks)

    @staticmethod
    def _parse_message(raw: str) -> dict[str, object]:
        value = strict_json_loads(raw)
        if type(value) is not dict:
            raise ProtocolError("message must be an object")
        if set(value) != {"message_type", "payload"}:
            raise ProtocolError("message fields are invalid")
        if not isinstance(value.get("message_type"), str):
            raise ProtocolError("message_type is required")
        payload = value.get("payload", {})
        if type(payload) is not dict:
            raise ProtocolError("payload must be an object")
        return value

    @staticmethod
    def _payload(request: dict[str, object]) -> dict[str, object]:
        payload = request.get("payload", {})
        if type(payload) is not dict:
            raise ProtocolError("payload must be an object")
        return payload

    @staticmethod
    def _string(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProtocolError(f"{key} is required")
        return value

    @staticmethod
    def _integer(payload: dict[str, object], key: str) -> int:
        value = payload.get(key)
        if type(value) is not int:
            raise ProtocolError(f"{key} must be an integer")
        return value

    @staticmethod
    def _require_fields(
        payload: dict[str, object],
        *,
        required: set[str],
    ) -> None:
        if set(payload) != required:
            raise ProtocolError("payload fields are invalid")

    @staticmethod
    def _ai_seats(value: object) -> frozenset[int]:
        if type(value) is not list or any(type(seat) is not int for seat in value):
            raise ProtocolError("ai_seats must be an integer array")
        return frozenset(value)

    @staticmethod
    async def _send_message(send: Send, message_type: str, payload: dict[str, object]) -> None:
        data = {"message_type": message_type, "payload": payload}
        await send(
            {
                "type": "websocket.send",
                "text": canonical_json_bytes(data).decode("utf-8"),
            }
        )

    async def _send_error(self, send: Send, code: str) -> None:
        await self._send_message(send, "protocol_error", {"code": code})

    @staticmethod
    async def _json_response(send: Send, status: int, payload: dict[str, object]) -> None:
        body = canonical_json_bytes(payload)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json; charset=utf-8"],
                    [b"content-length", str(len(body)).encode("ascii")],
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def create_app() -> TuppiASGIApp:
    """Create the process-local ASGI application."""

    return TuppiASGIApp(RoomManager.from_environment())


app = create_app()


def _port_value(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return value


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local Tuppi private-alpha server."
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("TUPPI_SERVER_HOST", "127.0.0.1"),
        help="bind address (default: TUPPI_SERVER_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        default=os.environ.get("TUPPI_SERVER_PORT", "8765"),
        type=_port_value,
        help="TCP port (default: TUPPI_SERVER_PORT or 8765)",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="listen on all IPv4 interfaces for same-network clients",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the local server installation without starting it",
    )
    return parser


def _local_ipv4_addresses() -> list[str]:
    try:
        entries = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted(
        {
            entry[4][0]
            for entry in entries
            if entry[4][0] and not entry[4][0].startswith("127.")
        }
    )


def _print_startup_message(host: str, port: int) -> None:
    print("Tuppi private-alpha server is running.")
    print(f"Bind address: {host}:{port}")
    if host in {"0.0.0.0", "::"}:
        addresses = _local_ipv4_addresses()
        if addresses:
            print("Clients on the same network should use:")
            for address in addresses:
                print(f"  http://{address}:{port}")
        else:
            print(
                "Find this Mac's local IPv4 address and enter "
                f"http://<address>:{port} in Tuppi."
            )
    else:
        print(f"Client URL: http://{host}:{port}")
    print("Press Ctrl-C to stop the server.")


def main(argv: Sequence[str] | None = None) -> None:
    args = _argument_parser().parse_args(argv)
    host = "0.0.0.0" if args.lan else args.host
    port = args.port

    if args.check:
        try:
            import uvicorn  # noqa: F401
            import websockets  # noqa: F401
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "Private-alpha server dependency missing. Install it with: "
                "python -m pip install -e '.[server]'"
            ) from exc
        print("Tuppi private-alpha server preflight passed.")
        print(f"Protocol: {PROTOCOL_VERSION}")
        print(f"Configured bind: {host}:{port}")
        return

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - only exercised as CLI setup
        raise SystemExit(
            "Install the optional server dependency first: "
            "python -m pip install 'tuppi-research[server]'"
        ) from exc
    _print_startup_message(host, port)
    # Access logs include room codes in URL paths. Keep private-alpha logging to
    # server lifecycle messages; request bodies and game state are never logged.
    uvicorn.run(app, host=host, port=port, reload=False, access_log=False)
