#!/usr/bin/env python3
"""Build review navigation and check artifacts using only the standard library.

Reads the recorded source inventories and current Markdown destinations. Never
imports Tuppi, loads a model/library, or starts a game. Refreshes SOURCE_INDEX.md
and VALIDATION.json in this review directory; does not update source snapshots.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

OUTPUT = Path(__file__).resolve().parents[1]
WORKSPACE = OUTPUT.parents[1]


def load(name):
    return json.loads((OUTPUT / name).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def link(path, label=None):
    return f"[{label or path}](../../{path})"


def definitions(record, maximum=7):
    ds = record.get("definitions", [])
    text = ", ".join(f"`{d['name']}`:{d['line']}" for d in ds[:maximum])
    if len(ds) > maximum:
        text += f"; +{len(ds) - maximum} more"
    return text or "package/constants/imports"


def make_index(snapshot):
    files = snapshot["files"]
    by_root = defaultdict(list)
    for record in files:
        by_root[record["path"].split("/")[0]].append(record)
    out = ["# Source index", "",
           f"Generated from the ending inventory completed **{snapshot['captured_utc']}**. "
           "Navigation covers selected source trees; it does not imply every file was manually reviewed. "
           "Line numbers belong to that inventory and may drift with later work.", "",
           "[Main report](REPORT.md) · [Architecture](ARCHITECTURE.md) · "
           "[Methods](METHODS_AND_EVIDENCE.md) · [Validation](VALIDATION.md)", "",
           "The JSON inventories hold every scoped file hash, Python top-level definition, import list, "
           "line count and Git identity. Python methods inside classes are not separately enumerated. "
           "Docstring flags are a navigation aid, not a documentation-quality score. "
           "Generated data, models, archives, caches and symlink targets are excluded; native research "
           "source copies and duplicated worktrees remain included.", "",
           "## Checkout inventory", "",
           "| Root | Files | Python | C / headers | Swift | Markdown |",
           "|---|---:|---:|---:|---:|---:|"]
    for root, records in sorted(by_root.items()):
        counts = Counter(f["suffix"] for f in records)
        out.append(f"| `{root}` | {len(records):,} | {counts['.py']:,} | "
                   f"{counts['.c']:,} / {counts['.h']:,} | {counts['.swift']:,} | {counts['.md']:,} |")
    groups = snapshot.get("identical_file_groups", [])
    out.extend(["", f"{len(files):,} scoped files; {len(set(f['sha256'] for f in files)):,} distinct "
                f"content hashes; {len(groups):,} repeated-content groups. These are file-level "
                "counts, not independently maintained implementations or semantic duplication measurements.", "",
                "## Current AI modules", "",
                "Paths identify implementation locations. The architecture guide supplies their roles.", "",
                "| Module | Top-level definitions and source lines |",
                "|---|---|"])
    for f in files:
        if f["path"].startswith("TuppiAI/tuppi_ai/") and f["suffix"] == ".py":
            out.append(f"| {link(f['path'], f['path'].removeprefix('TuppiAI/tuppi_ai/'))} | {definitions(f)} |")
    out.extend(["", "## Native source", "", "| File | Lines |", "|---|---:|"])
    for f in files:
        p = Path(f["path"])
        if str(p.parent) == "TuppiAI/native" and f["suffix"] in {".c", ".h"}:
            out.append(f"| {link(f['path'], p.name)} | {f['lines']:,} |")
    out.extend(["", "## Authoritative engine and research packages", "",
                "Current packages are summarized by their package directory. Legacy-only packages "
                "are listed separately to expose approaches absent from the product checkout.", "",
                "| Package | Python modules | Entry point / definitions |", "|---|---:|---|"])
    current_packages = set()
    for root in ("TuppiProject-current", "TuppiProject"):
        packages = defaultdict(list)
        for f in by_root[root]:
            parts = Path(f["path"]).parts
            if len(parts) >= 4 and parts[1] == "src" and f["suffix"] == ".py":
                packages[parts[2]].append(f)
        for package, records in sorted(packages.items()):
            if root == "TuppiProject" and package in current_packages:
                continue
            entries = [r for r in records if Path(r["path"]).name == "__init__.py" and
                       len(Path(r["path"]).parts) == 4]
            entry = (entries or records)[0]
            out.append(f"| `{root}/src/{package}` | {len(records)} | "
                       f"{link(entry['path'], Path(entry['path']).name)}: {definitions(entry, 5)} |")
        if root == "TuppiProject-current":
            current_packages = set(packages)
    out.extend(["", "## Prepared infrastructure checkout", "",
                "Only modules whose content differs from the main AI counterpart are listed here; "
                "a difference is not a validated improvement. Use its implementation reports and "
                "deferred runtime gates before integration.", "",
                "| Module | Top-level definitions and source lines |", "|---|---|"])
    hashes = {f["path"]: f["sha256"] for f in files}
    for f in files:
        if f["path"].startswith("TuppiAI-prior/tuppi_ai/") and f["suffix"] == ".py":
            counterpart = f["path"].replace("TuppiAI-prior/", "TuppiAI/", 1)
            if hashes.get(counterpart) != f["sha256"]:
                out.append(f"| {link(f['path'], f['path'].removeprefix('TuppiAI-prior/tuppi_ai/'))} | {definitions(f)} |")
    out.extend(["", "## Current client source", "", "| File | Lines |", "|---|---:|"])
    for f in files:
        if f["path"].startswith("TuppiClient-current/Sources/") and f["suffix"] == ".swift":
            out.append(f"| {link(f['path'], f['path'].removeprefix('TuppiClient-current/Sources/'))} | {f['lines']:,} |")
    out.extend(["", "## Research entry points", "",
                "- [C0–C5 implementation handoff](../TUPPI_IMPLEMENTATION_HANDOFF.md)",
                "- [C0–C5 implementation output](../tuppi_implementation_output/IMPLEMENTATION_REPORT.md)",
                "- [Self-play research packet](../tuppi_selfplay_research_20260929/TUPPI_SELFPLAY_STRENGTH_MAXIMISATION_PACKET.md)",
                "- [Policy-prior infrastructure](../tuppi_policy_prior_infrastructure_20261002/IMPLEMENTATION_REPORT.md)",
                "- [Checked comparisons and queues](../tuppi_experiment_tools_20261002/IMPLEMENTATION_REPORT.md)",
                "- [CVR/JRPL trial entry](../../tuppi_execution_12h/README.md)",
                "- [Corrected-sampler trial](../../tuppi_execution_sampler_v1/README.md)",
                "", "Regenerate with `python3 -B tools/validate_review.py` from this directory. "
                "It reads saved inventories; a later source inventory needs a new filename and "
                "an explicit change to this script's snapshot selection.", ""])
    (OUTPUT / "SOURCE_INDEX.md").write_text("\n".join(out))


def main():
    earlier, ending, probes = (load(n) for n in (
        "SOURCE_SNAPSHOT.json", "SOURCE_SNAPSHOT_END.json", "SOURCE_PROBES.json"))
    current_probes = {f["id"]: f for f in load("SOURCE_PROBES_CURRENT.json")["findings"]}
    make_index(ending)
    before = {f["path"]: f for f in earlier["files"]}
    after = {f["path"]: f for f in ending["files"]}
    changed = [p for p in sorted(before.keys() & after.keys())
               if before[p]["sha256"] != after[p]["sha256"]]
    git_changes = {}
    for name, repo in ending["repositories"].items():
        old = earlier["repositories"].get(name, {})
        git_changes[name] = {
            "earlier_head": old.get("head", {}).get("stdout", "").strip(),
            "ending_head": repo["head"]["stdout"].strip(),
            "ending_branch": repo["branch"]["stdout"].strip(),
            "ending_status": repo["status"]["stdout"].splitlines()}
    link_errors, checked_links = [], []
    docs = sorted(OUTPUT.glob("*.md"))
    for path in docs:
        body = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
        for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", body):
            target = target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            record = {"document": path.name, "target": target}
            checked_links.append(record)
            if not destination.exists() and destination != OUTPUT / "VALIDATION.json":
                link_errors.append(record)
    probe_checks = []
    for finding in probes["findings"]:
        src = finding["source"]
        current = WORKSPACE / src["path"]
        probe_checks.append({"id": finding["id"], "path": src["path"],
                             "matches_ending_inventory": after[src["path"]]["sha256"] == src["sha256"],
                             "original_matches_current_file": digest(current) == src["sha256"],
                             "latest_probe_matches_current_file": digest(current) == current_probes[finding["id"]]["source"]["sha256"],
                             "latest_probe_source": current_probes[finding["id"]]["source"]})
    script_checks = []
    for path in sorted((OUTPUT / "tools").glob("*.py")):
        ast.parse(path.read_bytes(), filename=str(path))
        script_checks.append({"path": str(path.relative_to(OUTPUT)), "ast_parse": True,
                              "sha256": digest(path)})
    git_errors = [{"repo": name, "operation": operation, "error": value}
                  for name, repo in ending["repositories"].items()
                  for operation, value in repo.items() if value["exit_code"] != 0]
    discovery = "audit_deliverables/tuppi_codebase_review_20261002/REPORT.md"
    discovery_present = discovery in (WORKSPACE / "README.md").read_text()
    inventory_paths_missing = [p for p in after if not (WORKSPACE / p).exists()]
    result = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "source metadata and documentation checks only; no game/native/Torch execution",
        "snapshot_times": {"earlier": earlier.get("captured_utc"),
                           "ending_started": ending.get("started_utc"),
                           "ending_completed": ending.get("captured_utc")},
        "files": {"earlier": len(before), "ending": len(after)},
        "ast_errors": {"earlier": earlier["ast_errors"], "ending": ending["ast_errors"]},
        "source_drift": {"changed": changed, "added": sorted(after.keys() - before.keys()),
                         "removed": sorted(before.keys() - after.keys())},
        "repository_identities": git_changes, "git_read_errors": git_errors,
        "documentation": {"documents": [p.name for p in docs],
                          "checked_local_links": len(checked_links), "broken_links": link_errors,
                          "workspace_readme_link_present": discovery_present},
        "probe_hash_checks": probe_checks, "review_script_checks": script_checks,
        "ending_inventory_paths_missing_now": inventory_paths_missing,
        "passed": (not link_errors and not git_errors and not inventory_paths_missing and
                   not earlier["ast_errors"] and not ending["ast_errors"] and discovery_present and
                   all(p["matches_ending_inventory"] and p["latest_probe_matches_current_file"] for p in probe_checks))}
    (OUTPUT / "VALIDATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
