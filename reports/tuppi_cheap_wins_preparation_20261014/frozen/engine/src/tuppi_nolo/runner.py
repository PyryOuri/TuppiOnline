"""N07: the coverage screen — does the security framing propose anything new?

This harness answers one bounded question and is written so it cannot flatter
the answer. It replays a fixed bank of deals with the v2 reference policy at all
four seats, and at every eligible decision along that single trajectory it asks
N04 what it would play instead. A difference only counts once it has survived
three separate filters: N03 re-verifies the certificate **from scratch**, N05
prices the resulting totals on the scoreboard, and a tie in score states is
discarded however large the trick difference was.

Three properties of the design matter more than the counts it produces.

*The decision function sees an observation and nothing else.* The real layout is
written to a different file, never to the record the decision is derived from,
and is used only for the oracle check below. `solve_security` rejects anything
that is not a `PlayerObservation`, so a leak would have to be deliberate.

*The true layout must lie inside the enumerated support.* This is the sharpest
soundness check available here: a certificate quantifies over a support believed
complete, so if the deal that is actually being played is not in it, the support
was not complete and every guarantee derived from it is void. It is checked
after the decision, from the preserved layout, on every resolved position.

*Unresolved positions stay in the denominators.* A position whose support or
search ran out of budget is reported as eligible-and-unresolved, never dropped.
Silently discarding them would turn a coverage rate into a rate among the easy
positions, which is a different and much friendlier number.

The N06 memo is deliberately not used: its reduction failed, and its task
permits N07 to use it only if it passed. The plain search is the reference.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path

from tuppi_agents.void_lead import void_seeking_agents
from tuppi_eval.deals import DealerPolicy, generate_base_deal
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    PlayerObservation,
    apply_action,
    create_deal_state,
    observation_for,
)
from tuppi_rules import Contract, MatchScore, card_to_code
from tuppi_valuation.corpus import forced_show_action

from .certificates import CheckStatus, all_action_bounds, verify_certificate
from .outcomes import ClaimLabel, classify_claim
from .security import SecurityStatus, solve_security
from .support import SupportBudget, SupportStatus, build_support

SCHEMA_VERSION = "tuppi.nolo.coverage.v1"

DEVELOPMENT_SEED = "nolo-info-dev-v1"
SCREEN_SEED = "nolo-info-coverage-v1"
INITIAL_DEALER = 0
STARTING_SCORE = MatchScore(0, 0)
DEFAULT_CAP_HOURS = 4.0
FEASIBILITY_THRESHOLD = 5

#: Names that must never appear in a decision record. The records are built from
#: public quantities by construction; this is the same defence-in-depth deny list
#: the server analysis modules use, so a future edit cannot quietly add a hand.
FORBIDDEN_RECORD_KEYS = frozenset({
    "hands", "hidden_hands", "own_hand", "layout", "assignment", "sampled_owner",
    "research_worlds", "research_paths", "counterexample", "sampled_worlds",
})

SOUNDNESS_CHECKS = (
    "false_certificate",
    "illegal_choice",
    "information_leak",
    "continuation_violation",
    "truth_outside_support",
)


class CoverageError(RuntimeError):
    """Implementation drift during a screen run; never silently absorbed."""


# --------------------------------------------------------------- the bank


def deal_state(seed: str, index: int):
    """The frozen starting position of one banked deal, after canonical shows.

    Round-robin dealers from seat 0, score (0,0), contract forced to NOLO. Every
    argument here is preregistered; none of them is a tunable of this harness.
    """

    base = generate_base_deal(
        root_seed=seed,
        index=index,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=INITIAL_DEALER,
        starting_score=STARTING_SCORE,
    )
    ref = f"nolo-n07:{seed}:{index}"
    state = create_deal_state(
        ExplicitDeal(dealer=base.dealer, hands=base.hands),
        starting_score=STARTING_SCORE,
        match_ref=ref,
        deal_ref=f"{ref}/deal:0",
        deal_number=0,
        event_start_index=0,
    )
    while state.phase is EnginePhase.SHOWING:
        observation = observation_for(state, state.current_actor)
        state = apply_action(state, forced_show_action(observation, Contract.NOLO))
    if state.phase is not EnginePhase.TRICK_PLAY:
        raise CoverageError(f"deal {index} did not reach trick play")
    return state


def decision_role(observation: PlayerObservation) -> str:
    """lead / follow / discard, as a property of the position, not of the card.

    Read from the legal set rather than from what was played: a seat holding the
    led suit is following even when it plays badly, and a seat with no card of
    the suit is discarding even if it happens to play the same rank.
    """

    if not observation.current_trick:
        return "lead"
    led = observation.current_trick[0].card.suit
    return "follow" if any(
        a.card.suit is led for a in observation.legal_actions
        if isinstance(a, PlayCardAction)
    ) else "discard"


def is_eligible(observation: PlayerObservation, budget: SupportBudget) -> bool:
    """The frozen eligibility rule: a real choice, near enough to the end."""

    remaining = 13 - len(observation.completed_tricks)
    return (
        observation.phase is EnginePhase.TRICK_PLAY
        and len(observation.legal_actions) >= 2
        and 1 <= remaining <= budget.max_remaining_tricks
    )


def true_content_key(state, observation: PlayerObservation):
    """The layout actually being played, in the support's own key format.

    Read from the private DealState **after** the decision has been taken. It is
    an audit input, never a decision input.
    """

    return tuple(
        tuple(sorted(card_to_code(card) for card in state.hands[seat]))
        for seat in range(4)
    )


def contains_forbidden_key(value) -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_RECORD_KEYS:
                return key
            found = contains_forbidden_key(item)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = contains_forbidden_key(item)
            if found is not None:
                return found
    return None


# ------------------------------------------------------- one decision


def _read_check(record, check, failures) -> None:
    """Turn one verifier verdict into soundness findings, never into silence."""

    if check.status is CheckStatus.ILLEGAL_PLAN:
        failures.append(
            "continuation_violation" if "illegal at this information key" in str(check.reason)
            else "false_certificate"
        )
    elif check.status is CheckStatus.DISPROVED_BOUND:
        failures.append("false_certificate")


def evaluate_decision(
    state,
    observation: PlayerObservation,
    baseline_action: PlayCardAction,
    *,
    budget: SupportBudget,
    verification_budget: SupportBudget,
) -> dict:
    """Screen one eligible position and return its public record.

    The order is deliberate. The search runs on the observation alone; every
    resolved position carries the verifier's verdict on its own certificate; a
    deviation — the only thing this screen counts — is then re-verified from
    scratch by a second independent N03 run and priced by N05; and the oracle
    check against the real layout happens last, where it cannot reach the
    decision.
    """

    started = time.perf_counter()
    remaining = 13 - len(observation.completed_tricks)
    record = {
        "seat": observation.observing_seat,
        "trick_index": len(observation.completed_tricks),
        "remaining_tricks": remaining,
        "role": decision_role(observation),
        "legal_count": len(observation.legal_actions),
        "baseline_action": card_to_code(baseline_action.card),
        "information_key": None,
        "support_status": None,
        "world_count": None,
        "status": None,
        "proposed_action": None,
        "deviation": False,
        "plan_size": 0,
        "claimed_bound": None,
        "verified_bound": None,
        "verification_status": None,
        "reverification_status": None,
        "candidate_totals": None,
        "baseline_totals": None,
        "baseline_status": None,
        "claim": "NOT_APPLICABLE",
        "claim_reason": None,
        "score_relevant": False,
        "candidate_score_states": None,
        "baseline_score_states": None,
        "search_engine_transitions": 0,
        "verification_engine_transitions": 0,
        "baseline_engine_transitions": 0,
        "nodes_visited": 0,
        "failures": [],
        "reason": None,
    }

    result = solve_security(observation, budget, verification_budget=verification_budget)
    record.update(
        information_key=result.information_key,
        status=result.status.value,
        world_count=result.world_count,
        search_engine_transitions=result.search_engine_transitions,
        verification_engine_transitions=result.verification_engine_transitions,
        nodes_visited=result.nodes_visited,
        reason=result.reason,
    )

    # The support is rebuilt here rather than borrowed from the search, so the
    # oracle check reads an independently enumerated set.
    support = build_support(observation, budget)
    record["support_status"] = support.status.value

    failures: list[str] = []
    if result.status is not SecurityStatus.EXACT_COMPLETE:
        # An unresolved position is reported, not dropped: it stays in the
        # eligible denominator and simply carries no proposal.
        record["failures"] = failures
        record["seconds"] = time.perf_counter() - started
        return record

    if support.status is SupportStatus.EXACT_COMPLETE:
        if true_content_key(state, observation) not in {
            world.assignment.content_key() for world in support.research_worlds
        }:
            failures.append("truth_outside_support")

    selected = result.selected_action
    if selected not in observation.legal_actions:
        failures.append("illegal_choice")
    if result.certificate.root_seat != observation.observing_seat:
        failures.append("information_leak")
    if result.information_key != support.decision_key:
        failures.append("information_leak")

    verification = result.verification
    record.update(
        verification_status=verification.status.value,
        plan_size=len(result.plan),
        claimed_bound=result.certificate.claimed_terminal_bound,
        proposed_action=card_to_code(selected.card),
        deviation=selected != baseline_action,
    )
    _read_check(record, verification, failures)
    if verification.status is CheckStatus.EXACT_COMPLETE:
        totals = sorted(verification.terminal_totals)
        record["candidate_totals"] = totals
        record["verified_bound"] = max(totals)
        record["candidate_score_states"] = [list(x) for x in sorted(verification.score_states)]
        if max(totals) > result.certificate.claimed_terminal_bound:
            failures.append("false_certificate")

    # A deviation is the only thing this screen will end up counting, so it is
    # re-verified independently: a second N03 run on its own budget, from the
    # certificate alone, which must reproduce the same terminal set.
    reverified = False
    if record["deviation"]:
        recheck = verify_certificate(observation, result.certificate, verification_budget)
        record["reverification_status"] = recheck.status.value
        _read_check(record, recheck, failures)
        if recheck.status is CheckStatus.EXACT_COMPLETE:
            reverified = True
            if sorted(recheck.terminal_totals) != record["candidate_totals"]:
                failures.append("false_certificate")
                record["reason"] = "the two verifications disagree on the terminal set"
        else:
            record["reason"] = f"re-verification unresolved: {recheck.reason}"

    if record["deviation"] and reverified:
        baseline = all_action_bounds(observation, baseline_action, verification_budget)
        record["baseline_status"] = baseline.status.value
        record["baseline_engine_transitions"] = baseline.engine_transitions
        if baseline.status is CheckStatus.EXACT_COMPLETE:
            baseline_totals = sorted(baseline.terminal_totals)
            record["baseline_totals"] = baseline_totals
            record["baseline_score_states"] = [list(x) for x in sorted(baseline.score_states)]
            assessment = classify_claim(
                seat=observation.observing_seat,
                score_before=STARTING_SCORE,
                candidate_totals=record["candidate_totals"],
                baseline_totals=baseline_totals,
                candidate_upper_bound=record["verified_bound"],
                baseline_lower_bound=min(baseline_totals),
            )
            record["claim"] = assessment.label.value
            record["claim_reason"] = assessment.reason
            record["score_relevant"] = assessment.label in (
                ClaimLabel.UNIVERSAL, ClaimLabel.SECURITY_ONLY
            )
        else:
            record["claim"] = "UNRESOLVED_BASELINE"
    elif not record["deviation"]:
        record["claim"] = "NO_DEVIATION"

    record["failures"] = failures
    record["seconds"] = time.perf_counter() - started
    return record


# ----------------------------------------------------------- one deal


def screen_deal(
    seed: str,
    index: int,
    *,
    budget: SupportBudget | None = None,
    verification_budget: SupportBudget | None = None,
) -> dict:
    """Replay one deal under the v2 reference trajectory and screen it.

    The trajectory is the baseline's, always: the proposed action is recorded
    and then discarded, and play continues with what v2 chose. Following the
    candidate instead would build a different, candidate-generated trajectory,
    which the preregistration excludes.
    """

    budget = budget or SupportBudget()
    verification_budget = verification_budget or SupportBudget()
    state = deal_state(seed, index)
    agents = void_seeking_agents()
    records: list[dict] = []
    oracle: list[dict] = []
    card_plays = 0

    while state.phase is EnginePhase.TRICK_PLAY:
        actor = state.current_actor
        observation = observation_for(state, actor)
        action = agents[actor].choose_action(observation)
        if not isinstance(action, PlayCardAction):
            raise CoverageError(f"deal {index}: reference policy returned {action!r}")
        if is_eligible(observation, budget):
            record = evaluate_decision(
                state, observation, action,
                budget=budget, verification_budget=verification_budget,
            )
            record["deal_index"] = index
            record["deal_id"] = f"{seed}#{index}"
            record["position_id"] = f"{seed}#{index}/{record['trick_index']}/{actor}"
            leaked = contains_forbidden_key(record)
            if leaked is not None:
                record.setdefault("failures", []).append("information_leak")
                record["reason"] = f"record carried a forbidden key: {leaked}"
            records.append(record)
            oracle.append({
                "position_id": record["position_id"],
                "hands": [list(hand) for hand in true_content_key(state, observation)],
                "actual_action": card_to_code(action.card),
            })
        state = apply_action(state, action)
        card_plays += 1

    return {
        "deal_index": index,
        "deal_id": f"{seed}#{index}",
        "dealer": state.dealer,
        "card_plays": card_plays,
        "team_tricks": list(state.team_tricks),
        "records": records,
        "oracle": oracle,
    }


def _worker(payload):
    seed, index, tricks, worlds, transitions = payload
    budget = SupportBudget(tricks, worlds, transitions)
    try:
        return screen_deal(seed, index, budget=budget, verification_budget=budget)
    except Exception as exc:  # pragma: no cover - reported, never swallowed
        return {"deal_index": index, "deal_id": f"{seed}#{index}", "error": repr(exc),
                "card_plays": 0, "records": [], "oracle": []}


# ------------------------------------------------------- the whole bank


def summarise(deals: list[dict], *, attempted: int, cap_reached: bool) -> dict:
    """The denominators, in the order the task fixes, and the gate they feed."""

    records = [r for deal in deals for r in deal["records"]]
    errors = [d for d in deals if d.get("error")]
    resolved = [r for r in records if r["status"] == SecurityStatus.EXACT_COMPLETE.value]
    verified_deviations = [
        r for r in resolved
        if r["deviation"] and r["reverification_status"] == CheckStatus.EXACT_COMPLETE.value
    ]
    score_relevant = [r for r in verified_deviations if r["score_relevant"]]
    distinct = sorted({r["deal_id"] for r in score_relevant})

    failures: dict[str, int] = {name: 0 for name in SOUNDNESS_CHECKS}
    failing_positions = []
    for record in records:
        for name in record.get("failures", ()):
            failures[name] = failures.get(name, 0) + 1
        if record.get("failures"):
            failing_positions.append(
                {"position_id": record["position_id"], "failures": record["failures"]}
            )
    sound = not any(failures.values())

    def tally(rows, key):
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row[key])] = counts.get(str(row[key]), 0) + 1
        return dict(sorted(counts.items()))

    def support_bucket(row):
        size = row["world_count"]
        if size is None:
            return "unresolved"
        for edge in (1, 2, 5, 10, 25, 50, 100):
            if size <= edge:
                return f"<={edge}"
        return ">100"

    complete = len(deals) == attempted and not errors and not cap_reached
    if not sound:
        outcome = "FAILED_CHECK"
    elif not complete:
        outcome = "INCONCLUSIVE"
    elif len(distinct) >= FEASIBILITY_THRESHOLD:
        outcome = "GO"
    else:
        outcome = "NO_USEFUL_SIGNAL"

    return {
        "schema_version": SCHEMA_VERSION,
        "outcome": outcome,
        "soundness": {"passed": sound, "failures": failures,
                      "failing_positions": failing_positions},
        "denominators": {
            "deals_attempted": attempted,
            "deals_completed": len(deals) - len(errors),
            "card_plays": sum(d["card_plays"] for d in deals),
            "eligible_choices": len(records),
            "complete_supports": sum(
                1 for r in records
                if r["support_status"] == SupportStatus.EXACT_COMPLETE.value
            ),
            "completed_searches": len(resolved),
            "verified_deviations": len(verified_deviations),
            "score_relevant_deviations": len(score_relevant),
            "distinct_deals_with_a_deviation": len(distinct),
        },
        "unresolved": {
            "eligible_but_unresolved": len(records) - len(resolved),
            "by_status": tally(
                [r for r in records
                 if r["status"] != SecurityStatus.EXACT_COMPLETE.value],
                "status",
            ),
        },
        "breakdowns": {
            "eligible_by_role": tally(records, "role"),
            "eligible_by_remaining_tricks": tally(records, "remaining_tricks"),
            "eligible_by_support_size": dict(sorted(
                {b: sum(1 for r in records if support_bucket(r) == b)
                 for b in {support_bucket(r) for r in records}}.items()
            )),
            "resolved_by_claim": tally(resolved, "claim"),
            "deviations_by_role": tally(verified_deviations, "role"),
            "deviations_by_remaining_tricks": tally(verified_deviations, "remaining_tricks"),
            "score_relevant_by_claim": tally(score_relevant, "claim"),
        },
        "distinct_deals": distinct,
        "errors": [{"deal_id": d["deal_id"], "error": d["error"]} for d in errors],
        "cap_reached": cap_reached,
        "threshold": FEASIBILITY_THRESHOLD,
    }


def run_coverage(
    *,
    seed: str,
    deals: int,
    workers: int,
    out_dir: Path,
    cap_hours: float = DEFAULT_CAP_HOURS,
    budget: SupportBudget | None = None,
    log=print,
) -> dict:
    """Screen a whole bank, writing records, oracle layouts and the report.

    Deals are independent and each decision is a deterministic function of its
    observation, so the work is spread over processes purely to fit the wall
    clock. No budget is shared between workers and no value depends on how many
    there are.
    """

    budget = budget or SupportBudget()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = [
        (seed, index, budget.max_remaining_tricks, budget.max_worlds,
         budget.max_engine_transitions)
        for index in range(deals)
    ]
    deadline = time.monotonic() + cap_hours * 3600
    started = time.monotonic()
    completed: list[dict] = []
    cap_reached = False

    records_path = out_dir / "records.jsonl"
    oracle_path = out_dir / "oracle.jsonl"
    with records_path.open("w", encoding="utf-8") as records_file, \
            oracle_path.open("w", encoding="utf-8") as oracle_file:

        def absorb(deal):
            completed.append(deal)
            for record in deal["records"]:
                records_file.write(json.dumps(record, sort_keys=True) + "\n")
            for entry in deal["oracle"]:
                oracle_file.write(json.dumps(entry, sort_keys=True) + "\n")
            records_file.flush()
            oracle_file.flush()
            deviations = sum(1 for r in deal["records"] if r["deviation"])
            relevant = sum(1 for r in deal["records"] if r["score_relevant"])
            log(
                f"[{len(completed):>4}/{deals}] deal {deal['deal_index']:>4} "
                f"eligible={len(deal['records']):>2} deviations={deviations} "
                f"score_relevant={relevant} "
                f"elapsed={(time.monotonic() - started) / 60:.1f}m"
                + (f" ERROR {deal['error']}" if deal.get("error") else "")
            )

        if workers <= 1:
            for payload in payloads:
                if time.monotonic() >= deadline:
                    cap_reached = True
                    break
                absorb(_worker(payload))
        else:
            context = get_context("spawn")
            with context.Pool(processes=workers) as pool:
                pending = pool.imap_unordered(_worker, payloads)
                for deal in pending:
                    absorb(deal)
                    if time.monotonic() >= deadline:
                        cap_reached = True
                        pool.terminate()
                        break

    report = summarise(completed, attempted=deals, cap_reached=cap_reached)
    report["run"] = {
        "seed": seed,
        "deals": deals,
        "workers": workers,
        "cap_hours": cap_hours,
        "budget": {
            "max_remaining_tricks": budget.max_remaining_tricks,
            "max_worlds": budget.max_worlds,
            "max_engine_transitions": budget.max_engine_transitions,
        },
        "wall_seconds": time.monotonic() - started,
        "cached_search": False,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
    )
    log(f"outcome {report['outcome']}  "
        f"{report['denominators']['score_relevant_deviations']} score-relevant "
        f"deviations in {report['denominators']['distinct_deals_with_a_deviation']} deals")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tuppi_nolo.runner")
    commands = parser.add_subparsers(dest="command", required=True)
    coverage = commands.add_parser("coverage", help="run the N07 coverage screen")
    coverage.add_argument("--seed", default=SCREEN_SEED)
    coverage.add_argument("--deals", type=int, default=256)
    coverage.add_argument("--workers", type=int, default=1)
    coverage.add_argument("--out", required=True)
    coverage.add_argument("--cap-hours", type=float, default=DEFAULT_CAP_HOURS)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "run.log"
    with log_path.open("a", encoding="utf-8") as handle:
        def log(message):
            print(message, flush=True)
            handle.write(message + "\n")
            handle.flush()

        report = run_coverage(
            seed=args.seed, deals=args.deals, workers=args.workers,
            out_dir=out_dir, cap_hours=args.cap_hours, log=log,
        )
    return 0 if report["soundness"]["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
