"""Reduce a 24 MB correctness capture to a committable per-section manifest."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      default=str).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def main() -> int:
    source = Path(sys.argv[1])
    data = json.loads(source.read_text())
    rows: dict[str, object] = {
        "capture_file_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "capture_bytes": source.stat().st_size,
    }
    batch = data["engine_batch"]
    rows["engine_batch"] = {
        "deals": len(batch),
        "trace_steps": sum(len(row["trace"]) for row in batch),
        "actions": sum(row["actions"] for row in batch),
        "action_digests": [row["action_digest"] for row in batch],
        "resolved": [row["resolved"] for row in batch],
        # Timing sections are excluded: they are the measured quantity.
        "trace_digest": digest([row["trace"] for row in batch]),
        "deal_result_digest": digest([row["deal_result"] for row in batch]),
    }
    rows["full_matches"] = {
        "count": len(data["full_matches"]),
        "deals": [row["deals"] for row in data["full_matches"]],
        "terminal": [row["terminal"] for row in data["full_matches"]],
        "digest": digest(data["full_matches"]),
    }
    rows["rejections"] = {
        "cases": len(data["rejections"]),
        "classes": sorted({row["raised"] for row in data["rejections"].values()
                           if row["raised"]}),
        "accepted": sorted(key for key, row in data["rejections"].items()
                           if row["raised"] is None),
        "digest": digest(data["rejections"]),
    }
    rows["uct"] = {
        "rows": len(data["uct"]),
        "digest": digest(data["uct"]),
        "per_row": {f"{row['position']}/{row['budget']}": digest(row["decision"])
                    for row in data["uct"]},
    }
    rows["live_messages"] = {
        "groups": len(data["live_messages"]),
        "digest": digest(data["live_messages"]),
    }
    rows["completed_review"] = data["completed_review"]
    Path(sys.argv[2]).write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(f"{sys.argv[2]} written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
