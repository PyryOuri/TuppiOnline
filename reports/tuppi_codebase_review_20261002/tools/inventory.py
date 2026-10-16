#!/usr/bin/env python3
"""Read-only, standard-library source inventory; never imports Tuppi modules.

Explicit input trees exclude run data, credentials, build caches and archives.
Symlinks are not followed. Git commands are read-only. Output lives in this
review directory. Re-running creates a new snapshot only when requested.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

WORKSPACE = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parents[1]
REPOS = ("TuppiAI", "TuppiAI-prior", "TuppiAI-sp", "TuppiAI-vn",
         "TuppiAI-perf", "TuppiProject-current", "TuppiProject",
         "TuppiClient-current", "TuppiClient")
TREES = {
    **{name: ("tuppi_ai", "native", "tools", "tests", "docs")
       for name in REPOS if name.startswith("TuppiAI")},
    "TuppiProject-current": ("src", "tests", "docs", "configs", "tools"),
    "TuppiProject": ("src", "tests", "docs", "configs", "tools"),
    "TuppiClient-current": ("Sources", "Tests", "docs", "tools"),
    "TuppiClient": ("Sources", "Tests", "docs", "tools"),
    "tuppi_execution_12h": ("code", "repairs"),
    "tuppi_execution_sampler_v1": ("code", "validation", "native_capture"),
    "tuppi_execution_v2": ("Tuppi_Joint_Partnership_Programme", "tuppi_broad_strength", "tests"),
    "tuppi_execution_v2_output": ("integration",),
    "audit_deliverables/tuppi_selfplay_independent_20260929": (),
}
EXTENSIONS = {".py", ".c", ".h", ".swift", ".sh", ".md", ".toml"}
SKIP = {".git", ".build", "__pycache__", "dist", "runs", "models", "Archive",
        "trajectories", "checkpoints", "outputs", "results", "data", "node_modules"}
ROOT_NAMES = {"README.md", "pyproject.toml", "Package.swift", "Makefile",
              "RESULTS.md", "START_HERE.md", "EXECUTION_PLAN.md", "ADAPTER_CONTRACT.md",
              "PREWORK_REPORT.md", "protocol.json", "GRANT.json", "CODE_IDENTITIES.json"}


def git(directory, *args):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(directory), *args],
                            capture_output=True, text=True, check=False)
    return {"exit_code": result.returncode, "stdout": result.stdout,
            "stderr": result.stderr.strip()}


def paths_under(base):
    if not base.exists() or base.is_symlink():
        return
    for directory, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and
                         not (Path(directory) / d).is_symlink())
        for name in sorted(names):
            p = Path(directory) / name
            if not p.is_symlink() and p.suffix in EXTENSIONS:
                yield p


def snapshot():
    started_utc = datetime.now(timezone.utc).isoformat()
    repos = {}
    for name in REPOS:
        p = WORKSPACE / name
        if p.exists():
            repos[name] = {
                "head": git(p, "rev-parse", "HEAD"),
                "branch": git(p, "branch", "--show-current"),
                "status": git(p, "status", "--porcelain=v1", "--untracked-files=normal"),
                "latest_commit": git(p, "log", "-1", "--format=%H %cI %s"),
            }
    files = []
    errors = []
    all_paths = set()
    for name, trees in TREES.items():
        root = WORKSPACE / name
        for tree in trees:
            all_paths.update(paths_under(root / tree) or ())
        if root.exists():
            all_paths.update(p for p in root.iterdir() if p.is_file() and
                             not p.is_symlink() and
                             (p.name in ROOT_NAMES or p.suffix in {".py", ".sh"}))
    for p in (WORKSPACE / "README.md", WORKSPACE / "AGENTS.md", WORKSPACE / "start_tuppi_server.sh"):
        if p.exists():
            all_paths.add(p)
    for p in sorted(all_paths):
        raw = p.read_bytes()
        record = {"path": str(p.relative_to(WORKSPACE)), "bytes": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest(),
                  "lines": len(raw.splitlines()), "suffix": p.suffix}
        if p.suffix == ".py":
            try:
                tree = ast.parse(raw, filename=str(p))
                record["definitions"] = [
                    {"name": n.name, "line": n.lineno,
                     "kind": type(n).__name__, "documented": ast.get_docstring(n) is not None}
                    for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                record["module_docstring"] = ast.get_docstring(tree) is not None
                record["imports"] = sorted(set(
                    (n.module or "") if isinstance(n, ast.ImportFrom) else alias.name
                    for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                    for alias in (n.names if isinstance(n, ast.Import) else [None])))
            except (SyntaxError, UnicodeDecodeError) as exc:
                errors.append({"path": record["path"], "error": str(exc)})
        files.append(record)
    groups = defaultdict(list)
    for f in files:
        groups[f["sha256"]].append(f["path"])
    counts = defaultdict(Counter)
    lines = defaultdict(Counter)
    for f in files:
        root = f["path"].split("/")[0]
        counts[root][f["suffix"]] += 1
        lines[root][f["suffix"]] += f["lines"]
    return {"started_utc": started_utc, "captured_utc": datetime.now(timezone.utc).isoformat(),
            "workspace": str(WORKSPACE), "scope": "explicit source trees; no runtime imports or games",
            "repositories": repos, "counts": dict(counts), "lines": dict(lines),
            "files": files, "ast_errors": errors,
            "identical_file_groups": [v for v in groups.values() if len(v) > 1]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="SOURCE_SNAPSHOT.json")
    args = parser.parse_args()
    destination = OUTPUT / args.out
    if destination.parent != OUTPUT or destination.exists():
        raise SystemExit("Use a new simple filename inside the review directory.")
    result = snapshot()
    with destination.open("x") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "files": len(result["files"]),
                      "counts": result["counts"], "ast_errors": result["ast_errors"],
                      "repos": {k: {"head": v["head"]["stdout"].strip(),
                                    "branch": v["branch"]["stdout"].strip(),
                                    "status_lines": len(v["status"]["stdout"].splitlines())}
                                for k, v in result["repositories"].items()}}, indent=2))


if __name__ == "__main__":
    main()
