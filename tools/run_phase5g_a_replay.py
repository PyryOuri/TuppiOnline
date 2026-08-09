"""Replay frozen agents for the Phase 5G-A evaluation-integrity audit.

The output is intentionally written to the caller-supplied external path and
contains pair records but no hidden hands.  This script does not define a new
agent or alter the complete-match protocol.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import time

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.statistics import pair_inference, secondary_metrics
from tuppi_search.multi_observer_registry import (
    build_agent as build_multi_observer_agent,
    specification_for as multi_specification_for,
)
from tuppi_search.phase5g_a_audit import (
    PHASE5G_A_SCHEMA_VERSION,
    pair_outcome_rows,
    resolve_agent_identity,
)
from tuppi_search.root_info_uct_registry import (
    build_agent as build_root_info_uct_agent,
    specification_for as root_specification_for,
)


BANKS = {
    "phase5d-c": {
        "name": "phase5d_b_match_v1",
        "root_seed": "tuppi-phase5d-b-match-v1",
        "purpose": "Exact Phase 5D-C/root-UCT historical development bank replay.",
        "default_pairs": 32,
        "default_safety_cap": 96,
    },
    "phase5f-control": {
        "name": "phase5f_root_uct_control_v1",
        "root_seed": "tuppi-phase5f-root-uct-control-v1",
        "purpose": "Exact Phase 5F root-UCT control-bank replay.",
        "default_pairs": 8,
        "default_safety_cap": 704,
    },
}


def bank_for(kind: str, pairs: int) -> StreamBank:
    spec = BANKS[kind]
    return StreamBank.build(
        name=spec["name"],
        role=BankRole.DEVELOPMENT,
        root_seed=spec["root_seed"],
        initial_dealer=0,
        stream_count=pairs,
        purpose=spec["purpose"],
    )


def builder(profile_key: str):
    resolved = "partner_aware_v1" if profile_key == "development_reference_v1" else profile_key
    phase4 = phase4_specifications_by_profile_key()
    if resolved in phase4:
        return lambda seat: construct_agent(phase4[resolved], seat=seat)
    if resolved in {"root_info_uct_smoke_v1", "root_info_uct_small_v1", "root_info_uct_standard_v1"}:
        root_specification_for(resolved)
        return lambda seat: build_root_info_uct_agent(resolved, seat=seat)
    if resolved in {
        "multi_observer_ismcts_smoke_v1",
        "multi_observer_ismcts_small_v1",
        "multi_observer_ismcts_standard_v1",
    }:
        multi_specification_for(resolved)
        return lambda seat: build_multi_observer_agent(resolved, seat=seat)
    raise ValueError(f"unknown profile {profile_key!r}")


def _unit(payload: tuple) -> tuple[int, dict]:
    kind, pairs, safety_cap, comparison_data, ordinal = payload
    comparison = MatchComparison.build(
        name=comparison_data["name"],
        candidate_profile_key=comparison_data["candidate_profile_key"],
        opponent_profile_key=comparison_data["opponent_profile_key"],
        candidate_agent_id=comparison_data["candidate_agent_id"],
        opponent_agent_id=comparison_data["opponent_agent_id"],
        result_class=comparison_data["result_class"],
        hypothesis=comparison_data["hypothesis"],
        starting_score=tuple(comparison_data["starting_score"]),
    )
    record = run_pair(
        stream=bank_for(kind, pairs).stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=builder(comparison.candidate_profile_key),
        build_opponent=builder(comparison.opponent_profile_key),
    )
    return ordinal, record.to_data()


def run_replay(
    *,
    kind: str,
    candidate_profile_key: str,
    opponent_profile_key: str,
    pairs: int,
    safety_cap: int,
    workers: int,
) -> dict[str, object]:
    candidate_resolved, candidate_id = resolve_agent_identity(candidate_profile_key)
    opponent_resolved, opponent_id = resolve_agent_identity(opponent_profile_key)
    comparison = MatchComparison.build(
        name=f"phase5g_a_{kind}_{candidate_profile_key}_vs_{opponent_profile_key}",
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=candidate_id,
        opponent_agent_id=opponent_id,
        result_class="development",
        hypothesis="Phase 5G-A exact deterministic replay for evaluation-integrity audit.",
    )
    payloads = [
        (kind, pairs, safety_cap, comparison.to_data(), ordinal)
        for ordinal in range(pairs)
    ]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        rows = tuple(pool.map(_unit, payloads, chunksize=1))
    records_by_ordinal = {ordinal: data for ordinal, data in rows}
    raw_records = [records_by_ordinal[index] for index in range(pairs)]
    from tuppi_match.executor import _pair_from_data

    records = tuple(_pair_from_data(data) for data in raw_records)
    bank = bank_for(kind, pairs)
    report = {
        "schema_version": PHASE5G_A_SCHEMA_VERSION,
        "replay_kind": kind,
        "comparison": comparison.to_data(),
        "candidate_profile_key": candidate_profile_key,
        "candidate_resolved_profile_key": candidate_resolved,
        "candidate_agent_id": candidate_id,
        "opponent_profile_key": opponent_profile_key,
        "opponent_resolved_profile_key": opponent_resolved,
        "opponent_agent_id": opponent_id,
        "bank": bank.to_data(),
        "pair_count": pairs,
        "safety_cap": safety_cap,
        "analysis_seed": bank.root_seed,
        "pair_records": [
            {"ordinal": ordinal, "record": data}
            for ordinal, data in enumerate(raw_records)
        ],
        "pair_outcomes": pair_outcome_rows(records),
        "primary_match_inference": pair_inference(
            records,
            confidence_level=0.95,
            analysis_seed=bank.root_seed,
            bootstrap_replicates=2_000,
            sign_flip_replicates=10_000,
        ),
        "secondary_metrics": secondary_metrics(records),
        "sealed_bank_opened": False,
        "operational_wall_seconds": time.perf_counter() - started,
        "worker_count": workers,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", choices=sorted(BANKS), required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--opponent", required=True)
    parser.add_argument("--pairs", type=int)
    parser.add_argument("--safety-cap", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    defaults = BANKS[args.bank]
    report = run_replay(
        kind=args.bank,
        candidate_profile_key=args.candidate,
        opponent_profile_key=args.opponent,
        pairs=args.pairs or defaults["default_pairs"],
        safety_cap=args.safety_cap or defaults["default_safety_cap"],
        workers=args.workers,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report["primary_match_inference"], indent=2, sort_keys=True))
    print(args.output)


if __name__ == "__main__":
    main()
