"""Finite noninteractive CLI for deal banks, comparisons, summaries, and cross-play."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import platform
import sys

from tuppi_rules import MatchScore, RulesError

from .arena import run_evaluation, summarize_run_directory
from .config import evaluation_config_from_data
from .crossplay import run_crossplay
from .deals import (
    DealerPolicy,
    generate_deal_bank,
    load_deal_bank,
    save_deal_bank,
)
from .errors import EvaluationError, EvaluationSerializationError
from .schedules import build_canonical_schedule
from .serialization import (
    require_exact_keys,
    require_object,
    strict_json_load_file,
)


def _seed(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        if not value:
            raise argparse.ArgumentTypeError("seed must be nonempty")
        return value


def _score(value: str) -> MatchScore:
    pieces = value.split("-")
    if len(pieces) != 2:
        raise argparse.ArgumentTypeError("score must use TEAM0-TEAM1 syntax")
    try:
        return MatchScore(int(pieces[0]), int(pieces[1]))
    except (RulesError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"invalid score: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic duplicate-deal evaluation for Tuppi"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate-deals", help="create a deal bank")
    generate.add_argument("--count", type=int, required=True)
    generate.add_argument("--seed", type=_seed, required=True)
    generate.add_argument(
        "--dealer-policy",
        choices=tuple(item.value for item in DealerPolicy),
        required=True,
    )
    generate.add_argument("--initial-dealer", type=int, required=True)
    generate.add_argument("--starting-score", type=_score, required=True)
    generate.add_argument("--output", required=True)

    compare = subparsers.add_parser("compare", help="run or resume a comparison")
    compare.add_argument("--config", required=True)
    compare.add_argument("--deal-bank", required=True)
    compare.add_argument("--output-dir", required=True)
    compare.add_argument("--max-new-games", type=int)

    summarize = subparsers.add_parser("summarize", help="rebuild a run summary")
    summarize.add_argument("--run-dir", required=True)

    crossplay = subparsers.add_parser("crossplay", help="run baseline cross-play")
    crossplay.add_argument("--config", required=True)
    crossplay.add_argument("--deal-bank", required=True)
    crossplay.add_argument("--output-dir", required=True)
    return parser


def _generate(args: argparse.Namespace) -> int:
    bank = generate_deal_bank(
        count=args.count,
        root_seed=args.seed,
        dealer_policy=DealerPolicy(args.dealer_policy),
        initial_dealer=args.initial_dealer,
        starting_score=args.starting_score,
        creation_metadata={
            "created_at": datetime.now(timezone.utc).isoformat(),
            "creator": "tuppi_eval.runner.generate-deals",
            "platform": platform.platform(),
            "python_version": sys.version,
        },
    )
    save_deal_bank(args.output, bank)
    print(bank.deal_bank_id)
    return 0


def _compare(args: argparse.Namespace) -> int:
    config = evaluation_config_from_data(strict_json_load_file(args.config))
    bank = load_deal_bank(args.deal_bank, expected_ruleset_id=config.ruleset_id)
    schedule = build_canonical_schedule(
        deal_bank=bank,
        team_a=config.team_a,
        team_b=config.team_b,
        mode=config.evaluation_mode,
        match_sequence_length=config.match_sequence_length,
    )
    arena = run_evaluation(
        config,
        bank,
        schedule,
        output_directory=args.output_dir,
        max_new_games=args.max_new_games,
    )
    print(arena.result.result_id)
    return 0


def _summarize(args: argparse.Namespace) -> int:
    result = summarize_run_directory(args.run_dir)
    print(result.result_id)
    return 0


def _crossplay(args: argparse.Namespace) -> int:
    request = require_object(strict_json_load_file(args.config), "cross-play request")
    require_exact_keys(
        request,
        {"comparisons", "deal_bank_id", "include_missing", "schema_version"},
        "cross-play request",
    )
    if request["schema_version"] != "tuppi.eval.crossplay_request.v1":
        raise EvaluationSerializationError("unsupported cross-play request schema")
    raw_comparisons = request["comparisons"]
    if type(raw_comparisons) is not list or not raw_comparisons:
        raise EvaluationSerializationError("comparisons must be a nonempty array")
    if type(request["include_missing"]) is not bool:
        raise EvaluationSerializationError("include_missing must be boolean")
    configurations = tuple(
        evaluation_config_from_data(item) for item in raw_comparisons
    )
    bank = load_deal_bank(args.deal_bank)
    if bank.deal_bank_id != request["deal_bank_id"]:
        raise EvaluationSerializationError("cross-play deal-bank ID mismatch")
    matrix = run_crossplay(
        configurations,
        bank,
        output_directory=args.output_dir,
        include_missing=request["include_missing"],
    )
    print(matrix.matrix_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-deals":
            return _generate(args)
        if args.command == "compare":
            return _compare(args)
        if args.command == "summarize":
            return _summarize(args)
        if args.command == "crossplay":
            return _crossplay(args)
        raise EvaluationSerializationError("unknown command")
    except EvaluationError as exc:
        print(f"tuppi-eval: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
