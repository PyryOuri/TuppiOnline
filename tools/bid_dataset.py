"""Bidding decisions from a game database (`tools/gen_game_db.py`) as a table.

One row per searched bid (real bids and shadow bids): the human-countable
features (`tuppi_ai.bid_features`), the bot's choice, and its own values: the
best RAMI show and the best NOLO show, and their gap (equity for the bidder's
team; positive means the bot prefers RAMI). Rows keep the deal index and the
database's held-out flag, so models are fitted and tested on different deals.

    python tools/bid_dataset.py --db runs/games/v3_pilot --out runs/bidding/pilot/bids.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from gen_game_db import load_games  # noqa: E402
from tuppi_ai.bid_features import bid_features  # noqa: E402


def bid_rows(game: dict):
    dealer = game["dealer"]
    forehand = (dealer + 1) % 4
    score = game["score"]
    bids = [dict(d, shadow=False) for d in game["decisions"] if d["phase"] == "SHOWING"]
    bids += [dict(d, shadow=True) for d in game.get("shadow_bids", [])]
    for bid in bids:
        if not bid["values"]:
            continue  # a forced show (one legal action): not a decision
        seat = bid["seat"]
        values = {int(k): v for k, v in bid["values"].items()}
        rami = [v for k, v in values.items() if 104 <= k < 156]
        nolo = [v for k, v in values.items() if 52 <= k < 104]
        if not rami or not nolo:
            continue
        own, opp = (score[0], score[1]) if seat % 2 == 0 else (score[1], score[0])
        row = bid_features(game["hands"][seat], position=(seat - forehand) % 4, own_score=own, opp_score=opp)
        row.update({
            "deal": game["index"], "seat": seat, "test": bool(game["test"]), "shadow": bid["shadow"],
            "bot_rami": bid["action"]["declared_contract"] == "RAMI",
            "best_rami": max(rami), "best_nolo": max(nolo), "gap": max(rami) - max(nolo),
        })
        yield row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n = shadow = rami = 0
    with gzip.open(args.out, "wt") as fh:
        for game in load_games(args.db):
            for row in bid_rows(game):
                fh.write(json.dumps(row) + "\n")
                n += 1
                shadow += row["shadow"]
                rami += row["bot_rami"]
    print(f"{n} bid decisions ({shadow} shadow), bot RAMI {100 * rami / max(n, 1):.1f}%")


if __name__ == "__main__":
    main()
