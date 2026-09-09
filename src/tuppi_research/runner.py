"""`python -m tuppi_research.runner` - run, resume and report one control cycle.

Deliberately not registered as a console script: adding one edits
``pyproject.toml``, which currently carries unrelated uncommitted work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .cycle import (
    DEFAULT_BASE_DEALS,
    CycleReport,
    analyse,
    build_candidate_inputs,
    build_inputs,
    candidate_declaration,
    determinism_check,
    execute_cycle,
    noop_parity_check,
    null_control_zero_check,
    preflight_legality,
    record_cycle_finding,
)
from .errors import ResearchError
from .ledger import ExecutionState, Ledger


def run_null_control(
    *,
    workspace: Path,
    base_deals: int = DEFAULT_BASE_DEALS,
    max_new_games: int | None = None,
    reviewed_by: str = "unreviewed",
    with_determinism_check: bool = False,
) -> CycleReport:
    """The whole loop, in order, with every step recorded before the next."""

    workspace = Path(workspace)
    output = workspace / "evaluation"
    inputs = build_inputs(base_deals=base_deals)
    with Ledger(workspace / "research.sqlite3") as ledger:
        experiment_id, run_id, state = None, None, None
        legality = preflight_legality(inputs)
        parity = noop_parity_check()
        experiment_id, run_id, state = execute_cycle(
            ledger, inputs, output_directory=output, max_new_games=max_new_games
        )
        ledger.record_control_check(
            run_id=run_id, name="preflight_legality", passed=True,
            detail=json.dumps(legality, sort_keys=True),
        )
        ledger.record_control_check(
            run_id=run_id, name="noop_delegation_parity", passed=True,
            detail=json.dumps(parity, sort_keys=True),
        )
        report = CycleReport(
            run_id=run_id, experiment_id=experiment_id, execution_state=state
        )
        if state is not ExecutionState.COMPLETE:
            report.control_checks = list(ledger.control_checks(run_id))
            report.blocked.append(
                f"run did not complete ({state.value}); resume before reviewing"
            )
            return report
        if with_determinism_check:
            detail = determinism_check(
                inputs, workspace / "determinism_a", workspace / "determinism_b"
            )
            ledger.record_control_check(
                run_id=run_id, name="repeat_run_determinism", passed=True,
                detail=json.dumps(detail, sort_keys=True),
            )
        analysis = analyse(inputs, output)
        zero = null_control_zero_check(analysis)
        ledger.record_control_check(
            run_id=run_id, name="null_control_exact_zero", passed=True,
            detail=json.dumps(zero, sort_keys=True),
        )
        verdict, finding_id = record_cycle_finding(
            ledger,
            experiment_id=experiment_id,
            run_id=run_id,
            analysis=analysis,
            output_directory=output,
            reviewed_by=reviewed_by,
        )
        stale = ledger.stale_artifacts(run_id, output)
        ledger.record_control_check(
            run_id=run_id, name="artifact_digests_current", passed=not stale,
            detail="all referenced artifacts match" if not stale else str(stale),
        )
        report.verdict = verdict
        report.finding_id = finding_id
        report.units = analysis["admitted_units"]
        report.summary = {
            "block_utilities": analysis["block_utilities"],
            "mean_paired_utility": analysis["statistics"]["mean_paired_utility"],
            "confidence_interval": analysis["statistics"]["confidence_interval"],
            "independent_base_deals": analysis["statistics"]["independent_base_deals"],
            "transformed_games": analysis["statistics"]["transformed_games"],
        }
        report.control_checks = list(ledger.control_checks(run_id))
        report.blocked = list(_blocked_capabilities())
        return report


def run_candidate_cycle(
    candidate_key: str,
    *,
    workspace: Path,
    base_deals: int = DEFAULT_BASE_DEALS,
    max_new_games: int | None = None,
    reviewed_by: str = "unreviewed",
) -> CycleReport:
    """The same loop for a declared research candidate against the incumbent.

    The only behavioural difference from the null control is which checks apply:
    the exact-zero identity is asserted for a pass-through candidate and not for
    one that genuinely differs. The verdict is still not the runner's to choose -
    ``review`` returns INCONCLUSIVE for any real candidate until a useful-effect
    threshold exists, and the ledger refuses ACCEPTED for a declared control.
    """

    workspace = Path(workspace)
    output = workspace / "evaluation"
    inputs = build_candidate_inputs(candidate_key, base_deals=base_deals)
    declaration = candidate_declaration(candidate_key)
    with Ledger(workspace / "research.sqlite3") as ledger:
        experiment_id, run_id, state = execute_cycle(
            ledger, inputs, output_directory=output,
            max_new_games=max_new_games, experiment=declaration,
        )
        report = CycleReport(
            run_id=run_id, experiment_id=experiment_id, execution_state=state
        )
        if state is not ExecutionState.COMPLETE:
            report.control_checks = list(ledger.control_checks(run_id))
            report.blocked.append(
                f"run did not complete ({state.value}); resume before reviewing"
            )
            return report
        analysis = analyse(inputs, output)
        if declaration.is_null_control:
            zero = null_control_zero_check(analysis)
            ledger.record_control_check(
                run_id=run_id, name="null_control_exact_zero", passed=True,
                detail=json.dumps(zero, sort_keys=True),
            )
        verdict, finding_id = record_cycle_finding(
            ledger, experiment_id=experiment_id, run_id=run_id, analysis=analysis,
            output_directory=output, reviewed_by=reviewed_by,
            is_null_control=declaration.is_null_control,
        )
        report.verdict = verdict
        report.finding_id = finding_id
        report.units = analysis["admitted_units"]
        report.summary = {
            "candidate": candidate_key,
            "candidate_id": declaration.candidate_id,
            "incumbent_id": declaration.incumbent_id,
            "is_null_control": declaration.is_null_control,
            "block_utilities": analysis["block_utilities"],
            "mean_paired_utility": analysis["statistics"]["mean_paired_utility"],
            "confidence_interval": analysis["statistics"]["confidence_interval"],
            "independent_base_deals": analysis["statistics"]["independent_base_deals"],
            "paired_permutation_p_value": analysis["statistics"][
                "paired_permutation_p_value"
            ],
        }
        report.control_checks = list(ledger.control_checks(run_id))
        report.blocked = list(_blocked_capabilities())
        return report


def _blocked_capabilities() -> tuple[str, ...]:
    """Capabilities this cycle does NOT have. Recorded, not silently implied."""

    return (
        "RESOLVED: a declared research candidate now constructs through the "
        "ordinary arena route (tuppi_agents.research_candidates + factory "
        "dispatch). Candidates must be declared, and identity is checked "
        "byte-for-byte against the declared entry.",
        "BLOCKED: no useful-effect threshold, sample-size design or opponent "
        "population is fixed, so no non-null candidate can be judged.",
        "BLOCKED: promotion requires fresh sealed confirmation and staged rules; "
        "this layer records promotion as not_performed and offers no path to it.",
        "NOT MEASURED: the ten-second production decision budget.",
    )


def _report(args: argparse.Namespace) -> int:
    with Ledger(Path(args.workspace) / "research.sqlite3") as ledger:
        run = ledger.run(args.run_id)
        payload = {
            "run": run,
            "units": [
                {
                    "block_index": unit.block_index,
                    "base_deal_id": unit.base_deal_id,
                    "execution_state": unit.execution_state.value,
                    "observed_games": unit.observed_games,
                    "paired_utility": unit.paired_utility,
                }
                for unit in ledger.units(args.run_id)
            ],
            "control_checks": ledger.control_checks(args.run_id),
            "artifacts": ledger.artifacts(args.run_id),
            "finding": ledger.finding(args.run_id),
        }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tuppi-research",
        description="One persistent control cycle. No promotion, no strength claim.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run or resume the null control cycle")
    run.add_argument("--workspace", required=True)
    run.add_argument("--base-deals", type=int, default=DEFAULT_BASE_DEALS)
    run.add_argument("--max-new-games", type=int, default=None,
                     help="stop after this many new games, to exercise resume")
    run.add_argument("--reviewed-by", default="unreviewed")
    run.add_argument("--determinism-check", action="store_true")

    candidate = sub.add_parser(
        "candidate", help="run a declared research candidate against the incumbent"
    )
    candidate.add_argument("--workspace", required=True)
    candidate.add_argument("--candidate", required=True)
    candidate.add_argument("--base-deals", type=int, default=DEFAULT_BASE_DEALS)
    candidate.add_argument("--max-new-games", type=int, default=None)
    candidate.add_argument("--reviewed-by", default="unreviewed")

    report = sub.add_parser("report", help="print one run's ledger rows")
    report.add_argument("--workspace", required=True)
    report.add_argument("--run-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "report":
        return _report(args)
    try:
        if args.command == "candidate":
            report = run_candidate_cycle(
                args.candidate,
                workspace=Path(args.workspace),
                base_deals=args.base_deals,
                max_new_games=args.max_new_games,
                reviewed_by=args.reviewed_by,
            )
            print(json.dumps(report.to_data(), indent=2, default=str))
            return 0 if report.execution_state is ExecutionState.COMPLETE else 1
        report = run_null_control(
            workspace=Path(args.workspace),
            base_deals=args.base_deals,
            max_new_games=args.max_new_games,
            reviewed_by=args.reviewed_by,
            with_determinism_check=args.determinism_check,
        )
    except ResearchError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.to_data(), indent=2, default=str))
    return 0 if report.execution_state is ExecutionState.COMPLETE else 1


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
