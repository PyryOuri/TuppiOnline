"""How often is RAMI bid and played? Per-hand bid rates by position and per-deal RAMI rates (v3 locked bids).

Under project_target_v3 all four bid blind; the bids are revealed from the
forehand and the first RAMI declares, so a deal is RAMI unless all four bid
NOLO. A seat's bid matters only when every earlier bid was NOLO, and that is
all it can know. So for each random deal every seat k (k = 0 forehand .. 3) is
asked for its bid in exactly the engine state in which the earlier k seats have
locked NOLO bids: its bid and the deal's contract follow without playing on.

    python tools/rami_rates.py --agent heur:v3 --deals 20000 --scores zero
    python tools/rami_rates.py --agent live --deals 300 --scores uniform --workers 3
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

_W: dict = {}


def _init(agent: str) -> None:
    import torch

    torch.set_num_threads(1)
    if agent == "live":
        from tuppi_ai.best import best_agents
        _W["agents"] = best_agents(worlds=1024)
    elif agent.startswith("search128"):
        from tuppi_ai.best import best_agents
        _W["agents"] = best_agents(worlds=128)
    else:
        from tuppi_ai.incumbent import incumbent_agents
        key = {"heur:v3": "partner_aware_lead_v3", "heur:v2": "partner_aware_lead_v2"}[agent]
        _W["agents"] = incumbent_agents(key)


def _score(rng: random.Random, mode: str) -> tuple[int, int]:
    if mode == "zero":
        return (0, 0)
    level = rng.randrange(13)
    if level == 0:
        return (0, 0)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)


def run(job) -> list[dict]:
    indices, mode, seed = job
    from tuppi_engine import (EnginePhase, ExplicitDeal, ShowAction, apply_match_action, begin_explicit_deal,
                              create_match, match_observation_for)
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import Contract, MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    out = []
    with trusted_transitions():
        for index in indices:
            rng = random.Random(f"{seed}|rami|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = rng.randrange(4), _score(rng, mode)
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="rami-rates",
                             ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=dealer, hands=hands))
            bids = []
            for k in range(4):
                if state.phase is not EnginePhase.SHOWING:
                    raise RuntimeError("showing ended before every seat was asked")
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                agent = _W["agents"][seat]
                if hasattr(agent, "reseed_for"):
                    agent.reseed_for(obs)
                action = agent.choose_action(obs)
                rami = isinstance(action, ShowAction) and action.declared_contract is Contract.RAMI
                own, opp = (score[seat % 2], score[1 - seat % 2])
                bids.append({"k": k, "seat": seat, "rami": rami, "own": own, "opp": opp})
                if k < 3:  # the next seat is asked only after a NOLO; any NOLO card (bids are unseen)
                    nolo = [a for a in obs.legal_actions
                            if isinstance(a, ShowAction) and a.declared_contract is Contract.NOLO]
                    if not nolo:
                        break  # this hand cannot bid NOLO (rare fallbacks): later seats are never asked
                    state = apply_match_action(state, nolo[0])
            out.append({"deal": index, "dealer": dealer, "score": score, "bids": bids,
                        "rami_deal": any(b["rami"] for b in bids)})
    return out


def report(rows: list[dict], label: str) -> dict:
    import math

    n = len(rows)
    deal = sum(r["rami_deal"] for r in rows) / n
    per_k = {}
    for k in range(4):
        b = [x["rami"] for r in rows for x in r["bids"] if x["k"] == k]
        if b:
            p = sum(b) / len(b)
            per_k[k] = (p, 1.96 * math.sqrt(p * (1 - p) / len(b)), len(b))
    allb = [x["rami"] for r in rows for x in r["bids"]]
    p_all = sum(allb) / len(allb)
    print(f"\n{label}: {n} deals")
    print(f"  RAMI is played in {deal:.1%} of deals (± {1.96 * math.sqrt(deal * (1 - deal) / n):.1%})")
    print(f"  a single hand bids RAMI {p_all:.1%} of the time (all positions)")
    names = ["forehand (1st)", "2nd", "3rd", "dealer (4th)"]
    for k, (p, ci, m) in per_k.items():
        print(f"    {names[k]:15s} {p:.1%} ± {ci:.1%}  (n={m})")
    return {"deals": n, "rami_deal": deal, "rami_hand": p_all, "by_position": {names[k]: v[0] for k, v in per_k.items()}}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True, help="heur:v3, heur:v2, search128 or live (W=1024)")
    p.add_argument("--deals", type=int, default=2000)
    p.add_argument("--scores", choices=("zero", "uniform"), default="zero")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--chunk", type=int, default=25)
    p.add_argument("--seed", default="rami-rates-v1")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    jobs = [(list(range(i, min(i + a.chunk, a.deals))), a.scores, a.seed) for i in range(0, a.deals, a.chunk)]
    t0, rows = time.time(), []
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.agent,)) as pool:
        for part in pool.map(run, jobs):
            rows.extend(part)
    res = report(rows, f"{a.agent}, {a.scores} scores ({time.time() - t0:.0f} s)")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"summary": res, "rows": rows, "args": vars(a)}, default=str))


if __name__ == "__main__":
    main()
