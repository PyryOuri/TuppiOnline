"""Small, atomic file-backed persistence for the private online alpha.

The private alpha is intentionally single-process.  A directory of one JSON
record per room is enough for its restart contract and keeps deployment free
of a database service.  The record contains private server material and must
never be sent over the network.
"""

from __future__ import annotations

import os
from pathlib import Path
import re

from tuppi_engine import atomic_write_canonical_json, strict_json_load_file


ROOM_RECORD_SCHEMA_VERSION = "tuppi.server.room_record.v1"
POST_MATCH_ANALYSIS_RECORD_SCHEMA_VERSION = (
    "tuppi.server.post_match_analysis_record.v1"
)
_ROOM_CODE = re.compile(r"^[A-Z0-9]{6}$")
_ANALYSIS_FILE = re.compile(r"^analysis-([A-Z0-9]{6})\.json$")


class PersistenceError(Exception):
    """A durable room record is missing, malformed, or cannot be written."""


class FileRoomStore:
    """Persist room records as atomically replaced canonical JSON files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()

    def save(self, record: dict[str, object]) -> None:
        code = record.get("room_code")
        if not isinstance(code, str) or _ROOM_CODE.fullmatch(code) is None:
            raise PersistenceError("room record has an invalid room_code")
        if record.get("schema_version") != ROOM_RECORD_SCHEMA_VERSION:
            raise PersistenceError("unsupported room record schema_version")
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.root, 0o700)
            target = self.root / f"room-{code}.json"
            atomic_write_canonical_json(target, record)
            os.chmod(target, 0o600)
        except OSError as exc:
            raise PersistenceError(f"cannot persist room {code}: {exc}") from exc

    def load_all(self) -> tuple[dict[str, object], ...]:
        if not self.root.exists():
            return ()
        if not self.root.is_dir():
            raise PersistenceError("persistence root is not a directory")
        records: list[dict[str, object]] = []
        for path in sorted(self.root.glob("room-*.json")):
            if path.is_symlink() or not path.is_file():
                raise PersistenceError(f"persistence entry is not a regular file: {path}")
            try:
                value = strict_json_load_file(path)
            except Exception as exc:
                raise PersistenceError(f"cannot load persisted room {path.name}") from exc
            if type(value) is not dict:
                raise PersistenceError(f"persisted room {path.name} must be an object")
            records.append(value)
        return tuple(records)

    def save_post_match_analysis(
        self,
        *,
        room_code: str,
        response: dict[str, object],
    ) -> None:
        """Persist only the already-filtered client analysis envelope."""

        if _ROOM_CODE.fullmatch(room_code) is None:
            raise PersistenceError("analysis record has an invalid room_code")
        if type(response) is not dict:
            raise PersistenceError("analysis response must be an object")
        if response.get("match_ref") is None:
            raise PersistenceError("analysis response has no match_ref")
        record = {
            "analysis": response,
            "room_code": room_code,
            "schema_version": POST_MATCH_ANALYSIS_RECORD_SCHEMA_VERSION,
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.root, 0o700)
            target = self.root / f"analysis-{room_code}.json"
            atomic_write_canonical_json(target, record)
            os.chmod(target, 0o600)
        except OSError as exc:
            raise PersistenceError(
                f"cannot persist post-match analysis for room {room_code}: {exc}"
            ) from exc

    def load_post_match_analysis(self, room_code: str) -> dict[str, object] | None:
        """Load one private analysis artifact, if it exists."""

        if _ROOM_CODE.fullmatch(room_code) is None:
            raise PersistenceError("analysis lookup has an invalid room_code")
        if not self.root.exists():
            return None
        target = self.root / f"analysis-{room_code}.json"
        if target.is_symlink():
            raise PersistenceError("analysis persistence entry is a symbolic link")
        if not target.exists():
            return None
        if not target.is_file():
            raise PersistenceError("analysis persistence entry is not a regular file")
        try:
            value = strict_json_load_file(target)
        except Exception as exc:
            raise PersistenceError(
                f"cannot load persisted post-match analysis for room {room_code}"
            ) from exc
        if type(value) is not dict or set(value) != {
            "analysis",
            "room_code",
            "schema_version",
        }:
            raise PersistenceError("persisted analysis record fields are invalid")
        if value["schema_version"] != POST_MATCH_ANALYSIS_RECORD_SCHEMA_VERSION:
            raise PersistenceError("unsupported analysis record schema_version")
        if value["room_code"] != room_code:
            raise PersistenceError("persisted analysis room_code disagrees")
        response = value["analysis"]
        if type(response) is not dict:
            raise PersistenceError("persisted analysis response must be an object")
        return response

    def post_match_analysis_codes(self) -> tuple[str, ...]:
        """Return analysis artifact room codes and reject malformed entries."""

        if not self.root.exists():
            return ()
        codes: list[str] = []
        for path in sorted(self.root.glob("analysis-*.json")):
            if path.is_symlink() or not path.is_file():
                raise PersistenceError(
                    f"analysis persistence entry is not a regular file: {path}"
                )
            match = _ANALYSIS_FILE.fullmatch(path.name)
            if match is None:
                raise PersistenceError(f"invalid analysis persistence filename: {path.name}")
            codes.append(match.group(1))
        return tuple(codes)
