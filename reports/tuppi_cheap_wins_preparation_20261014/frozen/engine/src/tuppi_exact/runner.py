"""Finite noninteractive CLI for the Phase 5B exact layer.

Every subcommand is deterministic, reads only explicit inputs, writes only
canonical JSON, and never opens stdin, a GUI, a socket, or a random source.

Large outputs belong outside the repository and outside any cloud-synced
directory. ``integrity --report`` prints a warning when the working tree looks
cloud-synced, because that was the reproducible cause of a stalled subprocess
test before the tree was relocated.
"""

from __future__ import annotations

import argparse
import sys
import time

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    atomic_write_canonical_json,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    strict_json_load_file,
)
from tuppi_rules import MatchScore, card_to_code

from .constraints import HardConstraintModel
from .continuation import hypothetical_continuation
from .counting import count_summary, exact_uniform_marginals
from .diagnosis import (
    DEFAULT_ABLATION_PAIRS,
    DEFAULT_CENSUS_DEALS,
    DEFAULT_SAFETY_CAP,
    DEFAULT_SAMPLES_PER_DECISION,
    diagnose,
    run_rule_ablation,
)
from .errors import ExactError
from .integrity import build_baseline, integrity_report, verify_baseline
from .sampling import UniformFeasibleSampler, uniform_sampling_summary
from .solver import (
    DEFAULT_MAXIMUM_TRICKS_REMAINING,
    monotonicity_certificate,
    solve_late_game,
)
from .variants import composition_check, diagnostic_variants


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Exact inference, exact late-game solving, and match-aware "
        "rule diagnosis for project_target_v1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    integrity = subparsers.add_parser(
        "integrity", help="write, verify, or report the frozen-baseline gate"
    )
    integrity.add_argument("--output", help="write the baseline snapshot here")
    integrity.add_argument("--verify", help="verify against a recorded baseline")
    integrity.add_argument(
        "--report", action="store_true", help="print the checks that need no baseline"
    )

    variants = subparsers.add_parser(
        "variants", help="list the Phase 5B diagnostic agent identities"
    )
    variants.add_argument("--output")

    monotone = subparsers.add_parser(
        "monotonicity", help="write the exhaustive match-utility certificate"
    )
    monotone.add_argument("--output")

    inspect = subparsers.add_parser(
        "inspect",
        help="build the constraint model, exact count, and sample for one position",
    )
    inspect.add_argument("--deal-file", required=True)
    inspect.add_argument("--seat", type=int, required=True)
    inspect.add_argument("--tricks", type=int, default=0,
                         help="advance this many tricks with first-legal play")
    inspect.add_argument("--samples", type=int, default=8)
    inspect.add_argument("--seed", default="tuppi-exact-cli-v1")
    inspect.add_argument("--output")

    solve = subparsers.add_parser(
        "solve", help="solve one late-game position exactly from an explicit deal"
    )
    solve.add_argument("--deal-file", required=True)
    solve.add_argument("--tricks", type=int, required=True,
                       help="advance this many tricks with first-legal play")
    solve.add_argument(
        "--max-tricks-remaining", type=int, default=DEFAULT_MAXIMUM_TRICKS_REMAINING
    )
    solve.add_argument("--output")

    census = subparsers.add_parser(
        "diagnose", help="run the match-aware rule diagnosis"
    )
    census.add_argument("--census-deals", type=int, default=DEFAULT_CENSUS_DEALS)
    census.add_argument(
        "--samples-per-decision", type=int, default=DEFAULT_SAMPLES_PER_DECISION
    )
    census.add_argument(
        "--max-tricks-remaining", type=int, default=DEFAULT_MAXIMUM_TRICKS_REMAINING
    )
    census.add_argument("--show-census-deals", type=int, default=0)
    census.add_argument("--ablation-pairs", type=int)
    census.add_argument("--output", required=True)

    ablation = subparsers.add_parser(
        "ablate", help="run only the fresh-design per-rule match ablation"
    )
    ablation.add_argument("--pairs", type=int, default=DEFAULT_ABLATION_PAIRS)
    ablation.add_argument("--safety-cap", type=int, default=DEFAULT_SAFETY_CAP)
    ablation.add_argument(
        "--workers",
        type=int,
        help="worker processes; affects wall-clock time only, never a result",
    )
    ablation.add_argument("--output", required=True)

    shows = subparsers.add_parser(
        "show-census", help="census the two showing rules over showing decisions only"
    )
    shows.add_argument("--deals", type=int, default=256)
    shows.add_argument("--output")
    return parser


def _progress(started: float, label: str):
    def report(done: int, total: int) -> None:
        if done % 8 == 0 or done == total:
            elapsed = time.perf_counter() - started
            rate = done / elapsed if elapsed > 0 else 0.0
            remaining = (total - done) / rate if rate > 0 else float("inf")
            print(
                f"  {label} {done}/{total}  {elapsed / 60:.1f} min elapsed  "
                f"~{remaining / 60:.1f} min remaining",
                file=sys.stderr,
                flush=True,
            )

    return report


def _integrity(args) -> int:
    if args.verify:
        problems = verify_baseline(strict_json_load_file(args.verify))
        if problems:
            for item in problems:
                print(f"DRIFT: {item}", file=sys.stderr)
            return 3
        print("the frozen Phase 4 and Phase 5A baseline is unchanged")
        return 0
    if args.report:
        report = integrity_report()
        for key in (
            "archive_manifest_problems",
            "capability_containment_problems",
            "sealed_bank_problems",
        ):
            for item in report[key]:
                print(f"PROBLEM: {item}", file=sys.stderr)
        tree = report["working_tree"]
        if tree["is_probably_cloud_synced"]:
            print(
                f"WARNING: {tree['repository_root']} looks cloud-synced "
                f"({', '.join(tree['cloud_synced_markers'])}); {tree['note']}",
                file=sys.stderr,
            )
        if args.output:
            atomic_write_canonical_json(args.output, report)
            print(args.output)
        else:
            print("holds" if report["holds"] else "problems found")
        return 0 if report["holds"] else 3
    baseline = build_baseline()
    if args.output:
        atomic_write_canonical_json(args.output, baseline)
        print(args.output)
    else:
        print(baseline["baseline_digest"])
    return 0


def _variants(args) -> int:
    payload = {
        "composition_check": composition_check(),
        "schema_version": "tuppi.exact.diagnostic_variant_list.v1",
        "variants": [item.to_data() for item in diagnostic_variants()],
    }
    if args.output:
        atomic_write_canonical_json(args.output, payload)
        print(args.output)
    else:
        for item in payload["variants"]:
            print(f"{item['label']:52s} {item['agent_id']}")
    return 0


def _monotonicity(args) -> int:
    certificate = monotonicity_certificate()
    if args.output:
        atomic_write_canonical_json(args.output, certificate)
        print(args.output)
    else:
        print(
            f"holds={certificate['holds']} cases={certificate['cases_checked']} "
            f"failures={len(certificate['failures'])}"
        )
    return 0 if certificate["holds"] else 3


def _load_deal(deal_file: str) -> tuple[ExplicitDeal, MatchScore]:
    """Load either an explicit deal or the first deal of a match input."""

    from tuppi_engine import (
        SerializationError,
        explicit_deal_from_data,
        match_input_from_data,
    )

    data = strict_json_load_file(deal_file)
    try:
        deal = explicit_deal_from_data(data)
        return deal, MatchScore()
    except SerializationError:
        pass
    try:
        match_input = match_input_from_data(data)
    except SerializationError as exc:
        raise ExactError(
            "--deal-file must be an explicit deal or an explicit match input"
        ) from exc
    if not match_input.deals:
        raise ExactError("the match input contains no deals")
    return match_input.deals[0], match_input.initial_score


def _advance(deal_file: str, tricks: int):
    """Replay an explicit deal with first-legal play for a reproducible position."""

    from tuppi_engine import FirstLegalActionAgent, apply_match_action

    if type(tricks) is not int or tricks < 0 or tricks > 13:
        raise ExactError("--tricks must be an integer in 0..13")
    deal, initial_score = _load_deal(deal_file)
    state = create_match(
        initial_score=initial_score,
        initial_dealer=deal.dealer,
        match_ref="exact-cli",
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=deal.dealer, hands=deal.hands))
    agents = tuple(FirstLegalActionAgent() for _ in range(4))
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        active = state.active_deal
        if (
            active is not None
            and active.phase is EnginePhase.TRICK_PLAY
            and len(active.completed_tricks) >= tricks
            and not active.current_trick
        ):
            return state
        actor = state.current_actor
        state = apply_match_action(
            state, agents[actor].choose_action(match_observation_for(state, actor))
        )
    return state


def _inspect(args) -> int:
    state = _advance(args.deal_file, args.tricks)
    if state.active_deal is None:
        raise ExactError("the deal ended before the requested position")
    if args.seat not in range(4):
        raise ExactError("--seat must be an integer in 0..3")
    observation = match_observation_for(state, args.seat)
    model = HardConstraintModel.build(observation)
    payload: dict[str, object] = {
        "counting": count_summary(model),
        "observing_seat": args.seat,
        "schema_version": "tuppi.exact.position_inspection.v1",
        "show_exclusion_sizes": [len(item) for item in model.show_exclusions],
        "void_suits": [
            sorted(suit.value for suit in item) for item in model.void_suits
        ],
    }
    if model.unknown_cards:
        payload["uniform_marginals"] = {
            card_to_code(card): [str(value) for value in per_seat]
            for card, per_seat in exact_uniform_marginals(model).items()
        }
        if args.samples > 0:
            payload["sampling"] = uniform_sampling_summary(
                observation, seed=args.seed, count=args.samples
            )
            sampler = UniformFeasibleSampler.build(model, seed=args.seed)
            payload["continuations_validated"] = sum(
                1
                for assignment in sampler.sample(args.samples)
                if hypothetical_continuation(observation, assignment).is_hypothetical
            )
    if args.output:
        atomic_write_canonical_json(args.output, payload)
        print(args.output)
    else:
        print(
            f"unknown={payload['counting']['unknown_card_count']} "
            f"feasible={payload['counting']['feasible_assignment_count']}"
        )
    return 0


def _solve(args) -> int:
    state = _advance(args.deal_file, args.tricks)
    if state.active_deal is None or state.active_deal.phase is not EnginePhase.TRICK_PLAY:
        raise ExactError("the requested position is not a trick-play position")
    solution = solve_late_game(
        state.active_deal, maximum_tricks_remaining=args.max_tricks_remaining
    )
    payload = solution.to_data()
    if args.output:
        atomic_write_canonical_json(args.output, payload)
        print(args.output)
    else:
        print(
            f"seat={solution.acting_seat} contract={solution.contract.value} "
            f"optimal_own_tricks={solution.optimal_own_team_tricks_final} "
            f"cards={[card_to_code(card) for card in solution.optimal_cards]} "
            f"nodes={solution.nodes_visited}"
        )
    return 0


def _diagnose(args) -> int:
    started = time.perf_counter()
    report = diagnose(
        census_deals=args.census_deals,
        samples_per_decision=args.samples_per_decision,
        show_census_deals=args.show_census_deals,
        ablation_pairs=args.ablation_pairs,
        maximum_tricks_remaining=args.max_tricks_remaining,
        progress=_progress(started, "unit"),
    )
    atomic_write_canonical_json(args.output, report)
    census = report["census"]
    print(f"decisions: {census['decisions_by_phase']}")
    for rule_id, summary in sorted(census["per_rule"].items()):
        exact = summary["exact_verdicts"]
        print(
            f"{rule_id:46s} changes={summary['decision_changes']:5d} "
            f"exact(n/h/x)={exact['neutral']}/{exact['rule_helps']}/"
            f"{exact['rule_hurts']}"
        )
    print(args.output)
    return 0


def _show_census(args) -> int:
    from .diagnosis import show_rule_census

    report = show_rule_census(deals=args.deals)
    if args.output:
        atomic_write_canonical_json(args.output, report)
        print(args.output)
    print(f"showing decisions: {report['decisions']}")
    for label, summary in sorted(report["per_variant"].items()):
        print(
            f"{label:44s} eligible={summary['eligible_decisions']:6d} "
            f"contract_flips={summary['contract_flips']:5d} "
            f"card_only={summary['card_only_changes']:5d}"
        )
    margin = report["threshold_margin"]
    print(
        f"threshold margin: mean={margin['mean']} within_2={margin['within_2_points']} "
        f"within_3={margin['within_3_points']} of {margin['count']}"
    )
    return 0


def _ablate(args) -> int:
    report = run_rule_ablation(
        pairs=args.pairs,
        safety_cap=args.safety_cap,
        workers=args.workers,
        progress=_progress(time.perf_counter(), "pair"),
    )
    atomic_write_canonical_json(args.output, report)
    for comparison in report["comparisons"]:
        inference = comparison["primary_match_inference"]
        print(
            f"{comparison['name']:56s} pairs={inference['complete_pair_count']} "
            f"p_win={inference['candidate_match_win_probability']} "
            f"censored={inference['censored_pair_count']}"
        )
    print(args.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "ablate": _ablate,
        "diagnose": _diagnose,
        "inspect": _inspect,
        "integrity": _integrity,
        "monotonicity": _monotonicity,
        "show-census": _show_census,
        "solve": _solve,
        "variants": _variants,
    }
    try:
        return handlers[args.command](args)
    except ExactError as exc:
        print(f"tuppi-exact: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
