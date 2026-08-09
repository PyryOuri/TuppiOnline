"""Run the Phase 5F unsealed complete-match comparison from a real module."""

from __future__ import annotations

import json
from pathlib import Path
import time

from tuppi_search.phase5f_evaluation import run_phase5f_match_comparison


def main() -> None:
    started = time.perf_counter()
    report = run_phase5f_match_comparison(
        candidate_profile_key="multi_observer_ismcts_standard_v1",
        opponent_profile_key="partner_aware_v1",
        pairs=32,
        workers=10,
        progress=lambda done, total: print(f"completed {done}/{total}", flush=True),
    )
    report["operational_wall_seconds"] = time.perf_counter() - started
    output = Path(
        "/Users/pyryouri/Developer/TuppiRuns/phase5f/evaluation/"
        "phase5f_standard_vs_reference_32_pairs.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    inference = report["primary_match_inference"]
    print(
        f"p_win={inference['candidate_match_win_probability']} "
        f"outcomes={inference['pair_outcomes']} "
        f"wall_seconds={report['operational_wall_seconds']:.1f}"
    )
    print(output)


if __name__ == "__main__":
    main()
