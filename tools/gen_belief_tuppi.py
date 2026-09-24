"""Belief-network training data from TuppiAI playing itself under the real game.

The first belief net (`tools/gen_belief.py`) learned from other policies (a
distilled search team and the incumbent clone) and is overconfident against
TuppiAI's bots (`docs/STATUS.md`, "Live odds tool against TuppiAI's bots").
This records the bots the owner actually plays: TuppiAI's best agent on all
four seats, project_target_v3 (locked bids, sooli), the authoritative engine.

At every step of ordinary trick play, **every** seat's observation is recorded
(not only the actor's): encoder-v2 features, and for each card the observer
cannot see, which other seat (relative 1..3 -> 0..2) holds it; 255 for cards
the observer sees (own hand, played). Sooli deals are skipped. Same format as
`tools/gen_belief.py`, so `python -m tuppi_ai.belief --data <out>` trains on it.

Throughput: about 12 CPU-seconds per deal (the searches), close to one deal
per second on this machine with two workers.

    python tools/gen_belief_tuppi.py --deals 1500 --out runs/belief/tuppi_v3
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENCODER = 2


def _score(rng: random.Random) -> tuple[int, int]:
    """0-0 half the time, else a random score the match can start a deal from."""
    if rng.random() < 0.5:
        return (0, 0)
    level = rng.randrange(1, 13)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)


def play(job: tuple[int, int, str, str]) -> dict:
    start, count, seed, out = job
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import native
    from tuppi_ai.best import best_agents
    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
                              create_match, match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK, card_to_index

    agents = best_agents(seed=start)
    dim = native.feature_dim(ENCODER)
    feats, locs = [], []
    sooli = 0
    t0 = time.time()
    with trusted_transitions():
        for index in range(start, start + count):
            rng = random.Random(f"{seed}|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer = index % 4
            match = create_match(initial_score=MatchScore(*_score(rng)), initial_dealer=dealer,
                                 match_ref=f"belief-{index}", ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            rows_f, rows_l = [], []
            while state.phase in ACTIVE_PHASES:
                deal = state.active_deal
                if deal.phase is EnginePhase.TRICK_PLAY and deal.soolaaja is None:
                    holder = np.full(52, -1, dtype=np.int8)
                    for s in range(4):
                        for card in deal.hands[s]:
                            holder[card_to_index(card)] = s
                    for observer in range(4):
                        obs = match_observation_for(state, observer)
                        f = np.zeros(dim, dtype=np.uint8)
                        native.encode(obs_from_player_observation(obs), f, ENCODER)
                        loc = np.full(52, 255, dtype=np.uint8)
                        other = (holder >= 0) & (holder != observer)
                        loc[other] = ((holder[other] - observer) % 4 - 1).astype(np.uint8)
                        rows_f.append(np.packbits(f))
                        rows_l.append(loc)
                seat = state.current_actor
                state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
            if state.completed_deals[-1].public_result.soolaaja is not None:
                sooli += 1
                continue  # the deal's rows describe play before a sooli that never came: drop them
            feats.extend(rows_f)
            locs.extend(rows_l)
    path = Path(out) / f"shard_tuppi_{start:06d}.npz"
    np.savez(path, feat=np.stack(feats), loc=np.stack(locs))
    return {"start": start, "deals": count, "rows": len(feats), "sooli_deals": sooli,
            "seconds": round(time.time() - t0, 1), "path": str(path)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, default=1500)
    p.add_argument("--seed", default="belief-tuppi-v3")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--chunk", type=int, default=50)
    p.add_argument("--first", type=int, default=0, help="first deal index (to extend a run)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    jobs = [(s, min(args.chunk, args.first + args.deals - s), args.seed, str(args.out))
            for s in range(args.first, args.first + args.deals, args.chunk)]
    t0 = time.time()
    rows = deals = 0
    with ProcessPoolExecutor(args.workers) as pool:
        for result in pool.map(play, jobs):
            rows += result["rows"]
            deals += result["deals"]
            print(f"{deals} deals, {rows} rows, {time.time() - t0:.0f}s ({result['sooli_deals']} sooli deals "
                  f"in the last chunk)", flush=True)
    print(f"done: {deals} deals, {rows} rows in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
