#!/usr/bin/env python3
"""Do the training overlay's behavioural assumptions hold for a *human*?

The overlay's assumed layer rests on rules measured against the reference bot,
which is deterministic — matching it 348 times out of 348 means the rule was
reverse engineered, not discovered. The open question is whether a person plays
the same way, and the only person in the system is whoever plays this server.

Nothing new has to be recorded to answer that. The server already persists,
by default, every room's explicit deals (all four hands) and every accepted
action, so each past decision can be replayed and each rule checked against
the hand the player actually held. Reading it back rather than logging
verdicts live has one decisive advantage: when a rule is revised — two have
already been rejected and one corrected — the whole archive can be re-measured
against the new definition, including games played months ago.

The rules themselves come from ``tuppi_server.training_analysis``, so this can
only ever measure the rules that actually ship.

Usage:
    python3 tools/measure_rule_validity.py [--archive PATH] [--export FILE]
                                           [--by-month]
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

import archive_replay


DEFAULT_ARCHIVE = "~/Library/Application Support/Tuppi/server"


def _load(path: pathlib.Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("runner") else None


def _wilson(hits: int, total: int) -> tuple[float, float]:
    """A proportion interval that stays sane at 0 of n, which is the usual case."""

    if total == 0:
        return (0.0, 1.0)
    z = 1.96
    p = hits / total
    d = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return (max(0.0, centre - spread), min(1.0, centre + spread))


def _verdicts(*, deal, action, hand, actor, match_ref, play_rule_firing, show_rule_firing):
    """Every rule that bears on this one action, and whether it held."""

    from tuppi_engine import PlayCardAction, ShowAction
    from tuppi_rules import Color, Contract
    from tuppi_rules.cards import ELIGIBLE_SHOW_RANKS, card_color

    held = set(hand)

    if isinstance(action, ShowAction):
        from tuppi_rules import verbal_declaration_required

        firing = show_rule_firing(
            seat=action.seat,
            shown_card=action.shown_card,
            declared_contract=action.declared_contract,
            verbal_required=verbal_declaration_required(
                hand, action.shown_card, action.declared_contract
            ),
        )
        if firing is None:
            return
        colour = (
            Color.RED
            if action.declared_contract is Contract.RAMI
            else Color.BLACK
        )
        options = [
            card
            for card in hand
            if card.rank in ELIGIBLE_SHOW_RANKS and card_color(card) is colour
        ]
        yield _verdict(firing, held, len(options), actor, match_ref, deal)
        return

    if not isinstance(action, PlayCardAction) or not deal.current_trick:
        return
    led = deal.current_trick[0].card.suit
    same = [card for card in hand if card.suit is led]
    followed = [play for play in deal.current_trick if play.card.suit is led]
    highest = max(play.card.rank.value for play in followed)
    is_final = len(deal.current_trick) == 3
    wins = action.card.suit is led and action.card.rank.value > highest

    firing = play_rule_firing(
        contract=deal.contract,
        led=led,
        highest=highest,
        play=_Played(action.seat, action.card),
        is_final=is_final,
        wins_trick=wins,
    )
    if firing is None:
        return
    if firing.rule == "duck_high":
        options = [c for c in same if c.rank.value < highest]
    elif firing.rule == "follow_low":
        options = [c for c in same if c.rank.value < highest]
    else:  # win_high_last
        options = [c for c in same if c.rank.value > highest]
    yield _verdict(firing, held, len(options), actor, match_ref, deal)


class _Played:
    """Minimal stand-in for a PlayedCard, which the rule helper only reads."""

    __slots__ = ("seat", "card")

    def __init__(self, seat, card):
        self.seat = seat
        self.card = card


def _verdict(firing, held, alternatives, actor, match_ref, deal):
    from tuppi_rules import card_to_code

    wrong = sorted(card_to_code(c) for c in (firing.excluded & held))
    return {
        "rule": firing.rule,
        "actor": actor,
        "contract": None if deal.contract is None else deal.contract.value,
        "seat": firing.seat,
        # Fewer than two options means the play was forced, so the rule was
        # true by construction. Counting those inflates a rate toward 100%
        # while measuring nothing; every summary below excludes them.
        "alternatives": alternatives,
        "non_trivial": alternatives >= 2,
        "excluded": len(firing.excluded),
        "violated": bool(wrong),
        "wrongly_excluded": wrong,
        "match_ref": match_ref,
        "deal_number": deal.deal_number,
    }


def summarise(rows, *, key):
    table = collections.defaultdict(lambda: collections.Counter())
    for row in rows:
        if not row["non_trivial"]:
            table[key(row)]["forced"] += 1
            continue
        cell = table[key(row)]
        cell["fires"] += 1
        cell["excluded"] += row["excluded"]
        if row["violated"]:
            cell["violations"] += 1
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default=DEFAULT_ARCHIVE)
    parser.add_argument("--export", help="write every firing as JSONL")
    parser.add_argument("--by-month", action="store_true",
                        help="break the human rows down by month")
    args = parser.parse_args()

    root = pathlib.Path(args.archive).expanduser()
    if not root.is_dir():
        print(f"No archive at {root}", file=sys.stderr)
        return 1

    from tuppi_server.training_analysis import play_rule_firing, show_rule_firing

    rows: list[dict] = []
    months: dict[str, list[dict]] = collections.defaultdict(list)
    matches = list(archive_replay.replay_archive(root))
    for match in matches:
        month = match.played.strftime("%Y-%m")
        for decision in match.decisions:
            deal = decision.deal
            if deal is None:
                continue
            for verdict in _verdicts(
                deal=deal,
                action=decision.action,
                hand=tuple(deal.hands[decision.seat]),
                actor=decision.actor,
                match_ref=decision.match_ref,
                play_rule_firing=play_rule_firing,
                show_rule_firing=show_rule_firing,
            ):
                rows.append(verdict)
                months[month].append(verdict)

    if args.export:
        with open(args.export, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    print(f"matches read: {len(matches)}   firings: {len(rows)}\n")
    table = summarise(rows, key=lambda r: (r["rule"], r["actor"]))
    print(f"{'rule':16s} {'actor':22s} {'real':>6} {'forced':>7} "
          f"{'wrong':>6} {'rate':>7}  {'95% interval':>16} {'cards/fire':>11}")
    for (rule, actor), cell in sorted(table.items()):
        fires = cell["fires"]
        if not fires:
            print(f"{rule:16s} {actor:22s} {0:>6} {cell['forced']:>7}"
                  f"{'':>6}{'':>8}  {'(no real choices)':>16}")
            continue
        bad = cell["violations"]
        low, high = _wilson(bad, fires)
        print(f"{rule:16s} {actor:22s} {fires:>6} {cell['forced']:>7} {bad:>6} "
              f"{100*bad/fires:>6.1f}% [{100*low:>5.1f}%,{100*high:>5.1f}%] "
              f"{cell['excluded']/fires:>10.1f}")

    print("\nThe bot rows are a control: they should stay at 0.0%. Anything else "
          "means this reader is wrong, or the bot's policy changed.")

    if args.by_month:
        print("\nHuman play by month (non-trivial firings only):")
        for month in sorted(months):
            human = [r for r in months[month] if r["actor"] == "human" and r["non_trivial"]]
            if not human:
                continue
            bad = sum(1 for r in human if r["violated"])
            print(f"  {month}  fires {len(human):>4}  followed the rule "
                  f"{100*(1-bad/len(human)):>5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
