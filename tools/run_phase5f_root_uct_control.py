"""Run the small Phase 5F multi-observer versus root-UCT control."""

from __future__ import annotations

import json
from pathlib import Path
import time

from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.statistics import pair_inference, secondary_metrics
from tuppi_search.phase5e_evaluation import phase5e_agent_builder, phase5e_agent_identity


ROOT_SEED = "tuppi-phase5f-root-uct-control-v1"


def unit(payload):
    comparison_data, ordinal, streams = payload
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
    bank = StreamBank.build(
        name="phase5f_root_uct_control_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=ROOT_SEED,
        initial_dealer=0,
        stream_count=streams,
        purpose="Phase 5F separate unsealed root-UCT control bank.",
    )
    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=704,
        ordinal=ordinal,
        build_candidate=phase5e_agent_builder("multi_observer_ismcts_standard_v1"),
        build_opponent=phase5e_agent_builder("root_info_uct_standard_v1"),
    )
    return ordinal, record.to_data()


def main() -> None:
    from concurrent.futures import ProcessPoolExecutor
    from tuppi_match.executor import _pair_from_data

    pairs = 8
    comparison = MatchComparison.build(
        name="phase5f_multi_observer_vs_root_uct_control",
        candidate_profile_key="multi_observer_ismcts_standard_v1",
        opponent_profile_key="root_info_uct_standard_v1",
        candidate_agent_id=phase5e_agent_identity("multi_observer_ismcts_standard_v1"),
        opponent_agent_id=phase5e_agent_identity("root_info_uct_standard_v1"),
        result_class="development",
        hypothesis="Does observer re-determinization improve over root-only information-set UCT?",
    )
    started = time.perf_counter()
    payload = [(comparison.to_data(), ordinal, pairs) for ordinal in range(pairs)]
    with ProcessPoolExecutor(max_workers=8) as pool:
        records = tuple(_pair_from_data(data) for _, data in pool.map(unit, payload, chunksize=1))
    report = {
        "bank": StreamBank.build(
            name="phase5f_root_uct_control_v1",
            role=BankRole.DEVELOPMENT,
            root_seed=ROOT_SEED,
            initial_dealer=0,
            stream_count=pairs,
            purpose="Phase 5F separate unsealed root-UCT control bank.",
        ).to_data(),
        "candidate_profile_key": "multi_observer_ismcts_standard_v1",
        "opponent_profile_key": "root_info_uct_standard_v1",
        "pair_count": pairs,
        "primary_match_inference": pair_inference(
            records,
            confidence_level=0.95,
            analysis_seed=ROOT_SEED,
            bootstrap_replicates=2000,
            sign_flip_replicates=10000,
        ),
        "secondary_metrics": secondary_metrics(records),
        "schema_version": "tuppi.search.phase5f_control.v1",
        "sealed_bank_opened": False,
        "operational_wall_seconds": time.perf_counter() - started,
    }
    output = Path(
        "/Users/pyryouri/Developer/TuppiRuns/phase5f/evaluation/"
        "phase5f_multi_observer_vs_root_uct_8_pairs.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report["primary_match_inference"], indent=2))
    print(output)


if __name__ == "__main__":
    main()
