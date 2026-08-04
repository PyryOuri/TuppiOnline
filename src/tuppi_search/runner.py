"""Finite noninteractive CLI for the Phase 5C search layer.

Every subcommand is deterministic, reads only explicit inputs, writes only canonical
JSON, and never opens stdin, a GUI, a socket, or a random source. Output paths and
verbosity are excluded from every recorded result, because neither can change a
decision.

Large outputs belong outside the repository and outside any cloud-synced directory.
"""

from __future__ import annotations

import argparse
import sys
import time

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    FirstLegalActionAgent,
    apply_action,
    atomic_write_canonical_json,
    begin_explicit_deal,
    create_match,
    observation_for,
    strict_json_load_file,
)
from tuppi_rules import MatchScore

from .benchmark import action_stability, full_benchmark
from .config import DEVELOPMENT_REFERENCE_POLICY
from .errors import SearchError
from .evaluation import (
    heterogeneous_partnership_diagnostic,
    run_deal_ablation,
    run_match_comparison,
    showing_contract_sensitivity,
)
from .registry import (
    PRIMARY_PROFILE_KEY,
    REGISTERED_CONFIGURATIONS,
    build_agent,
    registry_snapshot,
)
from .utilities import UtilityId, utility_catalogue
from .validation import boundary_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classical root PIMC over uniform feasible worlds for "
        "project_target_v1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    agents = subparsers.add_parser("agents", help="list registered PIMC agents")
    agents.add_argument("--output")

    utilities = subparsers.add_parser(
        "utilities", help="list the versioned utility adapters"
    )
    utilities.add_argument("--output")

    check = subparsers.add_parser(
        "validate", help="run the Phase 5C boundary gate"
    )
    check.add_argument("--output")

    explain = subparsers.add_parser(
        "explain", help="explain one PIMC decision from an explicit deal"
    )
    explain.add_argument("--deal-file", required=True)
    explain.add_argument("--profile", default=PRIMARY_PROFILE_KEY)
    explain.add_argument("--seat", type=int, required=True)
    explain.add_argument(
        "--tricks",
        type=int,
        default=0,
        help="advance this many tricks with first-legal play before deciding",
    )
    explain.add_argument("--output")

    bench = subparsers.add_parser("benchmark", help="measure search performance")
    bench.add_argument("--streams", type=int, default=2)
    bench.add_argument("--output")

    stability = subparsers.add_parser(
        "stability", help="measure action stability across nested world budgets"
    )
    stability.add_argument("--profile", default=PRIMARY_PROFILE_KEY)
    stability.add_argument("--streams", type=int, default=3)
    stability.add_argument("--decisions", type=int, default=40)
    stability.add_argument("--output")

    ablate = subparsers.add_parser(
        "ablate", help="deal-level duplicate screening between two agents"
    )
    ablate.add_argument("--candidate", required=True)
    ablate.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    ablate.add_argument("--deals", type=int, default=32)
    ablate.add_argument(
        "--utility",
        default=UtilityId.MATCH_TRANSITION_V1.value,
        choices=[item.value for item in UtilityId],
    )
    ablate.add_argument("--output", required=True)

    compare = subparsers.add_parser(
        "compare", help="complete-match comparison on the Phase 5C bank"
    )
    compare.add_argument("--candidate", default=PRIMARY_PROFILE_KEY)
    compare.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    compare.add_argument("--pairs", type=int, required=True)
    compare.add_argument("--safety-cap", type=int, default=704)
    compare.add_argument(
        "--workers",
        type=int,
        help="worker processes; affects wall-clock time only, never a result",
    )
    compare.add_argument("--output", required=True)

    sens = subparsers.add_parser(
        "showing-sensitivity",
        help="RAMI declaration rate as a function of the world budget",
    )
    sens.add_argument("--deals", type=int, default=24)
    sens.add_argument("--output")

    hetero = subparsers.add_parser(
        "heterogeneous", help="mixed-partnership deal diagnostic"
    )
    hetero.add_argument("--profile", default=PRIMARY_PROFILE_KEY)
    hetero.add_argument("--deals", type=int, default=16)
    hetero.add_argument("--output", required=True)
    return parser


def _progress(started: float, label: str):
    def report(done: int, total: int) -> None:
        if done % 4 == 0 or done == total:
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


def _write(path: str | None, payload: dict) -> None:
    if path:
        atomic_write_canonical_json(path, payload)
        print(path)


def _agents(args) -> int:
    snapshot = registry_snapshot()
    _write(args.output, snapshot)
    if not args.output:
        for entry in snapshot["agents"]:
            print(f"{entry['profile_key']:44s} {entry['agent_id']}")
        print(f"primary: {snapshot['primary_profile_key']}")
    return 0


def _utilities(args) -> int:
    payload = {
        "adapters": list(utility_catalogue()),
        "schema_version": "tuppi.search.utility_catalogue.v1",
    }
    _write(args.output, payload)
    if not args.output:
        for item in payload["adapters"]:
            print(
                f"{item['utility_id']:48s} registerable={item['is_registerable']} "
                f"range={item['range']}"
            )
    return 0


def _validate(args) -> int:
    report = boundary_report()
    for key, value in sorted(report.items()):
        if key.endswith("problems") and value:
            for item in value:
                print(f"PROBLEM: {item}", file=sys.stderr)
    _write(args.output, report)
    if not args.output:
        print("holds" if report["holds"] else "problems found")
    return 0 if report["holds"] else 3


def _advance(deal_file: str, tricks: int):
    from tuppi_engine import (
        SerializationError,
        explicit_deal_from_data,
        match_input_from_data,
    )

    if type(tricks) is not int or tricks < 0 or tricks > 13:
        raise SearchError("--tricks must be an integer in 0..13")
    data = strict_json_load_file(deal_file)
    try:
        deal = explicit_deal_from_data(data)
        score = MatchScore()
    except SerializationError:
        try:
            match_input = match_input_from_data(data)
        except SerializationError as exc:
            raise SearchError(
                "--deal-file must be an explicit deal or an explicit match input"
            ) from exc
        if not match_input.deals:
            raise SearchError("the match input contains no deals")
        deal = match_input.deals[0]
        score = match_input.initial_score
    state = create_match(
        initial_score=score, initial_dealer=deal.dealer, match_ref="search-cli"
    )
    state = begin_explicit_deal(
        state, ExplicitDeal(dealer=deal.dealer, hands=deal.hands)
    )
    active = state.active_deal
    agents = tuple(FirstLegalActionAgent() for _ in range(4))
    while not active.complete:
        if (
            active.phase is EnginePhase.TRICK_PLAY
            and len(active.completed_tricks) >= tricks
            and not active.current_trick
        ):
            return active
        actor = active.current_actor
        active = apply_action(
            active, agents[actor].choose_action(observation_for(active, actor))
        )
    raise SearchError("the deal ended before the requested position")


def _explain(args) -> int:
    if args.profile not in REGISTERED_CONFIGURATIONS:
        raise SearchError(f"unknown Phase 5C profile {args.profile!r}")
    if args.seat not in range(4):
        raise SearchError("--seat must be an integer in 0..3")
    state = _advance(args.deal_file, args.tricks)
    observation = observation_for(state, args.seat)
    if observation.current_actor != args.seat:
        raise SearchError(
            f"seat {args.seat} is not the acting seat at this position; the actor "
            f"is seat {observation.current_actor}"
        )
    agent = build_agent(args.profile, seat=args.seat)
    started = time.perf_counter()
    diagnostics = agent.explain(observation)
    payload = diagnostics.to_data()
    payload["operational_timing"] = {
        "decision_seconds": round(time.perf_counter() - started, 6),
        "note": "operational only; no decision depends on timing",
    }
    _write(args.output, payload)
    if not args.output:
        print(
            f"seat {payload['root_seat']} team {payload['root_team']} "
            f"phase {payload['phase']}"
        )
        for candidate in payload["candidates"]:
            marker = "*" if candidate["action"] == payload["selected_action"] else " "
            print(
                f" {marker} {candidate['action']:26s} mean={candidate['mean_utility']:+.6f} "
                f"sd={candidate['standard_deviation']:.6f} "
                f"wins={candidate['root_team_deal_wins']}/{candidate['evaluations']}"
            )
        print(f"selection gap: {payload['selection_gap']:+.6f}")
    return 0


def _benchmark(args) -> int:
    report = full_benchmark(streams=args.streams)
    _write(args.output, report)
    if not args.output:
        for entry in report["decisions"]["decisions"]:
            print(
                f"worlds={entry['world_count']:2d} tail={entry['exact_tail_enabled']!s:5s} "
                f"policy={entry['rollout_policy_key']:22s} "
                f"median={entry['latency'].get('median_ms')} ms "
                f"p95={entry['latency'].get('p95_ms')} ms"
            )
        throughput = report["match_throughput"]
        print(
            f"deals/s={throughput['deals_per_second']} "
            f"search decisions/deal={throughput['mean_search_decisions_per_deal']}"
        )
    return 0


def _stability(args) -> int:
    report = action_stability(
        profile_key=args.profile,
        streams=args.streams,
        maximum_decisions=args.decisions,
    )
    _write(args.output, report)
    if not args.output:
        for entry in report["stability"]:
            print(
                f"{entry['from_worlds']:2d} -> {entry['to_worlds']:2d} worlds: "
                f"agreement {entry['agreement_rate']:.3f} "
                f"({entry['agreements']}/{entry['comparisons']})"
            )
    return 0


def _ablate(args) -> int:
    report = run_deal_ablation(
        candidate_profile_key=args.candidate,
        opponent_profile_key=args.opponent,
        deals=args.deals,
        utility_id=UtilityId(args.utility),
        progress=_progress(time.perf_counter(), "deal pair"),
    )
    atomic_write_canonical_json(args.output, report)
    print(
        f"{report['candidate_profile_key']} vs {report['opponent_profile_key']}: "
        f"mean paired utility {report['mean_paired_utility']:+.6f} "
        f"(se {report['standard_error_paired_utility']:.6f}), "
        f"ahead/tied/behind "
        f"{report['pairs_candidate_ahead']}/{report['pairs_tied']}/"
        f"{report['pairs_candidate_behind']}"
    )
    print(args.output)
    return 0


def _compare(args) -> int:
    report = run_match_comparison(
        candidate_profile_key=args.candidate,
        opponent_profile_key=args.opponent,
        pairs=args.pairs,
        safety_cap=args.safety_cap,
        workers=args.workers,
        progress=_progress(time.perf_counter(), "pair"),
    )
    atomic_write_canonical_json(args.output, report)
    inference = report["primary_match_inference"]
    print(
        f"{report['name']}: pairs={inference['complete_pair_count']} "
        f"p_win={inference['candidate_match_win_probability']} "
        f"censored={inference['censored_pair_count']} "
        f"outcomes={inference['pair_outcomes']}"
    )
    print(args.output)
    return 0


def _showing_sensitivity(args) -> int:
    report = showing_contract_sensitivity(
        deals=args.deals, progress=_progress(time.perf_counter(), "deal")
    )
    _write(args.output, report)
    print(f"reference RAMI rate: {report['reference_rami_declaration_rate']:.4f}")
    for count, rate in sorted(
        report["pimc_rami_declaration_rate"].items(), key=lambda item: int(item[0])
    ):
        print(f"  {int(count):3d} worlds: PIMC RAMI rate {rate:.4f}")
    return 0


def _heterogeneous(args) -> int:
    report = heterogeneous_partnership_diagnostic(
        pimc_profile_key=args.profile,
        deals=args.deals,
        progress=_progress(time.perf_counter(), "deal"),
    )
    atomic_write_canonical_json(args.output, report)
    for design in report["designs"]:
        print(
            f"{design['name']:44s} mean candidate utility "
            f"{design['result']['mean_candidate_utility']:+.6f}"
        )
    print(args.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "ablate": _ablate,
        "agents": _agents,
        "benchmark": _benchmark,
        "compare": _compare,
        "explain": _explain,
        "heterogeneous": _heterogeneous,
        "showing-sensitivity": _showing_sensitivity,
        "stability": _stability,
        "utilities": _utilities,
        "validate": _validate,
    }
    try:
        return handlers[args.command](args)
    except SearchError as exc:
        print(f"tuppi-search: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
