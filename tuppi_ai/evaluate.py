"""Duplicate evaluation of a candidate against the incumbent, in the authoritative engine.

Each base deal is played 8 times: 4 rotations of the hands x 2 team
assignments, with the candidate partnership on one team and the incumbent on
the other. The per-base-deal value is the mean of the candidate team's
match-equity change, so a candidate identical to the incumbent scores exactly
zero on every base deal. This mirrors TuppiProject's T4/T5 design (dealer 0,
same rotations and assignments), extended to non-zero starting scores.

    python -m tuppi_ai.evaluate --checkpoint runs/x/ckpt.pt --deals 2000
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

ROOT = Path(__file__).resolve().parents[1]
DEALER = 0
_W: dict = {}


RULESETS = {"v1": "project_target_v1", "v2": "project_target_v2", "v3": "project_target_v3"}


def _with_sooli(agents: dict, ruleset: str) -> dict:
    """Agents without their own sooli play get TuppiProject's simple fallback."""
    if ruleset == "v1":
        return agents
    from tuppi_agents.sooli import SooliFallbackAgent
    return {s: a if getattr(a, "handles_sooli", False) else SooliFallbackAgent(a) for s, a in agents.items()}


def _init(candidate: str, opponent: str, equity_path: str, ruleset: str = "v1") -> None:
    import torch

    torch.set_num_threads(1)
    from . import native

    native.set_rollout_chunk(128)  # several processes run: least total work, same moves
    from .equity import Equity
    from .incumbent import incumbent_agents

    _W["equity"] = Equity.load(Path(equity_path))
    _W["ruleset"] = ruleset
    _W["opponent"] = _with_sooli(incumbent_agents(opponent), ruleset)
    _W["candidate"] = _with_sooli(_make_candidate(candidate), ruleset)


def _make_candidate(spec: str) -> dict:
    """`profile:<key>`, a policy spec (see policies.py), or
    `search:<ckpt>[:w=32][:dd=6][:show=1][:belief=4][:bt=1.0][:be=0.1]`, plus the
    efficiency options (docs/EFFICIENCY_PLAN.md): `eq=1` rank-equivalent cards
    searched once (E6); `adb=<batch>[:adz=<z>][:add=<delta>][:adp=1]` adaptive
    worlds for bids (and trick play with adp=1), `w` as the cap (E7); `rs=1`
    worlds seeded from the information state (paired measurements); `sf=1`
    worlds honour showing-fallback restrictions (B0-S1); `bp=<policy>` the
    policy that `keep=<margin>` keeps (default the rollout net); `ddn=<k>` k extra
    solver-tail tricks in NOLO;
    `vn=<value net>[:vlb=<tricks>][:vlp=<tricks>][:vbb=1]` value-net leaves
    for bid searches (vlb, default 0 = start of play; -1 off) and card-play
    searches (vlp, default -1 = off) (docs/VALUE_NET_PLAN.md)."""
    if spec == "best":
        from .best import best_agents
        return best_agents()
    if spec.startswith("profile:"):
        from .incumbent import incumbent_agents
        return incumbent_agents(spec.split(":", 1)[1])
    if spec.startswith("search:"):
        from . import model as qmodel
        from .search import SearchAgent
        parts = spec.split(":")[1:]
        opts = dict(p.split("=") for p in parts[1:])
        net = qmodel.load(parts[0], "cpu")
        table = _W["equity"].table
        belief = {"belief": int(opts.get("belief", 0)), "belief_t": float(opts.get("bt", 1.0)),
                  "belief_eps": float(opts.get("be", 0.1)), "belief_seats": opts.get("bs", "all")}
        if "ot" in opts:
            belief["opp_temp"] = float(opts["ot"])
        if "team" in opts:
            belief["team_net"] = qmodel.load(opts["team"], "cpu")
        if int(opts.get("ddn", 0)):  # extra NOLO solver-tail tricks (process-wide; the incumbent does not search)
            from . import native
            native.set_dd_extra_nolo(int(opts["ddn"]))
        if int(opts.get("sf", 0)):  # B0-S1 sampler fix (process-wide; the incumbent does not search)
            from . import native
            native.set_showing_fix(True)
        if "bn" in opts:
            from .belief import load as load_belief
            belief.update(belief_net=load_belief(opts["bn"]), belief_n=int(opts.get("bN", 1024)),
                          belief_alpha=float(opts.get("ba", 0.5)))
        return {s: SearchAgent(net, table, s, worlds=int(opts.get("w", 32)), dd_left=int(opts.get("dd", 0)),
                               search_showing=int(opts.get("show", "0")),
                               keep=float(opts["keep"]) if "keep" in opts else None,
                               blueprint_net=qmodel.load(opts["bp"], "cpu") if "bp" in opts else None,
                               rami_bonus=float(opts.get("rb", 0.0)),
                               show_worlds=int(opts["sw"]) if "sw" in opts else None,
                               equiv=bool(int(opts.get("eq", 0))), reseed=bool(int(opts.get("rs", 0))),
                               adaptive=({"batch": int(opts["adb"]), "z": float(opts.get("adz", 2.5)),
                                          "delta": float(opts.get("add", 0.0)),
                                          "play": bool(int(opts.get("adp", 0)))} if "adb" in opts else None),
                               value=({"path": opts["vn"], "leaf_bid": int(opts.get("vlb", 0)),
                                       "leaf_play": int(opts.get("vlp", -1)), "bot_bit": bool(int(opts.get("vbb", 0)))}
                                      if "vn" in opts else None),
                               **belief) for s in range(4)}
    from .policies import PolicyAgent, from_spec
    policy = from_spec(spec, "cpu")
    return {s: PolicyAgent(policy, s) for s in range(4)}


def _score_for(index: int, mode: str, seed: str) -> tuple[int, int]:
    if mode == "zero":
        return (0, 0)
    rng = random.Random(f"{seed}|score|{index}")
    level = rng.randrange(13)
    if level == 0:
        return (0, 0)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)


def _play(hands, score, candidate_team):
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_rules import MatchScore

    cand, opp = _W["candidate"], _W["opponent"]
    ruleset = _W.get("ruleset", "v1")
    if ruleset == "v1":
        match = create_match(initial_score=MatchScore(*score), initial_dealer=DEALER, match_ref="tuppi-ai-eval")
        active = (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY)
    else:
        from tuppi_engine.state import ACTIVE_PHASES
        from tuppi_rules import RulesetId
        match = create_match(initial_score=MatchScore(*score), initial_dealer=DEALER, match_ref="tuppi-ai-eval",
                             ruleset_id=RulesetId(RULESETS[ruleset]))
        active = ACTIVE_PHASES
    state = begin_explicit_deal(match, ExplicitDeal(dealer=DEALER, hands=hands))
    while state.phase in active:
        seat = state.current_actor
        actor = cand[seat] if seat % 2 == candidate_team else opp[seat]
        state = apply_match_action(state, actor.choose_action(match_observation_for(state, seat)))
    r = state.completed_deals[-1].public_result
    d0 = _W["equity"].delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), DEALER)
    value = d0 if candidate_team == 0 else -d0
    declarer_team = None if r.declarer is None else r.declarer % 2
    return {
        "value": value,
        "won": r.deal_score.winner_team.value == candidate_team,
        "points": r.deal_score.points if r.deal_score.winner_team.value == candidate_team else -r.deal_score.points,
        "tricks": r.team_tricks[candidate_team],
        "rami": r.contract.value == "RAMI",
        "cand_declared": declarer_team == candidate_team,
        "opp_declared": declarer_team is not None and declarer_team != candidate_team,
        "stolen": bool(getattr(r.deal_score, "stolen_rami", False)),
        "cand_sooli": getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 == candidate_team,
        "opp_sooli": getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 != candidate_team,
        "cand_sooli_won": (getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 == candidate_team
                           and r.deal_score.winner_team.value == candidate_team),
        "opp_sooli_won": (getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 != candidate_team
                          and r.deal_score.winner_team.value != candidate_team),
    }


def measure(index: int, seed: str, scores: str) -> dict:
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules.cards import FULL_DECK

    rng = random.Random(f"{seed}|deal|{index}")
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    base = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
    score = _score_for(index, scores, seed)
    games = []
    with trusted_transitions():
        for rotation in range(4):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for team in (0, 1):
                games.append(_play(hands, score, team))
    out = {"index": index, "score": score, "value": statistics.fmean(g["value"] for g in games),
           "games": games}
    for key in STAT_KEYS:
        out[key] = statistics.fmean(float(g[key]) for g in games)
    return out


STAT_KEYS = ("won", "points", "tricks", "rami", "cand_declared", "opp_declared", "stolen",
             "cand_sooli", "opp_sooli", "cand_sooli_won", "opp_sooli_won")


def summarise(rows: list[dict]) -> dict:
    values = [r["value"] for r in rows]
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else float("nan")
    se = sd / math.sqrt(n)
    summary = {"base_deals": n, "games": 8 * n, "equity_per_deal": mean, "sd": sd,
               "ci95": [mean - 1.96 * se, mean + 1.96 * se]}
    for key in STAT_KEYS:
        summary[key] = statistics.fmean(r[key] for r in rows)
    return summary


def evaluate(candidate: str, deals: int, seed: str = "tuppi-ai-eval-v1", scores: str = "zero",
             opponent: str = "partner_aware_lead_v2", workers: int = 12,
             equity_path: str = str(ROOT / "models" / "equity_incumbent.json"), ruleset: str = "v1") -> dict:
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init,
                             initargs=(candidate, opponent, equity_path, ruleset)) as pool:
        rows = list(pool.map(measure, range(deals), [seed] * deals, [scores] * deals, chunksize=8))
    summary = summarise(rows)
    summary.update({"candidate": candidate, "opponent": opponent, "seed": seed, "scores": scores,
                    "ruleset": RULESETS[ruleset],
                    "seconds": round(time.time() - t0, 1),
                    "values": [r["value"] for r in rows],
                    "games": [g for r in rows for g in r["games"]]})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True,
                        help="best | profile:<key> | checkpoint path | search:<ckpt>:<options>")
    parser.add_argument("--deals", type=int, default=1000)
    parser.add_argument("--seed", default="tuppi-ai-eval-v1")
    parser.add_argument("--scores", choices=("zero", "uniform"), default="zero")
    parser.add_argument("--opponent", default="partner_aware_lead_v2")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--ruleset", choices=tuple(RULESETS), default="v1",
                        help="v1; v2 = + sooli; v3 = + sooli and locked bids (the real game)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = evaluate(args.checkpoint, args.deals, args.seed, args.scores, args.opponent, args.workers,
                       ruleset=args.ruleset)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("values", "games")}, indent=1))
    if args.out:
        args.out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
