"""Duplicate report for human sessions played against tools/serve_human.py.

For every completed deal in every room under runs/human_server/<plan>/, the
deal is replayed from its recorded starting score with a bot in the human's
seat (0) and the same seat plan elsewhere; the human team's match-equity change
is compared with the bot's on identical cards.

    python tools/human_report.py [--bot search|incumbent] [--worlds 64]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ruleset(runner: dict):
    """The record's ruleset (match records before v4 are project_target_v1)."""
    from tuppi_rules import RulesetId
    return RulesetId(runner.get("ruleset_id", "project_target_v1"))


def _active(ruleset):
    from tuppi_engine import EnginePhase
    if ruleset.value == "project_target_v1":
        return (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY)
    from tuppi_engine.state import ACTIVE_PHASES
    return ACTIVE_PHASES


def _agents(plan: dict[int, str], bot: str, worlds: int, sooli: bool = False):
    from tuppi_ai.best import best_agents
    from tuppi_ai.incumbent import incumbent_agents

    inc = incumbent_agents()
    if sooli:
        from tuppi_agents.sooli import SooliFallbackAgent
        inc = {s: SooliFallbackAgent(a) for s, a in inc.items()}
    kinds = dict(plan)
    kinds[0] = bot
    searched = [s for s in range(4) if kinds.get(s, "incumbent") == "search"]
    best = best_agents(searched, worlds=worlds, seed=100)
    return {s: best.get(s, inc[s]) for s in range(4)}


def _deals_of(runner: dict):
    """(explicit deal, starting score) for every completed deal, by exact replay."""
    from tuppi_engine import (EnginePhase, action_from_data, apply_match_action,
                              begin_explicit_deal, create_match, explicit_deal_from_data)
    from tuppi_rules import MatchScore

    deals = [explicit_deal_from_data(d) for d in runner["deals"]]
    actions = [action_from_data(r["action"]) for r in sorted(runner["accepted_actions"],
                                                             key=lambda r: r["action_index"])]
    ruleset = _ruleset(runner)
    active = _active(ruleset)
    state = create_match(initial_score=MatchScore(*runner["initial_score"]),
                         initial_dealer=runner["initial_dealer"], match_ref=runner["match_ref"],
                         **({} if ruleset.value == "project_target_v1" else {"ruleset_id": ruleset}))
    out, k = [], 0
    for deal in deals:
        if state.terminal:
            break
        before = state.score
        state = begin_explicit_deal(state, deal)
        while state.phase in active and k < len(actions):
            state = apply_match_action(state, actions[k])
            k += 1
        if state.phase in active:
            break  # unfinished deal
        out.append((deal, before, state.completed_deals[-1].public_result))
    return out


def _replay(deal, before, agents, equity, ruleset):
    from tuppi_engine import apply_match_action, begin_explicit_deal, create_match, match_observation_for

    extra = {} if ruleset.value == "project_target_v1" else {"ruleset_id": ruleset}
    state = begin_explicit_deal(create_match(initial_score=before, initial_dealer=deal.dealer,
                                             match_ref="human-report", **extra), deal)
    while state.phase in _active(ruleset):
        seat = state.current_actor
        state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
    r = state.completed_deals[-1].public_result
    return equity.delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), deal.dealer)


def main() -> None:
    from tuppi_ai.equity import Equity

    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT / "runs" / "human_server")
    p.add_argument("--bot", choices=("search", "incumbent"), default="search")
    p.add_argument("--worlds", type=int, default=128)  # tuppi_ai.best.WORLDS
    args = p.parse_args()
    from tuppi_ai.best import EQUITY
    equity = Equity.load(EQUITY)
    for plan_dir in sorted(d for d in args.root.iterdir() if d.is_dir()):
        parts = plan_dir.name.split("_project_target_")[0]
        plan = {int(x.split("-")[0]): x.split("-")[1] for x in parts.split("_")}
        sooli = "_project_target_v" in plan_dir.name and not plan_dir.name.endswith("_project_target_v1")
        agents = _agents(plan, args.bot, args.worlds, sooli=sooli)
        diffs = []
        for room in sorted(plan_dir.glob("room-*.json")):
            runner = json.loads(room.read_text()).get("runner")
            if not runner:
                continue
            ruleset = _ruleset(runner)
            for deal, before, result in _deals_of(runner):
                human = equity.delta0(result.score_before.as_tuple(), result.score_after.as_tuple(), deal.dealer)
                diffs.append(human - _replay(deal, before, agents, equity, ruleset))
        if not diffs:
            print(f"{plan_dir.name}: no completed deals")
            continue
        m = statistics.fmean(diffs)
        se = statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else float("nan")
        print(f"{plan_dir.name}: {len(diffs)} deals; human minus {args.bot} bot in seat 0: "
              f"{m:+.4f} equity/deal [{m - 1.96 * se:+.4f}, {m + 1.96 * se:+.4f}]")


if __name__ == "__main__":
    main()
