"""Complete-match duplicate evaluation: match win probability against the incumbent.

Pair k plays two legs on the same deal stream (deal i of pair k has the same
hands in both legs): leg A with the candidate as team 0, leg B with the
candidate as team 1. Both legs run to natural termination under the rising
score, capped at `cap` deals (a capped leg is recorded as censored and scored
as unknown). Censored comparisons report identification bounds, with no win
point estimate or confidence interval. A completed pair score is the mean
of the two legs' results. Identical deterministic teams that reproduce the
same actions in both legs score 0.5 on every completed pair.

    python -m tuppi_ai.match_eval --checkpoint runs/x/latest.pt --pairs 256
"""

from __future__ import annotations

import argparse
import json
import random
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .evaluate import RULESETS, _init as _init_worker, _W
from .match_statistics import pair_result, summarize_pairs

DEFAULT_CAP = 400


def _leg(pair: int, seed: str, candidate_team: int, cap: int) -> dict:
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_rules import MatchScore
    from tuppi_rules.cards import FULL_DECK

    cand, opp = _W["candidate"], _W["opponent"]
    ruleset = _W.get("ruleset", "v1")
    if ruleset == "v1":
        state = create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="tuppi-ai-match")
        active = (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY)
    else:
        from tuppi_engine.state import ACTIVE_PHASES
        from tuppi_rules import RulesetId
        state = create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="tuppi-ai-match",
                             ruleset_id=RulesetId(RULESETS[ruleset]))
        active = ACTIVE_PHASES
    deals = 0
    while not state.terminal and deals < cap:
        rng = random.Random(f"{seed}|pair|{pair}|deal|{deals}")
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
        state = begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=hands))
        while state.phase in active:
            seat = state.current_actor
            actor = cand[seat] if seat % 2 == candidate_team else opp[seat]
            state = apply_match_action(state, actor.choose_action(match_observation_for(state, seat)))
        deals += 1
    if not state.terminal:
        return {"result": None, "deals": deals, "censored": True}
    won = state.score.for_team(__import__("tuppi_rules").Team(candidate_team)) >= 52
    return {"result": 1.0 if won else 0.0, "deals": deals, "censored": False}


def measure_pair(pair: int, seed: str, cap: int) -> dict:
    from tuppi_engine.trusted import trusted_transitions

    with trusted_transitions():
        a = _leg(pair, seed, 0, cap)
        b = _leg(pair, seed, 1, cap)
    return {"pair": pair, **pair_result(a, b)}


def evaluate_matches(candidate: str, pairs: int, seed: str = "tuppi-ai-match-v1",
                     opponent: str = "partner_aware_lead_v2", workers: int = 12,
                     cap: int = DEFAULT_CAP, equity_path: str | None = None, ruleset: str = "v1") -> dict:
    from .evaluate import ROOT
    if pairs < 1 or workers < 1 or cap < 1:
        raise ValueError("pairs, workers and cap must be positive")
    equity_path = equity_path or str(ROOT / "models" / "equity_incumbent.json")
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init_worker,
                             initargs=(candidate, opponent, equity_path, ruleset)) as pool:
        rows = list(pool.map(measure_pair, range(pairs), [seed] * pairs, [cap] * pairs, chunksize=1))
    return {"candidate": candidate, "opponent": opponent, "pairs": pairs, "seed": seed, "ruleset": RULESETS[ruleset],
            **summarize_pairs(rows),
            "seconds": round(time.time() - t0, 1)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, help="best | policy | profile:<key> | search:<ckpt>:<options>")
    parser.add_argument("--pairs", type=int, default=128)
    parser.add_argument("--seed", default="tuppi-ai-match-v1")
    parser.add_argument("--opponent", default="partner_aware_lead_v2", help="incumbent profile, best, or search spec")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    parser.add_argument("--ruleset", choices=tuple(RULESETS), default="v1",
                        help="v1; v3 = the real game (sooli and locked bids)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = evaluate_matches(args.checkpoint, args.pairs, args.seed, args.opponent,
                               args.workers, args.cap, ruleset=args.ruleset)
    print(json.dumps({k: v for k, v in summary.items() if k != "scores"}, indent=1))
    if args.out:
        args.out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
