"""Wins and losses per nickname across this server's finished online matches.

Nicknames are not verified: anyone may play under any name. Each finished
match is counted once (keyed by its match identity and first deal), for
every human seat; bots are not listed. A name on both teams of one match
is ambiguous and is not counted for that match.
"""

from __future__ import annotations

import os
from pathlib import Path
import time

from tuppi_engine import atomic_write_canonical_json, strict_json_load_file
from tuppi_engine.errors import SerializationError

from .persistence import PersistenceError

LEADERBOARD_RECORD_SCHEMA_VERSION = "tuppi.server.leaderboard.v1"
LEADERBOARD_RESPONSE_SCHEMA_VERSION = "tuppi.network.leaderboard.v1"
MAX_PLAYERS = 500
MAX_COUNTED_MATCHES = 2000
TOP_ENTRIES = 20


def name_key(name: str) -> str:
    return " ".join(name.split()).casefold()


class Leaderboard:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.players: dict[str, dict[str, object]] = {}
        self.counted: list[str] = []
        if path is not None and path.exists():
            self._load(path)

    def _load(self, path: Path) -> None:
        if path.is_symlink() or not path.is_file():
            raise PersistenceError("leaderboard entry is not a regular file")
        try:
            value = strict_json_load_file(path)
        except Exception as exc:
            raise PersistenceError("cannot load the leaderboard") from exc
        if (type(value) is not dict or set(value) != {"counted", "players", "schema_version"}
                or value["schema_version"] != LEADERBOARD_RECORD_SCHEMA_VERSION
                or type(value["counted"]) is not list or type(value["players"]) is not dict):
            raise PersistenceError("leaderboard fields are invalid")
        for key, entry in value["players"].items():
            if (type(entry) is not dict or set(entry) != {"last_played", "losses", "name", "wins"}
                    or not isinstance(entry["name"], str) or name_key(entry["name"]) != key
                    or any(type(entry[f]) is not int or entry[f] < 0 for f in ("wins", "losses"))
                    or type(entry["last_played"]) not in (int, float)):
                raise PersistenceError("leaderboard entry is invalid")
        if any(not isinstance(item, str) for item in value["counted"]):
            raise PersistenceError("leaderboard counted matches are invalid")
        self.players, self.counted = value["players"], value["counted"]

    def record(self, *, match_key: str, seats: dict[int, str], winner_team: int,
               finished_at: float | None = None) -> bool:
        """Count one finished match; False if it was already counted or has no human."""

        if match_key in self.counted or not seats:
            return False
        teams: dict[str, set[int]] = {}
        names: dict[str, str] = {}
        for seat, name in seats.items():
            key = name_key(name)
            if key:
                teams.setdefault(key, set()).add(seat % 2)
                names[key] = " ".join(name.split())
        when = time.time() if finished_at is None else finished_at
        for key, sides in teams.items():
            if len(sides) != 1:
                continue  # the same name on both teams cannot be credited
            entry = self.players.setdefault(key, {"last_played": when, "losses": 0, "name": names[key], "wins": 0})
            entry["wins" if sides == {winner_team} else "losses"] += 1
            entry["name"], entry["last_played"] = names[key], when
        self.counted = [*self.counted, match_key][-MAX_COUNTED_MATCHES:]
        if len(self.players) > MAX_PLAYERS:
            keep = sorted(self.players, key=lambda k: self.players[k]["last_played"], reverse=True)[:MAX_PLAYERS]
            self.players = {k: self.players[k] for k in keep}
        self._save()
        return True

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            atomic_write_canonical_json(self.path, {"counted": self.counted, "players": self.players,
                                                    "schema_version": LEADERBOARD_RECORD_SCHEMA_VERSION})
            os.chmod(self.path, 0o600)
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except (OSError, SerializationError) as exc:
            raise PersistenceError("cannot save the leaderboard") from exc

    def standings(self, limit: int = TOP_ENTRIES) -> list[dict[str, object]]:
        def rate(entry):
            played = entry["wins"] + entry["losses"]
            return round(100 * entry["wins"] / played) if played else 0
        ordered = sorted(self.players.values(), key=lambda e: (-e["wins"], -rate(e), -(e["wins"] + e["losses"]),
                                                               name_key(e["name"])))
        return [{"losses": e["losses"], "matches": e["wins"] + e["losses"], "name": e["name"],
                 "win_percent": rate(e), "wins": e["wins"]} for e in ordered[:limit]]
