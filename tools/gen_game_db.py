"""Game database: TuppiAI playing itself under the real game, every decision kept.

Each game is recorded completely enough that everything else can be rebuilt
by replaying it through the authoritative engine: the four hands, the dealer,
the starting score, every action, and, for every searched decision, the
search's value of **every candidate action** (equity change for the deciding
seat's team). Those values are free while the game is played and expensive to
recompute, and they are what bidding explanations, drills and value studies
need. Forced moves and heuristic decisions (the sooli return) have no values.

**Shadow bids.** Under locked bids a seat is asked only while every earlier
seat bid NOLO, so the seats after the first RAMI never bid and later seats'
bids would appear only in some deals. After each game, every seat that did
not bid is asked what it would have bid, from exactly the observation it would
have had (bids are blind: its hand, its position and how many bid before it);
`shadow_bids` holds those decisions. They never affect the game.

Output (`--out`): `meta.json` (the bot version, the library and code
identity, the action-id encoding) and one `games_<start>.jsonl.gz` per chunk.
A chunk whose file exists is skipped, so an interrupted run resumes by running
the same command again. A database is one bot version: `meta.json` must match
the current bot or the run refuses to extend it.

    caffeinate -i python tools/gen_game_db.py --deals 5000 --out runs/games/v3_pilot

About 1 deal per second with 3 workers (10.5 CPU-seconds per deal).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "tuppi_ai.game_db.v1"
ACTION_IDS = {
    "0-51": "play the card with that index (tuppi_rules.cards.card_to_index)",
    "52-103": "show card (id - 52) declaring NOLO",
    "104-155": "show card (id - 104) declaring RAMI",
    "sooli": "see tuppi_ai.native ACT_SOOLI_DECLINE / ACT_SOOLI_ACCEPT / ACT_EXCHANGE + card",
}


def bot_identity() -> dict:
    from tuppi_ai import best, native
    from tuppi_ai.search import SOOLI_DEFAULTS

    lib = Path(native.__file__).resolve().parents[1] / "native" / "libtuppi.dylib"
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "tuppi_ai",
                                     "native"], capture_output=True, text=True).stdout.strip())
    except Exception:
        commit, dirty = "unknown", True
    return {
        "worlds": best.WORLDS, "solver_tail": best.SOLVER_TAIL, "spec": best.SPEC.replace(str(ROOT), "<TuppiAI>"),
        "sooli": SOOLI_DEFAULTS, "libtuppi_sha256": hashlib.sha256(lib.read_bytes()).hexdigest(),
        "tuppiai_commit": commit, "tuppiai_dirty": dirty,
    }


def _score(rng: random.Random) -> tuple[int, int]:
    """0-0 half the time, else a random score the match can start a deal from."""
    if rng.random() < 0.5:
        return (0, 0)
    level = rng.randrange(1, 13)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)


def reseed(agents: dict, index: int) -> None:
    """Each game's randomness depends only on its index, not on its chunk."""
    import ctypes as C

    import numpy as np

    for seat, agent in agents.items():
        for searcher in {id(agent.searcher): agent.searcher,
                         id(agent.show_searcher): agent.show_searcher}.values():
            if searcher is None:
                continue
            seed = (index * 4 + seat) * 2654435761 + 12345
            searcher.rng = C.c_uint64(seed & (2**64 - 1))
            searcher.np_rng = np.random.default_rng(seed)
            # The search environment's sooli options as a fresh agent has them:
            # under project_target_v3 they otherwise carry over from the agent's
            # last sooli decision (docs/BIDDING_EXPLANATION_PLAN.md, prerequisite 1).
            searcher.env.set_sooli(0, False, False, 0.0)


def play_chunk(job: tuple[int, int, str, str, int]) -> dict:
    start, count, seed, out, test_every = job
    target = Path(out) / f"games_{start:07d}.jsonl.gz"
    if target.exists():
        return {"start": start, "deals": 0, "skipped": True}
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import native
    from tuppi_ai.best import best_agents
    from tuppi_engine import (ExplicitDeal, action_to_data, apply_match_action, begin_explicit_deal,
                              create_match, match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import Contract, MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK, card_to_code

    native.set_rollout_chunk(128)  # several processes run: least total work, same moves
    agents = best_agents(seed=0)
    games = []
    t0 = time.time()
    with trusted_transitions():
        for index in range(start, start + count):
            rng = random.Random(f"{seed}|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer = index % 4
            score = _score(rng)
            match = create_match(initial_score=MatchScore(*score), initial_dealer=dealer,
                                 match_ref=f"db-{index}", ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            reseed(agents, index)
            decisions = []
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                agent = agents[seat]
                action = agent.choose_action(observation)
                values = getattr(agent, "last_values", None)
                decisions.append({
                    "seat": seat, "phase": observation.phase.value, "action": action_to_data(action),
                    "values": None if values is None else {str(k): round(v, 6) for k, v in values.items()},
                })
                state = apply_match_action(state, action)
            r = state.completed_deals[-1].public_result
            shadow = []
            bid_seats = {d["seat"] for d in decisions if d["phase"] == "SHOWING"}
            if len(bid_seats) < 4:
                reseed(agents, index + 1_000_000_000)  # independent of the game's own draws
                forehand = (dealer + 1) % 4
                for position in range(4):
                    seat = (forehand + position) % 4
                    if seat in bid_seats:
                        continue
                    st = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
                    for _ in range(position):  # the earlier seats bid NOLO (blind: the card is not seen)
                        earlier = match_observation_for(st, st.current_actor)
                        st = apply_match_action(st, next(a for a in earlier.legal_actions
                                                         if a.declared_contract is Contract.NOLO))
                    if st.current_actor != seat:
                        raise RuntimeError("shadow bid reached the wrong seat")
                    action = agents[seat].choose_action(match_observation_for(st, seat))
                    values = agents[seat].last_values
                    shadow.append({
                        "seat": seat, "position": position, "action": action_to_data(action),
                        "values": None if values is None else {str(k): round(v, 6) for k, v in values.items()},
                    })
            games.append({
                "index": index, "dealer": dealer, "score": list(score), "test": index % test_every == 0,
                "hands": [[card_to_code(c) for c in h] for h in hands], "decisions": decisions,
                "shadow_bids": shadow,
                "result": {"contract": r.contract.value, "declarer": r.declarer, "soolaaja": r.soolaaja,
                           "outcome": r.outcome.value, "points": r.deal_score.points,
                           "winner_team": r.deal_score.winner_team.value, "team_tricks": list(r.team_tricks),
                           "score_after": [r.score_after.team0, r.score_after.team1]},
            })
    tmp = target.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as fh:
        for game in games:
            fh.write(json.dumps(game, separators=(",", ":")) + "\n")
    tmp.rename(target)  # a chunk exists only when complete
    return {"start": start, "deals": count, "skipped": False, "seconds": round(time.time() - t0, 1)}


def load_games(root: Path):
    """Every game in a database, in index order."""
    for path in sorted(root.glob("games_*.jsonl.gz")):
        with gzip.open(path, "rt") as fh:
            for line in fh:
                yield json.loads(line)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", default="game-db-v3")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--chunk", type=int, default=50)
    p.add_argument("--first", type=int, default=0)
    p.add_argument("--test-every", type=int, default=10, help="mark every n-th deal as held out")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    identity = bot_identity()
    meta_path = args.out / "meta.json"
    meta = {"schema": SCHEMA, "ruleset": "project_target_v3", "seed": args.seed, "test_every": args.test_every,
            "chunk": args.chunk, "bot": identity, "action_ids": ACTION_IDS}
    if meta_path.exists():
        old = json.loads(meta_path.read_text())
        old_cmp = {k: v for k, v in old.items() if k != "created"}
        if old_cmp != meta:
            raise SystemExit(f"{meta_path} describes another bot or setup; use a new --out directory")
    else:
        meta["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
        meta_path.write_text(json.dumps(meta, indent=1))
    if identity["tuppiai_dirty"]:
        print("warning: TuppiAI has uncommitted changes in tuppi_ai/ or native/", flush=True)
    jobs = [(s, min(args.chunk, args.first + args.deals - s), args.seed, str(args.out), args.test_every)
            for s in range(args.first, args.first + args.deals, args.chunk)]
    t0 = time.time()
    done = skipped = 0
    with ProcessPoolExecutor(args.workers) as pool:
        for result in pool.map(play_chunk, jobs):
            if result["skipped"]:
                skipped += 1
                continue
            done += result["deals"]
            rate = done / max(time.time() - t0, 1e-9)
            left = sum(j[1] for j in jobs) - done - skipped * args.chunk
            print(f"{done} new deals ({skipped} chunks already there), {rate:.2f} deals/s, "
                  f"about {left / max(rate, 1e-9) / 60:.0f} min left", flush=True)
    print(f"done: {done} new deals in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
