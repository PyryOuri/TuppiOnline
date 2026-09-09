"""T1: catalogue the reference's strategic rules, trace them, audit its certainties.

Contract in ``docs/audit/prereg_t0.md``. Three deliverables, none of which
touches the reference:

1. **Catalogue** - every catalogued rule the reference's profile implements, with
   its trigger, priority position, fallback, decision classes, validation status,
   and whether the profile will let it be disabled at all.
2. **Tracing** - opt-in activation traces via the existing diagnostics channel,
   with a proof on fixed streams that traced and untraced runs select identical
   actions and reach identical outcomes.
3. **Certainty audit** - the reference's *hard* ownership exclusions checked
   against true deals, plus the behavioural deduction the project has previously
   recorded as "robust under rationality".

The certainty audit reads hidden hands. It is an **offline analysis path**: it
never feeds a policy, and the traces it produces carry no hidden state. Keeping
those two things in one file would be the defect it is looking for, so the
hidden-state reader is confined to :func:`audit_hard_exclusions` and marked.

    PYTHONPATH=src python work/audit/t1_rule_audit.py --output reports/audit
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

from tuppi_agents import RULE_CATALOGUE, registered_profiles
from tuppi_agents.improved_registry import (
    corpus_reference_specification,
    improved_agent_from_specification,
)
from tuppi_agents.profiles import HeuristicProfile
from tuppi_agents.public_inference import PublicInference
from tuppi_corpus.packing import canonical_hands
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.serialization import action_to_data, observation_to_data
from tuppi_engine.trusted import trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

REFERENCE = "partner_aware_lead_v2"
BASE_PROFILE = "partner_aware_v1"
ROOT_SEED = "tuppi-t0-audit-v1"


def table() -> dict[int, object]:
    specification = corpus_reference_specification()
    return {
        seat: improved_agent_from_specification(
            specification, profile_key=REFERENCE, seat=seat
        )
        for seat in range(4)
    }


def deal_hands(index: int) -> tuple:
    stream = MatchStream.build(
        root_seed=ROOT_SEED, stream_index=index, initial_dealer=index % 4
    )
    return (canonical_hands(stream.deal(0).explicit_deal(index % 4).hands), index % 4)


def start(hands, dealer: int, ref: str = "t1-audit"):
    return begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=dealer, match_ref=ref),
        ExplicitDeal(dealer=dealer, hands=hands),
    )


# ------------------------------------------------------------------ catalogue


def build_catalogue() -> dict[str, object]:
    """Which rules the reference has, and which of them can be ablated at all."""

    control = registered_profiles()[BASE_PROFILE]
    in_profile = [
        rule for rule in RULE_CATALOGUE if BASE_PROFILE in rule.implementing_profiles
    ]
    # Priority position: the profile's enabled_rule_ids tuple is sorted, so it is
    # not a priority order. The real priority is the score-component order, which
    # action_scoring exposes per decision; the trace records it observationally
    # rather than this catalogue asserting it.
    rows = []
    for rule in sorted(in_profile, key=lambda item: item.rule_id):
        mechanical = rule.provenance.value == "mechanical"
        ablatable = None
        reason = None
        try:
            variant = HeuristicProfile.build(
                profile_key=BASE_PROFILE,
                family=control.family,
                showing_policy=control.showing_policy,
                parameters=dict(control.parameters),
                disabled_rule_ids=(rule.rule_id,),
                description="t1 eligibility probe",
            )
            ablatable = True
            reason = variant.profile_id
        except Exception as exc:  # noqa: BLE001 - the guard's message is the datum
            ablatable = False
            reason = f"{type(exc).__name__}: {exc}"
        rows.append(
            {
                "rule_id": rule.rule_id,
                "contracts": list(rule.contracts),
                "phases": list(rule.phases),
                "decision_classes": list(rule.contracts) + list(rule.phases),
                "condition": rule.condition,
                "action_preference": rule.action_preference,
                "provenance": rule.provenance.value,
                "validation_status": (
                    "mechanical consequence of the ruleset"
                    if mechanical
                    else "UNVALIDATED - no expert or simulation validation"
                ),
                "is_strategic_heuristic": not mechanical,
                "independently_disableable_claim": rule.independently_disableable,
                "profile_accepts_ablation": ablatable,
                "ablation_variant_or_refusal": reason,
                "limitations": rule.limitations,
                "rationale": rule.rationale,
            }
        )
    eligible = [r for r in rows if r["profile_accepts_ablation"]]
    return {
        "schema_version": "tuppi.audit.rule_catalogue.v1",
        "reference_profile_key": BASE_PROFILE,
        "reference_agent_id": corpus_reference_specification().agent_id,
        "catalogue_size": len(RULE_CATALOGUE),
        "rules_in_reference_profile": len(rows),
        "mechanical": sum(1 for r in rows if not r["is_strategic_heuristic"]),
        "strategic_unvalidated": sum(1 for r in rows if r["is_strategic_heuristic"]),
        "eligible_for_single_rule_ablation": len(eligible),
        "eligible_rule_ids": [r["rule_id"] for r in eligible],
        "uncatalogued_reference_layers": [
            "tuppi.agents.void_seeking_nolo_lead.v1",
            "tuppi.agents.establishment_rami_lead.v1",
        ],
        "rules": rows,
    }


# -------------------------------------------------------------------- tracing


def trace_deal(index: int) -> tuple[list, list]:
    """(actions, traces) for one deal. Traces carry no hidden state."""

    hands, dealer = deal_hands(index)
    agents = table()
    state = start(hands, dealer)
    actions, traces = [], []
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        decision = agents[seat].decide(observation, diagnostics=True)
        record = decision.diagnostics
        ranked = sorted(
            decision.scored.candidates, key=lambda c: c.selection_key, reverse=True
        )
        cited = collections.Counter(
            rule for candidate in decision.scored.candidates for rule in candidate.rule_ids
        )
        traces.append(
            {
                "deal": index,
                "ply": len(actions),
                "seat": seat,
                "phase": state.phase.value,
                "contract": observation.contract.value if observation.contract else None,
                "legal_actions": len(observation.legal_actions),
                "selected_action": action_to_data(decision.action),
                "selected_rule_ids": list(ranked[0].rule_ids),
                "selected_reason_codes": list(ranked[0].reason_codes),
                "component_names": list(ranked[0].component_names),
                "runner_up_rule_ids": list(ranked[1].rule_ids) if len(ranked) > 1 else [],
                "decided_by_tie_break": (
                    len(ranked) > 1 and ranked[0].score_vector == ranked[1].score_vector
                ),
                "rules_cited_by_any_candidate": dict(sorted(cited.items())),
                "profile_key": record.profile_key if record else None,
            }
        )
        actions.append((seat, action_to_data(decision.action)))
        state = apply_match_action(state, decision.action)
    result = state.completed_deals[-1].public_result
    actions.append(
        ("outcome", (result.contract.value, tuple(result.team_tricks),
                     result.deal_score.points))
    )
    traces.append(
        {
            "deal": index,
            "ply": "outcome",
            "contract": result.contract.value,
            "team_tricks": list(result.team_tricks),
            "points": result.deal_score.points,
            "winner_team": result.deal_score.winner_team.value,
        }
    )
    return (actions, traces)


def untraced_deal(index: int) -> list:
    hands, dealer = deal_hands(index)
    agents = table()
    state = start(hands, dealer)
    actions = []
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        action = agents[seat].choose_action(match_observation_for(state, seat))
        actions.append((seat, action_to_data(action)))
        state = apply_match_action(state, action)
    result = state.completed_deals[-1].public_result
    actions.append(("outcome", (result.contract.value, tuple(result.team_tricks),
                                result.deal_score.points)))
    return actions


def prove_tracing_is_inert(count: int = 64) -> dict[str, object]:
    """Traced and untraced reference runs must select identical actions.

    ``decide(diagnostics=True)`` and ``choose_action`` are documented to compute
    the same ranking, and the repository asserts it for every registered agent.
    This re-checks it for *this* reference on *this* manifest, because the trace
    is about to be used as evidence and a trace that perturbed play would
    invalidate every conclusion drawn from it.
    """

    mismatches = []
    with trusted_transitions():
        for index in range(count):
            traced_actions, _ = trace_deal(index)
            plain = untraced_deal(index)
            if traced_actions != plain:
                mismatches.append({"deal": index, "reason": "action sequence"})
    return {
        "deals_compared": count,
        "mismatched_deals": mismatches,
        "identical": not mismatches,
    }


# ------------------------------------------- OFFLINE HIDDEN-STATE ANALYSIS ONLY
#
# Everything below reads true hands. It is never reachable from a policy: it is
# called only from this script's audit path, its outputs go to a researcher-only
# file, and nothing it returns is fed back into an observation.


def audit_hard_exclusions(count: int) -> dict[str, object]:
    """Check the reference's *hard* ownership exclusions against true deals.

    ``PublicInference.can_seat_hold`` is documented as a hard public deduction.
    If it ever says a seat cannot hold a card that the seat does hold, the
    reference is acting on a false certainty - a finding, not a licence to edit
    the frozen policy.
    """

    checks = violations = 0
    examples = []
    duck_checks = duck_violations = 0
    duck_by_contract = collections.Counter()
    duck_total_by_contract = collections.Counter()

    agents = table()
    with trusted_transitions():
        for index in range(count):
            hands, dealer = deal_hands(index)
            true_owner = {
                card: seat for seat, hand in enumerate(hands) for card in hand
            }
            state = start(hands, dealer)
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                if state.phase is EnginePhase.TRICK_PLAY:
                    inference = PublicInference.build(observation)
                    for card, owner in true_owner.items():
                        if inference.is_played(card) or card in observation.own_hand:
                            continue
                        checks += 1
                        if not inference.can_seat_hold(owner, card):
                            violations += 1
                            if len(examples) < 12:
                                examples.append(
                                    {
                                        "deal": index,
                                        "observing_seat": seat,
                                        "card": str(card),
                                        "true_owner": owner,
                                        "possible_owners": sorted(
                                            inference.possible_owners(card)
                                        ),
                                    }
                                )
                state = apply_match_action(
                    state, agents[seat].choose_action(observation)
                )

            # The behavioural deduction: "took a trick it could have ducked
            # implies it holds nothing below the current high".
            result = state.completed_deals[-1].public_result
            label = result.contract.value
            remaining = [list(hand) for hand in hands]
            leader = result.first_leader
            for trick in result.completed_tricks:
                led = trick.plays[0].card.suit
                running = None
                for play in trick.plays:
                    hand = remaining[play.seat]
                    if play.seat == trick.winner and running is not None:
                        lower = [
                            card
                            for card in hand
                            if card.suit is led and card.rank < running.rank
                        ]
                        duck_checks += 1
                        duck_total_by_contract[label] += 1
                        if lower:
                            duck_violations += 1
                            duck_by_contract[label] += 1
                    if play.card.suit is led and (
                        running is None or play.card.rank > running.rank
                    ):
                        running = play.card
                    remaining[play.seat].remove(play.card)
                leader = trick.winner
    return {
        "hard_exclusion_checks": checks,
        "hard_exclusion_violations": violations,
        "hard_exclusions_sound": violations == 0,
        "violation_examples": examples,
        "ducking_deduction_checks": duck_checks,
        "ducking_deduction_violations": duck_violations,
        "ducking_violation_rate": duck_violations / max(1, duck_checks),
        "ducking_by_contract": {
            key: {
                "checks": duck_total_by_contract[key],
                "violations": duck_by_contract[key],
                "rate": duck_by_contract[key] / max(1, duck_total_by_contract[key]),
            }
            for key in sorted(duck_total_by_contract)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/audit"))
    parser.add_argument("--trace-deals", type=int, default=64)
    parser.add_argument("--audit-deals", type=int, default=200)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    catalogue = build_catalogue()
    print("T1.1 rule catalogue")
    print(f"  catalogue size                    {catalogue['catalogue_size']}")
    print(f"  in the reference's profile        {catalogue['rules_in_reference_profile']}")
    print(f"    mechanical (never ablate)       {catalogue['mechanical']}")
    print(f"    strategic and UNVALIDATED       {catalogue['strategic_unvalidated']}")
    print(f"  eligible for single-rule ablation {catalogue['eligible_for_single_rule_ablation']}")
    (args.output / "t1_rule_catalogue.json").write_text(
        json.dumps(catalogue, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("\nT1.2 tracing is inert")
    proof = prove_tracing_is_inert(args.trace_deals)
    print(f"  deals compared traced vs untraced {proof['deals_compared']}")
    print(f"  identical actions and outcomes    {proof['identical']}")
    if not proof["identical"]:
        print(f"  MISMATCHES: {proof['mismatched_deals']}")
        print("  -> tracing is not inert; this blocks its use as evidence")
        return 1

    print("\nT1.3 certainty audit (offline hidden-state path)")
    audit = audit_hard_exclusions(args.audit_deals)
    print(f"  hard ownership exclusion checks   {audit['hard_exclusion_checks']:,}")
    print(f"  violations                        {audit['hard_exclusion_violations']}")
    print(f"  => hard exclusions sound          {audit['hard_exclusions_sound']}")
    print(f"  ducking-deduction checks          {audit['ducking_deduction_checks']:,}")
    print(f"  ducking-deduction violations      {audit['ducking_deduction_violations']}"
          f"  = {100 * audit['ducking_violation_rate']:.1f}%")
    for key, row in audit["ducking_by_contract"].items():
        print(f"    {key:5s} {row['violations']:>6}/{row['checks']:<6} = {100*row['rate']:.1f}%")

    # A sample trace, for the schema and for the T4 packet's provenance.
    _actions, traces = trace_deal(0)
    (args.output / "t1_trace_sample.json").write_text(
        json.dumps({"schema_version": "tuppi.audit.rule_trace.v1", "traces": traces},
                   indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output / "t1_certainty_audit.json").write_text(
        json.dumps({"schema_version": "tuppi.audit.certainty.v1",
                    "tracing_proof": proof, **audit}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {args.output}/t1_rule_catalogue.json, t1_trace_sample.json, "
          "t1_certainty_audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
