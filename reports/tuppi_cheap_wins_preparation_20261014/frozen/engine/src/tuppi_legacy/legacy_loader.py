"""Locate, verify, and import the byte-frozen legacy emulator only."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import sysconfig
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

from .constants import (
    ARTIFACT_ID,
    EMULATOR_RELATIVE_PATH,
    EMULATOR_SHA256,
    GUI_RELATIVE_PATH,
    GUI_SHA256,
    MANIFEST_RELATIVE_PATH,
)
from .errors import ArtifactIntegrityError


@dataclass(frozen=True)
class ArtifactLocation:
    root: Path
    emulator: Path
    gui: Path
    manifest: Path


def _candidate_roots() -> list[Path]:
    candidates: list[Path] = []
    for origin in (Path(__file__).resolve(), Path.cwd().resolve()):
        candidates.extend(origin.parents)
        if origin.is_dir():
            candidates.append(origin)
    data_root = Path(sysconfig.get_path("data")) / "share" / "tuppi-legacy"
    candidates.append(data_root)

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


@lru_cache(maxsize=1)
def locate_artifacts() -> ArtifactLocation:
    for root in _candidate_roots():
        emulator = root / EMULATOR_RELATIVE_PATH
        gui = root / GUI_RELATIVE_PATH
        manifest = root / MANIFEST_RELATIVE_PATH
        if emulator.is_file() and gui.is_file() and manifest.is_file():
            return ArtifactLocation(root=root, emulator=emulator, gui=gui, manifest=manifest)
    raise ArtifactIntegrityError(
        "could not locate Archive/ and manifests/legacy_v9.json; "
        "run from the project checkout or install the package data"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactIntegrityError(f"could not read frozen artifact {path}: {exc}") from exc
    return digest.hexdigest()


@lru_cache(maxsize=1)
def verify_artifacts() -> tuple[ArtifactLocation, dict[str, Any]]:
    location = locate_artifacts()
    try:
        manifest = json.loads(location.manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError(f"could not read legacy manifest: {exc}") from exc

    if manifest.get("artifact_id") != ARTIFACT_ID:
        raise ArtifactIntegrityError(
            f"manifest artifact_id must be {ARTIFACT_ID!r}"
        )
    entries = {
        entry.get("path"): entry
        for entry in manifest.get("artifacts", [])
        if isinstance(entry, dict)
    }
    expected = (
        (location.emulator, EMULATOR_RELATIVE_PATH, EMULATOR_SHA256),
        (location.gui, GUI_RELATIVE_PATH, GUI_SHA256),
    )
    for path, relative_path, expected_hash in expected:
        entry = entries.get(relative_path)
        if entry is None:
            raise ArtifactIntegrityError(f"manifest is missing {relative_path}")
        actual_size = path.stat().st_size
        if entry.get("size_bytes") != actual_size:
            raise ArtifactIntegrityError(
                f"size mismatch for {relative_path}: manifest={entry.get('size_bytes')}, actual={actual_size}"
            )
        actual_hash = _sha256(path)
        if entry.get("sha256") != expected_hash or actual_hash != expected_hash:
            raise ArtifactIntegrityError(
                f"SHA-256 mismatch for immutable artifact {relative_path}: {actual_hash}"
            )
    return location, manifest


@lru_cache(maxsize=1)
def load_legacy_module() -> ModuleType:
    location, _ = verify_artifacts()
    module_name = "_tuppi_frozen_legacy_v9"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing

    spec = importlib.util.spec_from_file_location(module_name, location.emulator)
    if spec is None or spec.loader is None:
        raise ArtifactIntegrityError(
            f"could not construct import specification for {location.emulator}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module

