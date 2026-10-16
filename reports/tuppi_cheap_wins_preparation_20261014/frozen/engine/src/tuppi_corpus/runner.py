"""The finite, noninteractive corpus CLI.

Four verbs, and the second and third are the ones that matter:

``plan``      what a manifest asks for, without generating anything.
``generate``  produce the shards a manifest describes, resumably.
``verify``    the T0 gate: digests, a byte-identical shard rebuild in a fresh
              process, and authoritative replay of a sample of deals.
``stats``     what was actually produced, against what was asked for.

Parallelism is by shard, one worker per shard, with no coordination: a worker
writes its shard, fsyncs, and only then appends to the catalogue, so an
interrupted run leaves an uncatalogued file that the next run regenerates.
``--workers`` changes wall-clock time and nothing else - the bytes of a shard
are a pure function of the manifest and its stream range.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sys
import time

from .errors import CorpusError, CorpusIntegrityError
from .generation import assign_rows, generate_stream
from .manifest import RunManifest, load_manifest, pin_sources
from .records import FLAG_REVALIDATED
from .replay import verify_deal
from .shards import (
    append_catalog_entry,
    completed_shards,
    read_catalog,
    read_shard,
    shard_name,
    write_shard,
)
from .strata import (
    DEFAULT_HELDOUT_POLICY_SETS,
    DEFAULT_MIXTURE,
    DEFAULT_POLICY_SETS,
    DEFAULT_SCORE_SCHEDULE,
    DEFAULT_STRATIFIED_SCORE_SCHEDULE,
    SPLIT_NAMES,
    plan_stream,
    policy_identities,
)


MANIFEST_NAME = "manifest.json"
SHARD_DIRECTORY = "shards"


def build_manifest(args: argparse.Namespace) -> RunManifest:
    from tuppi_agents.improved_registry import corpus_reference_specification

    reference = corpus_reference_specification()
    return RunManifest(
        root_seed=args.root_seed,
        stream_start=args.stream_start,
        stream_stop=args.stream_stop,
        shard_streams=args.shard_streams,
        mixture=DEFAULT_MIXTURE,
        policy_sets=DEFAULT_POLICY_SETS,
        heldout_policy_sets=DEFAULT_HELDOUT_POLICY_SETS,
        score_schedule=DEFAULT_SCORE_SCHEDULE,
        stratified_score_schedule=DEFAULT_STRATIFIED_SCORE_SCHEDULE,
        reference_agent_id=reference.agent_id,
        reference_profile_key="partner_aware_lead_v2",
        epsilon_branch_probability_numerator=1,
        epsilon_branch_probability_denominator=1,
        softening_top_k=args.softening_top_k,
        softening_probability_numerator=args.softening_numerator,
        softening_probability_denominator=args.softening_denominator,
        match_deal_cap=args.deal_cap,
        revalidation_period=args.revalidation_period,
        exact_label_max_tricks=args.exact_label_max_tricks,
        split_boundaries=(args.train_boundary, args.validation_boundary),
        sources=pin_sources(),
    )


def resolve_manifest(directory: Path, args: argparse.Namespace | None) -> RunManifest:
    """Load the run's manifest, or write it on first use and refuse to change it."""

    path = Path(directory) / MANIFEST_NAME
    if path.exists():
        manifest = load_manifest(path)
        if args is not None:
            requested = build_manifest(args)
            if requested.run_id != manifest.run_id:
                raise CorpusError(
                    "this directory already holds a different run:\n"
                    f"  on disk:   {manifest.run_id}\n"
                    f"  requested: {requested.run_id}\n"
                    "generate into a new directory rather than mixing runs"
                )
        return manifest
    if args is None:
        raise CorpusError(f"no manifest at {path}")
    manifest = build_manifest(args)
    manifest.write(path)
    return manifest


def generate_shard(
    manifest_path: str, stream_start: int, stream_stop: int, directory: str
) -> dict[str, object]:
    """Generate and write one shard.  The unit of work, and of a worker."""

    manifest = load_manifest(Path(manifest_path))
    units: list = []
    for stream_index in range(stream_start, stream_stop):
        units.extend(generate_stream(manifest, stream_index))
    matches, deals = assign_rows(tuple(units))
    name = shard_name(stream_start, stream_stop)
    path = Path(directory) / SHARD_DIRECTORY / name
    started = time.perf_counter()
    digest = write_shard(
        path,
        run_id=manifest.run_id,
        stream_start=stream_start,
        stream_stop=stream_stop,
        matches=matches,
        deals=deals,
    )
    return {
        "deals": len(deals),
        "digest": digest,
        "matches": len(matches),
        "revalidated_deals": sum(1 for row in deals if row.flags & FLAG_REVALIDATED),
        "seconds": round(time.perf_counter() - started, 3),
        "shard": f"{SHARD_DIRECTORY}/{name}",
        "stream_start": stream_start,
        "stream_stop": stream_stop,
    }


def _command_plan(args: argparse.Namespace) -> int:
    manifest = build_manifest(args)
    counts = Counter(
        plan_stream(manifest, index).stratum_name
        for index in range(manifest.stream_start, manifest.stream_stop)
    )
    splits = Counter(
        SPLIT_NAMES[plan_stream(manifest, index).split]
        for index in range(manifest.stream_start, manifest.stream_stop)
    )
    total = manifest.stream_stop - manifest.stream_start
    print(f"run_id      {manifest.run_id}")
    print(f"reference   {manifest.reference_profile_key} {manifest.reference_agent_id}")
    print(f"streams     {manifest.stream_start}..{manifest.stream_stop} ({total})")
    print(f"shards      {len(manifest.shard_bounds())} of {manifest.shard_streams} streams")
    print(f"sources     {len(manifest.sources)} files pinned")
    print("strata      (asked / realised)")
    for name, weight in manifest.mixture:
        share = 100.0 * weight / sum(w for _, w in manifest.mixture)
        got = 100.0 * counts.get(name, 0) / total
        print(f"  {name:24s} {share:5.1f}%  {got:5.1f}%  ({counts.get(name, 0)})")
    print("splits      " + "  ".join(f"{k}={v}" for k, v in sorted(splits.items())))
    print("policies")
    for key, identity in sorted(policy_identities(manifest).items()):
        print(f"  {key:26s} {identity}")
    return 0


def _command_generate(args: argparse.Namespace) -> int:
    directory = Path(args.output)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = resolve_manifest(directory, args)
    manifest.verify_sources()
    manifest_path = str(directory / MANIFEST_NAME)

    done = completed_shards(directory)
    pending = [bounds for bounds in manifest.shard_bounds() if bounds not in done]
    print(f"run_id {manifest.run_id}")
    print(f"{len(done)} shards already catalogued, {len(pending)} to generate")
    if not pending:
        return 0

    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    started = time.perf_counter()
    deals = matches = revalidated = 0
    if workers == 1:
        for lo, hi in pending:
            entry = generate_shard(manifest_path, lo, hi, str(directory))
            append_catalog_entry(directory, entry)
            deals += entry["deals"]
            matches += entry["matches"]
            revalidated += entry["revalidated_deals"]
            print(f"  {entry['shard']}  {entry['deals']:7d} deals  {entry['digest'][:20]}...")
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(generate_shard, manifest_path, lo, hi, str(directory)): (lo, hi)
                for lo, hi in pending
            }
            for future in as_completed(futures):
                entry = future.result()
                append_catalog_entry(directory, entry)
                deals += entry["deals"]
                matches += entry["matches"]
                revalidated += entry["revalidated_deals"]
                print(
                    f"  {entry['shard']}  {entry['deals']:7d} deals  "
                    f"{entry['digest'][:20]}...",
                    flush=True,
                )
    elapsed = time.perf_counter() - started
    print(
        f"{matches} matches, {deals} deals in {elapsed:.1f}s "
        f"({deals / elapsed:.0f} deals/s on {workers} workers)"
    )
    print(f"{revalidated} deals also checked through the authoritative path")
    return 0


def _command_verify(args: argparse.Namespace) -> int:
    directory = Path(args.output)
    manifest = resolve_manifest(directory, None)
    manifest.verify_sources()
    entries = read_catalog(directory)
    if not entries:
        raise CorpusError("catalogue is empty; nothing to verify")

    print(f"run_id {manifest.run_id}")
    deals_seen = 0
    for entry in entries:
        header, matches, deals = read_shard(directory / entry["shard"])
        if header.run_digest != manifest.run_id:
            raise CorpusIntegrityError(f"{entry['shard']} belongs to another run")
        if len(deals) != entry["deals"] or len(matches) != entry["matches"]:
            raise CorpusIntegrityError(f"{entry['shard']} row counts disagree")
        deals_seen += len(deals)
    print(f"digests and row counts agree over {len(entries)} shards, {deals_seen} deals")

    # A byte-identical rebuild is the property that makes the corpus disposable
    # and a larger tier a scheduling question. Rebuild one shard and compare.
    target = entries[len(entries) // 2]
    rebuilt = generate_shard(
        str(directory / MANIFEST_NAME),
        int(target["stream_start"]),
        int(target["stream_stop"]),
        str(directory / "rebuild"),
    )
    if rebuilt["digest"] != target["digest"]:
        raise CorpusIntegrityError(
            f"rebuild of {target['shard']} diverged: "
            f"{rebuilt['digest']} != {target['digest']}"
        )
    print(f"rebuild of {target['shard']} reproduced its digest exactly")

    sample = args.sample
    checked = 0
    for entry in entries:
        _header, _matches, deals = read_shard(directory / entry["shard"])
        step = max(1, len(deals) // max(1, sample // max(1, len(entries))))
        for deal in deals[::step]:
            verify_deal(deal)
            checked += 1
            if checked >= sample:
                break
        if checked >= sample:
            break
    print(f"{checked} deals replayed through the authoritative engine and agreed")
    return 0


def _command_stats(args: argparse.Namespace) -> int:
    directory = Path(args.output)
    manifest = resolve_manifest(directory, None)
    strata = Counter()
    stratum_deals = Counter()
    splits = Counter()
    contracts = Counter()
    flags = Counter()
    deals = matches = 0
    points = 0
    for entry in read_catalog(directory):
        _header, match_rows, deal_rows = read_shard(directory / entry["shard"])
        matches += len(match_rows)
        deals += len(deal_rows)
        stratum_of_match = [manifest.mixture[row.stratum][0] for row in match_rows]
        for row in match_rows:
            strata[manifest.mixture[row.stratum][0]] += 1
            splits[SPLIT_NAMES[row.split]] += 1
        for row in deal_rows:
            stratum_deals[stratum_of_match[row.match_row]] += 1
            contracts[row.contract.value] += 1
            points += row.deal_points[0] + row.deal_points[1]
            for bit, name in (
                (1 << 3, "forced_contract"),
                (1 << 4, "epsilon_branch"),
                (1 << 5, "softened"),
                (1 << 6, "revalidated"),
                (1 << 7, "forced_play"),
            ):
                if row.flags & bit:
                    flags[name] += 1
    print(f"run_id     {manifest.run_id}")
    print(f"matches    {matches}")
    print(f"deals      {deals}")
    if deals:
        print(f"deals/match {deals / matches:.1f}")
        print(f"mean points {points / deals:.2f}")
    # The mixture is drawn per *stream*; paired strata contribute two matches
    # per stream, and a stratum that lengthens matches contributes more deals
    # than its stream share. Both denominators are shown so neither is mistaken
    # for the requested mixture.
    print("strata            matches (share)   deals (share)")
    for name, count in strata.most_common():
        deal_count = stratum_deals.get(name, 0)
        print(
            f"  {name:24s} {count:7d} {100.0 * count / max(1, matches):5.1f}%"
            f"  {deal_count:8d} {100.0 * deal_count / max(1, deals):5.1f}%"
        )
    print("splits (matches)  " + "  ".join(f"{k}={v}" for k, v in sorted(splits.items())))
    print("contracts (deals) " + "  ".join(f"{k}={v}" for k, v in sorted(contracts.items())))
    print("flagged deals     " + "  ".join(f"{k}={v}" for k, v in sorted(flags.items())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tuppi-corpus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_manifest_arguments(target: argparse.ArgumentParser) -> None:
        target.add_argument("--root-seed", default="tuppi-corpus-t1-v1")
        target.add_argument("--stream-start", type=int, default=0)
        target.add_argument("--stream-stop", type=int, default=1024)
        target.add_argument("--shard-streams", type=int, default=256)
        target.add_argument("--deal-cap", type=int, default=64)
        target.add_argument("--revalidation-period", type=int, default=32)
        target.add_argument("--exact-label-max-tricks", type=int, default=0)
        target.add_argument("--softening-top-k", type=int, default=3)
        target.add_argument("--softening-numerator", type=int, default=1)
        target.add_argument("--softening-denominator", type=int, default=4)
        target.add_argument("--train-boundary", type=int, default=800)
        target.add_argument("--validation-boundary", type=int, default=900)

    plan = sub.add_parser("plan", help="what a manifest asks for")
    add_manifest_arguments(plan)
    plan.set_defaults(handler=_command_plan)

    generate = sub.add_parser("generate", help="produce the shards, resumably")
    generate.add_argument("--output", required=True)
    generate.add_argument("--workers", type=int, default=None)
    add_manifest_arguments(generate)
    generate.set_defaults(handler=_command_generate)

    verify = sub.add_parser("verify", help="digests, a rebuild, and authoritative replay")
    verify.add_argument("--output", required=True)
    verify.add_argument("--sample", type=int, default=64)
    verify.set_defaults(handler=_command_verify)

    stats = sub.add_parser("stats", help="what was actually produced")
    stats.add_argument("--output", required=True)
    stats.set_defaults(handler=_command_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except CorpusError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    raise SystemExit(main())
