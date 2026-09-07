"""Compare two harness captures and locate the first structural difference."""
from __future__ import annotations

import json
import sys
from pathlib import Path

IGNORED_TOP_LEVEL = {"src", "python", "platform", "machine", "reps"}
# Wall/CPU section timings are the point of the change, not part of the contract.
IGNORED_KEYS = {"sections"}


def walk(left, right, path=""):
    if type(left) is not type(right):
        yield path, f"type {type(left).__name__} vs {type(right).__name__}"
        return
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key in IGNORED_KEYS:
                continue
            if key not in left:
                yield f"{path}/{key}", "missing on the left"
            elif key not in right:
                yield f"{path}/{key}", "missing on the right"
            else:
                yield from walk(left[key], right[key], f"{path}/{key}")
        return
    if isinstance(left, list):
        if len(left) != len(right):
            yield path, f"length {len(left)} vs {len(right)}"
        for index, (a, b) in enumerate(zip(left, right)):
            yield from walk(a, b, f"{path}[{index}]")
        return
    if left != right:
        yield path, f"{left!r} vs {right!r}"


def main() -> int:
    left = json.loads(Path(sys.argv[1]).read_text())
    right = json.loads(Path(sys.argv[2]).read_text())
    for key in IGNORED_TOP_LEVEL:
        left.pop(key, None)
        right.pop(key, None)
    differences = list(walk(left, right))
    if not differences:
        print(f"IDENTICAL: {sys.argv[1]} == {sys.argv[2]} "
              f"(excluding {sorted(IGNORED_TOP_LEVEL)})")
        return 0
    print(f"{len(differences)} DIFFERENCE(S)")
    for path, detail in differences[:60]:
        print(f"  {path}: {detail}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
