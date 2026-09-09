"""T1 firing analysis and the T4 observation-only review packet.

Two jobs the T2/T3 run left open.

**Why did three ablations change nothing?** A zero contrast is ambiguous: the
rule may never fire, may fire but be dominated by a higher-priority component,
or may fire and win but select an outcome-identical action. Those are different
findings. The trace distinguishes them by counting, per rule, how often it is
cited by *any* candidate, how often it is cited by the *selected* candidate, and
how often the decision came down to a tie-break.

**The T4 packet.** At most 24 cases from distinct underlying deals, containing
only the acting player's observation, its legal actions, and neutrally labelled
alternatives. The eventual outcome, the other hands, and every hidden-derived
annotation go in a separate researcher-only file. No expert feedback is invented.

    PYTHONPATH=src python work/audit/t4_packet.py --output reports/audit
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t2_t3_runner import (  # noqa: E402
    COMPOUND_ABLATION,
    SINGLE_RULE_ABLATIONS,
    deal_of,
    fresh,
    play_out,
    reference_agents,
)

from tuppi_engine import EnginePhase, apply_match_action, match_observation_for
from tuppi_engine.serialization import action_to_data, observation_to_data
from tuppi_engine.trusted import trusted_transitions

TRACE_DEALS = 400
PACKET_CASES = 24


def firing_analysis(count: int) -> dict[str, object]:
    """Per rule: cited by any candidate, cited by the winner, decided by tie-break."""

    cited_any = collections.Counter()
    cited_selected = collections.Counter()
    decisions = collections.Counter()
    tie_broken = 0
    total = 0
    agents = reference_agents()
    with trusted_transitions():
        for index in range(count):
            hands, dealer = deal_of(index)
            state = fresh(hands, dealer, "t1-firing")
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                decision = agents[seat].decide(observation, diagnostics=False)
                scored = decision.scored
                ranked = sorted(
                    scored.candidates, key=lambda c: c.selection_key, reverse=True
                )
                total += 1
                decisions[state.phase.value] += 1
                seen = set()
                for candidate in scored.candidates:
                    for rule in candidate.rule_ids:
                        if rule not in seen:
                            cited_any[rule] += 1
                            seen.add(rule)
                for rule in ranked[0].rule_ids:
                    cited_selected[rule] += 1
                if len(ranked) > 1 and ranked[0].score_vector == ranked[1].score_vector:
                    tie_broken += 1
                state = apply_match_action(state, decision.action)
    rules = sorted(set(cited_any) | set(cited_selected))
    return {
        "deals": count,
        "decisions": total,
        "decisions_by_phase": dict(decisions),
        "decided_by_tie_break": tie_broken,
        "tie_break_rate": tie_broken / max(1, total),
        "per_rule": {
            rule: {
                "cited_by_any_candidate": cited_any[rule],
                "cited_by_selected_candidate": cited_selected[rule],
                "any_rate": cited_any[rule] / max(1, total),
                "selected_rate": cited_selected[rule] / max(1, total),
            }
            for rule in rules
        },
    }


def build_packet(results: Path, cases: int) -> tuple[list, list]:
    """Cases where the T3 oracle found a gain: demonstrable left-on-the-table value.

    The reviewable half carries the acting seat's observation and its legal
    actions with neutral labels. Everything that depends on the hidden deal or
    the eventual outcome is separated out.
    """

    payload = json.loads(results.read_text(encoding="utf-8"))
    opportunities = []
    for row in payload["per_deal"]:
        for team_key, team in (("team0", 0), ("team1", 1)):
            entry = row["t3"][team_key]
            if entry["reached"] and entry["gain"] > 0:
                opportunities.append((row["deal"], team, entry))
    # Distinct underlying deals, largest realised gain first, deterministic.
    opportunities.sort(key=lambda item: (-item[2]["gain"], item[0], item[1]))
    chosen, seen = [], set()
    for deal, team, entry in opportunities:
        if deal in seen:
            continue
        seen.add(deal)
        chosen.append((deal, team, entry))
        if len(chosen) >= cases:
            break

    reviewable, researcher = [], []
    agents = reference_agents()
    with trusted_transitions():
        for ordinal, (deal, team, entry) in enumerate(chosen):
            hands, dealer = deal_of(deal)
            state = fresh(hands, dealer, "t4-case")
            root = None
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                if (
                    state.phase is EnginePhase.TRICK_PLAY
                    and len(observation.completed_tricks) == 11
                    and seat % 2 == team
                    and not any(p.seat % 2 == team for p in observation.current_trick)
                ):
                    root = (state, observation, seat)
                    break
                state = apply_match_action(
                    state, agents[seat].choose_action(observation)
                )
            if root is None:  # pragma: no cover - T3 reached every root
                continue
            state, observation, seat = root
            reference_action = agents[seat].choose_action(observation)
            alternatives = [
                {
                    "label": f"option {chr(ord('A') + i)}",
                    "action": action_to_data(action),
                }
                for i, action in enumerate(observation.legal_actions)
            ]
            reviewable.append(
                {
                    "case_id": f"T4-{ordinal + 1:02d}",
                    "question": (
                        "You are on lead or following in trick 12 of 13. Which of "
                        "the listed options do you play, and why? The options are "
                        "in the engine's legal order and are not ranked."
                    ),
                    "observation": observation_to_data(observation),
                    "legal_action_count": len(observation.legal_actions),
                    "alternatives": alternatives,
                }
            )
            researcher.append(
                {
                    "case_id": f"T4-{ordinal + 1:02d}",
                    "deal_index": deal,
                    "evaluated_team": team,
                    "acting_seat": seat,
                    "reference_action": action_to_data(reference_action),
                    "reference_option_label": next(
                        alt["label"]
                        for alt in alternatives
                        if alt["action"] == action_to_data(reference_action)
                    ),
                    "oracle_equity_gain": entry["gain"],
                    "legal_actions": entry["legal"],
                    "forced": entry["forced"],
                    "distinct_outcomes": entry["distinct_outcomes"],
                    "true_hands": [[str(card) for card in hand] for hand in hands],
                    "warning": (
                        "researcher-only: contains the hidden deal and the "
                        "hindsight-optimal branch. Never show alongside the "
                        "reviewable case."
                    ),
                }
            )
    return (reviewable, researcher)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/audit"))
    parser.add_argument("--trace-deals", type=int, default=TRACE_DEALS)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    print(f"T1.4 rule firing analysis over {args.trace_deals} deals")
    firing = firing_analysis(args.trace_deals)
    print(f"  decisions {firing['decisions']:,}  "
          f"({firing['decisions_by_phase']})")
    print(f"  decided by tie-break: {firing['tie_break_rate']:.1%}")
    print()
    ablatable = [rule for _v, rule in SINGLE_RULE_ABLATIONS]
    print(f"  {'rule':56s}{'cited by any':>14s}{'cited by winner':>17s}")
    for rule in ablatable:
        row = firing["per_rule"].get(rule)
        if row is None:
            print(f"  {rule:56s}{'NEVER CITED':>14s}{'NEVER CITED':>17s}")
            continue
        print(f"  {rule:56s}{row['any_rate']:>13.2%}{row['selected_rate']:>17.2%}")
    (args.output / "t1_firing_analysis.json").write_text(
        json.dumps(firing, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"\nT4 review packet")
    reviewable, researcher = build_packet(
        args.output / "t2_t3_results.json", PACKET_CASES
    )
    print(f"  cases from distinct deals: {len(reviewable)} (cap {PACKET_CASES})")
    if reviewable:
        keys = set(reviewable[0]["observation"].keys())
        forbidden = {"hands", "initial_hands", "deal_id"}
        leaked = keys & forbidden
        print(f"  observation keys: {len(keys)}; forbidden keys present: {leaked or 'none'}")
        assert not leaked, "the reviewable packet must not carry hidden state"
    (args.output / "t4_review_packet.json").write_text(
        json.dumps(
            {
                "schema_version": "tuppi.audit.t4_packet.v1",
                "instructions": (
                    "Observation-only review cases. Each contains one acting "
                    "player's formal observation and its legal actions in the "
                    "engine's order, unranked and neutrally labelled. No outcome, "
                    "no other hand, no annotation. Nothing here has been reviewed "
                    "by a human; no expert validation is claimed."
                ),
                "cases": reviewable,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output / "t4_researcher_only.json").write_text(
        json.dumps(
            {
                "schema_version": "tuppi.audit.t4_researcher.v1",
                "warning": "contains hidden deals and hindsight-optimal branches",
                "cases": researcher,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  wrote t1_firing_analysis.json, t4_review_packet.json, "
          f"t4_researcher_only.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
