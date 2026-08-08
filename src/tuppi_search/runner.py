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
    run_heterogeneous_match_comparison,
    run_match_comparison,
    run_phase5d_a_deal_screen,
    run_phase5d_a_match_comparison,
    showing_contract_sensitivity,
)
from .phase5d_b_evaluation import (
    run_root_info_uct_behavior_comparison,
    run_phase5d_b_heterogeneous_match_comparison,
    run_phase5d_b_match_comparison,
    run_root_info_uct_stability,
)
from .phase5e_evaluation import (
    run_phase5e_heterogeneous_match_comparison,
    run_phase5e_match_comparison,
    run_phase5e_behavior_comparison,
    run_multi_observer_stability,
)
from .registry import (
    PRIMARY_PROFILE_KEY,
    REGISTERED_CONFIGURATIONS,
    build_agent,
    phase5d_a_registry_snapshot,
    registry_snapshot,
)
from .root_info_uct_registry import (
    ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
    registry_snapshot as root_info_uct_registry_snapshot,
    build_agent as build_root_info_uct_agent,
)
from .multi_observer_registry import (
    MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
    build_agent as build_multi_observer_agent,
    registry_snapshot as multi_observer_registry_snapshot,
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

    diag_agents = subparsers.add_parser(
        "diagnostic-agents", help="list the Phase 5D-A diagnostic agents"
    )
    diag_agents.add_argument("--output")

    b_agents = subparsers.add_parser(
        "b-agents", help="list registered Phase 5D-B root-information UCT agents"
    )
    b_agents.add_argument("--output")

    b_explain = subparsers.add_parser(
        "b-explain", help="explain one Phase 5D-B decision from an explicit deal"
    )
    b_explain.add_argument("--deal-file", required=True)
    b_explain.add_argument("--profile", default=ROOT_INFO_UCT_PRIMARY_PROFILE_KEY)
    b_explain.add_argument("--seat", type=int, required=True)
    b_explain.add_argument("--tricks", type=int, default=0)
    b_explain.add_argument("--output")

    b_compare = subparsers.add_parser(
        "b-compare", help="Phase 5D-B complete-match development comparison"
    )
    b_compare.add_argument("--candidate", default=ROOT_INFO_UCT_PRIMARY_PROFILE_KEY)
    b_compare.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    b_compare.add_argument("--pairs", type=int, required=True)
    b_compare.add_argument("--safety-cap", type=int, default=704)
    b_compare.add_argument("--workers", type=int)
    b_compare.add_argument("--output", required=True)

    b_hetero = subparsers.add_parser(
        "b-heterogeneous", help="Phase 5D-B seat-balanced heterogeneous comparison"
    )
    b_hetero.add_argument("--search", default=ROOT_INFO_UCT_PRIMARY_PROFILE_KEY)
    b_hetero.add_argument("--partner", default=DEVELOPMENT_REFERENCE_POLICY)
    b_hetero.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    b_hetero.add_argument("--pairs", type=int, required=True)
    b_hetero.add_argument("--safety-cap", type=int, default=704)
    b_hetero.add_argument("--workers", type=int)
    b_hetero.add_argument("--output", required=True)

    b_stability = subparsers.add_parser(
        "b-stability", help="nested-budget root-information UCT stability"
    )
    b_stability.add_argument("--corpus", required=True)
    b_stability.add_argument("--budgets", default="2,4,8")
    b_stability.add_argument("--showing-limit", type=int)
    b_stability.add_argument("--trick-play-limit", type=int)
    b_stability.add_argument("--output", required=True)

    b_behavior = subparsers.add_parser(
        "b-behavior", help="same-observation reference/PIMC/root-UCT action comparison"
    )
    b_behavior.add_argument("--corpus", required=True)
    b_behavior.add_argument("--profile", default=ROOT_INFO_UCT_PRIMARY_PROFILE_KEY)
    b_behavior.add_argument("--showing-limit", type=int)
    b_behavior.add_argument("--trick-play-limit", type=int)
    b_behavior.add_argument("--output", required=True)

    e_agents = subparsers.add_parser(
        "e-agents", help="list registered Phase 5E multi-observer agents"
    )
    e_agents.add_argument("--output")

    e_explain = subparsers.add_parser(
        "e-explain", help="explain one Phase 5E multi-observer decision"
    )
    e_explain.add_argument("--deal-file", required=True)
    e_explain.add_argument("--profile", default=MULTI_OBSERVER_PRIMARY_PROFILE_KEY)
    e_explain.add_argument("--seat", type=int, required=True)
    e_explain.add_argument("--tricks", type=int, default=0)
    e_explain.add_argument("--output")

    e_compare = subparsers.add_parser(
        "e-compare", help="Phase 5E complete-match development comparison"
    )
    e_compare.add_argument("--candidate", default=MULTI_OBSERVER_PRIMARY_PROFILE_KEY)
    e_compare.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    e_compare.add_argument("--pairs", type=int, required=True)
    e_compare.add_argument("--safety-cap", type=int, default=704)
    e_compare.add_argument("--workers", type=int)
    e_compare.add_argument("--output", required=True)

    e_hetero = subparsers.add_parser(
        "e-heterogeneous", help="Phase 5E seat-balanced heterogeneous comparison"
    )
    e_hetero.add_argument("--search", default=MULTI_OBSERVER_PRIMARY_PROFILE_KEY)
    e_hetero.add_argument("--partner", default=DEVELOPMENT_REFERENCE_POLICY)
    e_hetero.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    e_hetero.add_argument("--pairs", type=int, required=True)
    e_hetero.add_argument("--safety-cap", type=int, default=704)
    e_hetero.add_argument("--workers", type=int)
    e_hetero.add_argument("--output", required=True)

    e_stability = subparsers.add_parser(
        "e-stability", help="nested-budget Phase 5E action stability"
    )
    e_stability.add_argument("--corpus", required=True)
    e_stability.add_argument("--budgets", default="2,8,32")
    e_stability.add_argument("--showing-limit", type=int)
    e_stability.add_argument("--trick-play-limit", type=int)
    e_stability.add_argument("--output", required=True)

    e_behavior = subparsers.add_parser(
        "e-behavior", help="Phase 5E/reference/root-UCT behavior comparison"
    )
    e_behavior.add_argument("--corpus", required=True)
    e_behavior.add_argument("--showing-limit", type=int)
    e_behavior.add_argument("--trick-play-limit", type=int)
    e_behavior.add_argument("--output", required=True)

    d_compare = subparsers.add_parser(
        "d-compare",
        help="Phase 5D-A homogeneous complete-match comparison on a fresh bank",
    )
    d_compare.add_argument("--candidate", required=True)
    d_compare.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    d_compare.add_argument("--pairs", type=int, required=True)
    d_compare.add_argument("--safety-cap", type=int, default=704)
    d_compare.add_argument("--workers", type=int)
    d_compare.add_argument("--output", required=True)

    d_hetero = subparsers.add_parser(
        "d-heterogeneous",
        help="Phase 5D-A seat-balanced heterogeneous complete-match comparison",
    )
    d_hetero.add_argument("--search", required=True)
    d_hetero.add_argument("--partner", default=DEVELOPMENT_REFERENCE_POLICY)
    d_hetero.add_argument("--opponent", default=DEVELOPMENT_REFERENCE_POLICY)
    d_hetero.add_argument("--pairs", type=int, required=True)
    d_hetero.add_argument("--safety-cap", type=int, default=704)
    d_hetero.add_argument("--workers", type=int)
    d_hetero.add_argument("--output", required=True)

    corpus_cmd = subparsers.add_parser(
        "corpus", help="build and summarize the frozen Phase 5D-A decision corpus"
    )
    corpus_cmd.add_argument("--showing", type=int, default=256)
    corpus_cmd.add_argument("--trick-play", type=int, default=512)
    corpus_cmd.add_argument("--streams", type=int, default=96)
    corpus_cmd.add_argument("--workers", type=int)
    corpus_cmd.add_argument("--output", required=True)

    converge = subparsers.add_parser(
        "converge", help="nested-budget convergence over the decision corpus"
    )
    converge.add_argument("--showing", type=int, default=64)
    converge.add_argument("--trick-play", type=int, default=128)
    converge.add_argument("--streams", type=int, default=48)
    converge.add_argument("--showing-limit", type=int, default=32)
    converge.add_argument("--trick-play-limit", type=int, default=48)
    converge.add_argument(
        "--budgets", default="2,4,8,16,32", help="ascending, comma separated"
    )
    converge.add_argument(
        "--workers",
        type=int,
        help="worker processes; affects wall-clock time only, never a result",
    )
    converge.add_argument(
        "--corpus",
        help="reload a corpus artifact produced by the corpus subcommand",
    )
    converge.add_argument("--output", required=True)

    decompose = subparsers.add_parser(
        "decompose", help="showing, card-play, and rollout-mismatch decomposition"
    )
    decompose.add_argument(
        "--corpus",
        help="reload a corpus artifact produced by the corpus subcommand",
    )
    decompose.add_argument("--showing", type=int, default=192)
    decompose.add_argument("--trick-play", type=int, default=384)
    decompose.add_argument("--streams", type=int, default=96)
    decompose.add_argument("--mismatch-positions", type=int, default=24)
    decompose.add_argument("--workers", type=int)
    decompose.add_argument("--output", required=True)

    d_screen = subparsers.add_parser(
        "d-screen", help="Phase 5D-A deal-level duplicate screen on a fresh bank"
    )
    d_screen.add_argument("--candidate", required=True)
    d_screen.add_argument("--opponent", required=True)
    d_screen.add_argument("--deals", type=int, default=12)
    d_screen.add_argument("--output", required=True)

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


def _diagnostic_agents(args) -> int:
    snapshot = phase5d_a_registry_snapshot()
    _write(args.output, snapshot)
    if not args.output:
        for entry in snapshot["agents"]:
            print(f"{entry['profile_key']:44s} {entry['agent_id']}")
        baseline = snapshot["negative_baseline"]
        print(f"negative baseline: {baseline['designation']}")
        print(f"  agent (unchanged): {baseline['agent_id']}")
        print(f"phase5c digest unchanged: {snapshot['phase5c_registry_digest_unchanged']}")
    return 0


def _b_agents(args) -> int:
    snapshot = root_info_uct_registry_snapshot()
    _write(args.output, snapshot)
    if not args.output:
        for entry in snapshot["agents"]:
            print(f"{entry['profile_key']:44s} {entry['agent_id']}")
        print(f"primary: {snapshot['primary_profile_key']}")
    return 0


def _b_explain(args) -> int:
    state = _advance(args.deal_file, args.tricks)
    if args.seat not in range(4):
        raise SearchError("--seat must be an integer in 0..3")
    observation = observation_for(state, args.seat)
    if observation.current_actor != args.seat:
        raise SearchError(
            f"seat {args.seat} is not the acting seat at this position; the actor "
            f"is {observation.current_actor}"
        )
    agent = build_root_info_uct_agent(args.profile, seat=args.seat)
    started = time.perf_counter()
    payload = agent.explain(observation).to_data()
    payload["operational_timing"] = {
        "decision_seconds": round(time.perf_counter() - started, 6),
        "note": "operational only; no decision depends on timing",
    }
    _write(args.output, payload)
    if not args.output:
        print(
            f"seat {payload['root_seat']} team {payload['root_team']} "
            f"phase {payload['phase']} selected {payload['selected_action']}"
        )
    return 0


def _b_compare(args) -> int:
    report = run_phase5d_b_match_comparison(
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
        f"outcomes={inference['pair_outcomes']}"
    )
    print(args.output)
    return 0


def _b_heterogeneous(args) -> int:
    report = run_phase5d_b_heterogeneous_match_comparison(
        search_profile_key=args.search,
        partner_profile_key=args.partner,
        opponent_profile_key=args.opponent,
        pairs=args.pairs,
        safety_cap=args.safety_cap,
        workers=args.workers,
        progress=_progress(time.perf_counter(), "pair"),
    )
    atomic_write_canonical_json(args.output, report)
    for entry in report["arrangements"]:
        inference = entry["primary_match_inference"]
        print(
            f"arrangement {entry['arrangement']}: "
            f"p_win={inference['candidate_match_win_probability']} "
            f"outcomes={inference['pair_outcomes']}"
        )
    print(args.output)
    return 0


def _b_stability(args) -> int:
    from .corpus import DecisionCorpus

    corpus = DecisionCorpus.from_data(strict_json_load_file(args.corpus))
    budgets = tuple(int(part) for part in args.budgets.split(","))
    report = run_root_info_uct_stability(
        corpus,
        budgets=budgets,
        showing_limit=args.showing_limit,
        trick_play_limit=args.trick_play_limit,
    )
    atomic_write_canonical_json(args.output, report)
    for entry in report["adjacent_action_agreement"]:
        print(
            f"{entry['from_budget']:3d} -> {entry['to_budget']:3d}: "
            f"agreement {entry['agreement_rate']:.3f}"
        )
    print(args.output)
    return 0


def _b_behavior(args) -> int:
    from .corpus import DecisionCorpus

    corpus = DecisionCorpus.from_data(strict_json_load_file(args.corpus))
    report = run_root_info_uct_behavior_comparison(
        corpus,
        profile_key=args.profile,
        showing_limit=args.showing_limit,
        trick_play_limit=args.trick_play_limit,
    )
    atomic_write_canonical_json(args.output, report)
    print(report["categories"])
    print(args.output)
    return 0


def _e_agents(args) -> int:
    snapshot = multi_observer_registry_snapshot()
    _write(args.output, snapshot)
    if not args.output:
        for entry in snapshot["agents"]:
            print(f"{entry['profile_key']:44s} {entry['agent_id']}")
        print(f"primary: {snapshot['primary_profile_key']}")
    return 0


def _e_explain(args) -> int:
    state = _advance(args.deal_file, args.tricks)
    if args.seat not in range(4):
        raise SearchError("--seat must be an integer in 0..3")
    observation = observation_for(state, args.seat)
    if observation.current_actor != args.seat:
        raise SearchError(
            f"seat {args.seat} is not the acting seat at this position; the actor "
            f"is {observation.current_actor}"
        )
    started = time.perf_counter()
    payload = build_multi_observer_agent(args.profile, seat=args.seat).explain(observation).to_data()
    payload["operational_timing"] = {
        "decision_seconds": round(time.perf_counter() - started, 6),
        "note": "operational only; no decision depends on timing",
    }
    _write(args.output, payload)
    if not args.output:
        print(
            f"seat {payload['root_seat']} team {payload['root_team']} "
            f"phase {payload['phase']} selected {payload['selected_action']}"
        )
    return 0


def _e_compare(args) -> int:
    report = run_phase5e_match_comparison(
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
        f"outcomes={inference['pair_outcomes']}"
    )
    print(args.output)
    return 0


def _e_heterogeneous(args) -> int:
    report = run_phase5e_heterogeneous_match_comparison(
        search_profile_key=args.search,
        partner_profile_key=args.partner,
        opponent_profile_key=args.opponent,
        pairs=args.pairs,
        safety_cap=args.safety_cap,
        workers=args.workers,
        progress=_progress(time.perf_counter(), "pair"),
    )
    atomic_write_canonical_json(args.output, report)
    for entry in report["arrangements"]:
        inference = entry["primary_match_inference"]
        print(
            f"arrangement {entry['arrangement']}: "
            f"p_win={inference['candidate_match_win_probability']} "
            f"outcomes={inference['pair_outcomes']}"
        )
    print(args.output)
    return 0


def _e_stability(args) -> int:
    from .corpus import DecisionCorpus

    corpus = DecisionCorpus.from_data(strict_json_load_file(args.corpus))
    budgets = tuple(int(part) for part in args.budgets.split(","))
    report = run_multi_observer_stability(
        corpus,
        budgets=budgets,
        showing_limit=args.showing_limit,
        trick_play_limit=args.trick_play_limit,
    )
    atomic_write_canonical_json(args.output, report)
    for entry in report["adjacent_action_agreement"]:
        print(
            f"{entry['from_budget']:3d} -> {entry['to_budget']:3d}: "
            f"agreement {entry['agreement_rate']:.3f}"
        )
    print(args.output)
    return 0


def _e_behavior(args) -> int:
    from .corpus import DecisionCorpus

    corpus = DecisionCorpus.from_data(strict_json_load_file(args.corpus))
    report = run_phase5e_behavior_comparison(
        corpus,
        showing_limit=args.showing_limit,
        trick_play_limit=args.trick_play_limit,
    )
    atomic_write_canonical_json(args.output, report)
    print(report["categories"])
    print(args.output)
    return 0


def _d_compare(args) -> int:
    report = run_phase5d_a_match_comparison(
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
        f"outcomes={inference['pair_outcomes']} "
        f"p={inference['sign_flip_p_value']:.4f}"
    )
    print(args.output)
    return 0


def _d_heterogeneous(args) -> int:
    report = run_heterogeneous_match_comparison(
        search_profile_key=args.search,
        partner_profile_key=args.partner,
        opponent_profile_key=args.opponent,
        pairs=args.pairs,
        safety_cap=args.safety_cap,
        workers=args.workers,
        progress=_progress(time.perf_counter(), "pair"),
    )
    atomic_write_canonical_json(args.output, report)
    for entry in report["arrangements"]:
        inference = entry["primary_match_inference"]
        print(
            f"arrangement {entry['arrangement']} "
            f"({entry['arrangement_meaning']}): "
            f"p_win={inference['candidate_match_win_probability']} "
            f"outcomes={inference['pair_outcomes']}"
        )
    print(args.output)
    return 0


def _build_corpus(args):
    from .corpus import DecisionCorpus

    corpus_path = getattr(args, "corpus", None)
    if corpus_path:
        return DecisionCorpus.from_data(strict_json_load_file(corpus_path))

    from .corpus import build_corpus

    return build_corpus(
        showing_target=args.showing,
        trick_play_target=args.trick_play,
        streams=args.streams,
        workers=getattr(args, "workers", None),
        progress=_progress(time.perf_counter(), "deal"),
    )


def _corpus(args) -> int:
    corpus = _build_corpus(args)
    payload = corpus.to_data()
    payload["positions"] = [item.to_data() for item in corpus.positions]
    atomic_write_canonical_json(args.output, payload)
    print(
        f"corpus {corpus.corpus_id}: {payload['showing_positions']} showing, "
        f"{payload['trick_play_positions']} trick play"
    )
    disagree = sum(
        1 for item in corpus.positions if item.pimc_disagrees_with_reference
    )
    print(f"PIMC disagrees with the reference at {disagree}/{len(corpus)} positions")
    print(args.output)
    return 0


def _converge(args) -> int:
    from .convergence import run_convergence

    budgets = tuple(int(part) for part in args.budgets.split(","))
    corpus = _build_corpus(args)
    report = run_convergence(
        corpus,
        budgets=budgets,
        showing_limit=args.showing_limit,
        trick_play_limit=args.trick_play_limit,
        workers=args.workers,
        progress=_progress(time.perf_counter(), "position"),
    )
    report["corpus"] = corpus.to_data()
    atomic_write_canonical_json(args.output, report)
    for entry in report["adjacent_agreement"]:
        print(
            f"{entry['from_worlds']:3d} -> {entry['to_worlds']:3d} worlds: "
            f"agreement {entry['agreement_rate']:.3f} "
            f"({entry['agreements']}/{entry['comparisons']})"
        )
    for entry in report["declaration_shift"]:
        if entry["rami_declaration_rate"] is not None:
            print(
                f"  {entry['world_count']:3d} worlds: RAMI rate "
                f"{entry['rami_declaration_rate']:.3f} "
                f"({entry['showing_decisions']} showing decisions)"
            )
    print(args.output)
    return 0


def _decompose(args) -> int:
    from .decomposition import (
        card_play_decomposition,
        rollout_mismatch,
        showing_decomposition,
    )

    corpus = _build_corpus(args)
    report = {
        "card_play": card_play_decomposition(corpus, workers=args.workers),
        "corpus": corpus.to_data(),
        "rollout_mismatch": rollout_mismatch(
            corpus,
            positions_limit=args.mismatch_positions,
            workers=args.workers,
            progress=_progress(time.perf_counter(), "position"),
        ),
        "schema_version": "tuppi.search.phase5d_a_decomposition.v1",
        "showing": showing_decomposition(corpus, workers=args.workers),
    }
    atomic_write_canonical_json(args.output, report)
    show = report["showing"]
    print(
        f"showing: PIMC RAMI {show['pimc_rami_declaration_rate']:.3f} vs reference "
        f"{show['reference_rami_declaration_rate']:.3f} "
        f"(difference {show['rami_rate_difference']:+.3f})"
    )
    for key, value in sorted(show["classification_rates"].items()):
        print(f"  {key:34s} {value:.3f}")
    print(f"card play: disagreement rate {report['card_play']['disagreement_rate']:.3f}")
    for kind, stats in sorted(report["rollout_mismatch"]["by_partner_kind"].items()):
        print(
            f"  mismatch {kind:20s} matched fraction "
            f"{stats['mean_matched_fraction']:.3f} "
            f"diverged {stats['diverged_positions']}/{stats['positions']}"
        )
    print(args.output)
    return 0


def _d_screen(args) -> int:
    report = run_phase5d_a_deal_screen(
        candidate_profile_key=args.candidate,
        opponent_profile_key=args.opponent,
        deals=args.deals,
        progress=_progress(time.perf_counter(), "deal pair"),
    )
    atomic_write_canonical_json(args.output, report)
    print(
        f"{report['candidate_profile_key']} vs {report['opponent_profile_key']}: "
        f"mean paired utility {report['mean_paired_utility']:+.6f} "
        f"(se {report['standard_error_paired_utility']:.6f}), "
        f"ahead/tied/behind {report['pairs_candidate_ahead']}/"
        f"{report['pairs_tied']}/{report['pairs_candidate_behind']}"
    )
    print(args.output)
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
        "b-agents": _b_agents,
        "b-behavior": _b_behavior,
        "b-compare": _b_compare,
        "b-explain": _b_explain,
        "b-heterogeneous": _b_heterogeneous,
        "b-stability": _b_stability,
        "benchmark": _benchmark,
        "compare": _compare,
        "explain": _explain,
        "converge": _converge,
        "corpus": _corpus,
        "d-compare": _d_compare,
        "decompose": _decompose,
        "d-heterogeneous": _d_heterogeneous,
        "d-screen": _d_screen,
        "diagnostic-agents": _diagnostic_agents,
        "e-agents": _e_agents,
        "e-behavior": _e_behavior,
        "e-compare": _e_compare,
        "e-explain": _e_explain,
        "e-heterogeneous": _e_heterogeneous,
        "e-stability": _e_stability,
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
