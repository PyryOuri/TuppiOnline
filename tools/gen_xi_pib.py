"""Expert-iteration data from the search with play inference (XI-PIB, 2026-10-17).

The teacher is the live search bot with play inference on all four seats
(`best:pib=4:pibt=2:pibe=0.5`, W=128 by default). It plays v3 deals from random
cards, dealers and reachable scores. Every unforced showing and card-play
decision becomes a row: the acting seat's features (encoder 2), legal mask,
the teacher's action (`act`) and the lite bot's action (`bp`, VRPO3 greedy).
Sooli phases are not recorded: the lite bot handles them with fixed rules.

Shards are written as `shard_<index>.npz` in the layout `tuppi_ai.distill`
reads. Each shard has its own seed, and finished shards are skipped, so an
interrupted run resumes where it stopped.

    python tools/gen_xi_pib.py --out runs/xi_pib/data --hours 20 --workers 7
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TEACHER = "best:w={w}:pib=4:pibt=2:pibe=0.5"
_W: dict = {}


def _init(worlds: int) -> None:
    import torch
    torch.set_num_threads(1)
    from tuppi_ai import evaluate, native
    from tuppi_ai.best import ANCHOR
    from tuppi_ai import model as qmodel
    native.set_rollout_chunk(128)
    _W["agents"] = evaluate._with_sooli(evaluate._make_candidate(TEACHER.format(w=worlds)), "v3")
    _W["lite"] = native.Mlp(qmodel.load(ANCHOR, "cpu"))


def shard(index: int, games: int, out: str) -> dict:
    from tuppi_engine import begin_explicit_deal, create_match, apply_match_action, match_observation_for
    from tuppi_engine import ExplicitDeal
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK
    from tuppi_ai import native
    from tuppi_ai.bridge import action_id, obs_from_player_observation

    path = Path(out) / f"shard_{index:05d}.npz"
    if path.exists():
        return {"index": index, "skipped": True}
    t0 = time.time()
    rng = random.Random(f"xi-pib|{index}")
    dim = native.feature_dim(2)
    feat = np.zeros((1, dim), np.uint8)
    F, M, A, B, P = [], [], [], [], []
    agents, lite = _W["agents"], _W["lite"]
    with trusted_transitions():
        for _ in range(games):
            cards = list(FULL_DECK); rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            level = rng.randrange(13)
            score = (0, 0) if level == 0 else ((4 * level, 0) if rng.random() < 0.5 else (0, 4 * level))
            dealer = rng.randrange(4)
            match = create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="xi-pib",
                                 ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                action = agents[seat].choose_action(observation)
                legal = observation.legal_actions
                if len(legal) > 1:
                    obs = obs_from_player_observation(observation)
                    if obs.phase in (native.PH_SHOW, native.PH_PLAY) and obs.soolaaja < 0:
                        ids = [action_id(a) for a in legal]
                        native.encode(obs, feat[0], 2)
                        mask = np.zeros(native.NUM_ACTIONS, np.uint8); mask[ids] = 1
                        q = lite.forward(feat)[0]
                        F.append(np.packbits(feat[0])); M.append(np.packbits(mask))
                        A.append(action_id(action)); B.append(max(ids, key=lambda i: q[i])); P.append(obs.phase)
                state = apply_match_action(state, action)
    n = len(A)
    tmp = path.with_suffix(".tmp.npz")
    np.savez(tmp, feat=np.array(F, np.uint8).reshape(n, -1), mask=np.array(M, np.uint8).reshape(n, -1),
             act=np.array(A, np.int16), bp=np.array(B, np.int16), phase=np.array(P, np.int8),
             val=np.zeros((n, 1), np.float16))
    os.replace(tmp, path)
    return {"index": index, "rows": n, "differs": float(np.mean(np.array(A) != np.array(B))) if n else 0.0,
            "seconds": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--hours", type=float, default=20.0, help="stop starting new shards after this")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--games", type=int, default=32, help="games per shard")
    ap.add_argument("--shards", type=int, default=100000, help="upper bound on shard indices")
    ap.add_argument("--worlds", type=int, default=128)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TUPPI_AI_SERIAL", "1")
    deadline = time.time() + args.hours * 3600
    todo = (i for i in range(args.shards) if not (args.out / f"shard_{i:05d}.npz").exists())
    log = (args.out / "progress.jsonl").open("a")
    # Workers search on one thread each (TUPPI_AI_SERIAL=1 above): spread over all
    # cores in many processes, worker memory grows (docs/PLAY_INFERENCE.md).
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.worlds,)) as pool:
        running = {pool.submit(shard, next(todo), args.games, str(args.out)) for _ in range(args.workers)}
        while running:
            done = next(as_completed(running))
            running.remove(done)
            row = done.result(); row["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            log.write(json.dumps(row) + "\n"); log.flush()
            print(json.dumps(row), flush=True)
            if time.time() < deadline:
                running.add(pool.submit(shard, next(todo), args.games, str(args.out)))


if __name__ == "__main__":
    main()
