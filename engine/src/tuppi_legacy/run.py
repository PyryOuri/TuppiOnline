"""Command-line entry point for finite, reproducible legacy execution."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Sequence

from .adapter import RunnerConfig, execute_legacy_deals
from .canonical import canonical_json_line
from .deals import generate_deals, load_deals
from .errors import ConfigurationError, LegacyHarnessError
from .legacy_loader import locate_artifacts

_RANKS = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}


def parse_show_banned_ranks(value: str) -> tuple[int, ...]:
    stripped = value.strip()
    if not stripped or stripped.lower() == "none":
        return ()
    tokens = [token.strip().upper() for token in stripped.split(",")]
    if any(not token for token in tokens):
        raise ConfigurationError(
            "--show-ban contains an empty rank; use 'none' for an empty set"
        )
    ranks: list[int] = []
    for token in tokens:
        if token not in _RANKS:
            raise ConfigurationError(
                f"unknown rank {token!r} in --show-ban; expected 2..10,J,Q,K,A or 'none'"
            )
        rank = _RANKS[token]
        if rank in ranks:
            raise ConfigurationError(f"duplicate rank {token!r} in --show-ban")
        ranks.append(rank)
    return tuple(sorted(ranks))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen legacy_v9_unverified Tuppi artifact headlessly. "
            "This does not implement the target ruleset."
        )
    )
    parser.add_argument("--deals", type=int, required=True, help="finite positive deal count")
    deal_source = parser.add_mutually_exclusive_group(required=True)
    deal_source.add_argument("--deal-seed", type=int, help="seed for stable external deal generation")
    deal_source.add_argument("--deal-file", type=Path, help="validated explicit JSON deal or deal set")
    parser.add_argument(
        "--dealer",
        type=int,
        default=None,
        help="initial dealer 0..3 for generated deals only (default: 0)",
    )
    parser.add_argument("--legacy-rng-seed", type=int, required=True)
    parser.add_argument("--rollouts", type=int, required=True, help="positive rollouts per legal move")
    parser.add_argument("--scoring", choices=("rising", "flat"), required=True)
    parser.add_argument(
        "--show-ban",
        default="2,J,Q,K",
        help="comma-separated ranks, or 'none' for a genuinely empty set",
    )
    parser.add_argument("--output", type=Path, required=True, help="JSONL output path")
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase stderr logging; does not affect canonical results",
    )
    return parser


def _positive(name: str, value: int) -> None:
    if value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")


def _write_jsonl(path: Path, records: Sequence[dict]) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        temporary = parent / f".{path.name}.tmp-{os.getpid()}"
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json_line(record))
        os.replace(temporary, path)
    except OSError as exc:
        raise ConfigurationError(f"could not write output {path}: {exc}") from exc


def _validate_output_path(output: Path, deal_file: Path | None) -> None:
    resolved_output = output.resolve(strict=False)
    archive = (locate_artifacts().root / "Archive").resolve()
    if resolved_output == archive or archive in resolved_output.parents:
        raise ConfigurationError("--output must not write inside the frozen Archive directory")
    if deal_file is not None and resolved_output == deal_file.resolve(strict=False):
        raise ConfigurationError("--output must not overwrite --deal-file")


def run_from_args(args: argparse.Namespace) -> list[dict]:
    _positive("--deals", args.deals)
    _positive("--rollouts", args.rollouts)
    banned = parse_show_banned_ranks(args.show_ban)
    _validate_output_path(args.output, args.deal_file)

    if args.deal_file is not None:
        if args.dealer is not None:
            raise ConfigurationError("--dealer cannot be used with --deal-file")
        deals = load_deals(args.deal_file)
        deal_source_mode = "explicit_file"
        deal_generation_seed = None
        initial_dealer = None
    else:
        dealer = 0 if args.dealer is None else args.dealer
        if dealer not in range(4):
            raise ConfigurationError("--dealer must be an integer in 0..3")
        deals = generate_deals(count=args.deals, seed=args.deal_seed, initial_dealer=dealer)
        deal_source_mode = "generated"
        deal_generation_seed = args.deal_seed
        initial_dealer = dealer

    if len(deals) != args.deals:
        raise ConfigurationError(
            f"--deals requests {args.deals}, but the deal file contains {len(deals)}"
        )

    config = RunnerConfig(
        deal_count=args.deals,
        legacy_rng_seed=args.legacy_rng_seed,
        rollouts=args.rollouts,
        scoring=args.scoring,
        show_banned_ranks=banned,
        deal_source_mode=deal_source_mode,
        deal_generation_seed=deal_generation_seed,
        initial_dealer=initial_dealer,
    )
    records = execute_legacy_deals(config, deals)
    _write_jsonl(args.output, records)
    if args.verbose:
        print(
            f"wrote {len(records)} legacy result record(s) to {args.output}",
            file=sys.stderr,
        )
    return records


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        run_from_args(args)
    except LegacyHarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
