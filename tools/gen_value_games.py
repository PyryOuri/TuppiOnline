"""VN2 training rows: the best agent's pair against the incumbent's pair (docs/VALUE_NET_PLAN.md).

Each game is played in the authoritative engine (project_target_v3, as
`tuppi_ai.evaluate` plays it) and mirrored action by action in the native
core. Every ordinary trick-play position at a trick boundary with more than
six tricks left, and the end of bidding before a sooli offer, becomes a row: its full-information features
(`native.encode_pi`, bot-side bit set when the side to move is the bot pair)
and the deal's realised match-equity change for the side to move.

    python tools/gen_value_games.py --games 20000 --worlds 64 --out runs/value/vn2_train --seed vn2-train
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_W: dict = {}


def _init(worlds: int) -> None:
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import native

    native.set_rollout_chunk(128)  # several processes run: least total work, same moves
    from tuppi_ai.best import EQUITY, best_agents
    from tuppi_ai.equity import Equity
    from tuppi_ai.evaluate import _with_sooli
    from tuppi_ai.incumbent import incumbent_agents

    _W["bot"] = best_agents(worlds=worlds)
    _W["inc"] = _with_sooli(incumbent_agents("partner_aware_lead_v2"), "v3")
    _W["equity"] = Equity.load(EQUITY)


def play_chunk(job: tuple[int, int, str, str]) -> dict:
    start, count, seed, out = job
    target_path = Path(out) / f"rows_{start:07d}.npz"
    if target_path.exists():
        return {"start": start, "rows": 0, "skipped": True}
    from tuppi_ai import native
    from tuppi_ai.bridge import action_id, mask_of
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    feats, targets, games = [], [], []
    t0 = time.time()
    with trusted_transitions():
        for index in range(start, start + count):
            rng = random.Random(f"{seed}|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer = index % 4
            score = (0, 0) if rng.random() < 0.5 else (
                (4 * rng.randrange(1, 13), 0) if rng.random() < 0.5 else (0, 4 * rng.randrange(1, 13)))
            bot_team = rng.randrange(2)
            for seat, agent in _W["bot"].items():  # a fresh agent's sooli options each game
                agent.searcher.env.set_sooli(0, False, False, 0.0)
            match = create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref=f"vn2-{index}",
                                 ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            deal = native.new_deal([mask_of(h) for h in hands], dealer, score[0], score[1], ruleset=3)
            rows, teams = [], []
            while state.phase in ACTIVE_PHASES:
                boundary = deal.phase == native.PH_PLAY and deal.n_played % 4 == 0 and 13 - deal.n_played // 4 > 6
                pre_offer = deal.phase == native.PH_SOOLI_OFFER and deal.n_decisions == 0
                if boundary or pre_offer:
                    rows.append(native.encode_pi(deal, bot_side=(deal.cur & 1) == bot_team))
                    teams.append(deal.cur & 1)
                seat = state.current_actor
                if seat != deal.cur:
                    raise RuntimeError(f"native mirror out of step at game {index}")
                agent = _W["bot"][seat] if seat % 2 == bot_team else _W["inc"][seat]
                action = agent.choose_action(match_observation_for(state, seat))
                if native.lib.tc_apply(C.byref(deal), action_id(action)) != 0:
                    raise RuntimeError(f"native mirror rejected an engine action at game {index}")
                state = apply_match_action(state, action)
            r = state.completed_deals[-1].public_result
            d0 = _W["equity"].delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), dealer)
            for f, team in zip(rows, teams):
                feats.append(f)
                targets.append(d0 if team == 0 else -d0)
            games.append({"index": index, "rows": len(rows), "bot_team": bot_team, "delta0": d0})
    feat = np.packbits(np.array(feats, dtype=np.uint8).reshape(-1, native.PI_DIM), axis=1)
    tmp = target_path.with_suffix(".tmp.npz")
    np.savez(tmp, feat=feat, target=np.array(targets, dtype=np.float32))
    tmp.rename(target_path)
    return {"start": start, "rows": len(targets), "games": len(games), "seconds": round(time.time() - t0, 1)}


def load_rows(root: Path) -> tuple[np.ndarray, np.ndarray]:
    parts = [np.load(p) for p in sorted(Path(root).glob("rows_*.npz"))]
    return np.concatenate([p["feat"] for p in parts]), np.concatenate([p["target"] for p in parts])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, required=True)
    p.add_argument("--worlds", type=int, default=64)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--chunk", type=int, default=100)
    p.add_argument("--merge", type=Path, help="also write all rows into this .npz")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = [(s, min(args.chunk, args.games - s), args.seed, str(args.out)) for s in range(0, args.games, args.chunk)]
    t0 = time.time()
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.worlds,)) as pool:
        for r in pool.map(play_chunk, jobs):
            print(json.dumps(r), flush=True)
    if args.merge:
        feat, target = load_rows(args.out)
        np.savez(args.merge, feat=feat, target=target)
        print(json.dumps({"rows": len(target), "seconds": round(time.time() - t0, 1)}))


if __name__ == "__main__":
    main()
