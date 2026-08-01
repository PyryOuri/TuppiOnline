"""Canonical JSON and strict atomic file boundaries for evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .errors import EvaluationSerializationError


JSONValue = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]


def canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvaluationSerializationError(
            "value is not canonical-JSON serializable"
        ) from exc


def canonical_json_text(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")


def content_digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationSerializationError(
                f"duplicate JSON object key {key!r}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise EvaluationSerializationError(
        f"non-finite JSON number {value!r} is forbidden"
    )


def strict_json_loads(text: str) -> object:
    if not isinstance(text, str):
        raise EvaluationSerializationError("JSON input must be text")
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except EvaluationSerializationError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise EvaluationSerializationError(f"invalid JSON: {exc}") from exc


def strict_json_load_file(path: str | Path) -> object:
    if str(path) == "-":
        raise EvaluationSerializationError("stdin is not supported")
    target = Path(path)
    try:
        metadata = target.stat()
        if not stat.S_ISREG(metadata.st_mode):
            raise EvaluationSerializationError("JSON input must be a regular file")
        return strict_json_loads(target.read_text(encoding="utf-8"))
    except EvaluationSerializationError:
        raise
    except (OSError, UnicodeError) as exc:
        raise EvaluationSerializationError(
            f"cannot read JSON input {target}: {exc}"
        ) from exc


def require_object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise EvaluationSerializationError(f"{label} must be a JSON object")
    return value


def require_exact_keys(
    value: dict[str, Any], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise EvaluationSerializationError(
            f"{label} fields differ; "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise EvaluationSerializationError(f"{label} must be a nonempty string")
    return value


def require_int(value: object, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        qualifier = "" if minimum is None else f" >= {minimum}"
        raise EvaluationSerializationError(f"{label} must be an integer{qualifier}")
    return value


def require_sha256(value: object, label: str) -> str:
    text = require_string(value, label)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise EvaluationSerializationError(f"{label} must be a sha256 identifier")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise EvaluationSerializationError(
            f"{label} must be a lower-case sha256 identifier"
        ) from exc
    if text != text.lower():
        raise EvaluationSerializationError(
            f"{label} must be a lower-case sha256 identifier"
        )
    return text


def _validate_output_target(target: Path) -> None:
    if not target.parent.exists() or not target.parent.is_dir():
        raise EvaluationSerializationError("output parent directory does not exist")
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise EvaluationSerializationError(
            f"cannot inspect output {target}: {exc}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvaluationSerializationError(
            "existing output destination must be a regular file"
        )


def atomic_write_canonical_json(path: str | Path, value: object) -> None:
    if str(path) == "-":
        raise EvaluationSerializationError("stdout is not an artifact destination")
    target = Path(path)
    _validate_output_target(target)
    payload = canonical_json_bytes(value) + b"\n"
    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    except OSError as exc:
        raise EvaluationSerializationError(
            f"cannot write canonical JSON to {target}: {exc}"
        ) from exc
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)
