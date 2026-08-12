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


ROOM_RECORD_SCHEMA_VERSION = "tuppi.server.room_record.v2"
LEGACY_ROOM_RECORD_SCHEMA_VERSION = "tuppi.server.room_record.v1"
POST_MATCH_ANALYSIS_RECORD_SCHEMA_VERSION = (
    "tuppi.server.post_match_analysis_record.v1"
)
COMPLETED_DEAL_ANALYSIS_RECORD_SCHEMA_VERSION = (
    "tuppi.server.completed_deal_analysis_record.v1"
)
_ROOM_CODE = re.compile(r"^[A-Z0-9]{6}$")
_ANALYSIS_FILE = re.compile(r"^analysis-([A-Z0-9]{6})\.json$")
_DEAL_ANALYSIS_FILE = re.compile(
    r"^deal-analysis-([A-Z0-9]{6})-(0|[1-9][0-9]*)-([0-3])\.json$"
)


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

    def save_completed_deal_analysis(
        self,
        *,
        room_code: str,
        deal_number: int,
        seat: int,
        response: dict[str, object],
        analysis_schema_version: str,
        bot_policy_id: str,
    ) -> None:
        """Persist one authenticated-seat review cache entry atomically."""

        self._validate_deal_analysis_identity(room_code, deal_number, seat)
        if type(response) is not dict:
            raise PersistenceError("completed-deal analysis response must be an object")
        if response.get("schema_version") != analysis_schema_version:
            raise PersistenceError("completed-deal analysis schema metadata disagrees")
        policy = response.get("bot_policy")
        if type(policy) is not dict or policy.get("policy_id") != bot_policy_id:
            raise PersistenceError("completed-deal analysis policy metadata disagrees")
        record = {
            "analysis": response,
            "analysis_schema_version": analysis_schema_version,
            "bot_policy_id": bot_policy_id,
            "deal_number": deal_number,
            "room_code": room_code,
            "schema_version": COMPLETED_DEAL_ANALYSIS_RECORD_SCHEMA_VERSION,
            "seat": seat,
        }
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.root, 0o700)
            target = self.root / self._deal_analysis_filename(
                room_code, deal_number, seat
            )
            atomic_write_canonical_json(target, record)
            os.chmod(target, 0o600)
        except OSError as exc:
            raise PersistenceError(
                f"cannot persist completed-deal analysis for room {room_code}: {exc}"
            ) from exc

    def load_completed_deal_analysis(
        self,
        *,
        room_code: str,
        deal_number: int,
        seat: int,
        analysis_schema_version: str,
        bot_policy_id: str,
    ) -> dict[str, object] | None:
        """Load a current cache entry; obsolete schema/policy entries invalidate."""

        self._validate_deal_analysis_identity(room_code, deal_number, seat)
        if not self.root.exists():
            return None
        target = self.root / self._deal_analysis_filename(
            room_code, deal_number, seat
        )
        if target.is_symlink():
            raise PersistenceError("completed-deal analysis entry is a symbolic link")
        if not target.exists():
            return None
        if not target.is_file():
            raise PersistenceError("completed-deal analysis entry is not a regular file")
        try:
            value = strict_json_load_file(target)
        except Exception as exc:
            raise PersistenceError(
                f"cannot load completed-deal analysis for room {room_code}"
            ) from exc
        expected = {
            "analysis",
            "analysis_schema_version",
            "bot_policy_id",
            "deal_number",
            "room_code",
            "schema_version",
            "seat",
        }
        if type(value) is not dict or set(value) != expected:
            raise PersistenceError("persisted completed-deal analysis fields are invalid")
        if value["schema_version"] != COMPLETED_DEAL_ANALYSIS_RECORD_SCHEMA_VERSION:
            raise PersistenceError(
                "unsupported completed-deal analysis record schema_version"
            )
        if (
            value["room_code"] != room_code
            or value["deal_number"] != deal_number
            or value["seat"] != seat
        ):
            raise PersistenceError("persisted completed-deal analysis identity disagrees")
        # A deliberate schema or policy bump invalidates an otherwise well-formed
        # cache instead of trying to coerce old replay semantics.
        if (
            value["analysis_schema_version"] != analysis_schema_version
            or value["bot_policy_id"] != bot_policy_id
        ):
            return None
        response = value["analysis"]
        if type(response) is not dict:
            raise PersistenceError("persisted completed-deal analysis must be an object")
        return response

    @staticmethod
    def _validate_deal_analysis_identity(
        room_code: str,
        deal_number: int,
        seat: int,
    ) -> None:
        if _ROOM_CODE.fullmatch(room_code) is None:
            raise PersistenceError("completed-deal analysis room_code is invalid")
        if type(deal_number) is not int or deal_number < 0:
            raise PersistenceError("completed-deal analysis deal_number is invalid")
        if type(seat) is not int or seat not in range(4):
            raise PersistenceError("completed-deal analysis seat is invalid")

    @staticmethod
    def _deal_analysis_filename(room_code: str, deal_number: int, seat: int) -> str:
        filename = f"deal-analysis-{room_code}-{deal_number}-{seat}.json"
        if _DEAL_ANALYSIS_FILE.fullmatch(filename) is None:
            raise PersistenceError("completed-deal analysis filename is invalid")
        return filename
