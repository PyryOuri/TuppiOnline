"""Research command line (C0.07).

    python -m tuppi_ai.research.cli protect-check     # A12: protected paths unchanged since the baseline
    python -m tuppi_ai.research.cli ledger            # contract-stage resource totals vs caps
    python -m tuppi_ai.research.cli validate-manifest research/c1_pilot_manifest.json
    python -m tuppi_ai.research.cli state [TASK STATUS]

`validate-manifest` never launches anything: it reports whether a manifest is
complete AND enabled AND approved. Every package pilot manifest is disabled,
so it reports NOT_LAUNCHABLE with the missing fields.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .identity import OUTPUT_DIR

STATE = OUTPUT_DIR / "IMPLEMENTATION_STATE.json"
STATUSES = ("NOT_STARTED", "IN_PROGRESS", "IMPLEMENTED_NOT_TESTED", "CONTRACT_PASS", "PILOT_READY",
            "PILOT_COMPLETE", "BLOCKED", "NOT_AUTHORISED", "REJECTED", "CONFIRMATION_PASS")
REQUIRED_FOR_LAUNCH = ("approval", "candidate_id", "baseline_id", "native_build_ids", "source_hashes",
                       "lifecycle_contract", "policy_factories_by_seat", "opponent_population", "score_distribution",
                       "estimator_version", "required_sample_size", "sample_size_basis", "cpu_seconds_cap",
                       "wall_seconds_cap", "memory_bytes_cap", "max_workers", "max_native_concurrency",
                       "futility_rule", "independent_reference_plan", "reference_noise_adjustment",
                       "seed_namespace", "stream_protocol", "result_path")


def protect_check() -> dict:
    from .identity import compare_protected, protected_snapshot

    before = json.loads((OUTPUT_DIR / "research" / "protected_snapshot_before.json").read_text())
    after = protected_snapshot()
    problems = compare_protected(before, after)
    out = {"schema": "tuppi.research.protect_check.v1", "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "unchanged": not problems, "problems": problems,
           "checked": ["installed dylib, model and equity hashes", "every tracked AI file",
                       "HEAD/branch of AI, ENGINE, RESEARCH, CLIENT", "every dirty/untracked file of other authors",
                       "both input packages", "stat metadata of TuppiAI/runs (contents never read)"],
           "not_read": after["private_excluded_not_read"]}
    (OUTPUT_DIR / "logs" / "protect_check.json").write_text(json.dumps(out, indent=1))
    return out


def validate_manifest(path: Path) -> dict:
    m = json.loads(Path(path).read_text())
    missing = [k for k in REQUIRED_FOR_LAUNCH if m.get(k) in (None, "", [], {}, "REQUIRES_APPROVAL")]
    splits = m.get("splits") or {}
    split_missing = [k for k in ("FIT", "PLAN", "SCREEN", "CONFIRM") if not splits.get(k)]
    if splits.get("parent_overlap_allowed", False):
        missing.append("splits.parent_overlap_allowed must be false")
    namespaces = [splits.get(k, {}).get("parent_namespace") for k in ("FIT", "PLAN", "SCREEN", "CONFIRM")
                  if isinstance(splits.get(k), dict)]
    if len(namespaces) != len(set(namespaces)):
        missing.append("split parent namespaces overlap")
    launchable = bool(m.get("execution_enabled")) and not missing and not split_missing
    return {"manifest": str(path), "execution_enabled": bool(m.get("execution_enabled")),
            "missing_for_launch": missing + [f"splits.{k}" for k in split_missing],
            "verdict": "LAUNCHABLE" if launchable else "NOT_LAUNCHABLE"}


def set_state(task: str, status: str, evidence: list[str] | None = None, blockers: list[str] | None = None,
              note: str | None = None, owner_approval: str | None = None) -> None:
    """`owner_approval` (who/when/scope) is required to move a package-disabled task past NOT_AUTHORISED."""
    if status not in STATUSES:
        raise ValueError(status)
    state = json.loads(STATE.read_text())
    for t in state["tasks"]:
        if t["id"] == task:
            if (not t.get("execution_enabled_in_package", True) and status not in ("NOT_AUTHORISED", "BLOCKED")
                    and not owner_approval):
                raise PermissionError(f"{task} is disabled in the package; it stays NOT_AUTHORISED")
            if owner_approval:
                t["owner_approval"] = owner_approval
            t["status"] = status
            if evidence is not None:
                t["evidence"] = evidence
            if blockers is not None:
                t["blockers"] = blockers
            if note is not None:
                t["note"] = note
            break
    else:
        raise KeyError(task)
    state["updated"] = time.strftime("%Y-%m-%d")
    STATE.write_text(json.dumps(state, indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("protect-check")
    sub.add_parser("ledger")
    v = sub.add_parser("validate-manifest")
    v.add_argument("path", type=Path)
    s = sub.add_parser("state")
    s.add_argument("task", nargs="?")
    s.add_argument("status", nargs="?")
    args = parser.parse_args()
    if args.cmd == "protect-check":
        out = protect_check()
        print(json.dumps(out, indent=1))
        sys.exit(0 if out["unchanged"] else 1)
    if args.cmd == "ledger":
        from .ledger import summary

        print(json.dumps(summary(), indent=1))
    elif args.cmd == "validate-manifest":
        print(json.dumps(validate_manifest(args.path), indent=1))
    elif args.cmd == "state":
        if args.task and args.status:
            set_state(args.task, args.status)
        for t in json.loads(STATE.read_text())["tasks"]:
            print(f"{t['id']:8s} {t['status']}")


if __name__ == "__main__":
    main()
