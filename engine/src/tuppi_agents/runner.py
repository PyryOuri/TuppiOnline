"""Finite noninteractive CLI for the Phase 4 baseline agents.

Every subcommand is deterministic, reads only explicit files, writes only
canonical JSON, and never opens stdin, a GUI, a socket, or a random source.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from tuppi_engine import (
    EnginePhase,
    action_to_data,
    atomic_write_canonical_json,
    begin_explicit_deal,
    create_match,
    match_input_from_data,
    match_observation_for,
    research_run_result_to_data,
    strict_json_load_file,
)
from tuppi_engine.runner import run_match_input

from .benchmark import run_benchmark
from .errors import AgentsError
from .evaluation import (
    ALL_COMPARISONS,
    BANK_FILES,
    build_baseline_report,
    load_report,
    read_bank,
    reusable_comparisons,
    run_comparisons,
    run_crossplay_matrix,
    write_banks,
    write_manifests,
)
from .factory import construct_agent
from .profiles import profile_catalogue_to_data, registered_profiles
from .protocol import DiagnosticsRecordingAgent
from .registry import (
    LADDER_PROFILE_KEYS,
    phase4_specifications_by_profile_key,
    phase4_team_specifications,
)
from .rule_catalogue import rule_catalogue_to_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic observation-only Tuppi baseline agents"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("agents", help="list registered agents, profiles, and teams")

    catalogue = subparsers.add_parser("catalogue", help="write the strategy-rule catalogue")
    catalogue.add_argument("--output", required=True)

    profiles = subparsers.add_parser("profiles", help="write the profile catalogue")
    profiles.add_argument("--output", required=True)

    play = subparsers.add_parser("play-deal", help="play one explicit deal or match")
    play.add_argument("--deal-file", required=True)
    play.add_argument("--profile", required=True)
    play.add_argument("--output", required=True)
    play.add_argument("--diagnostics")

    decide = subparsers.add_parser(
        "explain", help="print the first decision of an explicit deal"
    )
    decide.add_argument("--deal-file", required=True)
    decide.add_argument("--profile", required=True)
    decide.add_argument("--output", required=True)

    banks = subparsers.add_parser("write-banks", help="write the development deal banks")
    banks.add_argument("--output-dir", required=True)

    manifests = subparsers.add_parser(
        "write-manifests", help="write the immutable evaluation manifests"
    )
    manifests.add_argument("--bank-dir", required=True)
    manifests.add_argument("--output-dir", required=True)

    suite = subparsers.add_parser("run-suite", help="run the frozen Phase 4 evaluation")
    suite.add_argument("--bank-dir", required=True)
    suite.add_argument("--output-dir", required=True)
    suite.add_argument("--report", required=True)
    suite.add_argument(
        "--only",
        choices=("all", "comparisons", "crossplay", "benchmark"),
        default="all",
    )
    suite.add_argument("--benchmark-deals", type=int, default=12)
    suite.add_argument(
        "--resume-report",
        help=(
            "reuse comparison blocks from an earlier report whose manifest "
            "identity still matches"
        ),
    )
    suite.add_argument(
        "--reuse-crossplay",
        action="store_true",
        help="carry the cross-play matrix over from --resume-report",
    )

    bench = subparsers.add_parser("benchmark", help="measure latency and throughput")
    bench.add_argument("--output", required=True)
    bench.add_argument("--deals", type=int, default=12)
    return parser


def _agents(_: argparse.Namespace) -> int:
    specifications = phase4_specifications_by_profile_key()
    profiles = registered_profiles()
    print("Phase 4 strategic agents (deterministic, observation-only):")
    for key in sorted(specifications):
        profile = profiles[key]
        marker = "ladder" if key in LADDER_PROFILE_KEYS else "variant"
        print(f"  [{marker:7s}] {key}")
        print(f"      agent_id   {specifications[key].agent_id}")
        print(f"      profile_id {profile.profile_id}")
        print(f"      showing    {profile.showing_policy.value}")
        print(f"      convention {profile.partner_convention_id or 'none'}")
    print("\nRegistered partnerships:")
    for name, team in sorted(phase4_team_specifications().items()):
        print(f"  {name}: {team.team_id}")
    return 0


def _catalogue(args: argparse.Namespace) -> int:
    atomic_write_canonical_json(args.output, rule_catalogue_to_data())
    print(args.output)
    return 0


def _profiles(args: argparse.Namespace) -> int:
    atomic_write_canonical_json(args.output, profile_catalogue_to_data())
    print(args.output)
    return 0


def _load_agents(profile_key: str, *, recording: bool):
    specifications = phase4_specifications_by_profile_key()
    if profile_key not in specifications:
        raise AgentsError(f"unknown profile {profile_key!r}")
    specification = specifications[profile_key]
    built = [construct_agent(specification, seat=seat) for seat in range(4)]
    if not recording:
        return tuple(built), ()
    wrappers = tuple(DiagnosticsRecordingAgent(agent) for agent in built)
    return wrappers, wrappers


def _play_deal(args: argparse.Namespace) -> int:
    match_input = match_input_from_data(strict_json_load_file(args.deal_file))
    agents, wrappers = _load_agents(args.profile, recording=bool(args.diagnostics))
    result = run_match_input(match_input, agents)
    atomic_write_canonical_json(args.output, research_run_result_to_data(result))
    if args.diagnostics:
        atomic_write_canonical_json(
            args.diagnostics,
            {
                "decisions": [
                    record.to_data()
                    for wrapper in wrappers
                    for record in wrapper.records
                ],
                "profile_key": args.profile,
                "schema_version": "tuppi.agents.decision_diagnostics_bundle.v1",
            },
        )
    print(result.match_input_id)
    return 0


def _explain(args: argparse.Namespace) -> int:
    match_input = match_input_from_data(strict_json_load_file(args.deal_file))
    specifications = phase4_specifications_by_profile_key()
    if args.profile not in specifications:
        raise AgentsError(f"unknown profile {args.profile!r}")
    specification = specifications[args.profile]
    state = create_match(
        initial_score=match_input.initial_score,
        initial_dealer=match_input.initial_dealer,
        match_ref=match_input.match_ref,
    )
    state = begin_explicit_deal(state, match_input.deals[0])
    if state.phase not in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        raise AgentsError("the explicit deal has no first decision")
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    agent = construct_agent(specification, seat=actor)
    decision = agent.decide(observation, diagnostics=True)
    assert decision.diagnostics is not None
    atomic_write_canonical_json(args.output, decision.diagnostics.to_data())
    print(action_to_data(decision.action))
    return 0


def _write_banks(args: argparse.Namespace) -> int:
    identifiers = write_banks(args.output_dir)
    for name in sorted(identifiers):
        print(f"{BANK_FILES[name]} {identifiers[name]}")
    return 0


def _write_manifests(args: argparse.Namespace) -> int:
    for name in write_manifests(args.output_dir, args.bank_dir):
        print(name)
    return 0


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _run_suite(args: argparse.Namespace) -> int:
    bank_directory = Path(args.bank_dir)
    output = Path(args.output_dir)
    comparisons: list[dict[str, object]] = []
    crossplay = None
    performance = None
    reuse = (
        reusable_comparisons(args.resume_report) if args.resume_report else None
    )
    if args.only in ("all", "comparisons"):
        comparisons = run_comparisons(
            bank_directory=bank_directory,
            output_directory=output,
            selected=ALL_COMPARISONS,
            progress=_progress,
            reuse=reuse,
        )
    if args.reuse_crossplay:
        if not args.resume_report:
            raise AgentsError("--reuse-crossplay requires --resume-report")
        crossplay = load_report(args.resume_report).get("crossplay")
        _progress("reusing the cross-play matrix")
    elif args.only in ("all", "crossplay"):
        crossplay = run_crossplay_matrix(
            bank_directory=bank_directory,
            output_directory=output,
            progress=_progress,
        )
    if args.only in ("all", "benchmark"):
        _progress("running the performance benchmark")
        performance = run_benchmark(deal_count=args.benchmark_deals)
    identifiers = {
        name: read_bank(bank_directory, name).deal_bank_id for name in BANK_FILES
    }
    report = build_baseline_report(
        comparisons=comparisons,
        crossplay=crossplay,
        performance=performance,
        bank_identifiers=identifiers,
    )
    atomic_write_canonical_json(args.report, report)
    print(args.report)
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    atomic_write_canonical_json(args.output, run_benchmark(deal_count=args.deals))
    print(args.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "agents": _agents,
        "benchmark": _benchmark,
        "catalogue": _catalogue,
        "explain": _explain,
        "play-deal": _play_deal,
        "profiles": _profiles,
        "run-suite": _run_suite,
        "write-banks": _write_banks,
        "write-manifests": _write_manifests,
    }
    try:
        return handlers[args.command](args)
    except AgentsError as exc:
        print(f"tuppi-agents: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
