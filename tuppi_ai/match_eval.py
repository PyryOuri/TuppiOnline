"""Complete-match duplicate evaluation: match win probability against the incumbent.

Pair k plays two legs on the same deal stream (deal i of pair k has the same
hands in both legs): leg A with the candidate as team 0, leg B with the
candidate as team 1. Both legs run to natural termination under the rising
score, capped at `cap` deals (a capped leg is recorded as censored and scored
as a draw). The pair score is the mean of the two legs' results, so identical
teams score exactly 0.5 on every pair.

    python -m tuppi_ai.match_eval --checkpoint runs/x/latest.pt --pairs 256
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .evaluate import _init as _init_worker, _W

DEFAULT_CAP = 400


def _leg(pair: int, seed: str, candidate_team: int, cap: int) -> dict:
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_rules import MatchScore
    from tuppi_rules.cards import FULL_DECK

    cand, opp = _W["candidate"], _W["opponent"]
    state = create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="tuppi-ai-match")
    deals = 0
    while not state.terminal and deals < cap:
        rng = random.Random(f"{seed}|pair|{pair}|deal|{deals}")
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
        state = begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=hands))
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            actor = cand[seat] if seat % 2 == candidate_team else opp[seat]
            state = apply_match_action(state, actor.choose_action(match_observation_for(state, seat)))
        deals += 1
    if not state.terminal:
        return {"result": 0.5, "deals": deals, "censored": True}
    won = state.score.for_team(__import__("tuppi_rules").Team(candidate_team)) >= 52
    return {"result": 1.0 if won else 0.0, "deals": deals, "censored": False}


def measure_pair(pair: int, seed: str, cap: int) -> dict:
    from tuppi_engine.trusted import trusted_transitions

    with trusted_transitions():
        a = _leg(pair, seed, 0, cap)
        b = _leg(pair, seed, 1, cap)
    return {"pair": pair, "score": (a["result"] + b["result"]) / 2,
            "deals": a["deals"] + b["deals"], "censored": int(a["censored"]) + int(b["censored"])}


def evaluate_matches(candidate: str, pairs: int, seed: str = "tuppi-ai-match-v1",
                     opponent: str = "partner_aware_lead_v2", workers: int = 12,
                     cap: int = DEFAULT_CAP, equity_path: str | None = None) -> dict:
    from .evaluate import ROOT
    equity_path = equity_path or str(ROOT / "models" / "equity_incumbent.json")
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init_worker,
                             initargs=(candidate, opponent, equity_path)) as pool:
        rows = list(pool.map(measure_pair, range(pairs), [seed] * pairs, [cap] * pairs, chunksize=1))
    scores = [r["score"] for r in rows]
    mean = statistics.fmean(scores)
    se = statistics.stdev(scores) / math.sqrt(len(scores)) if len(scores) > 1 else float("nan")
    return {"candidate": candidate, "opponent": opponent, "pairs": pairs, "seed": seed,
            "p_win": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se],
            "pair_wins": sum(s == 1.0 for s in scores), "pair_ties": sum(s == 0.5 for s in scores),
            "pair_losses": sum(s == 0.0 for s in scores),
            "censored_legs": sum(r["censored"] for r in rows),
            "mean_deals_per_leg": statistics.fmean(r["deals"] for r in rows) / 2,
            "seconds": round(time.time() - t0, 1)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, help="checkpoint path or profile:<key>")
    parser.add_argument("--pairs", type=int, default=128)
    parser.add_argument("--seed", default="tuppi-ai-match-v1")
    parser.add_argument("--opponent", default="partner_aware_lead_v2")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = evaluate_matches(args.checkpoint, args.pairs, args.seed, args.opponent,
                               args.workers, args.cap)
    print(json.dumps(summary, indent=1))
    if args.out:
        args.out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
