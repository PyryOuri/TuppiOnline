"""Strict validation for the authoritative network and fixture contracts.

The live server deliberately does not depend on JSON Schema at runtime.  This
module belongs to the fixture/development layer and is used by export tests,
bundle synchronization, and release checks.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from tuppi_engine import strict_json_load_file


class ProtocolValidationError(RuntimeError):
    """The exported protocol bundle is incomplete, stale, or invalid."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def schema_paths(root: Path | None = None) -> tuple[Path, ...]:
    project_root = root or repository_root()
    return tuple(
        sorted((project_root / "schemas/engine").glob("*.schema.json"))
        + sorted((project_root / "schemas/network").glob("*.schema.json"))
    )


def schema_metadata(root: Path | None = None) -> dict[str, dict[str, str]]:
    project_root = root or repository_root()
    metadata: dict[str, dict[str, str]] = {}
    for path in schema_paths(project_root):
        schema = strict_json_load_file(path)
        schema_id = schema.get("$id") if isinstance(schema, dict) else None
        if not isinstance(schema_id, str):
            raise ProtocolValidationError(f"schema has no $id: {path}")
        relative = path.relative_to(project_root).as_posix()
        metadata[relative] = {
            "schema_id": schema_id,
            "sha256": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        }
    return metadata


@lru_cache(maxsize=4)
def _schema_registry(project_root: Path):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource
    except ImportError as exc:  # pragma: no cover - exercised by CLI environments
        raise ProtocolValidationError(
            "protocol validation requires the project dev dependencies"
        ) from exc

    registry = Registry()
    for path in schema_paths(project_root):
        contents = strict_json_load_file(path)
        Draft202012Validator.check_schema(contents)
        registry = registry.with_resource(
            contents["$id"],
            Resource.from_contents(contents),
        )
    return registry


def _validator(schema_ref: str, root: Path | None = None):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError as exc:  # pragma: no cover - exercised by CLI environments
        raise ProtocolValidationError(
            "protocol validation requires the project dev dependencies"
        ) from exc

    project_root = (root or repository_root()).resolve()
    wrapper = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": schema_ref,
    }
    return Draft202012Validator(
        wrapper,
        registry=_schema_registry(project_root),
        format_checker=FormatChecker(),
    )


def validate_instance(
    value: object,
    schema_ref: str,
    *,
    root: Path | None = None,
) -> None:
    errors = sorted(
        _validator(schema_ref, root).iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ProtocolValidationError(
            f"{schema_ref} rejected {location}: {first.message}"
        )


def validate_protocol_manifest(root: Path | None = None) -> dict[str, object]:
    project_root = root or repository_root()
    manifest = strict_json_load_file(
        project_root / "schemas/network/protocol_manifest.json"
    )
    validate_instance(
        manifest,
        "https://example.invalid/tuppi/schemas/network/protocol_manifest.schema.json",
        root=project_root,
    )
    ids = [item["id"] for item in manifest["messages"]]
    if len(ids) != len(set(ids)):
        raise ProtocolValidationError("protocol manifest contains duplicate message IDs")
    return manifest


def validate_bundle(bundle_dir: Path, *, root: Path | None = None) -> None:
    project_root = root or repository_root()
    manifest = strict_json_load_file(bundle_dir / "manifest.json")
    checksums = strict_json_load_file(bundle_dir / "sha256sums.json")
    compatibility = strict_json_load_file(bundle_dir / "compatibility.json")
    transport = strict_json_load_file(bundle_dir / "transport/cases.json")
    recordings = strict_json_load_file(bundle_dir / "transport/wire-recordings.json")

    validate_protocol_manifest(project_root)
    validate_instance(
        transport,
        "https://example.invalid/tuppi/schemas/network/transport_cases.schema.json",
        root=project_root,
    )
    validate_instance(
        recordings,
        "https://example.invalid/tuppi/schemas/network/wire_recordings.schema.json",
        root=project_root,
    )

    if compatibility.get("protocol_version") != "tuppi.network.v1":
        raise ProtocolValidationError("bundle compatibility protocol is invalid")
    if manifest.get("protocol_version") != "tuppi.network.v1":
        raise ProtocolValidationError("bundle manifest protocol is invalid")
    if manifest.get("ruleset_id") != "project_target_v1":
        raise ProtocolValidationError("bundle manifest ruleset is invalid")
    if manifest.get("schema_digests") != schema_metadata(project_root):
        raise ProtocolValidationError("bundle schema digests are stale")

    declared = checksums.get("files")
    if not isinstance(declared, dict):
        raise ProtocolValidationError("bundle checksum file is invalid")
    for relative, expected in declared.items():
        path = bundle_dir / relative
        if not path.is_file():
            raise ProtocolValidationError(f"bundle file is missing: {relative}")
        actual = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        if actual != expected:
            raise ProtocolValidationError(f"bundle checksum mismatch: {relative}")

    for recording in recordings["http"]:
        if recording["request_schema_ref"] is not None:
            validate_instance(
                recording["request"],
                recording["request_schema_ref"],
                root=project_root,
            )
        validate_instance(
            recording["response"],
            recording["response_schema_ref"],
            root=project_root,
        )
    for recording in recordings["websocket"]:
        validate_instance(
            recording["message"],
            recording["schema_ref"],
            root=project_root,
        )

    observation_ref = (
        "https://example.invalid/tuppi/schemas/engine/player_observation.schema.json"
    )
    event_log_ref = (
        "https://example.invalid/tuppi/schemas/engine/public_event_log.schema.json"
    )
    match_result_ref = (
        "https://example.invalid/tuppi/schemas/engine/match_result.schema.json"
    )
    showing_ref = (
        "https://example.invalid/tuppi/schemas/network/showing_ui_hints.schema.json"
    )
    ack_ref = (
        "https://example.invalid/tuppi/schemas/network/action_acknowledgement.schema.json"
    )
    for scenario in manifest["scenarios"]:
        scenario_dir = bundle_dir / "fixtures" / scenario["name"]
        for seat_file in scenario["seat_files"]:
            seat_fixture = strict_json_load_file(bundle_dir / seat_file)
            for snapshot in seat_fixture["snapshots"]:
                validate_instance(snapshot["observation"], observation_ref, root=project_root)
                validate_instance(snapshot["showing_ui_hints"], showing_ref, root=project_root)
        validate_instance(
            strict_json_load_file(scenario_dir / "public-events.json"),
            event_log_ref,
            root=project_root,
        )
        accepted = strict_json_load_file(scenario_dir / "accepted-actions.json")
        for record in accepted["actions"]:
            validate_instance(record["acknowledgement"], ack_ref, root=project_root)
        result_path = scenario_dir / "match-result.json"
        if result_path.is_file():
            validate_instance(
                strict_json_load_file(result_path),
                match_result_ref,
                root=project_root,
            )

    analysis_path = bundle_dir / "analysis/example-exact-52.json"
    if analysis_path.is_file():
        validate_instance(
            strict_json_load_file(analysis_path),
            "https://example.invalid/tuppi/schemas/network/post_match_analysis.schema.json",
            root=project_root,
        )


__all__ = (
    "ProtocolValidationError",
    "repository_root",
    "schema_metadata",
    "schema_paths",
    "validate_bundle",
    "validate_instance",
    "validate_protocol_manifest",
)
