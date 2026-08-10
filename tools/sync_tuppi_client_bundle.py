#!/usr/bin/env python3
"""Synchronize the authoritative fixture bundle into TuppiClient.

The Python exporter is the only writer of the checked-in Swift fixture tree.
``--check`` is read-only and fails when the client copy has drifted. ``--sync``
replaces that exact fixture directory with a freshly exported, validated bundle.
"""

from __future__ import annotations

import argparse
import filecmp
from pathlib import Path
import shutil
import tempfile

from tuppi_ui_fixtures.exporter import export_bundle
from tuppi_ui_fixtures.validation import validate_bundle


CLIENT_BUNDLE_RELATIVE = Path("Sources/TuppiClient/Resources/Fixtures")


class BundleDriftError(RuntimeError):
    """The checked-in Swift bundle differs from the authoritative export."""


def _relative_files(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(path.relative_to(root) for path in root.rglob("*") if path.is_file())
    )


def _assert_identical(expected: Path, actual: Path) -> None:
    expected_files = _relative_files(expected)
    actual_files = _relative_files(actual)
    if expected_files != actual_files:
        missing = sorted(set(expected_files) - set(actual_files))
        extra = sorted(set(actual_files) - set(expected_files))
        raise BundleDriftError(
            "fixture file inventory differs; "
            f"missing={[str(item) for item in missing]}, "
            f"extra={[str(item) for item in extra]}"
        )
    changed = [
        relative
        for relative in expected_files
        if not filecmp.cmp(expected / relative, actual / relative, shallow=False)
    ]
    if changed:
        raise BundleDriftError(
            "fixture contents differ: " + ", ".join(str(item) for item in changed)
        )


def synchronize(client_root: Path, *, check: bool) -> Path:
    client_root = client_root.expanduser().resolve()
    if not (client_root / "Package.swift").is_file():
        raise BundleDriftError(f"not a TuppiClient root: {client_root}")
    target = client_root / CLIENT_BUNDLE_RELATIVE

    with tempfile.TemporaryDirectory(prefix="tuppi-fixture-export-") as raw_temp:
        exported = export_bundle(Path(raw_temp) / "Fixtures")
        validate_bundle(exported)
        if check:
            _assert_identical(exported, target)
            return target

        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.parent / f".{target.name}.sync"
        previous = target.parent / f".{target.name}.previous"
        if staged.exists() or previous.exists():
            raise BundleDriftError(
                "stale synchronization directory exists beside the fixture bundle"
            )
        shutil.copytree(exported, staged)
        validate_bundle(staged)
        if target.exists():
            target.rename(previous)
        try:
            staged.rename(target)
            _assert_identical(exported, target)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if previous.exists():
                previous.rename(target)
            raise
        if previous.exists():
            shutil.rmtree(previous)
        return target


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize the authoritative Python fixture bundle into TuppiClient"
    )
    parser.add_argument("--client-root", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--sync", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    target = synchronize(args.client_root, check=args.check)
    verb = "matches" if args.check else "synchronized"
    print(f"TuppiClient fixture bundle {verb}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
