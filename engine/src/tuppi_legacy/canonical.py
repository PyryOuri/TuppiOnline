"""Canonical JSON helpers used for stable IDs and JSONL output."""

from __future__ import annotations

import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically without presentation-only whitespace."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_json_line(value: Any) -> str:
    return canonical_json(value) + "\n"

