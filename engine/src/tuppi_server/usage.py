"""Anonymous server usage, one log line a minute for the owner.

Counts and timings only: no room codes, names, tokens, cards or addresses.
``in_play`` (unfinished matches someone is using) and ``connections`` say
whether a redeploy would interrupt players.
"""

from __future__ import annotations

from collections import Counter
import re
import resource
import time

#: Seconds between lines while anyone is connected or anything happened.
USAGE_INTERVAL_SECONDS = 60
#: Seconds between lines on an idle server.
QUIET_INTERVAL_SECONDS = 900
_CODE = re.compile(r"[a-z_]{1,40}")


def resident_megabytes() -> int:
    """Current resident memory on Linux; the peak elsewhere."""
    try:
        with open("/proc/self/status") as status:
            for line in status:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak // 2**20 if peak > 2**32 else peak // 1024  # bytes on macOS, KiB on Linux


class Usage:
    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.errors: Counter[str] = Counter()
        self.save_ms_max = 0.0
        self.record_bytes_max = 0
        self.matches_seen: set[tuple[str, str]] = set()
        self.matches_finished: set[tuple[str, str]] = set()
        self.last_line = 0.0

    def error(self, code: str) -> None:
        self.errors[code if _CODE.fullmatch(code) else "other"] += 1

    def saved(self, seconds: float, record_bytes: int) -> None:
        self.counts["saves"] += 1
        self.save_ms_max = max(self.save_ms_max, seconds * 1000)
        self.record_bytes_max = max(self.record_bytes_max, record_bytes)

    def observe_matches(self, rooms) -> None:
        """Count matches started and finished since the last call."""
        for code, room in rooms.items():
            runner = room.runner
            if runner is None:
                continue
            key = (code, getattr(runner, "match_ref", None))
            if key not in self.matches_seen:
                self.matches_seen.add(key)
                self.counts["started"] += 1
            if runner.terminal and key not in self.matches_finished:
                self.matches_finished.add(key)
                self.counts["finished"] += 1
        live = {(code, getattr(room.runner, "match_ref", None)) for code, room in rooms.items() if room.runner is not None}
        self.matches_seen &= live
        self.matches_finished &= live

    def baseline(self, rooms) -> None:
        """Matches already on disk at startup are not new."""
        self.observe_matches(rooms)
        self.counts.clear()

    def line(self, gauges: dict[str, object], now: float | None = None, *, force: bool = False) -> str | None:
        """The next log line, or None while the server is quiet."""
        now = time.time() if now is None else now
        busy = bool(self.counts or self.errors or gauges.get("connections") or gauges.get("in_play"))
        if not force and not busy and now - self.last_line < QUIET_INTERVAL_SECONDS:
            return None
        fields = dict(gauges)
        for name in ("created", "started", "finished", "moves", "opens", "saves", "results"):
            fields[name] = self.counts.get(name, 0)
        if self.counts.get("records"):
            fields["records"] = self.counts["records"]  # offline match records received (research.py)
        if self.counts.get("saves"):
            fields["save_ms_max"] = round(self.save_ms_max)
            fields["record_kb_max"] = round(self.record_bytes_max / 1024)
        if self.errors:
            fields["errors"] = ",".join(f"{code}:{n}" for code, n in sorted(self.errors.items()))
        self.counts.clear(); self.errors.clear()
        self.save_ms_max, self.record_bytes_max, self.last_line = 0.0, 0, now
        return "tuppi usage " + " ".join(f"{key}={value}" for key, value in fields.items())
