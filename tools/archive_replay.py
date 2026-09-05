#!/usr/bin/env python3
"""Replay the server's persisted rooms into decisions and completed deals.

The private-alpha server keeps, by default under
``~/Library/Application Support/Tuppi/server``, every room's explicit deals —
all four hands — and every accepted action in order. That is enough to
reconstruct each past decision exactly as the player faced it, which is what
every mining tool in this directory needs.

Replaying rather than logging matters: a verdict written at play time is
frozen against the rule or metric that existed then, while a replay can be
re-run against a revised one over the whole archive, including games played
months ago.

This module is a library. See ``mine_decisions.py``, ``mine_holdings.py`` and
``measure_rule_validity.py`` for the tools built on it.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime
import json
import pathlib
from typing import Iterator


DEFAULT_ARCHIVE = "~/Library/Application Support/Tuppi/server"


@dataclass(frozen=True, slots=True)
class Decision:
    """One accepted action, and the position exactly as its actor saw it."""

    match_ref: str
    deal_number: int
    seat: int
    actor: str          # "human", or the AI profile key
    is_human: bool
    state: object       # MatchState immediately before the action
    observation: object
    action: object

    @property
    def deal(self):
        return self.state.active_deal


@dataclass(frozen=True, slots=True)
class ReplayedMatch:
    match_ref: str
    room_code: str
    played: datetime.date
    humans: frozenset
    profile: str
    decisions: tuple
    completed_deals: tuple   # ResearchDealResult per finished deal


def archive_root(value: str | None = None) -> pathlib.Path:
    return pathlib.Path(value or DEFAULT_ARCHIVE).expanduser()


def room_records(root: pathlib.Path) -> Iterator[tuple[pathlib.Path, dict]]:
    """Every persisted room record, skipping the stored analysis payloads."""

    for path in sorted(root.glob("*.json")):
        if path.name.startswith(("deal-analysis", "post-match")):
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and value.get("runner"):
            yield path, value


def replay(path: pathlib.Path, record: dict) -> ReplayedMatch | None:
    """Rebuild one room's decisions and finished deals, or ``None`` if it cannot.

    A room can legitimately fail to replay — it may have been abandoned
    mid-action, or written by an older schema — so a failure is skipped rather
    than raised.
    """

    from tuppi_engine import (
        EnginePhase,
        ExplicitDeal,
        action_from_data,
        apply_match_action,
        begin_explicit_deal,
        create_match,
        explicit_deal_from_data,
        match_observation_for,
    )
    from tuppi_rules import MatchScore

    runner = record["runner"]
    humans = frozenset(
        item["seat"] for item in (record.get("sessions") or []) if "seat" in item
    )
    profile = runner.get("ai_profile_key") or "ai"
    score = runner.get("initial_score") or [0, 0]
    decisions: list[Decision] = []
    try:
        state = create_match(
            initial_score=MatchScore(score[0], score[1]),
            initial_dealer=runner.get("initial_dealer", 0),
            match_ref=runner["match_ref"],
        )
        deals = [explicit_deal_from_data(item) for item in runner.get("deals") or []]
        if not deals:
            return None
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=deals[0].dealer, hands=deals[0].hands)
        )
        used = 1
        for raw in runner.get("accepted_actions") or []:
            if state.phase is EnginePhase.DEAL_COMPLETE:
                if used >= len(deals):
                    break
                state = begin_explicit_deal(
                    state,
                    ExplicitDeal(dealer=deals[used].dealer, hands=deals[used].hands),
                )
                used += 1
            action = action_from_data(raw["action"])
            deal = state.active_deal
            if deal is None or state.current_actor != action.seat:
                break
            decisions.append(
                Decision(
                    match_ref=runner["match_ref"],
                    deal_number=deal.deal_number,
                    seat=action.seat,
                    actor="human" if action.seat in humans else profile,
                    is_human=action.seat in humans,
                    state=state,
                    observation=match_observation_for(state, action.seat),
                    action=action,
                )
            )
            state = apply_match_action(state, action)
    except Exception:
        # A room can stop replaying part-way — an abandoned action, an older
        # schema. Everything reconstructed before that point is still exact,
        # so it is kept rather than thrown away.
        if not decisions:
            return None
        state = None

    return ReplayedMatch(
        match_ref=runner["match_ref"],
        room_code=record.get("room_code", path.stem),
        played=datetime.date.fromtimestamp(path.stat().st_mtime),
        humans=humans,
        profile=profile,
        decisions=tuple(decisions),
        completed_deals=tuple(state.completed_deals) if state is not None else (),
    )


def replay_archive(root: pathlib.Path) -> Iterator[ReplayedMatch]:
    for path, record in room_records(root):
        match = replay(path, record)
        if match is not None:
            yield match


def seat_role(deal, seat: int) -> str:
    """Where a seat sat in the current trick: leader, second, third or fourth."""

    return ("leader", "second", "third", "fourth")[len(deal.current_trick)]


if __name__ == "__main__":  # a quick census, so the module is runnable
    import sys

    root = archive_root(sys.argv[1] if len(sys.argv) > 1 else None)
    matches = list(replay_archive(root))
    decisions = sum(len(m.decisions) for m in matches)
    human = sum(1 for m in matches for d in m.decisions if d.is_human)
    deals = sum(len(m.completed_deals) for m in matches)
    print(f"archive   : {root}")
    print(f"matches   : {len(matches)}")
    print(f"deals     : {deals}")
    print(f"decisions : {decisions}  (human {human})")
    if matches:
        span = sorted(m.played for m in matches)
        print(f"spanning  : {span[0]} to {span[-1]}")
