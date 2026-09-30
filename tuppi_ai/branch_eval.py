"""Branch-point evaluation: a low-noise screen for small changes to the agent.

`tuppi_ai.evaluate` plays a variant and the reference as separate games; one
changed card early in a deal makes the rest of the two games diverge, so the
paired difference carries the whole deal's noise (sd about 0.009 per base deal
on 512 deals in the E6 test). Here the reference's games are played once, the
same 4 rotations x 2 team assignments against the incumbent, and at every
decision of the candidate pair the variant is asked too. Where it would act
differently, that action is played out to the end of the deal by the same
reference agents and the incumbent, and the branch's result minus the main
line's is the effect of that one deviation. A game's effect is the sum over
its deviations; identical decisions contribute exactly zero, and both lines
share the hidden cards.

This measures the variant's one-step deviations continued by the reference
(a first-order estimate of replacing the reference by the variant). It is a
screen, not a replacement for the game test.

**Validation (2026-09-29): noisier than the game test for frequent
deviations.** E6 on the 512 deals of its game test: +0.00061 [-0.00096,
+0.00218], sd 0.0181 per base deal, 36 branches per base deal, 19,779 CPU-s.
The game test measured -0.00057 [-0.00135, +0.00021] with sd 0.0090 for
18,517 CPU-s over both arms. Each deviation's continuation diverges on its
own, so a sum of about 4.5 branch outcomes per game adds noise rather than
removing it. It may still suit rare deviations (bid-only changes), but that
has not been validated.

Both specs should use `rs=1` (worlds seeded from the information state), so a
search depends only on what the seat knows. The search environments' sooli
options are reset before every decision (the ruleset-3 carry-over otherwise
depends on each agent object's history, which differs between lines).

    python -m tuppi_ai.branch_eval --ref "search:...:rs=1" --variant "search:...:rs=1:eq=1" --deals 256
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

from .evaluate import DEALER, RULESETS, ROOT, _make_candidate, _score_for, _W, _with_sooli


def _init(ref: str, variant: str, opponent: str, equity_path: str, ruleset: str) -> None:
    import torch

    torch.set_num_threads(1)
    from . import native
    from .equity import Equity
    from .incumbent import incumbent_agents

    native.set_rollout_chunk(128)
    _W["equity"] = Equity.load(Path(equity_path))
    _W["ruleset"] = ruleset
    _W["opponent"] = _with_sooli(incumbent_agents(opponent), ruleset)
    _W["ref"] = _with_sooli(_make_candidate(ref), ruleset)
    _W["var"] = _with_sooli(_make_candidate(variant), ruleset)


def _reset_sooli(agent) -> None:
    for sr in (getattr(agent, "searcher", None), getattr(agent, "show_searcher", None)):
        if sr is not None:
            sr.env.set_sooli(0, False, False, 0.0)


def _value(state, candidate_team: int) -> float:
    r = state.completed_deals[-1].public_result
    d0 = _W["equity"].delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), DEALER)
    return d0 if candidate_team == 0 else -d0


def _finish(state, candidate_team: int, active) -> float:
    """Plays a line to the end of the deal with the reference pair and the incumbent."""
    from tuppi_engine import apply_match_action, match_observation_for

    while state.phase in active:
        seat = state.current_actor
        agent = _W["ref"][seat] if seat % 2 == candidate_team else _W["opponent"][seat]
        _reset_sooli(agent)
        state = apply_match_action(state, agent.choose_action(match_observation_for(state, seat)))
    return _value(state, candidate_team)


def _game(hands, score, candidate_team: int) -> dict:
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_rules import MatchScore, RulesetId

    from .bridge import action_id

    match = create_match(initial_score=MatchScore(*score), initial_dealer=DEALER, match_ref="tuppi-ai-branch",
                         ruleset_id=RulesetId(RULESETS[_W["ruleset"]]))
    state = begin_explicit_deal(match, ExplicitDeal(dealer=DEALER, hands=hands))
    branches = []
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        if seat % 2 != candidate_team:
            agent = _W["opponent"][seat]
            state = apply_match_action(state, agent.choose_action(observation))
            continue
        ref, var = _W["ref"][seat], _W["var"][seat]
        _reset_sooli(ref)
        a_ref = ref.choose_action(observation)
        if len(observation.legal_actions) > 1:
            _reset_sooli(var)
            a_var = var.choose_action(observation)
            if action_id(a_var) != action_id(a_ref):
                kind = observation.phase.value
                branches.append((kind, _finish(apply_match_action(state, a_var), candidate_team, ACTIVE_PHASES)))
        state = apply_match_action(state, a_ref)
    main = _value(state, candidate_team)
    return {"main": main, "effect": sum(v - main for _, v in branches), "branches": len(branches),
            "by_kind": {k: sum(v - main for kk, v in branches if kk == k) for k, _ in branches}}


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
                games.append(_game(hands, score, team))
    kinds: dict[str, float] = {}
    for g in games:
        for k, v in g["by_kind"].items():
            kinds[k] = kinds.get(k, 0.0) + v / 8
    return {"index": index, "effect": statistics.fmean(g["effect"] for g in games),
            "main": statistics.fmean(g["main"] for g in games),
            "branches": sum(g["branches"] for g in games), "by_kind": kinds}


def evaluate(ref: str, variant: str, deals: int, seed: str, scores: str = "zero",
             opponent: str = "partner_aware_lead_v2", workers: int = 12,
             equity_path: str = str(ROOT / "models" / "equity_incumbent.json"), ruleset: str = "v3") -> dict:
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init,
                             initargs=(ref, variant, opponent, equity_path, ruleset)) as pool:
        rows = list(pool.map(measure, range(deals), [seed] * deals, [scores] * deals, chunksize=4))
    if len(rows) != deals:
        raise RuntimeError("missing base deals")
    e = [r["effect"] for r in rows]
    mean = statistics.fmean(e)
    se = statistics.stdev(e) / math.sqrt(len(e)) if len(e) > 1 else float("nan")
    kinds = sorted({k for r in rows for k in r["by_kind"]})
    return {"ref": ref, "variant": variant, "seed": seed, "ruleset": RULESETS[ruleset], "base_deals": deals,
            "effect_per_deal": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se], "sd": statistics.stdev(e),
            "reference_equity_per_deal": statistics.fmean(r["main"] for r in rows),
            "branches_per_base_deal": statistics.fmean(r["branches"] for r in rows),
            "effect_by_kind": {k: statistics.fmean(r["by_kind"].get(k, 0.0) for r in rows) for k in kinds},
            "seconds": round(time.time() - t0, 1), "effects": e}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ref", required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--deals", type=int, default=256)
    p.add_argument("--seed", default="tuppi-ai-branch-v1")
    p.add_argument("--scores", choices=("zero", "uniform"), default="zero")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--ruleset", choices=tuple(RULESETS), default="v3")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    summary = evaluate(a.ref, a.variant, a.deals, a.seed, a.scores, workers=a.workers, ruleset=a.ruleset)
    print(json.dumps({k: v for k, v in summary.items() if k != "effects"}, indent=1))
    if a.out:
        a.out.write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
