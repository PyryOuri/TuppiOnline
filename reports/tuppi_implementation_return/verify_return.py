"""Verify this return package: every file against SHA256SUMS.txt, and the manifest's task list.

Usage: python3 verify_return.py        (standard library only; no game code is executed)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    problems = []
    listed = {}
    for line in (ROOT / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    for name, digest in listed.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT):
            problems.append(f"unsafe path {name}")
            continue
        if not path.exists():
            problems.append(f"missing {name}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            problems.append(f"hash mismatch {name}")
    on_disk = {str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()} - {"SHA256SUMS.txt"}
    unlisted = sorted(on_disk - set(listed))
    if unlisted:
        problems.append(f"unlisted files: {unlisted[:5]}")
    manifest = json.loads((ROOT / "RETURN_MANIFEST.json").read_text())
    if len(manifest["tasks"]) != 27:
        problems.append("the manifest does not list all 27 DAG tasks")
    print(json.dumps({"successful": not problems, "problems": problems, "files_checked": len(listed),
                      "tasks": len(manifest["tasks"]), "game_code_executed": False}, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
