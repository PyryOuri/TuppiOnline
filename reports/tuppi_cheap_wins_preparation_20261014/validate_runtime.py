#!/usr/bin/env python3
"""Bounded preparation checks. Never executes a scientific analysis plan."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from launch import OUT, PYTHON, publish, verify
from statistics_tools import paired


def main():
    verify()
    directory = OUT / "checks"
    directory.mkdir(exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
    env.pop("PYTHONPATH", None)
    start = time.perf_counter()
    test = subprocess.run([PYTHON, "-B", "-m", "pytest", str(OUT / "test_preparation.py"), "-q", "-p", "no:cacheprovider"], env=env, capture_output=True, text=True, timeout=30)
    (directory / "pytest.log").write_text(test.stdout + test.stderr)
    if test.returncode:
        raise RuntimeError("Candidate/statistics checks failed; see checks/pytest.log")
    results = {}
    cases = (("installed", "baseline", OUT / "runtime/native/libtuppi.dylib"),
             ("rebuilt", "baseline", OUT / "builds/rebuilt/libtuppi.dylib"),
             ("bucket_off", "baseline", OUT / "builds/reward_bucket/libtuppi.dylib"),
             ("bucket_on", "reward_bucket", OUT / "builds/reward_bucket/libtuppi.dylib"),
             ("same_net", "same_net", OUT / "runtime/native/libtuppi.dylib"))
    for label, arm, library in cases:
        child_env = dict(env, CW_ROOT_ARM=arm, TUPPI_CHEAP_WINS_LIBRARY=str(library))
        child = subprocess.run([PYTHON, "-B", str(OUT / "native_roots.py")], env=child_env, capture_output=True, text=True, timeout=45)
        (directory / (label + ".stderr.log")).write_text(child.stderr)
        if child.returncode:
            raise RuntimeError(f"Native root probe failed: {label}")
        data = json.loads(child.stdout)
        publish(directory / (label + ".json"), data)
        results[label] = data
    def projected(data):
        return [{k: v for k, v in row.items() if k != "wall_seconds"} for row in data["rows"]]
    baseline = projected(results["installed"])
    parity = {label: projected(data) == baseline for label, data in results.items()}
    if not all(parity[label] for label in ("rebuilt", "bucket_off", "bucket_on")):
        raise RuntimeError("Rebuild/reward bucket native root fingerprints differ")
    if not any(len(set(row["values"])) > 1 for row in baseline if row["phase"] == 1):
        raise RuntimeError("Tail coverage is inert; add a discriminating root before accepting parity")
    # Two parent bundles at W4 are pipeline/identity controls, not a strength
    # screen. Complete baseline-vs-baseline should cancel exactly by design.
    smoke_context = {"package_sha256": hashlib.sha256((OUT / "FROZEN.json").read_bytes()).hexdigest(),
                     "controller_lifecycle": "fresh_indexed_game", "design": "4_rotations_2_teams", "qualification": "preparation smoke"}
    job = {"id": "pipeline_smoke", "kind": "duplicate", "arm": "baseline", "opponent": "baseline",
           "worlds": 4, "samples": 2, "seed": "cw-pipeline-control-v1", "scores": "uniform", "serial": True,
           "cpu_seconds": 30, "wall_seconds": 35}
    publish(directory / "smoke_job.json", {"job": job, "context": smoke_context})
    child_env = dict(env)
    child_env.pop("TUPPI_CHEAP_WINS_LIBRARY", None)
    child = subprocess.run([PYTHON, "-B", str(OUT / "worker.py"), "--job", str(directory / "smoke_job.json"), "--out", str(directory / "pipeline_smoke.json")],
                           env=child_env, capture_output=True, text=True, timeout=40)
    (directory / "pipeline_smoke.log").write_text(child.stdout + child.stderr)
    if child.returncode:
        raise RuntimeError("Authoritative pipeline smoke failed")
    smoke = json.loads((directory / "pipeline_smoke.json").read_text())
    paired(smoke, smoke)
    if smoke["values"] != [0., 0.]:
        raise RuntimeError("Indexed baseline identity control did not cancel")
    record = {"schema": "tuppi.cheap_wins.preparation_checks.v1", "status": "PREPARATION_CHECKS_PASS",
              "pytest_exit": test.returncode, "native_root_parity": parity,
              "native_root_count": len(baseline), "native_root_scope": "Ordinary roots including partial tricks and C/O/P modes; W1024 only on exact-tail roots",
              "same_net_exact_on_checked_roots": parity["same_net"], "authoritative_pipeline_smoke": {"worlds": 4, "base_deals": 2, "games": 16, "values": smoke["values"]},
              "wall_seconds": time.perf_counter()-start, "qualification": "Prepared mechanism and pipeline checks. Full W1024 bids/sooli, repeated speed work and strength comparisons remain unexecuted."}
    publish(OUT / "PREPARATION_CHECKS.json", record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
