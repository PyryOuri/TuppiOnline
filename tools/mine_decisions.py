#!/usr/bin/env python3
"""Mine every archived decision for where a player and the reference disagree —
and, in the endgame, for who was actually right.

Two questions, one pass over the archive.

**Where do I differ from the strongest policy this project has?** Cheap: ask
the reference for its ranking at each position and record where the played card
sat in it. Broken down by contract, by seat position in the trick, and by trick
number, that says *which kind of decision* to work on rather than just how
often you disagree.

**Who was right?** Disagreement alone proves nothing — the reference is a
practical policy, not an optimum, and importing a maxim from bridge has already
measured negative here twice. But in the last few tricks the Phase 5B solver
gives perfect-information ground truth, so ``--exact`` scores both the played
card and the reference's pick against it. That produces the two lists worth
having:

  * decisions where the **human found the optimal card and the reference did
    not** — candidate improvements to the bot, proven rather than argued;
  * decisions where the **reference would have saved a trick the human lost** —
    the player's own recurring mistakes, also proven.

The solver is exact or an error, never an estimate, and it only runs on
positions inside its documented range, so a verdict here is not a heuristic.

Usage:
    python3 tools/mine_decisions.py [--archive PATH] [--exact]
                                    [--actor human|bot|all] [--export FILE]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys

import archive_replay


def reference_view(policy, observation, action):
    """Where the played action sat in the reference policy's own ranking."""

    ranking = policy.decide(observation, diagnostics=False).scored
    candidates = ranking.candidates
    played = next((item for item in candidates if item.action == action), None)
    if played is None:
        return None
    played_vector = tuple(float(v) for v in played.score_vector)
    strictly_better = sum(
        1
        for item in candidates
        if tuple(float(v) for v in item.score_vector) > played_vector
    )
    ordered = ranking.ranked()
    rank = 1 + next(
        index for index, item in enumerate(ordered) if item.action == action
    )
    return {
        "legal_actions": len(candidates),
        "played_rank": rank,
        "strictly_better": strictly_better,
        "agreed": ranking.action == action,
        # A tie means the reference did not care, which is not a disagreement.
        "indifferent": ranking.action != action and strictly_better == 0,
        "reference_action": ranking.action,
    }


def exact_verdict(decision, reference_action):
    """Score the played card and the reference's pick against perfect play."""

    from tuppi_engine import EnginePhase, PlayCardAction
    from tuppi_exact import SolverBudgetError, SolverError, solve_late_game

    if not isinstance(decision.action, PlayCardAction):
        return None
    deal = decision.deal
    if deal is None or deal.phase is not EnginePhase.TRICK_PLAY:
        return None
    if len(decision.observation.legal_actions) < 2:
        return None  # forced, so nothing to be right or wrong about
    try:
        solution = solve_late_game(deal, maximum_tricks_remaining=4)
    except (SolverBudgetError, SolverError):
        return None
    played_regret = solution.regret_in_tricks(decision.action.card)
    verdict = {
        "played_regret": played_regret,
        "played_optimal": played_regret <= 0,
        "optimal_cards": [c for c in solution.optimal_cards],
    }
    if isinstance(reference_action, PlayCardAction):
        reference_regret = solution.regret_in_tricks(reference_action.card)
        verdict["reference_regret"] = reference_regret
        verdict["reference_optimal"] = reference_regret <= 0
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive")
    parser.add_argument("--actor", choices=("human", "bot", "all"), default="human")
    parser.add_argument("--exact", action="store_true",
                        help="also score the endgame against the exact solver")
    parser.add_argument("--export", help="write every mined decision as JSONL")
    args = parser.parse_args()

    from tuppi_agents.void_lead import BASE_PROFILE_KEY, construct_void_lead_agent
    from tuppi_engine import EnginePhase, PlayCardAction
    from tuppi_rules import card_to_code

    root = archive_replay.archive_root(args.archive)
    if not root.is_dir():
        print(f"No archive at {root}", file=sys.stderr)
        return 1

    policies = {seat: construct_void_lead_agent(seat, profile_key=BASE_PROFILE_KEY)
                for seat in range(4)}
    buckets = collections.defaultdict(collections.Counter)
    rows: list[dict] = []
    human_better: list[dict] = []
    human_worse: list[dict] = []

    for match in archive_replay.replay_archive(root):
        for decision in match.decisions:
            if args.actor == "human" and not decision.is_human:
                continue
            if args.actor == "bot" and decision.is_human:
                continue
            view = reference_view(
                policies[decision.seat], decision.observation, decision.action
            )
            if view is None or view["legal_actions"] < 2:
                continue  # forced: agreement is meaningless
            deal = decision.deal
            showing = deal.phase is EnginePhase.SHOWING
            contract = "SHOW" if showing else deal.contract.value
            where = "show" if showing else archive_replay.seat_role(deal, decision.seat)
            trick = None if showing else len(deal.completed_tricks)

            cell = buckets[(contract, where)]
            cell["decisions"] += 1
            cell["agreed"] += int(view["agreed"])
            cell["indifferent"] += int(view["indifferent"])
            cell["rank_sum"] += view["played_rank"]
            if trick is not None and trick >= 9:
                cell["late"] += 1

            row = {
                "match_ref": decision.match_ref,
                "deal": decision.deal_number,
                "seat": decision.seat,
                "actor": decision.actor,
                "contract": contract,
                "where": where,
                "trick": trick,
                "played_rank": view["played_rank"],
                "legal_actions": view["legal_actions"],
                "agreed": view["agreed"],
                "indifferent": view["indifferent"],
            }

            if args.exact:
                verdict = exact_verdict(decision, view["reference_action"])
                if verdict is not None:
                    row["played_regret"] = verdict["played_regret"]
                    row["reference_regret"] = verdict.get("reference_regret")
                    cell["exact_scored"] += 1
                    cell["regret"] += verdict["played_regret"]
                    ref_regret = verdict.get("reference_regret")
                    if ref_regret is not None:
                        detail = {
                            "match_ref": decision.match_ref,
                            "deal": decision.deal_number,
                            "trick": trick,
                            "contract": contract,
                            "played": card_to_code(decision.action.card),
                            "reference": card_to_code(view["reference_action"].card)
                            if isinstance(view["reference_action"], PlayCardAction)
                            else None,
                            "played_regret": verdict["played_regret"],
                            "reference_regret": ref_regret,
                        }
                        if verdict["played_regret"] < ref_regret:
                            human_better.append(detail)
                        elif verdict["played_regret"] > ref_regret:
                            human_worse.append(detail)
            rows.append(row)

    if args.export:
        with open(args.export, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    print(f"decisions with a real choice: {len(rows)}   actor filter: {args.actor}\n")
    print(f"{'contract':9s} {'where':8s} {'n':>5} {'agreed':>8} {'indiff':>7} "
          f"{'mean rank':>10}" + ("  " + f"{'exact n':>8} {'regret':>7}" if args.exact else ""))
    for (contract, where), cell in sorted(buckets.items()):
        n = cell["decisions"]
        line = (f"{contract:9s} {where:8s} {n:>5} {100*cell['agreed']/n:>7.1f}% "
                f"{100*cell['indifferent']/n:>6.1f}% {cell['rank_sum']/n:>10.2f}")
        if args.exact:
            scored = cell["exact_scored"]
            line += f"  {scored:>8} {cell['regret']:>7}" if scored else f"  {'-':>8} {'-':>7}"
        print(line)

    if args.exact:
        print(f"\nEndgame, scored against perfect play:")
        print(f"  played better than the reference : {len(human_better)}")
        print(f"  played worse than the reference  : {len(human_worse)}")
        for title, rows_ in (("BETTER than the reference", human_better),
                             ("WORSE than the reference", human_worse)):
            if not rows_:
                continue
            print(f"\n  {title} (up to 10):")
            for item in sorted(rows_, key=lambda r: -abs(
                r["played_regret"] - r["reference_regret"]))[:10]:
                print(f"    deal {item['deal']} trick {item['trick']} {item['contract']}: "
                      f"played {item['played']} (regret {item['played_regret']}) vs "
                      f"reference {item['reference']} (regret {item['reference_regret']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
