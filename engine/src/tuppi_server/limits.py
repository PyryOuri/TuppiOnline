"""Per-client request limits under a global ceiling (hosted.py).

A client is the address the hosting proxy reports in a configured header
(``TUPPI_CLIENT_IP_HEADER``), or the direct peer when no header is configured.
A request without a usable address counts only towards the global ceiling,
which is how every limit worked before per-client limits existed. Addresses
are kept in memory for one window and never logged.
"""

from __future__ import annotations

from collections import deque
import ipaddress
import os
import time

#: Distinct client addresses remembered per limit; beyond this the oldest go.
MAX_TRACKED_CLIENTS = 4096


def client_header_from_environment() -> bytes | None:
    """TUPPI_CLIENT_IP_HEADER: the request header holding the client address
    as set by the hosting proxy (Render is behind Cloudflare, which sets
    ``cf-connecting-ip``). Unset: the direct peer address."""
    value = (os.environ.get("TUPPI_CLIENT_IP_HEADER") or "").strip().lower()
    if not value:
        return None
    if not all(c.isalnum() or c == "-" for c in value) or len(value) > 64 or value == "x-forwarded-for":
        # X-Forwarded-For keeps whatever the client sent, so it can be forged.
        raise ValueError("TUPPI_CLIENT_IP_HEADER must name a single-address proxy header")
    return value.encode()


def client_address(scope, header: bytes | None) -> str | None:
    """The request's client address, or None when it is not known."""
    if header is not None:
        raw = next((value for name, value in scope.get("headers", []) if name == header), b"")
    else:
        peer = scope.get("client")
        raw = str(peer[0]).encode() if peer else b""
    try:
        return str(ipaddress.ip_address(raw.decode("ascii").strip()))
    except (UnicodeDecodeError, ValueError):
        return None


class WindowLimit:
    """At most ``per_client`` events per client and ``total`` events in all
    within a sliding window of ``window`` seconds."""

    def __init__(self, per_client: int, total: int, window: float = 60.0) -> None:
        self.per_client, self.total, self.window = per_client, total, window
        self.events: deque[float] = deque()
        self.clients: dict[str, deque[float]] = {}

    def _expire(self, now: float) -> None:
        while self.events and now - self.events[0] >= self.window:
            self.events.popleft()
        if len(self.clients) > MAX_TRACKED_CLIENTS:
            for client in [c for c, times in self.clients.items() if not times or now - times[-1] >= self.window]:
                del self.clients[client]
            while len(self.clients) > MAX_TRACKED_CLIENTS:
                del self.clients[next(iter(self.clients))]

    def _recent(self, client: str, now: float) -> deque[float]:
        times = self.clients.get(client)
        if times is None:
            return deque()
        while times and now - times[0] >= self.window:
            times.popleft()
        return times

    def allows(self, client: str | None, now: float | None = None) -> bool:
        """Whether one more event fits; records nothing."""
        now = time.monotonic() if now is None else now
        self._expire(now)
        if len(self.events) >= self.total:
            return False
        return client is None or len(self._recent(client, now)) < self.per_client

    def add(self, client: str | None, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.events.append(now)
        if client is not None:
            times = self._recent(client, now)
            times.append(now)
            self.clients.pop(client, None)
            self.clients[client] = times  # most recently active last

    def take(self, client: str | None, now: float | None = None) -> bool:
        """Record one event if it fits; whether it did."""
        now = time.monotonic() if now is None else now
        if not self.allows(client, now):
            return False
        self.add(client, now)
        return True

    def tracked_clients(self, now: float | None = None) -> int:
        """Distinct addresses seen within the window (usage gauge)."""
        now = time.monotonic() if now is None else now
        return sum(1 for times in self.clients.values() if times and now - times[-1] < self.window)
