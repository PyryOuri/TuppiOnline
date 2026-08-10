#!/usr/bin/env python3
"""Dependency-free HTTP preflight for a running Tuppi private-alpha server.

The default check is read-only. ``--room-flow`` additionally creates a small
solo room and marks it ready, which verifies the HTTP bootstrap path but does
leave a private room record in the configured server data directory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class SmokeFailure(RuntimeError):
    """The running server did not satisfy the private-alpha contract."""


def _request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read()
            status = response.status
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SmokeFailure(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SmokeFailure(f"Could not reach {base_url}: {exc.reason}") from exc
    except OSError as exc:
        raise SmokeFailure(f"Could not reach {base_url}: {exc}") from exc
    if status != 200:
        raise SmokeFailure(f"{method} {path} returned HTTP {status}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeFailure(f"{method} {path} returned invalid JSON") from exc
    if type(value) is not dict:
        raise SmokeFailure(f"{method} {path} returned a non-object JSON value")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check a running Tuppi private-alpha server over HTTP."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("TUPPI_SERVER_URL", "http://127.0.0.1:8765"),
        help="server base URL (default: TUPPI_SERVER_URL or localhost)",
    )
    parser.add_argument(
        "--room-flow",
        action="store_true",
        help="also create a solo room and mark it ready; this writes server state",
    )
    parser.add_argument(
        "--display-name",
        default="Tuppi smoke test",
        help="display name used only with --room-flow",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    health = _request(args.url, "GET", "/healthz")
    if health.get("status") != "ok":
        raise SmokeFailure("/healthz did not report status=ok")
    compatibility = _request(args.url, "GET", "/v1/compatibility")
    if compatibility.get("protocol_version") != "tuppi.network.v1":
        raise SmokeFailure("server protocol version is not tuppi.network.v1")

    print(f"HTTP preflight passed: {args.url.rstrip('/')}")
    print(f"Protocol: {compatibility['protocol_version']}")

    if args.room_flow:
        created = _request(
            args.url,
            "POST",
            "/v1/rooms",
            {"display_name": args.display_name, "ai_seats": [1, 2, 3]},
        )
        room_code = created.get("room_code")
        token = created.get("session_token")
        if not isinstance(room_code, str) or not isinstance(token, str):
            raise SmokeFailure("room bootstrap did not return a room code and token")
        ready = _request(
            args.url,
            "POST",
            f"/v1/rooms/{room_code}/ready",
            {"session_token": token},
        )
        if ready.get("playing") is not True:
            raise SmokeFailure("solo room did not enter playing state")
        print(f"HTTP room flow passed: room {room_code}")
        print("Note: this smoke room remains in the server data directory.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"Smoke check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
