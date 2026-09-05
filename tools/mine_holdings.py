#!/usr/bin/env python3
"""Which holdings actually won tricks — yours against the bot's, same shapes.

``tuppi_valuation.attribution`` attributes every trick of a played deal to the
holding that won it, exactly. Pointing it at the archive answers a question no
model is needed for: when you and the bot both held ``Kxx`` in NOLO, whose
``Kxx`` took more tricks?

That comparison is the useful one because it needs no theory. Both sides played
real deals under the same rules, so a difference in tricks-per-holding is a
difference in play, not in assumptions — and in NOLO, winning tricks with a
holding is the failure, not the success.

Rows with very few observations are noise and are hidden by default; raise
``--min`` to be stricter or lower it to see everything.

Usage:
    python3 tools/mine_holdings.py [--archive PATH] [--contract NOLO|RAMI]
                                   [--min N] [--export FILE]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

import archive_replay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive")
    parser.add_argument("--contract", choices=("NOLO", "RAMI"))
    parser.add_argument("--min", type=int, default=4,
                        help="hide shapes seen fewer than this many times per side")
    parser.add_argument("--export", help="write every holding row as JSONL")
    args = parser.parse_args()

    from tuppi_valuation.attribution import attribute_deal

    root = archive_replay.archive_root(args.archive)
    if not root.is_dir():
        print(f"No archive at {root}", file=sys.stderr)
        return 1

    # (contract, skeleton) -> side -> [tricks won by that holding]
    shapes: dict[tuple, dict[str, list[int]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    lengths: dict[tuple, dict[str, list[int]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    rows: list[dict] = []
    deals = 0

    for match in archive_replay.replay_archive(root):
        for research in match.completed_deals:
            try:
                holdings, _hands = attribute_deal(research)
            except Exception:
                continue
            deals += 1
            for holding in holdings:
                if args.contract and holding.contract != args.contract:
                    continue
                side = "you" if holding.seat in match.humans else "bot"
                shapes[(holding.contract, holding.skeleton)][side].append(
                    holding.tricks_won_in_suit
                )
                lengths[(holding.contract, holding.length)][side].append(
                    holding.tricks_won_in_suit
                )
                if args.export:
                    row = holding.to_data()
                    row["side"] = side
                    rows.append(row)

    if args.export:
        with open(args.export, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")

    print(f"deals attributed: {deals}\n")

    def table(title: str, data: dict, label: str) -> None:
        print(title)
        print(f"  {label:>10} {'you n':>6} {'you':>7} {'bot n':>6} {'bot':>7} {'diff':>7}")
        interesting = []
        for key, sides in data.items():
            mine, theirs = sides.get("you", []), sides.get("bot", [])
            if len(mine) < args.min or len(theirs) < args.min:
                continue
            a = sum(mine) / len(mine)
            b = sum(theirs) / len(theirs)
            interesting.append((abs(a - b), key, len(mine), a, len(theirs), b))
        if not interesting:
            print("   (nothing seen often enough on both sides)")
            return
        for _, key, n_mine, a, n_theirs, b in sorted(interesting, reverse=True)[:14]:
            contract, shape = key
            print(f"  {str(shape):>10} {n_mine:>6} {a:>7.2f} {n_theirs:>6} {b:>7.2f} "
                  f"{a - b:>+7.2f}   [{contract}]")

    table("Tricks won by holding shape (in NOLO, lower is better):", shapes, "skeleton")
    print()
    table("Tricks won by suit length:", lengths, "length")
    print("\nA positive diff means your holding of that shape took more tricks "
          "than the bot's did.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
