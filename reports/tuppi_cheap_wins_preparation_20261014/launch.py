#!/usr/bin/env python3
"""Verify, preview, seal and later execute finite single-worker analysis plans.

Run is a dry run unless --execute is supplied. Failed/timed-out jobs retain
their attempts and charge their full reservation. A new run directory is
required; there is no partial-parent reuse or automatic retry.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
PYTHON = "/Users/pyryouri/.venvs/tuppi-v2/bin/python"
ARMS = {"baseline", "hard_anchor", "suit_ensemble", "reward_bucket", "same_net"}
OPPONENTS = {"baseline", "vrpo3", "heuristic_v3"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def publish(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def verify():
    frozen = json.loads((OUT / "FROZEN.json").read_text())
    for key in ("frozen_hashes", "runtime_base_hashes"):
        for name, expected in frozen[key].items():
            if digest(OUT / name) != expected:
                raise ValueError(f"Captured input changed: {name}")
    expected_files = set(frozen["frozen_hashes"]) | set(frozen["runtime_base_hashes"])
    actual_files = {str(p.relative_to(OUT)) for base in (OUT / "frozen", OUT / "runtime")
                    for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    if actual_files != expected_files:
        raise ValueError("Frozen/runtime input file set changed")
    build = json.loads((OUT / "NATIVE_BUILD.json").read_text())
    for arm, record in build["libraries"].items():
        directory = OUT / "builds" / arm
        if digest(directory / "libtuppi.dylib") != record["sha256"]:
            raise ValueError(f"Native library changed: {arm}")
        for name, expected in record["source_hashes"].items():
            if digest(directory / name) != expected:
                raise ValueError(f"Native source changed: {arm}/{name}")
    package = OUT / "PACKAGE.json"
    if package.exists():
        seal = json.loads(package.read_text())
        for name, expected in seal["files"].items():
            if digest(OUT / name) != expected:
                raise ValueError(f"Sealed package changed: {name}")
        now = {str(p.relative_to(OUT)) for p in OUT.glob("*.py")} | {str(p.relative_to(OUT)) for p in (OUT / "configs").glob("*.json")}
        expected = {name for name in seal["files"] if name.endswith(".py") and "/" not in name or name.startswith("configs/")}
        if now != expected:
            raise ValueError("Executable/configuration file set changed")
    return {"frozen_files": len(frozen["frozen_hashes"]), "native_builds": list(build["libraries"]), "sealed": package.exists()}


def validate_plan(plan):
    if plan.get("schema") != "tuppi.cheap_wins.plan.v1" or plan.get("execution_enabled") is not False:
        raise ValueError("Expected a preparation plan with explicit execution_enabled=false")
    if set(plan) != {"schema", "name", "stage", "execution_enabled", "budget_cpu_seconds", "budget_wall_seconds", "jobs"}:
        raise ValueError("Unknown/missing plan fields")
    if plan["stage"] not in {"costing", "speed_validation", "development"}:
        raise ValueError("Confirmation requires a separately sized, frozen plan")
    for key in ("budget_cpu_seconds", "budget_wall_seconds"):
        if type(plan[key]) is not int or plan[key] <= 0:
            raise ValueError("Finite positive integer budgets required")
    if not plan["jobs"]:
        raise ValueError("No jobs")
    known, cpu, wall = set(), 0, 0
    for job in plan["jobs"]:
        fields = {"id", "kind", "arm", "worlds", "samples", "seed", "scores", "serial", "cpu_seconds", "wall_seconds"}
        if job["kind"] in {"duplicate", "match_cost"}:
            fields |= {"opponent"}
        if job["kind"] == "match_cost":
            fields |= {"match_cap"}
        if set(job) != fields or job["kind"] not in {"duplicate", "full_deals", "match_cost"}:
            raise ValueError("Unknown/missing job fields")
        if not isinstance(job["id"], str) or not job["id"].replace("_", "").isalnum() or job["id"] in known:
            raise ValueError("Invalid/duplicate job ID")
        known.add(job["id"])
        if job["arm"] not in ARMS or job.get("opponent", "baseline") not in OPPONENTS:
            raise ValueError("Unknown candidate/opponent")
        if job["kind"] != "full_deals" and job["arm"] in {"reward_bucket", "same_net"}:
            raise ValueError("Speed arms first qualify via separate-process full-deal fingerprints")
        for key in ("worlds", "samples", "cpu_seconds", "wall_seconds"):
            if type(job[key]) is not int or job[key] <= 0:
                raise ValueError(f"Invalid {key}")
        if not 1 <= job["worlds"] <= 4096 or job["worlds"] > 128 and job["worlds"] % 128:
            raise ValueError("Invalid adaptive world cap")
        if job["kind"] == "duplicate" and job["samples"] < 2:
            raise ValueError("At least two complete parent bundles")
        if job["kind"] == "match_cost" and (type(job["match_cap"]) is not int or job["match_cap"] < 1):
            raise ValueError("Invalid match cap")
        if job["kind"] == "match_cost" and job["scores"] != "zero":
            raise ValueError("Complete-match costing starts from 0-0")
        if job["serial"] is not True or job["scores"] not in {"zero", "uniform"} or not isinstance(job["seed"], str) or not job["seed"]:
            raise ValueError("This preparation supports explicit single-core jobs and fixed score designs")
        cpu += job["cpu_seconds"]
        wall += job["wall_seconds"]
    if cpu > plan["budget_cpu_seconds"] or wall > plan["budget_wall_seconds"]:
        raise ValueError("Job reservations exceed the finite plan budget")
    return {"name": plan["name"], "stage": plan["stage"], "jobs": len(known), "workers": 1,
            "cpu_reserved_seconds": cpu, "wall_reserved_seconds": wall,
            "status": "PREPARED_NOT_EXECUTED", "automatic_confirmation": False}


def seal():
    verify()
    checks = json.loads((OUT / "PREPARATION_CHECKS.json").read_text())
    if checks["status"] != "PREPARATION_CHECKS_PASS":
        raise ValueError("Preparation checks have not passed")
    files = list(OUT.glob("*.py")) + list((OUT / "configs").glob("*.json"))
    files += [OUT / name for name in ("FROZEN.json", "NATIVE_BUILD.json", "PREPARATION_CHECKS.json", "README.md", "PROTOCOL.md")]
    files += [p for p in (OUT / "checks").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    record = {"schema": "tuppi.cheap_wins.package.v1", "files": {str(p.relative_to(OUT)): digest(p) for p in files},
              "controller_lifecycle": "fresh_indexed_game_for_duplicates_retained_per_match_leg",
              "scope": "Prepared candidates and finite designs; no strength or whole-bot speed promotion."}
    publish(OUT / "PACKAGE.json", record)
    return {"package_sha256": digest(OUT / "PACKAGE.json"), "files": len(files)}


def context(job):
    return {"package_sha256": digest(OUT / "PACKAGE.json"), "worlds": job["worlds"], "workers": 1,
            "native_parallel": False, "rollout_chunk": 32, "design": "4_rotations_2_teams" if job["kind"] == "duplicate" else job["kind"],
            "controller_lifecycle": "fresh_indexed_game" if job["kind"] == "duplicate" else "retained",
            "score_design": job["scores"], "sampler_fix": True, "dd_extra_nolo": 0,
            "sooli_reset": "fresh_on_construction_only", "deal_id_schema": "actual_cards_index_score_dealer.v1"}


def run(plan, destination):
    verify()
    if not (OUT / "PACKAGE.json").exists():
        raise ValueError("Package must be sealed after preparation checks")
    if not destination.resolve().is_relative_to(OUT / "runs"):
        raise ValueError("Results must stay under this package's runs/")
    destination.mkdir(parents=True, exist_ok=False)
    publish(destination / "plan.json", plan)
    rows, cpu_charged, wall_charged = [], 0., 0.
    for job in plan["jobs"]:
        if cpu_charged + job["cpu_seconds"] > plan["budget_cpu_seconds"] or wall_charged + job["wall_seconds"] > plan["budget_wall_seconds"]:
            break
        verify()
        attempt = destination / job["id"]
        attempt.mkdir()
        publish(attempt / "job.json", {"job": job, "context": context(job)})
        command = [PYTHON, "-B", str(OUT / "worker.py"), "--job", str(attempt / "job.json"), "--out", str(attempt / "result.json")]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
        env.pop("PYTHONPATH", None)
        if job["arm"] == "reward_bucket":
            env["TUPPI_CHEAP_WINS_LIBRARY"] = str(OUT / "builds/reward_bucket/libtuppi.dylib")
        else:
            env.pop("TUPPI_CHEAP_WINS_LIBRARY", None)
        publish(attempt / "reservation.json", {"command": command, "cpu_reserved_seconds": job["cpu_seconds"], "wall_reserved_seconds": job["wall_seconds"]})
        before = time.perf_counter()
        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
        with (attempt / "worker.log").open("x") as log:
            try:
                child = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=job["wall_seconds"]+2, check=False)
                success = child.returncode == 0 and (attempt / "result.json").exists()
                code = child.returncode
            except subprocess.TimeoutExpired:
                success, code = False, "TIMEOUT"
        elapsed = time.perf_counter() - before
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu = usage_after.ru_utime + usage_after.ru_stime - usage_before.ru_utime - usage_before.ru_stime
        if success:
            result = json.loads((attempt / "result.json").read_text())
            if result["job"] != job or result["context"] != context(job):
                raise ValueError("Worker result identity differs")
            cpu_charge = child_cpu  # includes startup, writing and process shutdown
            if job["kind"] == "duplicate":
                from statistics_tools import paired
                paired(result, result)  # validates full parents before publication
        else:
            cpu_charge = job["cpu_seconds"]  # unknown partial work stays charged
        cpu_charged += cpu_charge
        wall_charged += elapsed if success else max(elapsed, job["wall_seconds"])
        row = {"job": job["id"], "success": success, "returncode": code, "cpu_charge": cpu_charge, "measured_child_cpu": child_cpu, "wall_charge": elapsed,
               "result_sha256": digest(attempt / "result.json") if success else None}
        rows.append(row)
        publish(attempt / "status.json", row)
        if not success:
            break  # no automatic retry or continuation after a failed cap
    summary = {"schema": "tuppi.cheap_wins.run.v1", "jobs": rows, "cpu_charged_seconds": cpu_charged,
               "wall_charged_seconds": wall_charged, "complete": len(rows)==len(plan["jobs"]) and all(r["success"] for r in rows)}
    publish(destination / "status.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("seal")
    preview = sub.add_parser("preview")
    preview.add_argument("plan", type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("plan", type=Path)
    execute.add_argument("--out", type=Path)
    execute.add_argument("--execute", action="store_true")
    compare = sub.add_parser("compare")
    compare.add_argument("candidate", type=Path)
    compare.add_argument("reference", type=Path)
    compare.add_argument("--out", type=Path, required=True)
    traces = sub.add_parser("compare_traces")
    traces.add_argument("candidate", type=Path)
    traces.add_argument("reference", type=Path)
    traces.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "verify":
        result = verify()
    elif args.command == "seal":
        result = seal()
    elif args.command in {"compare", "compare_traces"}:
        verify()
        from statistics_tools import paired, compare_traces
        comparator = paired if args.command == "compare" else compare_traces
        result = comparator(json.loads(args.candidate.read_text()), json.loads(args.reference.read_text()))
        publish(args.out, result)
    else:
        verify()
        plan = json.loads(args.plan.read_text())
        result = validate_plan(plan)
        if args.command == "run" and args.execute:
            if args.out is None:
                raise ValueError("New --out directory required")
            result = run(plan, args.out)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
