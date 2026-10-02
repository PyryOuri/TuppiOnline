"""How do RAMI and NOLO deals end when the same agent plays all four seats? (v3 rules)

Plays complete deals and records the contract, the declarer, the team tricks,
the points and stolen RAMIs, so that RAMI make rates can be compared across
defenders: e.g. the live bot declaring against heuristic defenders (from
`tuppi_ai.evaluate` records) against the live bot declaring against itself.

    python tools/rami_outcomes.py --agent search128 --deals 300 --workers 3
    python tools/rami_outcomes.py --agent heur:v3 --deals 20000
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from rami_rates import _init, _score, _W  # noqa: E402  (same agent specs)


def run(job) -> list[dict]:
    indices, mode, seed = job
    from tuppi_agents.sooli import SooliFallbackAgent
    from tuppi_engine import (ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    agents = {s: a if getattr(a, "handles_sooli", False) else SooliFallbackAgent(a) for s, a in _W["agents"].items()}
    out = []
    with trusted_transitions():
        for index in indices:
            rng = random.Random(f"{seed}|outcome|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = rng.randrange(4), _score(rng, mode)
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="rami-outcomes",
                             ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=dealer, hands=hands))
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
            r = state.completed_deals[-1].public_result
            out.append({"deal": index, "score": score, "contract": r.contract.value,
                        "declarer": r.declarer, "team_tricks": list(r.team_tricks),
                        "winner": r.deal_score.winner_team.value, "points": r.deal_score.points,
                        "stolen": bool(getattr(r.deal_score, "stolen_rami", False)),
                        "sooli": getattr(r, "soolaaja", None) is not None})
    return out


def report(rows: list[dict], label: str) -> None:
    rami = [r for r in rows if r["contract"] == "RAMI" and not r["sooli"]]
    nolo = [r for r in rows if r["contract"] == "NOLO" and not r["sooli"]]
    print(f"\n{label}: {len(rows)} deals; RAMI {len(rami) / len(rows):.1%}, NOLO {len(nolo) / len(rows):.1%}, "
          f"sooli {sum(r['sooli'] for r in rows) / len(rows):.1%}")
    if rami:
        made = [r for r in rami if r["winner"] == r["declarer"] % 2]
        dtricks = [r["team_tricks"][r["declarer"] % 2] for r in rami]
        print(f"  RAMI made {len(made) / len(rami):.1%}, stolen {sum(r['stolen'] for r in rami) / len(rami):.1%}; "
              f"declaring team tricks {st.fmean(dtricks):.2f}")
        print(f"  points: made avg {st.fmean(r['points'] for r in made):.1f}, "
              f"stolen avg {st.fmean(r['points'] for r in rami if r['stolen']) if any(r['stolen'] for r in rami) else 0:.1f}")
        hist = {t: sum(1 for x in dtricks if x == t) / len(dtricks) for t in range(4, 14)}
        print("  declaring team tricks: " + "  ".join(f"{t}:{p:.0%}" for t, p in hist.items() if p >= 0.005))
    if nolo:
        print(f"  NOLO points avg {st.fmean(r['points'] for r in nolo):.1f}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True, help="heur:v3, heur:v2, search128 or live (W=1024)")
    p.add_argument("--deals", type=int, default=300)
    p.add_argument("--scores", choices=("zero", "uniform"), default="uniform")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--chunk", type=int, default=5)
    p.add_argument("--seed", default="rami-outcomes-v1")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    jobs = [(list(range(i, min(i + a.chunk, a.deals))), a.scores, a.seed) for i in range(0, a.deals, a.chunk)]
    t0, rows = time.time(), []
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.agent,)) as pool:
        for part in pool.map(run, jobs):
            rows.extend(part)
    report(rows, f"{a.agent} on all four seats, {a.scores} scores ({time.time() - t0:.0f} s)")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"rows": rows, "args": vars(a)}, default=str))


if __name__ == "__main__":
    main()
