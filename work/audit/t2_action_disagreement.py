"""Did the ablations change any ACTION, or only fail to change outcomes?

T2 reported outcome change. That is not the same as action disagreement: 50.3%
of trick-play choices are outcome-neutral (measured separately), so a rule can
change what is played and leave the deal's result identical. Distinguishing the
two decides whether a zero contrast means "the rule is never decisive" or "the
rule is decisive but only over equivalent actions".

    PYTHONPATH=src python work/audit/t2_action_disagreement.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t2_t3_runner import (  # noqa: E402
    DEALS,
    SINGLE_RULE_ABLATIONS,
    deal_of,
    fresh,
    mixed,
    reference_agents,
    variant_agents,
)

from tuppi_engine import EnginePhase, apply_match_action, match_observation_for
from tuppi_engine.serialization import action_to_data
from tuppi_engine.trusted import trusted_transitions


def sequence(hands, dealer, seats) -> list:
    state = fresh(hands, dealer, "t2-disagree")
    out = []
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        action = seats[seat].choose_action(match_observation_for(state, seat))
        out.append((seat, action_to_data(action)))
        state = apply_match_action(state, action)
    result = state.completed_deals[-1].public_result
    return (out, tuple(result.team_tricks))


def main() -> int:
    control = reference_agents()
    rows = {}
    with trusted_transitions():
        for variant, rule_id in SINGLE_RULE_ABLATIONS:
            agents, identity = variant_agents(variant)
            diverged = outcome_changed = 0
            first_plies = []
            for index in range(DEALS):
                hands, dealer = deal_of(index)
                for team in (0, 1):
                    base, base_tricks = sequence(hands, dealer, control)
                    var, var_tricks = sequence(hands, dealer, mixed(agents, control, team))
                    if base != var:
                        diverged += 1
                        for ply, (a, b) in enumerate(zip(base, var)):
                            if a != b:
                                first_plies.append(ply)
                                break
                    if base_tricks != var_tricks:
                        outcome_changed += 1
            total = 2 * DEALS
            rows[variant] = {
                "rule_id": rule_id,
                "identity": identity,
                "assignments": total,
                "action_sequence_diverged": diverged,
                "action_divergence_rate": diverged / total,
                "outcome_changed": outcome_changed,
                "outcome_change_rate": outcome_changed / total,
                "mean_first_divergence_ply": (
                    sum(first_plies) / len(first_plies) if first_plies else None
                ),
            }
            print(f"  {variant} {rule_id}")
            print(f"      action sequence diverged {diverged:>5}/{total} = "
                  f"{100*diverged/total:5.1f}%")
            print(f"      deal outcome changed     {outcome_changed:>5}/{total} = "
                  f"{100*outcome_changed/total:5.1f}%")
            if first_plies:
                print(f"      mean first divergence ply {sum(first_plies)/len(first_plies):.1f}")
    Path("reports/audit").mkdir(parents=True, exist_ok=True)
    Path("reports/audit/t2_action_disagreement.json").write_text(
        json.dumps({"schema_version": "tuppi.audit.t2_disagreement.v1", "variants": rows},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("\nwrote reports/audit/t2_action_disagreement.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
