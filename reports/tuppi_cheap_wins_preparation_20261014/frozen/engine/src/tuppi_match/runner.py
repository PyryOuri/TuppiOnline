"""Finite noninteractive CLI for the complete-match protocol.

Every subcommand is deterministic, reads only explicit inputs, writes only
canonical JSON, and never opens stdin, a GUI, a socket, or a random source.

Large outputs belong outside a cloud-synced directory. Pass ``--output-dir``
under local scratch storage; see ``docs/match/complete_match_protocol.md``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

from tuppi_engine import atomic_write_canonical_json

from .banks import (
    BankRole,
    StreamBank,
    open_sealed_bank,
    sealed_commitment,
    write_sealed_seed,
)
from .calibration import (
    calibrate_safety_cap,
    calibration_bank,
    development_bank,
    diagnostic_bank,
    ladder_comparisons,
)
from .diagnostics import score_state_comparisons, summarize_score_states
from .errors import MatchProtocolError
from .experiment import build_report, load_pairs, run
from .freeze import build_snapshot, verify_snapshot
from .manifest import DEFAULT_SAFETY_CAP, MatchManifest
from .statistics import length_distribution


ENGINE_IDENTITY = "tuppi_engine:v1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Complete-match duplicate evaluation for project_target_v1"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser(
        "freeze", help="write or verify the Phase 4 baseline snapshot"
    )
    freeze.add_argument("--output")
    freeze.add_argument("--verify")

    plan = subparsers.add_parser("plan", help="write a resolved match manifest")
    plan.add_argument(
        "--design", choices=("calibration", "development", "diagnostics"), required=True
    )
    plan.add_argument("--pairs", type=int, required=True)
    plan.add_argument("--safety-cap", type=int, default=DEFAULT_SAFETY_CAP)
    plan.add_argument("--output", required=True)
    plan.add_argument("--candidate", default="match_aware_v1")
    plan.add_argument("--opponent", default="match_aware_no_match_features_v1")

    execute = subparsers.add_parser("run", help="execute a design and store artifacts")
    execute.add_argument(
        "--design", choices=("calibration", "development", "diagnostics"), required=True
    )
    execute.add_argument("--pairs", type=int, required=True)
    execute.add_argument("--safety-cap", type=int, default=DEFAULT_SAFETY_CAP)
    execute.add_argument("--output-dir", required=True)
    execute.add_argument("--workers", type=int)
    execute.add_argument("--candidate", default="match_aware_v1")
    execute.add_argument("--opponent", default="match_aware_no_match_features_v1")

    report = subparsers.add_parser(
        "report", help="rebuild a report from stored pairs without running"
    )
    report.add_argument(
        "--design", choices=("calibration", "development", "diagnostics"), required=True
    )
    report.add_argument("--pairs", type=int, required=True)
    report.add_argument("--safety-cap", type=int, default=DEFAULT_SAFETY_CAP)
    report.add_argument("--output-dir", required=True)
    report.add_argument("--output", required=True)
    report.add_argument("--candidate", default="match_aware_v1")
    report.add_argument("--opponent", default="match_aware_no_match_features_v1")

    cap = subparsers.add_parser(
        "calibrate-cap", help="derive a safety cap from stored match lengths"
    )
    cap.add_argument("--report", required=True)
    cap.add_argument("--output")

    seal = subparsers.add_parser("seal", help="create or open the sealed bank")
    seal.add_argument("--action", choices=("create", "open"), required=True)
    seal.add_argument("--seed-file", required=True)
    seal.add_argument("--seed")
    seal.add_argument("--streams", type=int, default=512)
    seal.add_argument("--reason")
    seal.add_argument("--output", required=True)
    return parser


def _design(args) -> tuple[StreamBank, tuple]:
    if args.design == "calibration":
        bank = calibration_bank(stream_count=max(args.pairs, 1))
        return bank, ladder_comparisons()
    if args.design == "development":
        bank = development_bank(stream_count=max(args.pairs, 1))
        return bank, ladder_comparisons(result_class="development")
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    bank = diagnostic_bank(stream_count=max(args.pairs, 1))
    return bank, score_state_comparisons(
        candidate_profile_key=args.candidate,
        opponent_profile_key=args.opponent,
        candidate_agent_id=specifications[args.candidate].agent_id,
        opponent_agent_id=specifications[args.opponent].agent_id,
    )


def _manifest(args) -> MatchManifest:
    from tuppi_agents import AGENTS_VERSION

    bank, comparisons = _design(args)
    return MatchManifest.build(
        name=f"phase5a_{args.design}",
        bank=bank,
        comparisons=comparisons,
        pair_count=args.pairs,
        engine_identity=ENGINE_IDENTITY,
        agents_version=AGENTS_VERSION,
        safety_cap=args.safety_cap,
        software_environment={"design": args.design, "phase": "phase5a"},
    )


def _freeze(args) -> int:
    if args.verify:
        from tuppi_engine import strict_json_load_file

        problems = verify_snapshot(strict_json_load_file(args.verify))
        if problems:
            for item in problems:
                print(f"DRIFT: {item}", file=sys.stderr)
            return 3
        print("frozen Phase 4 agents are unchanged")
        return 0
    snapshot = build_snapshot()
    if args.output:
        atomic_write_canonical_json(args.output, snapshot)
        print(args.output)
    else:
        print(snapshot["snapshot_digest"])
    return 0


def _plan(args) -> int:
    manifest = _manifest(args)
    atomic_write_canonical_json(args.output, manifest.to_data())
    print(manifest.manifest_id)
    return 0


def _progress(started: float):
    def report(done: int, total: int) -> None:
        if done % 8 == 0 or done == total:
            elapsed = time.perf_counter() - started
            rate = done / elapsed if elapsed > 0 else 0.0
            remaining = (total - done) / rate if rate > 0 else float("inf")
            print(
                f"  {done}/{total} pairs  {elapsed / 60:.1f} min elapsed  "
                f"~{remaining / 60:.1f} min remaining",
                file=sys.stderr,
                flush=True,
            )

    return report


def _run(args) -> int:
    manifest = _manifest(args)
    print(f"manifest {manifest.manifest_id}", file=sys.stderr)
    print(f"bank role {manifest.role.value}", file=sys.stderr)
    result = run(
        manifest,
        output_directory=args.output_dir,
        workers=args.workers,
        progress=_progress(time.perf_counter()),
    )
    for comparison in result.report["comparisons"]:
        inference = comparison["primary_match_inference"]
        print(
            f"{comparison['name']}: pairs={inference['complete_pair_count']} "
            f"p_win={inference['candidate_match_win_probability']} "
            f"censored={inference['censored_pair_count']}"
        )
    return 0


def _report(args) -> int:
    manifest = _manifest(args)
    directory = Path(args.output_dir)
    pairs = load_pairs(directory, manifest)
    snapshot = build_snapshot()
    report = build_report(manifest, pairs, snapshot)
    report["score_state_summary"] = summarize_score_states(report)
    atomic_write_canonical_json(args.output, report)
    print(args.output)
    return 0


def _calibrate_cap(args) -> int:
    from tuppi_engine import strict_json_load_file

    report = strict_json_load_file(args.report)
    lengths: list[int] = []
    for comparison in report.get("comparisons", []):
        distribution = comparison["secondary_metrics"].get("deals_per_match")
        if distribution and distribution.get("maximum") is not None:
            lengths.extend([int(distribution["maximum"])] * 1)
            lengths.extend([int(distribution["median"])] * 1)
    if not lengths:
        raise MatchProtocolError("the report contains no match-length data")
    result = calibrate_safety_cap(lengths)
    if args.output:
        atomic_write_canonical_json(args.output, result)
        print(args.output)
    else:
        print(result["proposed_safety_cap"])
    return 0


def _seal(args) -> int:
    if args.action == "create":
        if not args.seed:
            raise MatchProtocolError("creating a sealed bank requires --seed")
        location = write_sealed_seed(args.seed_file, seed=args.seed)
        bank = StreamBank.build(
            name="phase5a_promotion_sealed_v1",
            role=BankRole.PROMOTION_SEALED,
            root_seed=args.seed,
            initial_dealer=0,
            stream_count=args.streams,
            purpose=(
                "Promotion-sealed complete-match fixtures. Generated after the "
                "Phase 4 agents and the Phase 5A protocol were frozen."
            ),
        )
        commitment = sealed_commitment(bank, streams=min(args.streams, 64))
        commitment["seed_digest"] = location["seed_digest"]
        atomic_write_canonical_json(args.output, commitment)
        print(f"seed written outside the repository: {location['path']}")
        print(args.output)
        return 0
    if not args.reason:
        raise MatchProtocolError("opening a sealed bank requires --reason")
    _, record = open_sealed_bank(
        name="phase5a_promotion_sealed_v1",
        stream_count=args.streams,
        initial_dealer=0,
        purpose="Promotion-sealed complete-match fixtures.",
        reason=args.reason,
        seed_path=args.seed_file,
    )
    atomic_write_canonical_json(args.output, record)
    print(args.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "calibrate-cap": _calibrate_cap,
        "freeze": _freeze,
        "plan": _plan,
        "report": _report,
        "run": _run,
        "seal": _seal,
    }
    try:
        return handlers[args.command](args)
    except MatchProtocolError as exc:
        print(f"tuppi-match: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
