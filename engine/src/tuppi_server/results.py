"""Anonymous match results, for research on the bot against people.

One JSON line per finished match in ``results.jsonl`` next to the rooms:
offline matches reported by browsers (one person and a bot partner against
two bots) and online matches from this server. A line holds only the day,
the source, the bot level, how many people sat on each team, the winning
team, the final score and the numbers of deals and conceded deals; never
names, room codes, tokens, cards, hands or addresses. A match is counted
once (its id), and the file stops growing at MAX_RESULT_BYTES.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time

from .persistence import PersistenceError

RESULTS_FILE = "results.jsonl"
RESULT_SCHEMA_VERSION = "tuppi.server.result.v1"
#: About 100,000 matches.
MAX_RESULT_BYTES = 16 * 2**20
OFFLINE_BOTS = {128: "w128", 1024: "w1024"}
_ID = re.compile(r"[A-Za-z0-9-]{16,64}")


class ResultRejected(ValueError):
    pass


def offline_row(payload: object, *, day: str) -> dict[str, object]:
    """Validate a browser's report of a finished offline match.

    ``winner_team`` and ``final_score`` are from the person's team's view
    (team 0). In the rising score the winner has 52 or more and the loser 0.
    """

    if type(payload) is not dict or set(payload) != ({"conceded", "deals", "final_score", "id", "winner_team", "worlds"} |
                                                  ({"bot"} if "bot" in payload else set())):
        raise ResultRejected("invalid_result")
    match_id, worlds, winner = payload["id"], payload["worlds"], payload["winner_team"]
    bot = payload.get("bot")
    if bot is not None and (not isinstance(bot, str) or bot not in {"heidi05", "heidi10"}):
        raise ResultRejected("invalid_result")
    if (bot == "heidi05" and worlds != 128) or (bot == "heidi10" and worlds != 1024):
        raise ResultRejected("invalid_result")
    score, deals, conceded = payload["final_score"], payload["deals"], payload["conceded"]
    if (not isinstance(match_id, str) or not _ID.fullmatch(match_id) or worlds not in OFFLINE_BOTS
            or type(worlds) is not int or winner not in (0, 1) or type(winner) is not int
            or type(score) is not list or len(score) != 2 or any(type(v) is not int for v in score)
            or not 52 <= score[winner] <= 200 or score[1 - winner] != 0
            or type(deals) is not int or not 1 <= deals <= 1000
            or type(conceded) is not int or not 0 <= conceded < deals):
        raise ResultRejected("invalid_result")
    return {"bot": bot or OFFLINE_BOTS[worlds], "conceded": conceded, "day": day, "deals": deals,
            "final_score": score, "id": f"offline-{match_id}", "source": "offline",
            "team_humans": [1, 0], "winner_team": winner}


class Results:
    def __init__(self, root: Path | None) -> None:
        self.path = None if root is None else Path(root) / RESULTS_FILE
        self.seen: set[str] = set()
        self.totals: dict[str, dict[str, dict[str, int]]] = {}
        self.bytes = 0
        if self.path is not None and self.path.is_file() and not self.path.is_symlink():
            with self.path.open("rb") as stream:
                for line in stream:
                    self.bytes += len(line)
                    try:
                        self._count(json.loads(line))
                    except (ValueError, KeyError, TypeError):
                        continue  # a torn last line after a crash

    def _count(self, row: dict[str, object]) -> None:
        self.seen.add(row["id"])
        people = row["team_humans"]
        # The people's side: team 0 offline; online, the team with more people.
        side = 0 if people[0] >= people[1] else 1
        total = self.totals.setdefault(row["source"], {}).setdefault(row["bot"], {
            "conceded_deals": 0, "deals": 0, "matches": 0, "people_wins": 0})
        total["matches"] += 1
        total["deals"] += row["deals"]
        total["conceded_deals"] += row["conceded"]
        total["people_wins"] += int(row["winner_team"] == side and people[side] > people[1 - side])

    def record(self, row: dict[str, object]) -> bool:
        """Append one row; False if this match is already recorded."""

        if row["id"] in self.seen:
            return False
        line = (json.dumps({"schema_version": RESULT_SCHEMA_VERSION, **row}, sort_keys=True,
                           separators=(",", ":")) + "\n").encode()
        if self.bytes + len(line) > MAX_RESULT_BYTES:
            raise ResultRejected("results_full")
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                try:
                    os.write(descriptor, line)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise PersistenceError("cannot save the match result") from exc
        self.bytes += len(line)
        self._count(row)
        return True

    def summary(self) -> dict[str, object]:
        """Totals by source and bot level (people_wins: matches the side with
        more people won; mixed-team online matches count only as played)."""

        return {"schema_version": "tuppi.network.results_summary.v1", "totals": self.totals,
                "file_bytes": self.bytes}


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())
