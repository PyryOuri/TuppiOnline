"""Same hand, both bids: how often does the forehand's team win the deal with RAMI vs with NOLO?

For random deals the forehand's bid is branched: RAMI (its preferred RAMI card)
and NOLO (its preferred NOLO card); everything after is played by the same
agents (v3 rules, TuppiProject's sooli fallback). By the forehand's hand
strength (v2/v3's RAMI score), the table gives the forehand team's deal-win
rate, points and match-equity change under each bid.

    python tools/rami_vs_nolo.py --agent heur:v3 --deals 20000
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import statistics as st
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from rami_rates import _init as _init_agents, _score, _W  # noqa: E402


def _init(agent: str) -> None:
    _init_agents(agent)
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    _W["equity"] = Equity.load(EQUITY)


def run(job) -> list[dict]:
    indices, mode, seed = job
    from tuppi_agents.sooli import SooliFallbackAgent
    from tuppi_engine import (ExplicitDeal, ShowAction, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import Contract, MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    from tuppi_ai.bridge import mask_of
    from tuppi_ai.heuristic_rules import hand_scores

    agents = {s: a if getattr(a, "handles_sooli", False) else SooliFallbackAgent(a) for s, a in _W["agents"].items()}

    def finish(state, team, dealer):
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
        r = state.completed_deals[-1].public_result
        d0 = _W["equity"].delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), dealer)
        won = r.deal_score.winner_team.value == team
        return {"won": won, "points": r.deal_score.points if won else -r.deal_score.points,
                "equity": d0 if team == 0 else -d0, "stolen": bool(getattr(r.deal_score, "stolen_rami", False))}

    out = []
    with trusted_transitions():
        for index in indices:
            rng = random.Random(f"{seed}|rvn|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = rng.randrange(4), _score(rng, mode)
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="rami-vs-nolo",
                             ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=dealer, hands=hands))
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            legal = obs.legal_actions
            by = {c: [a for a in legal if isinstance(a, ShowAction) and a.declared_contract is c]
                  for c in (Contract.RAMI, Contract.NOLO)}
            if not by[Contract.RAMI] or not by[Contract.NOLO]:
                continue
            chosen = agents[seat].choose_action(obs)
            pick = {}
            for c in (Contract.RAMI, Contract.NOLO):  # the agent's own card when it chose c, else its first card
                pick[c] = chosen if chosen in by[c] else by[c][0]
            team = seat % 2
            row = {"rami_score": hand_scores(mask_of(hands[seat]))[0],
                   "chosen": "RAMI" if chosen.declared_contract is Contract.RAMI else "NOLO",
                   "own": score[team], "opp": score[1 - team]}
            for c, name in ((Contract.RAMI, "rami"), (Contract.NOLO, "nolo")):
                row[name] = finish(apply_match_action(state, pick[c]), team, dealer)
            out.append(row)
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default="heur:v3")
    p.add_argument("--deals", type=int, default=20000)
    p.add_argument("--scores", choices=("zero", "uniform"), default="uniform")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--chunk", type=int, default=100)
    p.add_argument("--seed", default="rami-vs-nolo-v1")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    jobs = [(list(range(i, min(i + a.chunk, a.deals))), a.scores, a.seed) for i in range(0, a.deals, a.chunk)]
    rows = []
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.agent,)) as pool:
        for part in pool.map(run, jobs):
            rows.extend(part)
    g = collections.defaultdict(list)
    for r in rows:
        b = min(int(r["rami_score"] // 3) * 3, 24)
        g[b].append(r)
    print(f"{a.agent}, {a.scores} scores, {len(rows)} forehand hands. Same hand, both bids:")
    print(f"{'RAMI score':>10s} {'share':>6s} {'bids RAMI':>9s} | {'win RAMI':>8s} {'win NOLO':>8s} | {'pts RAMI':>8s} {'pts NOLO':>8s} | "
          f"{'stolen':>6s} | {'equity RAMI - NOLO':>18s}")
    for b in sorted(g):
        v = g[b]
        d = [x["rami"]["equity"] - x["nolo"]["equity"] for x in v]
        m, se = st.fmean(d), (st.stdev(d) / len(d) ** 0.5 if len(d) > 1 else 0)
        print(f"{b:4d}-{b + 3:<5d} {len(v) / len(rows):6.1%} {sum(x['chosen'] == 'RAMI' for x in v) / len(v):9.0%} | "
              f"{st.fmean(x['rami']['won'] for x in v):8.0%} {st.fmean(x['nolo']['won'] for x in v):8.0%} | "
              f"{st.fmean(x['rami']['points'] for x in v):+8.1f} {st.fmean(x['nolo']['points'] for x in v):+8.1f} | "
              f"{st.fmean(x['rami']['stolen'] for x in v):6.0%} | {m:+.4f} ± {1.96 * se:.4f}")
    if a.out:
        a.out.write_text(json.dumps({"rows": rows, "args": vars(a)}, default=str))


if __name__ == "__main__":
    main()
