"""Contract-stage resource ledger (master prompt caps; V10 accounting).

Every execution of Tuppi game code, native code or a model during the
contract stage is run through this wrapper, which appends one JSON line with
measured wall time, total CPU of the child and all its descendants/threads,
peak child RSS, and the workload counters the child reports:

    python -m tuppi_ai.research.ledger --purpose "C0.04 parity" -- python -m ...

Children report counters by appending JSON objects to the file named in
TUPPI_RESEARCH_COUNTS (see `count`). `summary()` aggregates the ledger and
compares it with the package's default contract caps.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from .identity import OUTPUT_DIR

LEDGER = OUTPUT_DIR / "logs" / "resource_ledger.jsonl"
#: EXECUTION_PLAN.json default_contract_caps.
CAPS = {"python_workers": 1, "concurrent_native_searches": 1, "development_fixture_deals": 32,
        "search_observation_probes": 32, "max_worlds_per_probe": 128, "complete_search_smoke_games": 2,
        "wall_seconds": 900, "total_cpu_seconds": 1800}
COUNTERS = ("development_fixture_deals", "search_observation_probes", "complete_search_smoke_games",
            "native_search_calls", "runner_test_deals")
#: Identity-keyed counters: a rerun of the same deterministic deck or probe is
#: not a new development deal or probe (its CPU is still charged in full).
ID_COUNTERS = {"fixture_deal_ids": "development_fixture_deals", "runner_deal_ids": "runner_test_deals",
               "probe_ids": "search_observation_probes", "search_game_ids": "complete_search_smoke_games"}


def count(**counters) -> None:
    """Report workload from inside a ledger-wrapped process (no-op otherwise).

    Integer counters (e.g. native_search_calls=3) add up; identity counters
    (fixture_deal_ids=[...], runner_deal_ids, probe_ids, search_game_ids) are
    deduplicated across the whole ledger.
    """
    path = os.environ.get("TUPPI_RESEARCH_COUNTS")
    if not path:
        return
    unknown = set(counters) - set(COUNTERS) - set(ID_COUNTERS)
    if unknown:
        raise ValueError(f"unknown counters {unknown}")
    with open(path, "a") as f:
        f.write(json.dumps(counters) + "\n")


def append(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


def run(purpose: str, cmd: list[str], cwd: str | None = None) -> int:
    counts_path = LEDGER.parent / f".counts-{os.getpid()}-{time.time_ns()}.jsonl"
    env = {**os.environ, "TUPPI_RESEARCH_COUNTS": str(counts_path)}
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    rc = subprocess.run(cmd, cwd=cwd, env=env).returncode
    wall = time.perf_counter() - t0
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    totals = dict.fromkeys(COUNTERS, 0)
    ids: dict[str, list] = {k: [] for k in ID_COUNTERS}
    if counts_path.exists():
        for line in counts_path.read_text().splitlines():
            for k, v in json.loads(line).items():
                if k in ID_COUNTERS:
                    ids[k].extend(v)
                else:
                    totals[k] += v
        counts_path.unlink()
    for k, v in ids.items():
        ids[k] = sorted(set(v))
    append({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "purpose": purpose, "command": cmd,
            "returncode": rc, "wall_s": round(wall, 3),
            "cpu_s": round((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime), 3),
            "peak_child_rss_bytes": after.ru_maxrss, "counts": totals, "ids": ids, "measured": True})
    return rc


def summary() -> dict:
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines()] if LEDGER.exists() else []
    total = {"wall_seconds": sum(r["wall_s"] for r in rows), "total_cpu_seconds": sum(r["cpu_s"] for r in rows)}
    for key in COUNTERS:
        total[key] = sum(r["counts"].get(key, 0) for r in rows)
    for id_key, key in ID_COUNTERS.items():
        unique = {i for r in rows for i in r.get("ids", {}).get(id_key, [])}
        total[key] += len(unique)
    total["all_cheap_policy_deals"] = total["development_fixture_deals"] + total["runner_test_deals"]
    within = {"wall_seconds": total["wall_seconds"] <= CAPS["wall_seconds"],
              "total_cpu_seconds": total["total_cpu_seconds"] <= CAPS["total_cpu_seconds"],
              "development_fixture_deals": total["development_fixture_deals"] <= CAPS["development_fixture_deals"],
              "search_observation_probes": total["search_observation_probes"] <= CAPS["search_observation_probes"],
              "complete_search_smoke_games":
                  total["complete_search_smoke_games"] <= CAPS["complete_search_smoke_games"]}
    return {"entries": len(rows), "totals": total, "caps": CAPS, "within_caps": within,
            "unmeasured_entries": sum(1 for r in rows if not r.get("measured", True))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purpose")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.summary:
        print(json.dumps(summary(), indent=1))
        return
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    if not args.purpose or not cmd:
        parser.error("--purpose and a command are required")
    sys.exit(run(args.purpose, cmd))


if __name__ == "__main__":
    main()
