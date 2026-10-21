"""Anonymous match records for developing the bots (owner request 2026-10-19, round 15).

A record holds every deal's four hands and every action in order, with who
made it: a person, a bot, or played automatically after a concession.
Online matches are recorded by this server when they finish, or when they
close or expire unfinished. Offline matches are sent by browsers when they
finish, under the same research setting as the results, and are accepted
only if every action replays legally on this engine. A record never holds
names, room codes, tokens or addresses; of the time, only the day.

Records are gzip files in ``research/`` next to the rooms, one per match;
the oldest are removed when they exceed the size cap. The owner downloads
them all as one gzip stream of JSON lines with the secret in
TUPPI_RESEARCH_KEY; without that variable there is no download.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re

from tuppi_engine import EnginePhase, ExplicitDeal, MatchState, apply_match_action, begin_explicit_deal, create_match
from tuppi_engine.serialization import action_from_data, action_to_data
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import card_from_index, card_to_code

from .persistence import PersistenceError
from .projection import project_completed_deals

RECORD_SCHEMA_VERSION = "tuppi.research.match.v1"
RESEARCH_DIRECTORY = "research"
#: Records kept in all (gzip bytes; TUPPI_RESEARCH_MAX_MB); the oldest go
#: first. About 40,000 20-deal matches at the default, beside the 200 MB room
#: archive on the 1 GB disk.
DEFAULT_MAX_RECORD_BYTES = 200 * 2**20
#: An offline report's body at most (a 100-deal match is about 40 KB).
MAX_OFFLINE_BODY_BYTES = 256 * 1024
OFFLINE_BOTS = {128: "w128", 1024: "w1024"}
_ID = re.compile(r"[A-Za-z0-9-]{16,64}")
_VERSION = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_FILE = re.compile(r"((?:online|offline)-[A-Za-z0-9-]{16,64})\.json\.gz")
_TERMINAL = (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)


class RecordRejected(ValueError):
    pass


def _by_online(client_action_id: str) -> str:
    """Who made an online action, from the runner's action id."""
    if client_action_id.startswith("ai:"):
        return "bot"
    if client_action_id.startswith("concede:"):
        return "forced"
    return "human"


def _deal_entry(state: MatchState, deal: ExplicitDeal) -> dict[str, object]:
    return {"actions": [], "complete": False, "dealer": deal.dealer,
            "hands": [[card_to_code(card) for card in hand] for hand in deal.hands],
            "score_before": [state.score.team0, state.score.team1]}


def _summary(state: MatchState, deals: list[dict[str, object]]) -> dict[str, object]:
    finished = state.phase is EnginePhase.MATCH_COMPLETE
    score = [state.score.team0, state.score.team1]
    return {"deals": deals, "final_score": score, "finished": finished,
            "winner_team": (0 if score[0] > score[1] else 1) if finished else None}


def deal_entries(runner) -> list[dict[str, object]]:
    """Every deal of a live match so far, as in its record: dealt hands,
    score before, and every accepted action with who made it.

    Each accepted action is placed in its deal by its first public event:
    a deal's actions come after the previous finished deal's last event.
    """

    actions = sorted(runner._accepted_actions, key=lambda item: item.action_index)
    finished = project_completed_deals(runner.state)
    last_events = [deal["events"][-1]["event_index"] for deal in finished]
    entries: list[dict[str, object]] = []
    number = 0
    for item in actions:
        if item.accepted_event_indices:
            first = item.accepted_event_indices[0]
            number = sum(1 for last in last_events if last < first)
        while len(entries) <= number:
            index = len(entries)
            deal = runner._deals[index]
            score = finished[index]["score_before"] if index < len(finished) else [runner.state.score.team0, runner.state.score.team1]
            entries.append({"actions": [], "complete": index < len(finished), "dealer": deal.dealer,
                            "hands": [[card_to_code(card) for card in hand] for hand in deal.hands],
                            "score_before": list(score)})
        entries[number]["actions"].append([item.seat, _by_online(item.client_action_id), item.action])
    for item in runner.conceded_deals():
        if item["deal_number"] < len(entries):
            entries[item["deal_number"]]["conceded_after_tricks"] = item["after_tricks"]
    return entries


def finished_deal_records(runner) -> list[dict[str, object]]:
    """The finished deals' full records, for everyone in the room (feature
    deal_records): once a deal is over, its hands, all four bids and any sooli
    exchange are no longer private. The deal in play is never included.
    Finished deals come first, so deal n is item n."""

    return [entry for entry in deal_entries(runner) if entry["complete"]]


def online_record(runner, *, bot: str, day: str, bot_version: str | None = None) -> dict[str, object] | None:
    """The record of a live match so far; None if nothing has been played."""

    entries = deal_entries(runner)
    if not entries:
        return None
    score = [runner.state.score.team0, runner.state.score.team1]
    key = f"{runner.match_ref}:{runner._deals[0].deal_id}"
    return {"bot": bot, **({"bot_version": bot_version} if bot_version else {}), "day": day, "deals": entries,
            "final_score": score, "finished": runner.terminal, "id": "online-" + hashlib.sha256(key.encode()).hexdigest()[:32],
            "ruleset_id": runner.ruleset_id.value, "schema_version": RECORD_SCHEMA_VERSION, "source": "online",
            "winner_team": (0 if score[0] > score[1] else 1) if runner.terminal else None}


def _offline_action(action: int, seat: int, phase: EnginePhase) -> dict[str, object]:
    """The browser's action number as engine data (see network.mjs networkActionID)."""
    if 52 <= action < 156 and phase is EnginePhase.SHOWING:
        rami = action >= 104
        return {"declared_contract": "RAMI" if rami else "NOLO", "seat": seat,
                "shown_card": card_to_code(card_from_index(action - 104 if rami else action - 52)), "type": "show"}
    if action in (156, 157):
        return {"play_sooli": action == 157, "seat": seat, "type": "sooli_decision"}
    if 158 <= action < 210:
        return {"card": card_to_code(card_from_index(action - 158)), "seat": seat, "type": "sooli_exchange"}
    if 0 <= action < 52:
        return {"card": card_to_code(card_from_index(action)), "seat": seat, "type": "play"}
    raise RecordRejected("invalid_record")


def offline_record(payload: object, *, day: str) -> dict[str, object]:
    """See ``_offline_record``. Each action's legality is still checked, and
    each deal is validated in full where it starts and ends; only the engine's
    re-checks of its own states within a deal are skipped (about 12x faster)."""

    with trusted_transitions():
        return _offline_record(payload, day=day)


def _offline_record(payload: object, *, day: str) -> dict[str, object]:
    """Check a browser's finished offline match by replaying it and return its
    record. The person sits at seat 0; the bots at 1-3 (seat 2 is the
    person's bot partner). Each saved deal starts from its own score. A save
    records a concession only by the tricks completed before it, so the
    plays from the trick then in progress on are marked forced (online the
    server marks exactly the plays after it)."""

    if type(payload) is not dict or set(payload) != ({"deals", "id", "runtime", "worlds"} |
                                                  ({"bot"} if "bot" in payload else set())):
        raise RecordRejected("invalid_record")
    bot = payload.get("bot")
    if bot is not None and (not isinstance(bot, str) or bot not in {"heidi05", "heidi10"}):
        raise RecordRejected("invalid_record")
    match_id, worlds, runtime, saved = payload["id"], payload["worlds"], payload["runtime"], payload["deals"]
    if (bot == "heidi05" and worlds != 128) or (bot == "heidi10" and worlds != 1024):
        raise RecordRejected("invalid_record")
    if (not isinstance(match_id, str) or not _ID.fullmatch(match_id) or type(worlds) is not int
            or worlds not in OFFLINE_BOTS or not isinstance(runtime, str) or not _VERSION.fullmatch(runtime)
            or type(saved) is not list or not 1 <= len(saved) <= 500):
        raise RecordRejected("invalid_record")
    entries: list[dict[str, object]] = []
    state = None
    for item in saved:
        if (type(item) is not dict or not set(item) <= {"actions", "cards", "conceded", "dealer", "score"}
                or not {"actions", "cards", "dealer", "score"} <= set(item)):
            raise RecordRejected("invalid_record")
        cards, dealer, score, actions = item["cards"], item["dealer"], item["score"], item["actions"]
        conceded = item.get("conceded")
        if (type(cards) is not list or sorted(cards) != list(range(52)) or any(type(c) is not int for c in cards)
                or type(dealer) is not int or dealer not in range(4) or type(score) is not list or len(score) != 2
                or any(type(v) is not int or v < 0 for v in score) or type(actions) is not list or len(actions) > 64
                or any(type(a) is not int for a in actions)
                or (conceded is not None and (type(conceded) is not dict or set(conceded) != {"afterTricks"}
                    or type(conceded["afterTricks"]) is not int or not 0 <= conceded["afterTricks"] <= 12))):
            raise RecordRejected("invalid_record")
        if state is not None and [state.score.team0, state.score.team1] != score:
            raise RecordRejected("invalid_record")  # deals must follow on from each other
        deal = ExplicitDeal(dealer=dealer, hands=tuple(tuple(card_from_index(c) for c in cards[s * 13:s * 13 + 13])
                                                        for s in range(4)))
        state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=dealer,
                                                 match_ref="research", ruleset_id=RulesetId.PROJECT_TARGET_V3), deal)
        entry = _deal_entry(state, deal)
        plays = 0
        for action in actions:
            if state.phase in _TERMINAL:
                raise RecordRejected("invalid_record")
            seat, phase = state.current_actor, state.phase
            data = _offline_action(action, seat, phase)
            try:
                state = apply_match_action(state, action_from_data(data))
            except Exception as exc:
                raise RecordRejected("invalid_record") from exc
            forced = conceded is not None and phase is EnginePhase.TRICK_PLAY and plays >= conceded["afterTricks"] * 4
            plays += phase is EnginePhase.TRICK_PLAY
            entry["actions"].append([seat, "forced" if forced else "human" if seat == 0 else "bot",
                                     action_to_data(action_from_data(data))])
        if state.phase not in _TERMINAL:
            raise RecordRejected("invalid_record")  # only finished deals are saved
        entry["complete"] = True
        if conceded is not None:
            entry["conceded_after_tricks"] = conceded["afterTricks"]
        entries.append(entry)
    if state.phase is not EnginePhase.MATCH_COMPLETE:
        raise RecordRejected("invalid_record")  # only finished matches are sent
    return {"bot": bot or OFFLINE_BOTS[worlds], "bot_version": runtime, "day": day, "id": f"offline-{match_id}",
            "ruleset_id": RulesetId.PROJECT_TARGET_V3.value, "schema_version": RECORD_SCHEMA_VERSION,
            "source": "offline", **_summary(state, entries)}


class MatchRecords:
    """One gzip file per match; the oldest are removed past ``max_bytes``."""

    def __init__(self, root: Path | None, max_bytes: int = DEFAULT_MAX_RECORD_BYTES) -> None:
        self.directory = None if root is None else Path(root) / RESEARCH_DIRECTORY
        self.max_bytes = max_bytes
        self.saved: dict[str, int] = {}  # id -> bytes; memory only without a directory
        self.order: list[str] = []
        if self.directory is not None and self.directory.is_dir():
            files = [p for p in self.directory.iterdir() if p.is_file() and not p.is_symlink() and _FILE.fullmatch(p.name)]
            for path in sorted(files, key=lambda p: (p.stat().st_mtime, p.name)):
                record_id = _FILE.fullmatch(path.name).group(1)
                self.saved[record_id] = path.stat().st_size
                self.order.append(record_id)

    def __contains__(self, record_id: str) -> bool:
        return record_id in self.saved

    def save(self, record: dict[str, object], *, replace: bool = False) -> bool:
        """Write one record; False if this match is already recorded (unless
        ``replace``, e.g. an online match recorded unfinished, then finished)."""

        record_id = record["id"]
        if record_id in self.saved and not replace:
            return False
        data = gzip.compress((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(), 9, mtime=0)
        if self.directory is not None:
            try:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = self.directory / f"{record_id}.json.gz"
                temporary = self.directory / f".{record_id}.tmp"
                with open(temporary, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, target)
            except OSError as exc:
                raise PersistenceError("cannot save the match record") from exc
        if record_id in self.saved:
            self.order.remove(record_id)
        self.saved[record_id] = len(data)
        self.order.append(record_id)
        self._prune()
        return True

    def _prune(self) -> None:
        while self.order and sum(self.saved.values()) > self.max_bytes:
            oldest = self.order.pop(0)
            self.saved.pop(oldest)
            if self.directory is not None:
                try:
                    (self.directory / f"{oldest}.json.gz").unlink()
                except OSError:
                    pass

    def download(self):
        """Every record, oldest first, as one gzip stream of JSON lines."""
        if self.directory is None:
            return
        for record_id in list(self.order):
            try:
                yield (self.directory / f"{record_id}.json.gz").read_bytes()
            except OSError:
                continue

    def summary(self) -> dict[str, int]:
        return {"matches": len(self.saved), "bytes": sum(self.saved.values())}
