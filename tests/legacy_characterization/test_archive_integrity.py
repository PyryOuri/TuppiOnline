from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tuppi_legacy.constants import (
    ARTIFACT_ID,
    EMULATOR_RELATIVE_PATH,
    EMULATOR_SHA256,
    GUI_RELATIVE_PATH,
    GUI_SHA256,
)

ROOT = Path(__file__).resolve().parents[2]


def test_frozen_archive_hashes_and_sizes_match_manifest() -> None:
    manifest = json.loads((ROOT / "manifests/legacy_v9.json").read_text(encoding="utf-8"))
    assert manifest["artifact_id"] == ARTIFACT_ID
    entries = {entry["path"]: entry for entry in manifest["artifacts"]}
    expected = {
        EMULATOR_RELATIVE_PATH: (EMULATOR_SHA256, 71435),
        GUI_RELATIVE_PATH: (GUI_SHA256, 16033),
    }
    for relative_path, (expected_hash, expected_size) in expected.items():
        data = (ROOT / relative_path).read_bytes()
        assert len(data) == expected_size
        assert hashlib.sha256(data).hexdigest() == expected_hash
        assert entries[relative_path]["sha256"] == expected_hash
        assert entries[relative_path]["size_bytes"] == expected_size

