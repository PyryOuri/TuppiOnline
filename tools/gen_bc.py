"""Record the incumbent's decisions for behaviour cloning, in the authoritative engine.

Every decision of every seat is labelled with the incumbent's own choice. With
probability --deviate the executed action is instead a uniformly random legal
one (the label stays the incumbent's), so the data covers positions the
incumbent's own play would never reach (DAgger-style coverage). Starting
scores and dealers are random, because the network sees the score.

Features are native encoder v2, bit-packed; shards go to runs/bc/<name>/.

    python tools/gen_bc.py --name v1 --deals 100000 --workers 12
"""

from __future__ import annotations

import argparse
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
_A = None


def _shard(args) -> tuple[str, int]:
    index, deals, deviate, out, encoder, seed = args
    global _A
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore
    from tuppi_rules.cards import FULL_DECK

    from tuppi_ai import native
    from tuppi_ai.bridge import action_id, obs_from_player_observation
    from tuppi_ai.incumbent import incumbent_agents

    if _A is None:
        _A = incumbent_agents()
    rng = random.Random(f"{seed}|shard|{index}")
    dim = native.feature_dim(encoder)
    feats, acts, masks = [], [], []
    buf = np.zeros(dim, dtype=np.uint8)
    with trusted_transitions():
        for _ in range(deals):
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer = rng.randrange(4)
            level = rng.randrange(13) if rng.random() < 0.5 else 0
            score = (0, 0) if level == 0 else ((4 * level, 0) if rng.random() < 0.5 else (0, 4 * level))
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="bc-gen"),
                ExplicitDeal(dealer=dealer, hands=hands))
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                label = _A[seat].choose_action(observation)
                legal = observation.legal_actions
                if len(legal) > 1:
                    native.encode(obs_from_player_observation(observation), buf, encoder)
                    feats.append(np.packbits(buf))
                    acts.append(action_id(label))
                    m = np.zeros(native.NUM_ACTIONS, dtype=bool)
                    m[[action_id(a) for a in legal]] = True
                    masks.append(np.packbits(m))
                action = rng.choice(legal) if rng.random() < deviate else label
                state = apply_match_action(state, action)
    path = Path(out) / f"shard_{index:05d}.npz"
    np.savez(path, feat=np.array(feats), act=np.array(acts, dtype=np.int16), mask=np.array(masks))
    return str(path), len(acts)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--deals", type=int, default=100_000)
    p.add_argument("--per-shard", type=int, default=500)
    p.add_argument("--deviate", type=float, default=0.03)
    p.add_argument("--encoder", type=int, default=2)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--seed", default="tuppi-ai-bc-v1")
    args = p.parse_args()
    out = ROOT / "runs" / "bc" / args.name
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(i, args.per_shard, args.deviate, str(out), args.encoder, args.seed)
            for i in range(args.deals // args.per_shard)]
    t0 = time.time()
    total = 0
    with ProcessPoolExecutor(args.workers) as pool:
        for path, n in pool.map(_shard, jobs):
            total += n
    print(f"{len(jobs)} shards, {total} decisions in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
