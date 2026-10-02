"""Frozen, sequential evaluation queues. Default run is a dry run; no Torch/native imports."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from .experiment_io import canonical, digest, file_digest, read_json, write_json
from .paired_results import CONTEXT_SCHEMA, RESULT_SCHEMA, compare, validate_result

PLAN_SCHEMA = "tuppi.experiment_plan.v1"
FROZEN_SCHEMA = "tuppi.frozen_queue.v1"
STATE_SCHEMA = "tuppi.queue_state.v1"
RETRYABLE = {"failed", "interrupted", "timed_out"}
SEARCH_KEYS = set("w dd show keep prior keep_adaptive record_prior bp rb sw eq rs adb adz add adp team sf ddn belief bt be bs ot bn bN ba vn vlb vlp vbb".split())


def _search_options(parts):
    opts = dict(part.split("=", 1) for part in parts)
    bools = {"keep_adaptive", "record_prior", "eq", "rs", "adp", "sf", "vbb"}
    ints = {"w", "dd", "show", "sw", "adb", "ddn", "belief", "bN", "vlb", "vlp"} | bools
    floats = SEARCH_KEYS - ints - {"bp", "team", "bn", "vn", "bs"}
    numbers = {}
    for key in ints & opts.keys():
        numbers[key] = int(opts[key])
        if key in bools and numbers[key] not in (0, 1):
            raise ValueError(f"{key} must be 0 or 1")
        if key in {"w", "sw", "bN"} and numbers[key] < 1:
            raise ValueError(f"{key} must be positive")
        if key in {"dd", "ddn", "belief"} and numbers[key] < 0:
            raise ValueError(f"{key} must be nonnegative")
        if key == "show" and numbers[key] not in (0, 1, 2):
            raise ValueError("show must be 0, 1 or 2")
        if key in {"vlb", "vlp"} and numbers[key] < -1:
            raise ValueError(f"{key} must be -1 or nonnegative")
    for key in floats & opts.keys():
        numbers[key] = float(opts[key])
        if not math.isfinite(numbers[key]):
            raise ValueError(f"{key} must be finite")
    if any(numbers.get(key, 0) < 0 for key in ("keep", "prior", "adz", "add", "ba", "ot")):
        raise ValueError("prior/margins and adaptive/temperature parameters must be nonnegative")
    if numbers.get("bt", 1) <= 0 or not 0 <= numbers.get("be", 0.1) <= 1:
        raise ValueError("belief temperature must be positive and epsilon between 0 and 1")
    if any(numbers.get(key, 0) > 13 for key in ("dd", "ddn")):
        raise ValueError("solver tail lengths cannot exceed 13 tricks")
    if opts.get("bs", "all") not in {"all", "opp"}:
        raise ValueError("belief seats must be all or opp")
    if "adb" in numbers:
        batch = numbers["adb"]
        if batch < 2 or any(cap < batch or cap % batch for cap in (numbers.get("w", 32), numbers.get("sw", numbers.get("w", 32)))):
            raise ValueError("adaptive caps must be positive multiples of a batch >= 2")
    if "prior" in numbers and ("keep" in numbers or numbers.get("keep_adaptive")):
        raise ValueError("soft prior and fixed keep are separate arms")
    if numbers.get("keep_adaptive") and "keep" not in numbers:
        raise ValueError("keep_adaptive needs a keep margin")
    if ("prior" in numbers or numbers.get("keep_adaptive")) and (numbers.get("eq") or numbers.get("rb") or numbers.get("show") == 2):
        raise ValueError("prior arms require all legal candidates and no RAMI bonus")
    return numbers


def _positive(value, name, *, integer=False, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= minimum:
        raise ValueError(f"{name} must be finite and > {minimum}")
    if integer and type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


def _path(value, base):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("nonempty path required")
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def _input(path, roots):
    if not any(path.is_relative_to(root) for root in roots):
        raise ValueError(f"input outside checkout/engine: {path}")
    if not path.is_file():
        raise ValueError(f"missing input: {path}")
    return path


def _spec(spec, checkout, engine, *, opponent=False):
    if not isinstance(spec, str) or not spec or "\x00" in spec:
        raise ValueError("nonempty agent spec required")
    roots, inputs = (checkout, engine), []

    def model(value):
        p = _input(_path(value, checkout), roots)
        inputs.append(p)
        return str(p)

    if spec == "best":
        raise ValueError("expand best into an explicit search spec to freeze its configuration")
    if spec.startswith("search:"):
        parts = spec.split(":")
        if len(parts) < 2:
            raise ValueError("missing search model")
        parts[1] = model(parts[1])
        seen = set()
        for i in range(2, len(parts)):
            key, sep, value = parts[i].partition("=")
            if not sep or key not in SEARCH_KEYS or key in seen or not value:
                raise ValueError(f"unknown/duplicate/malformed search option: {parts[i]}")
            seen.add(key)
            if key in {"bp", "team", "bn", "vn"}:
                parts[i] = f"{key}={model(value)}"
        _search_options(parts[2:])
        return ":".join(parts), inputs
    if not opponent and spec.startswith("cons:"):
        parts = spec.split(":")
        if len(parts) < 3:
            raise ValueError("conservative policy needs two checkpoints")
        parts[1:3] = [model(p) for p in parts[1:3]]
        seen = set()
        for part in parts[3:]:
            key, sep, value = part.partition("=")
            if not sep or key not in {"m", "show"} or key in seen or not value:
                raise ValueError("unknown/duplicate/malformed conservative-policy option")
            seen.add(key)
            if key == "m" and not math.isfinite(float(value)):
                raise ValueError("conservative margin must be finite")
            if key == "show" and value not in {"bp", "q"}:
                raise ValueError("conservative showing must be bp or q")
        return ":".join(parts), inputs
    if spec.startswith("profile:"):
        name = spec.split(":", 1)[1]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("nonempty profile key required")
        return (name if opponent else spec), inputs
    if not opponent and spec.startswith("heur:"):
        return spec, inputs
    if opponent:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", spec):
            raise ValueError("opponent must be an incumbent profile or explicit search spec")
        return spec, inputs
    return model(spec), inputs


def normalize(plan: dict, base: Path) -> tuple[dict, list[Path]]:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("wrong experiment-plan schema")
    allowed = {"schema", "checkout", "engine", "python", "equity", "budget_wall_seconds", "max_workers", "jobs", "extra_inputs"}
    if set(plan) - allowed:
        raise ValueError(f"unknown plan fields: {sorted(set(plan) - allowed)}")
    checkout, engine = (_path(plan[k], base) for k in ("checkout", "engine"))
    if not (checkout / "tuppi_ai").is_dir() or not (engine / "src" / "tuppi_engine").is_dir():
        raise ValueError("checkout and canonical engine source directories are required")
    roots = (checkout, engine)
    equity = _input(_path(plan["equity"], checkout), roots)
    python = plan.get("python", sys.executable)
    if not isinstance(python, str) or not Path(python).is_absolute() or "\x00" in python:
        raise ValueError("python must be an absolute executable path (no shell command)")
    budget = _positive(plan["budget_wall_seconds"], "budget_wall_seconds")
    workers = _positive(plan["max_workers"], "max_workers", integer=True)
    rows = plan.get("jobs")
    if not isinstance(rows, list) or not rows:
        raise ValueError("nonempty job list required")
    jobs, ids, inputs = [], set(), [equity]
    for raw in rows:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", raw["id"]):
            raise ValueError("job ids must contain only letters, digits, underscore or hyphen")
        if raw["id"] in ids:
            raise ValueError("duplicate job id")
        ids.add(raw["id"])
        kind = raw.get("kind")
        common = {"id", "kind", "depends_on", "wall_seconds"}
        fields = {"candidate", "opponent", "seed", "ruleset", "scores", "samples", "workers"} if kind == "deal_eval" else {"candidate_result", "reference_result"} if kind == "paired_analysis" else None
        if fields is None or set(raw) - common - fields:
            raise ValueError("unsupported job kind or unknown fields")
        job = {"id": raw["id"], "kind": kind,
               "wall_seconds": _positive(raw["wall_seconds"], "job wall_seconds")}
        deps = raw.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ValueError("dependencies must be unique job ids")
        job["depends_on"] = list(deps)
        if kind == "deal_eval":
            for key in ("candidate", "opponent"):
                job[key], files = _spec(raw[key], checkout, engine, opponent=key == "opponent")
                inputs.extend(files)
            if all(job[k].startswith("search:") for k in ("candidate", "opponent")):
                settings = [_search_options(job[k].split(":")[2:]) for k in ("candidate", "opponent")]
                if any(settings[0].get(k, 0) != settings[1].get(k, 0) for k in ("sf", "ddn")):
                    raise ValueError("searched sides must share sampler/NOLO-tail settings")
            job["samples"] = _positive(raw["samples"], "samples", integer=True, minimum=1)
            job["workers"] = _positive(raw["workers"], "workers", integer=True)
            if job["workers"] > workers:
                raise ValueError("job worker count exceeds max_workers")
            if raw.get("ruleset") not in ("v1", "v2", "v3") or raw.get("scores") not in ("zero", "uniform"):
                raise ValueError("explicit ruleset and starting-score mode required")
            if not isinstance(raw.get("seed"), str) or not raw["seed"]:
                raise ValueError("explicit seed required")
            job.update({key: raw[key] for key in ("seed", "ruleset", "scores")})
        else:
            for key in ("candidate_result", "reference_result"):
                if not isinstance(raw.get(key), str):
                    raise ValueError("analysis must reference evaluation job ids")
                job[key] = raw[key]
                if raw[key] not in job["depends_on"]:
                    job["depends_on"].append(raw[key])
        jobs.append(job)
    by_id = {j["id"]: j for j in jobs}
    visited, active = set(), set()

    def visit(identity):
        if identity not in by_id:
            raise ValueError(f"unknown dependency: {identity}")
        if identity in active:
            raise ValueError("cyclic job dependencies")
        if identity in visited:
            return
        active.add(identity)
        for dep in by_id[identity]["depends_on"]:
            visit(dep)
        active.remove(identity)
        visited.add(identity)

    for job in jobs:
        visit(job["id"])
        if job["kind"] == "paired_analysis":
            a, b = (by_id[job[k]] for k in ("candidate_result", "reference_result"))
            keys = ("seed", "ruleset", "scores", "opponent", "samples", "workers")
            if any(j["kind"] != "deal_eval" for j in (a, b)) or any(a[k] != b[k] for k in keys):
                raise ValueError("paired jobs must share opponent, samples, seed, rules, scores and workers")
    extra = plan.get("extra_inputs", [])
    if not isinstance(extra, list):
        raise ValueError("extra_inputs must be a list")
    extra = sorted(set(_input(_path(p, checkout), roots) for p in extra))
    inputs.extend(extra)
    normalized = {"schema": PLAN_SCHEMA, "checkout": str(checkout), "engine": str(engine), "python": python,
                  "equity": str(equity), "budget_wall_seconds": budget, "max_workers": workers, "jobs": jobs,
                  "extra_inputs": [str(p) for p in extra]}
    return normalized, sorted(set(inputs))


def _source_inputs(plan):
    root, engine = Path(plan["checkout"]), Path(plan["engine"])
    files = list((root / "tuppi_ai").rglob("*.py")) + list((engine / "src").rglob("*.py"))
    files += list((engine / "configs" / "rules").glob("*.json"))
    files += [p for p in (root / "native").iterdir() if p.suffix in {".c", ".h", ".sh"}]
    files.append(root / "native" / "libtuppi.dylib")
    return [_input(p.resolve(), (root, engine)) for p in sorted(set(files))]


def prepare(plan_path: Path, directory: Path):
    plan, inputs = normalize(read_json(plan_path), plan_path.resolve().parent)
    directory = directory.resolve()
    if not directory.is_relative_to(Path(plan["checkout"]) / "runs"):
        raise ValueError("queue directory must be inside this checkout's runs directory")
    if directory.exists():
        raise ValueError("queue directory exists; preserve it and choose a fresh directory")
    files = sorted(set(inputs + _source_inputs(plan)))
    frozen = {"schema": FROZEN_SCHEMA, "plan": plan,
              "inputs": {str(p): file_digest(p) for p in files}}
    frozen["fingerprint"] = digest(frozen)
    state = {"schema": STATE_SCHEMA, "fingerprint": frozen["fingerprint"], "wall_charged_seconds": 0.0,
             "jobs": {j["id"]: {"status": "pending", "attempts": []} for j in plan["jobs"]}}
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "frozen.json", frozen, replace=False)
    write_json(directory / "state.json", state, replace=False)
    return frozen


def load(directory: Path):
    frozen, state = (read_json(directory / name) for name in ("frozen.json", "state.json"))
    if frozen.get("schema") != FROZEN_SCHEMA or state.get("schema") != STATE_SCHEMA:
        raise ValueError("wrong queue schema")
    payload = {k: v for k, v in frozen.items() if k != "fingerprint"}
    if digest(payload) != frozen.get("fingerprint") or state.get("fingerprint") != frozen["fingerprint"]:
        raise ValueError("frozen configuration changed or state belongs to another queue")
    expected = {j["id"] for j in frozen["plan"]["jobs"]}
    if set(state["jobs"]) != expected:
        raise ValueError("state job set differs from frozen configuration")
    charge = state.get("wall_charged_seconds")
    if isinstance(charge, bool) or not isinstance(charge, (int, float)) or not math.isfinite(charge) or charge < 0:
        raise ValueError("invalid budget accounting")
    accounted = []
    for identity, row in state["jobs"].items():
        if row.get("status") not in {"pending", "running", "completed", *RETRYABLE} or not isinstance(row.get("attempts"), list):
            raise ValueError("invalid job state")
        for number, attempt in enumerate(row["attempts"], 1):
            if attempt.get("status") not in {"running", "completed", *RETRYABLE}:
                raise ValueError("invalid attempt state")
            _positive(attempt["allocated_seconds"], "reserved timeout")
            if attempt.get("directory") != f"attempts/{identity}/{number}":
                raise ValueError("attempt directory does not match queue history")
            pid = attempt.get("pid")
            if pid is not None and (type(pid) is not int or pid < 1):
                raise ValueError("invalid child process identity")
            elapsed = attempt.get("elapsed_seconds")
            if elapsed is not None and (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0):
                raise ValueError("invalid elapsed attempt time")
            accounted.append(elapsed if elapsed is not None else attempt["allocated_seconds"])
        if row["status"] != "pending" and (not row["attempts"] or row["attempts"][-1]["status"] != row["status"]):
            raise ValueError("job state and last attempt disagree")
        if row["status"] == "pending" and row["attempts"] and row["attempts"][-1]["status"] not in RETRYABLE:
            raise ValueError("only failed/interrupted attempts may be returned to pending")
    if not math.isclose(charge, math.fsum(accounted), rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError("budget accounting disagrees with attempt history")
    return frozen, state


def verify_inputs(frozen):
    for name, expected in frozen["inputs"].items():
        if file_digest(Path(name)) != expected:
            raise ValueError(f"frozen input changed: {name}")
    # Detect added source files too, not only modifications/deletions.
    if not set(map(str, _source_inputs(frozen["plan"]))).issubset(frozen["inputs"]):
        raise ValueError("new source files appeared after freezing")


@contextmanager
def _lock(directory):
    with (directory / "queue.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise ValueError("another runner owns this queue") from e
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        if not _group_alive(process.pid):
            break
    process.wait()


def _launch(argv, cwd, env, log, timeout, started):
    # The actual workload cannot start until the parent has durably saved its
    # PID. This closes the otherwise ambiguous crash window immediately after Popen.
    token = secrets.token_hex(16)
    spec_path = log.parent / "launch.json"
    write_json(spec_path, {"argv": argv, "parent_pid": os.getpid(), "token": token}, replace=False)
    with log.open("xb") as stream:
        process = subprocess.Popen([argv[0], "-m", "tuppi_ai.experiment_worker", str(spec_path)],
                                   cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            started(process.pid)
            write_json(log.parent / "go.json", {"token": token}, replace=False)
            code = process.wait(timeout=timeout)
            if _group_alive(process.pid):
                _stop(process)  # an exited parent must not leave an orphaned evaluator running
            return {"status": "completed" if code == 0 else "failed", "returncode": code}
        except subprocess.TimeoutExpired:
            _stop(process)
            return {"status": "timed_out", "returncode": process.returncode}
        except KeyboardInterrupt:
            _stop(process)
            return {"status": "interrupted", "returncode": process.returncode}
        except BaseException:
            _stop(process)
            raise


def command(job, plan, state, directory, output):
    if job["kind"] == "deal_eval":
        return [plan["python"], "-m", "tuppi_ai.evaluate", "--checkpoint", job["candidate"],
                "--opponent", job["opponent"], "--deals", str(job["samples"]), "--seed", job["seed"],
                "--ruleset", job["ruleset"], "--scores", job["scores"], "--workers", str(job["workers"]),
                "--equity-path", plan["equity"], "--out", str(output)]
    files = [directory / state["jobs"][job[k]]["result"] for k in ("candidate_result", "reference_result")]
    return [plan["python"], "-m", "tuppi_ai.paired_results", *map(str, files), "--out", str(output)]


def _check_completed(state, directory):
    for row in state["jobs"].values():
        if row["status"] == "completed":
            path = (directory / row["result"]).resolve()
            if not path.is_relative_to(directory.resolve()) or file_digest(path) != row["result_sha256"]:
                raise ValueError("completed result is missing or changed; refusing reuse")


def _evaluation_context(job, frozen):
    """Attest shared inputs separately from the intentionally changed candidate."""
    plan = frozen["plan"]
    checkout, engine = Path(plan["checkout"]), Path(plan["engine"])
    _, candidate = _spec(job["candidate"], checkout, engine)
    _, opponent = _spec(job["opponent"], checkout, engine, opponent=True)
    common = _source_inputs(plan) + opponent + [Path(plan["equity"])]
    common += [Path(p) for p in plan["extra_inputs"]]

    def fingerprint(paths):
        return digest({str(p): frozen["inputs"][str(p)] for p in sorted(set(paths))})

    return {"schema": CONTEXT_SCHEMA, "inputs_sha256": fingerprint(common),
            "candidate_inputs_sha256": fingerprint(candidate), "inventory_sha256": digest(frozen["inputs"]),
            "workers": job["workers"], "design": "4_rotations_2_teams",
            "chunksize": 8, "controller_state": "persistent_per_worker"}


def _validate_output(result, job, frozen, state, directory):
    if job["kind"] == "deal_eval":
        validate_result(result, allow_legacy=True)
        expected = {"candidate": job["candidate"], "opponent": job["opponent"], "seed": job["seed"],
                    "scores": job["scores"], "ruleset": f"project_target_{job['ruleset']}", "base_deals": job["samples"]}
        if result.get("schema") != RESULT_SCHEMA or any(result.get(k) != v for k, v in expected.items()):
            raise ValueError("worker result does not match its frozen job")
        result["evaluation_context"] = _evaluation_context(job, frozen)
        validate_result(result)
    else:
        a, b = (read_json(directory / state["jobs"][job[k]]["result"]) for k in ("candidate_result", "reference_result"))
        if canonical(result) != canonical(compare(a, b)):
            raise ValueError("analysis output does not match its frozen dependencies")
    return result


def inspect(directory):
    frozen, state = load(directory)
    return {"fingerprint": frozen["fingerprint"], "budget_wall_seconds": frozen["plan"]["budget_wall_seconds"],
            "wall_charged_seconds": state["wall_charged_seconds"],
            "remaining_wall_seconds": max(0.0, frozen["plan"]["budget_wall_seconds"] - state["wall_charged_seconds"]),
            "jobs": {k: {"status": row["status"], "attempts": len(row["attempts"]),
                         "result": row.get("result"),
                         "last_error": row["attempts"][-1].get("error") if row["attempts"] else None}
                     for k, row in state["jobs"].items()},
            "execution": "dry run unless --execute is explicitly passed"}


def run(directory: Path, *, execute=False, retry_failed=False, launch=_launch, clock=time.monotonic):
    directory = directory.resolve()
    if not execute:
        return inspect(directory)
    with _lock(directory):
        frozen, state = load(directory)
        verify_inputs(frozen)
        _check_completed(state, directory)
        for row in state["jobs"].values():
            if row["status"] == "running":
                attempt = row["attempts"][-1]
                if attempt.get("pid") is not None and _group_alive(attempt["pid"]):
                    raise ValueError("an interrupted runner may still have a child process; stop/inspect its recorded process group before resuming")
                if attempt.get("pid") is None and (directory / attempt["directory"] / "go.json").exists():
                    raise ValueError("launch acknowledgement exists without a recorded child identity; manual recovery required")
                row["status"] = attempt["status"] = "interrupted"
                attempt["error"] = "Runner vanished; full reserved timeout remains charged."
            if retry_failed and row["status"] in RETRYABLE:
                row["status"] = "pending"
        write_json(directory / "state.json", state)
        plan = frozen["plan"]
        env = os.environ.copy()
        env.update(PYTHONPATH=os.pathsep.join([str(Path(plan["engine"]) / "src"), plan["checkout"]]),
                   PYTHONHASHSEED="0", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
        while True:
            ready = [j for j in plan["jobs"] if state["jobs"][j["id"]]["status"] == "pending"
                     and all(state["jobs"][d]["status"] == "completed" for d in j["depends_on"])]
            remaining = plan["budget_wall_seconds"] - state["wall_charged_seconds"]
            if not ready or remaining <= 0:
                break
            job = ready[0]
            row = state["jobs"][job["id"]]
            timeout = min(job["wall_seconds"], remaining)
            attempt_dir = directory / "attempts" / job["id"] / str(len(row["attempts"]) + 1)
            attempt_dir.mkdir(parents=True, exist_ok=False)
            partial, result_path = attempt_dir / "worker.json", attempt_dir / "result.json"
            argv = command(job, plan, state, directory, partial)
            attempt = {"status": "running", "allocated_seconds": timeout, "pid": None, "argv": argv,
                       "directory": str(attempt_dir.relative_to(directory))}
            row["attempts"].append(attempt)
            row["status"] = "running"
            state["wall_charged_seconds"] += timeout  # reserve BEFORE launching; crashes cannot restore the budget
            write_json(directory / "state.json", state)
            t0 = clock()

            def started(pid):
                attempt["pid"] = pid
                write_json(directory / "state.json", state)

            try:
                outcome = launch(argv, plan["checkout"], env, attempt_dir / "process.log", timeout, started)
                attempt.update(outcome)
                if outcome["status"] == "completed":
                    verify_inputs(frozen)
                    _check_completed(state, directory)
                    result = _validate_output(read_json(partial), job, frozen, state, directory)
                    result["experiment"] = {"queue_fingerprint": frozen["fingerprint"], "job": job["id"],
                                             "attempt": len(row["attempts"])}
                    write_json(result_path, result, replace=False)
                    row["result"] = str(result_path.relative_to(directory))
                    row["result_sha256"] = file_digest(result_path)
            except KeyboardInterrupt:
                attempt.update(status="interrupted", error="Interrupted during result validation.")
            except Exception as e:
                attempt.update(status="failed", error=str(e))
            elapsed = max(0.0, clock() - t0)
            attempt["elapsed_seconds"] = elapsed
            state["wall_charged_seconds"] += elapsed - timeout
            row["status"] = attempt["status"]
            write_json(directory / "state.json", state)
            if row["status"] != "completed":
                break  # retry is always explicit; partial/failed output is never reused
        return inspect(directory)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="action", required=True)
    preview = commands.add_parser("preview", help="validate configuration; no hashes or workloads")
    preview.add_argument("plan", type=Path)
    create = commands.add_parser("prepare", help="freeze configuration and input hashes; no workloads")
    create.add_argument("plan", type=Path)
    create.add_argument("directory", type=Path)
    status = commands.add_parser("status")
    status.add_argument("directory", type=Path)
    runner = commands.add_parser("run", help="dry run by default; execute only when compute is available")
    runner.add_argument("directory", type=Path)
    runner.add_argument("--execute", action="store_true")
    runner.add_argument("--retry-failed", action="store_true")
    args = p.parse_args()
    try:
        if args.action == "preview":
            plan, inputs = normalize(read_json(args.plan), args.plan.resolve().parent)
            result = {"plan": plan, "model_and_equity_inputs": list(map(str, inputs)), "execution": "not started"}
        elif args.action == "prepare":
            prepare(args.plan, args.directory)
            result = inspect(args.directory)
        elif args.action == "status":
            result = inspect(args.directory)
        else:
            result = run(args.directory, execute=args.execute, retry_failed=args.retry_failed)
    except (ValueError, OSError, KeyError, TypeError) as e:
        p.error(str(e))
    print(canonical(result).decode())
    if args.action == "run" and args.execute and any(row["status"] != "completed" for row in result["jobs"].values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
