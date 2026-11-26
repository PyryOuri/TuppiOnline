"""Stage 3 evaluator of the base-network task: `tuppi_ai.evaluate` with three spec extensions.

audit_deliverables/tuppi_base_network_task_20261022 (PLAN.json "measures", "release").
Every duplicate game is played by tuppi_ai.evaluate's own code (`measure`, `_play`,
`summarise`, `_score_for`: the same base deals for a seed, 4 rotations x 2 team
assignments, dealer 0, the same equity table and output format). Only the construction
of agents gains three options, needed by the Stage 3 search and lite measures:

    best:...:rs=1         every search reseeded from the information state
                          (SearchAgent.reseed, as the `search:` spec's rs=1): two runs on
                          the same deals draw the same worlds wherever their games agree,
                          so the arms of a paired measure share the opponent's searches and
                          identical agents give identical games
    best:...:bp=<actor>   the anchor (the policy that keep 0.003 / bids 0.03 keeps) is
                          <actor> instead of best.ANCHOR; with pib=<k> the play-inference
                          likelihood model follows the anchor, as best_agents' factory does
                          (best.py: `policy = native.Mlp(anchor ...)`), unless pibp= is given
    best:...:pibp=<actor> (tuppi_ai.evaluate's own `best` option, passed through) the likelihood
                          model named explicitly; with bp= this is "anchor only", the new
                          anchor with the likelihood model kept. Heidi 1.2 (owner 2026-10-23):
                          best:w=128:pib=8:rs=1:bp=<new actor>:pibp=<models/vrpo3_final.pt>
                          `best` options are checked: an unknown one, or pibp/pibt/pibe/pibs
                          without pib=, is an error (tuppi_ai.evaluate would ignore it silently)
    lite:<npz>[:c1|:c1h]  the hosted lite bot (tuppi_ai.lite.LiteAgent) on that exported
                          network; c1 / c1h = the face-up safety net with play inference
                          (Nelli; without people C1H plays exactly as C1). The agents'
                          cursors restart at every game (duplicate) or match (pairs), as in
                          TuppiAI-faceup's native harness, so games are reproducible and paired

A spec without these options builds exactly the agents tuppi_ai.evaluate builds. Rows also
carry each base deal's process CPU seconds (`deal_cpu_s`, measurement only).

    python tools/stage3_eval.py --checkpoint <spec> --opponent <spec> --deals N --seed S
        --scores uniform --ruleset v3 --workers 12 --out OUT.json
    python tools/stage3_eval.py pairs --checkpoint <spec> --opponent <spec> --pairs N --seed S --out OUT.json
    python tools/stage3_eval.py describe <spec> [<spec> ...] [--known name=path ...] [--out F]
        # the agents each spec builds (anchor, likelihood and rollout networks named by
        # fingerprint), as JSON: an object for one spec, a list for several

pairs: complete matches from 0-0 to 52 (v3 rules); each pair plays one deal sequence twice,
the candidate on team 0 and then on team 1; prints the candidate's match-win rate with a 95%
interval over pairs (identical agents give exactly 0.5 per pair).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tuppi_ai import evaluate as E  # noqa: E402

_ORIGINAL_MAKE = E._make_candidate
_ORIGINAL_PLAY = E._play


#: tuppi_ai.evaluate's `best` options (rs= and bp= are this tool's).
BEST_OPTIONS = {"w", "pib", "pibt", "pibe", "pibs", "pibp"}


def _options(parts: list[str]) -> dict:
    return dict(p.split("=", 1) for p in parts)


def make_candidate(spec: str) -> dict:
    """tuppi_ai.evaluate._make_candidate plus rs=, bp= on `best` (pibp= passed through) and the
    lite: spec."""
    if spec.startswith("lite:"):
        from tuppi_ai import lite
        parts = spec.split(":")[1:]
        flags = set(parts[1:])
        unknown = flags - {"c1", "c1h"}
        if unknown:
            raise ValueError(f"unknown lite options {sorted(unknown)}")
        mlp = lite.load_mlp(Path(parts[0]))
        options = lite.C1H if "c1h" in flags else lite.C1 if "c1" in flags else lite.LiteOptions()
        return {s: lite.LiteAgent(s, mlp=mlp, options=options) for s in range(4)}
    if spec == "best" or spec.startswith("best:"):
        opts = _options(spec.split(":")[1:])
        reseed = int(opts.pop("rs", "0"))
        anchor = opts.pop("bp", None)
        unknown = set(opts) - BEST_OPTIONS
        if unknown:
            raise ValueError(f"unknown best options {sorted(unknown)}")
        if "pib" not in opts and set(opts) & {"pibt", "pibe", "pibs", "pibp"}:
            raise ValueError(f"{spec}: pibt/pibe/pibs/pibp need pib=<k>")
        base = ":".join(["best"] + [f"{k}={v}" for k, v in opts.items()])
        if anchor is not None:
            from tuppi_ai import best
            saved = best.ANCHOR
            best.ANCHOR = Path(anchor)  # read by best_agents and by evaluate's pib default at call time
            try:
                agents = _ORIGINAL_MAKE(base)
            finally:
                best.ANCHOR = saved
        else:
            agents = _ORIGINAL_MAKE(base)
        if reseed:
            for agent in agents.values():
                agent.reseed = True
        return agents
    return _ORIGINAL_MAKE(spec)


def reset_cursors(agents: dict) -> None:
    """Lite agents' cursors back to their initial values (other agents are left as they are)."""
    from tuppi_ai import lite
    for seat, agent in agents.items():
        if isinstance(agent, lite.LiteAgent):
            agent.rng.value = lite.initial_cursor(seat)
            agent.gate_rng.value, agent.belief_rng.value = lite.initial_net_cursors(seat)


def _play(hands, score, candidate_team):
    reset_cursors(E._W["candidate"])
    reset_cursors(E._W["opponent"])
    return _ORIGINAL_PLAY(hands, score, candidate_team)


def _init(candidate: str, opponent: str, equity_path: str, ruleset: str) -> None:
    E._make_candidate = make_candidate
    E._play = _play
    E._init(candidate, opponent, equity_path, ruleset)


def _measure(index: int, seed: str, scores: str) -> dict:
    t0 = time.process_time()
    row = E.measure(index, seed, scores)
    row["cpu_s"] = round(time.process_time() - t0, 3)
    return row


def evaluate(candidate: str, deals: int, seed: str, scores: str, opponent: str, workers: int,
             equity_path: str, ruleset: str) -> dict:
    """tuppi_ai.evaluate.evaluate with the extended agent construction."""
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(workers, initializer=_init,
                             initargs=(candidate, opponent, equity_path, ruleset)) as pool:
        for row in pool.map(_measure, range(deals), [seed] * deals, [scores] * deals, chunksize=8):
            rows.append(row)
            if len(rows) % 64 == 0:
                print(f"stage3_eval: {len(rows)}/{deals} deals, {time.time() - t0:.0f} s", file=sys.stderr, flush=True)
    summary = E.summarise(rows)
    summary.update({"candidate": candidate, "opponent": opponent, "seed": seed, "scores": scores,
                    "ruleset": E.RULESETS[ruleset], "seconds": round(time.time() - t0, 1),
                    "instrument": "tools/stage3_eval.py (tuppi_ai.evaluate measure/summarise)",
                    "deal_cpu_s": [r["cpu_s"] for r in rows],
                    "values": [r["value"] for r in rows],
                    "games": [g for r in rows for g in r["games"]]})
    return summary


# --------------------------------------------------------------------------- complete matches
def _deal(seed: str, pair: int, k: int):
    from tuppi_rules.cards import FULL_DECK
    rng = random.Random(f"{seed}|pair|{pair}|deal|{k}")
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


def _match(pair: int, seed: str, candidate_team: int, max_deals: int) -> tuple[int, int]:
    """(winning team or -1, deals played) of one match from 0-0, dealer pair % 4."""
    from tuppi_engine import (ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId

    cand, opp = E._W["candidate"], E._W["opponent"]
    reset_cursors(cand)
    reset_cursors(opp)
    state = create_match(initial_score=MatchScore(0, 0), initial_dealer=pair % 4, match_ref="stage3-pairs",
                         ruleset_id=RulesetId(E.RULESETS["v3"]))
    k = 0
    with trusted_transitions():
        while not state.terminal and k < max_deals:
            state = begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=_deal(seed, pair, k)))
            while state.active_deal is not None and not state.active_deal.complete:
                seat = state.current_actor
                actor = cand[seat] if seat % 2 == candidate_team else opp[seat]
                state = apply_match_action(state, actor.choose_action(match_observation_for(state, seat)))
            k += 1
    if not state.terminal:
        return -1, k
    return (0 if state.score.team0 >= 52 else 1), k


def _pair(pair: int, seed: str, max_deals: int) -> dict:
    t0 = time.process_time()
    out = {"pair": pair, "wins": [], "deals": []}
    for team in (0, 1):
        winner, k = _match(pair, seed, team, max_deals)
        out["wins"].append(None if winner < 0 else int(winner == team))
        out["deals"].append(k)
    out["cpu_s"] = round(time.process_time() - t0, 3)
    return out


def pairs(candidate: str, opponent: str, n: int, seed: str, workers: int, equity_path: str,
          max_deals: int = 400) -> dict:
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(candidate, opponent, equity_path, "v3")) as pool:
        for row in pool.map(_pair, range(n), [seed] * n, [max_deals] * n, chunksize=4):
            rows.append(row)
            if len(rows) % 64 == 0:
                print(f"stage3_eval pairs: {len(rows)}/{n}, {time.time() - t0:.0f} s", file=sys.stderr, flush=True)
    finished = [r for r in rows if None not in r["wins"]]
    values = [sum(r["wins"]) / 2 for r in finished]
    m = statistics.fmean(values) if values else float("nan")
    half = 1.96 * statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else float("nan")
    return {"mode": "pairs", "candidate": candidate, "opponent": opponent, "seed": seed, "ruleset": E.RULESETS["v3"],
            "pairs": n, "matches": 2 * n, "finished_pairs": len(finished), "unfinished_matches": sum(
                w is None for r in rows for w in r["wins"]), "deals": sum(sum(r["deals"]) for r in rows),
            "win_rate": m, "ci95": [m - half, m + half], "pair_values": values,
            "seconds": round(time.time() - t0, 1), "pair_cpu_s": [r["cpu_s"] for r in rows],
            "rows": rows, "instrument": "tools/stage3_eval.py pairs"}


# --------------------------------------------------------------------------- describe
def _fingerprint(mlp) -> str:
    """sha256 of a native network's outputs on fixed rows: equal networks, equal prints."""
    import numpy as np
    from tuppi_ai import native
    rng = np.random.default_rng(20261023)
    feat = (rng.random((4, native.feature_dim(mlp.encoder))) < 0.05).astype(np.uint8)
    return hashlib.sha256(mlp.forward(feat).tobytes()).hexdigest()[:16]


def _torch_print(net) -> str:
    from tuppi_ai import native
    return _fingerprint(native.Mlp(net))


def describe(spec: str, known: dict[str, str] | None = None) -> dict:
    """The agents `spec` builds (seat 0; every seat is built alike), with network fingerprints
    named after the model files in `known` ({name: path}; files with equal networks are named
    together, `a=b`). For a search agent: the anchor (keep rule for bids and play), the
    play-inference likelihood model (None without pib=) and the rollout networks."""
    from tuppi_ai import model as qmodel
    from tuppi_ai.equity import Equity
    E._W["equity"] = Equity.load(ROOT / "models" / "equity_incumbent.json")
    prints = {}
    for label, path in (known or {}).items():
        if str(path).endswith(".npz"):
            from tuppi_ai import lite
            fp = _fingerprint(lite.load_mlp(Path(path)))
        else:
            fp = _torch_print(qmodel.load(path, "cpu"))
        prints[fp] = f"{prints[fp]}={label}" if fp in prints else label
    name = lambda fp: prints.get(fp, fp)  # noqa: E731
    agents = make_candidate(spec)
    a = agents[0]
    out = {"spec": spec, "class": type(a).__name__, "handles_sooli": bool(getattr(a, "handles_sooli", False))}
    if type(a).__name__ == "SearchAgent":
        sr = a.searcher
        belief = getattr(sr.env, "_belief_model", None)
        out.update({"worlds": sr.worlds, "solver_tail": sr.dd_left, "search_showing": a.search_showing,
                    "keep": a.keep, "keep_bids": a.keep_show, "rami_bonus": a.rami_bonus, "reseed": a.reseed,
                    "adaptive": a.adaptive, "show_worlds": a.show_searcher.worlds if a.show_searcher else None,
                    "rollouts_opponents": name(_fingerprint(sr.mlp) if sr.mlp is not None else _torch_print(sr.net)),
                    "rollouts_team": name(_torch_print(sr.team_net)) if sr.team_net is not None else "shared with opponents",
                    "anchor": name(_torch_print(a.blueprint_net)),
                    "likelihood": name(_fingerprint(belief)) if belief is not None else None})
    elif type(a).__name__ == "LiteAgent":
        out.update({"network": name(_fingerprint(a.mlp)), "options": a.options.__dict__})
    elif type(a).__name__ == "PolicyAgent":
        out.update({"policy": type(a.policy).__name__, "network": name(_torch_print(a.policy.net))})
    return out


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "describe":
        p = argparse.ArgumentParser()
        p.add_argument("mode")
        p.add_argument("spec", nargs="+")
        p.add_argument("--known", nargs="*", default=[], help="name=path model files to name fingerprints")
        p.add_argument("--out", type=Path)
        a = p.parse_args()
        known = dict(k.split("=", 1) for k in a.known)
        res = [describe(s, known) for s in a.spec]
        text = json.dumps(res[0] if len(res) == 1 else res, indent=1, default=str)
        print(text)
        if a.out:
            a.out.write_text(text + "\n")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "pairs":
        p = argparse.ArgumentParser()
        p.add_argument("mode")
        p.add_argument("--checkpoint", required=True)
        p.add_argument("--opponent", required=True)
        p.add_argument("--pairs", type=int, required=True)
        p.add_argument("--seed", required=True)
        p.add_argument("--workers", type=int, default=12)
        p.add_argument("--out", type=Path)
        a = p.parse_args()
        res = pairs(a.checkpoint, a.opponent, a.pairs, a.seed, a.workers, str(ROOT / "models" / "equity_incumbent.json"))
        print(json.dumps({k: v for k, v in res.items() if k not in ("pair_values", "rows", "pair_cpu_s")}, indent=1))
        if a.out:
            a.out.write_text(json.dumps(res, indent=1))
        return
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--deals", type=int, default=1000)
    p.add_argument("--seed", default="tuppi-ai-eval-v1")
    p.add_argument("--scores", choices=("zero", "uniform"), default="zero")
    p.add_argument("--opponent", default=E.INCUMBENT)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--ruleset", choices=tuple(E.RULESETS), default="v1")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    summary = evaluate(a.checkpoint, a.deals, a.seed, a.scores, a.opponent, a.workers,
                       str(ROOT / "models" / "equity_incumbent.json"), a.ruleset)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("values", "games", "deal_cpu_s")}, indent=1))
    if a.out:
        a.out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
