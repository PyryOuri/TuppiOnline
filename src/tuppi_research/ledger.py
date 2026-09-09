"""A small SQLite metadata ledger over artifacts other layers already wrote.

Deliberate non-goals: it stores no hands, no game records, no event logs, no
statistics and no policy bytes. Every heavy artifact remains a file written by
:mod:`tuppi_eval` (canonical JSON) or :mod:`tuppi_corpus` (binary shards), and is
referenced here by relative path plus SHA-256 so a row can be re-verified or
found stale, never silently trusted.

Two independent axes are recorded and never collapsed:

``ExecutionState``
    Did the work run to completion? Owned by the executor.
``Verdict``
    Did the evidence establish anything? Owned by review. ``NOT_REVIEWED`` is the
    initial state, and a completed run that nobody reviewed stays there.

Unit rows are the resume boundary. A unit is one independent base deal - the same
unit the paired estimator treats as one observation - so resuming re-enters at a
boundary the analysis also recognises, and a partially executed unit is never
counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .errors import LedgerError

LEDGER_SCHEMA_VERSION = "tuppi.research.ledger.v1"


class ExecutionState(StrEnum):
    """Did it run? Nothing about whether the result means anything."""

    PLANNED = "planned"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETE = "complete"
    FAILED = "failed"


class Verdict(StrEnum):
    """Did review accept it? Deliberately not derivable from ExecutionState."""

    NOT_REVIEWED = "not_reviewed"
    NO_EFFECT = "no_effect"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


#: Promotion is a separate governed act. The ledger records that it did not
#: happen and offers no column that could be mistaken for it having happened.
PROMOTION_NOT_PERFORMED = "not_performed"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS ledger_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiment (
    experiment_id   TEXT PRIMARY KEY,
    hypothesis      TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    incumbent_id    TEXT NOT NULL,
    candidate_id    TEXT NOT NULL,
    is_null_control INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    notes           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cycle_run (
    run_id            TEXT PRIMARY KEY,
    experiment_id     TEXT NOT NULL REFERENCES experiment(experiment_id),
    evaluation_id     TEXT NOT NULL,
    schedule_id       TEXT NOT NULL,
    config_digest     TEXT NOT NULL,
    deal_bank_id      TEXT NOT NULL,
    output_directory  TEXT NOT NULL,
    planned_units     INTEGER NOT NULL,
    planned_games     INTEGER NOT NULL,
    execution_state   TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    failure           TEXT,
    UNIQUE (experiment_id, evaluation_id)
);

CREATE TABLE IF NOT EXISTS unit (
    run_id           TEXT NOT NULL REFERENCES cycle_run(run_id),
    block_index      INTEGER NOT NULL,
    base_deal_id     TEXT NOT NULL,
    planned_games    INTEGER NOT NULL,
    observed_games   INTEGER,
    execution_state  TEXT NOT NULL,
    block_record_id  TEXT,
    paired_utility   REAL,
    PRIMARY KEY (run_id, block_index),
    UNIQUE (run_id, base_deal_id)
);

CREATE TABLE IF NOT EXISTS artifact (
    run_id        TEXT NOT NULL REFERENCES cycle_run(run_id),
    kind          TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    bytes         INTEGER NOT NULL,
    recorded_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, relative_path)
);

CREATE TABLE IF NOT EXISTS control_check (
    run_id      TEXT NOT NULL REFERENCES cycle_run(run_id),
    name        TEXT NOT NULL,
    passed      INTEGER NOT NULL,
    detail      TEXT NOT NULL,
    PRIMARY KEY (run_id, name)
);

CREATE TABLE IF NOT EXISTS finding (
    finding_id      TEXT PRIMARY KEY,
    experiment_id   TEXT NOT NULL REFERENCES experiment(experiment_id),
    run_id          TEXT NOT NULL REFERENCES cycle_run(run_id),
    verdict         TEXT NOT NULL,
    promotion       TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    summary_sha256  TEXT NOT NULL,
    statement       TEXT NOT NULL,
    reviewed_by     TEXT NOT NULL,
    recorded_at     TEXT NOT NULL,
    UNIQUE (run_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_file(path: Path) -> tuple[str, int]:
    """SHA-256 and size of an artifact that stays where its writer put it."""

    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def content_id(prefix: str, payload: dict[str, Any]) -> str:
    """A content address over canonical JSON, matching the repository's style."""

    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"{prefix}:sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True)
class UnitRow:
    block_index: int
    base_deal_id: str
    planned_games: int
    observed_games: int | None
    execution_state: ExecutionState
    block_record_id: str | None
    paired_utility: float | None


class Ledger:
    """Durable experiment metadata. One SQLite file, opened per use."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        # Durability over speed: a control cycle is not throughput-bound, and a
        # torn ledger is worse than a slow one.
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript(_SCHEMA)
        self._assert_schema_version()

    def _assert_schema_version(self) -> None:
        row = self._connection.execute(
            "SELECT value FROM ledger_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            self._connection.execute(
                "INSERT INTO ledger_meta (key, value) VALUES ('schema_version', ?)",
                (LEDGER_SCHEMA_VERSION,),
            )
            return
        if row["value"] != LEDGER_SCHEMA_VERSION:
            raise LedgerError(
                f"ledger at {self.path} has schema {row['value']!r}, "
                f"this build writes {LEDGER_SCHEMA_VERSION!r}; migrate explicitly"
            )

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- writes
    def record_experiment(
        self,
        *,
        hypothesis: str,
        endpoint: str,
        incumbent_id: str,
        candidate_id: str,
        is_null_control: bool,
        notes: str = "",
    ) -> str:
        """Register an experiment. Content-addressed, so re-registering is a no-op."""

        if not hypothesis or not endpoint or not incumbent_id or not candidate_id:
            raise LedgerError("an experiment requires all identity fields")
        experiment_id = content_id(
            "experiment",
            {
                "candidate_id": candidate_id,
                "endpoint": endpoint,
                "hypothesis": hypothesis,
                "incumbent_id": incumbent_id,
                "is_null_control": bool(is_null_control),
                "schema_version": LEDGER_SCHEMA_VERSION,
            },
        )
        self._connection.execute(
            "INSERT OR IGNORE INTO experiment (experiment_id, hypothesis, endpoint,"
            " incumbent_id, candidate_id, is_null_control, created_at, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                experiment_id, hypothesis, endpoint, incumbent_id, candidate_id,
                int(bool(is_null_control)), _now(), notes,
            ),
        )
        return experiment_id

    def open_run(
        self,
        *,
        experiment_id: str,
        evaluation_id: str,
        schedule_id: str,
        config_digest: str,
        deal_bank_id: str,
        output_directory: str,
        planned_units: tuple[tuple[int, str], ...],
        games_per_unit: int,
    ) -> str:
        """Create or re-open a run and its planned unit rows.

        Re-opening is how resume works: the planned manifest is written once and
        an existing run must present the same plan, or the call is refused rather
        than quietly re-planning around whatever already happened.
        """

        if not planned_units:
            raise LedgerError("a run must plan at least one unit")
        run_id = content_id(
            "run",
            {
                "config_digest": config_digest,
                "evaluation_id": evaluation_id,
                "experiment_id": experiment_id,
                "schedule_id": schedule_id,
            },
        )
        existing = self._connection.execute(
            "SELECT * FROM cycle_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        plan = tuple(sorted(planned_units))
        if existing is not None:
            recorded = tuple(
                (row["block_index"], row["base_deal_id"])
                for row in self._connection.execute(
                    "SELECT block_index, base_deal_id FROM unit WHERE run_id = ?"
                    " ORDER BY block_index",
                    (run_id,),
                )
            )
            if recorded != plan:
                raise LedgerError(
                    "run already exists with a different planned manifest; "
                    "use a new evaluation rather than re-planning this one"
                )
            self._connection.execute(
                "UPDATE cycle_run SET execution_state = ?, finished_at = NULL,"
                " failure = NULL WHERE run_id = ?",
                (ExecutionState.RUNNING.value, run_id),
            )
            return run_id
        with self._transaction():
            self._connection.execute(
                "INSERT INTO cycle_run (run_id, experiment_id, evaluation_id,"
                " schedule_id, config_digest, deal_bank_id, output_directory,"
                " planned_units, planned_games, execution_state, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id, experiment_id, evaluation_id, schedule_id, config_digest,
                    deal_bank_id, str(output_directory), len(plan),
                    len(plan) * games_per_unit, ExecutionState.RUNNING.value, _now(),
                ),
            )
            self._connection.executemany(
                "INSERT INTO unit (run_id, block_index, base_deal_id, planned_games,"
                " observed_games, execution_state, block_record_id, paired_utility)"
                " VALUES (?, ?, ?, ?, NULL, ?, NULL, NULL)",
                [
                    (run_id, index, base_deal_id, games_per_unit,
                     ExecutionState.PLANNED.value)
                    for index, base_deal_id in plan
                ],
            )
        return run_id

    def complete_unit(
        self,
        *,
        run_id: str,
        block_index: int,
        observed_games: int,
        block_record_id: str,
        paired_utility: float,
    ) -> None:
        """Mark one planned unit complete. Refuses an unplanned unit."""

        row = self._connection.execute(
            "SELECT planned_games, execution_state FROM unit"
            " WHERE run_id = ? AND block_index = ?",
            (run_id, block_index),
        ).fetchone()
        if row is None:
            raise LedgerError(
                f"unit {block_index} was not planned for this run; "
                "results cannot introduce new independent observations"
            )
        if observed_games != row["planned_games"]:
            raise LedgerError(
                f"unit {block_index} observed {observed_games} games, "
                f"planned {row['planned_games']}"
            )
        self._connection.execute(
            "UPDATE unit SET observed_games = ?, execution_state = ?,"
            " block_record_id = ?, paired_utility = ? WHERE run_id = ?"
            " AND block_index = ?",
            (
                observed_games, ExecutionState.COMPLETE.value, block_record_id,
                float(paired_utility), run_id, block_index,
            ),
        )

    def fail_unit(self, *, run_id: str, block_index: int, detail: str) -> None:
        updated = self._connection.execute(
            "UPDATE unit SET execution_state = ? WHERE run_id = ? AND block_index = ?",
            (ExecutionState.FAILED.value, run_id, block_index),
        ).rowcount
        if not updated:
            raise LedgerError(f"unit {block_index} was not planned for this run")
        self.record_control_check(
            run_id=run_id, name=f"unit_{block_index}_failure",
            passed=False, detail=detail,
        )

    def set_run_state(
        self, *, run_id: str, state: ExecutionState, failure: str | None = None
    ) -> None:
        finished = state in (
            ExecutionState.COMPLETE, ExecutionState.FAILED, ExecutionState.INTERRUPTED
        )
        self._connection.execute(
            "UPDATE cycle_run SET execution_state = ?, failure = ?,"
            " finished_at = ? WHERE run_id = ?",
            (state.value, failure, _now() if finished else None, run_id),
        )

    def record_artifact(self, *, run_id: str, kind: str, path: Path, root: Path) -> str:
        """Reference an artifact by digest. The bytes are not copied in."""

        sha256, size = digest_file(path)
        relative = str(Path(path).resolve().relative_to(Path(root).resolve()))
        self._connection.execute(
            "INSERT OR REPLACE INTO artifact (run_id, kind, relative_path, sha256,"
            " bytes, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, kind, relative, sha256, size, _now()),
        )
        return sha256

    def record_control_check(
        self, *, run_id: str, name: str, passed: bool, detail: str
    ) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO control_check (run_id, name, passed, detail)"
            " VALUES (?, ?, ?, ?)",
            (run_id, name, int(bool(passed)), detail),
        )

    def record_finding(
        self,
        *,
        experiment_id: str,
        run_id: str,
        verdict: Verdict,
        endpoint: str,
        summary_sha256: str,
        statement: str,
        reviewed_by: str,
    ) -> str:
        """Record the scientific verdict, which promotion never follows from.

        Refuses to record any verdict for a run that did not complete, and
        refuses ``ACCEPTED`` for an experiment declared a null control.
        """

        run = self._connection.execute(
            "SELECT execution_state, experiment_id FROM cycle_run WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if run is None:
            raise LedgerError("cannot record a finding for an unknown run")
        if run["execution_state"] != ExecutionState.COMPLETE.value:
            raise LedgerError(
                "a finding requires a completed run; execution status and "
                "scientific verdict are separate but a verdict still needs evidence"
            )
        control = self._connection.execute(
            "SELECT is_null_control FROM experiment WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
        if control is None:
            raise LedgerError("cannot record a finding for an unknown experiment")
        if control["is_null_control"] and verdict is Verdict.ACCEPTED:
            raise LedgerError(
                "a null control must never be accepted as an improvement"
            )
        if self.incomplete_units(run_id):
            raise LedgerError(
                "a finding requires every planned unit; incomplete evidence "
                "cannot become a recorded result"
            )
        finding_id = content_id(
            "finding",
            {
                "endpoint": endpoint,
                "experiment_id": experiment_id,
                "run_id": run_id,
                "summary_sha256": summary_sha256,
                "verdict": verdict.value,
            },
        )
        self._connection.execute(
            "INSERT OR REPLACE INTO finding (finding_id, experiment_id, run_id,"
            " verdict, promotion, endpoint, summary_sha256, statement, reviewed_by,"
            " recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                finding_id, experiment_id, run_id, verdict.value,
                PROMOTION_NOT_PERFORMED, endpoint, summary_sha256, statement,
                reviewed_by, _now(),
            ),
        )
        return finding_id

    # ----------------------------------------------------------------- reads
    def completed_units(self, run_id: str) -> frozenset[int]:
        """Block indices already complete, so a resume can skip them."""

        return frozenset(
            row["block_index"]
            for row in self._connection.execute(
                "SELECT block_index FROM unit WHERE run_id = ? AND execution_state = ?",
                (run_id, ExecutionState.COMPLETE.value),
            )
        )

    def incomplete_units(self, run_id: str) -> tuple[int, ...]:
        return tuple(
            row["block_index"]
            for row in self._connection.execute(
                "SELECT block_index FROM unit WHERE run_id = ? AND execution_state != ?"
                " ORDER BY block_index",
                (run_id, ExecutionState.COMPLETE.value),
            )
        )

    def units(self, run_id: str) -> tuple[UnitRow, ...]:
        return tuple(
            UnitRow(
                block_index=row["block_index"],
                base_deal_id=row["base_deal_id"],
                planned_games=row["planned_games"],
                observed_games=row["observed_games"],
                execution_state=ExecutionState(row["execution_state"]),
                block_record_id=row["block_record_id"],
                paired_utility=row["paired_utility"],
            )
            for row in self._connection.execute(
                "SELECT * FROM unit WHERE run_id = ? ORDER BY block_index", (run_id,)
            )
        )

    def run(self, run_id: str) -> dict[str, Any]:
        row = self._connection.execute(
            "SELECT * FROM cycle_run WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise LedgerError(f"unknown run {run_id!r}")
        return dict(row)

    def finding(self, run_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM finding WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if row is None else dict(row)

    def control_checks(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self._connection.execute(
                "SELECT * FROM control_check WHERE run_id = ? ORDER BY name", (run_id,)
            )
        )

    def artifacts(self, run_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(row)
            for row in self._connection.execute(
                "SELECT * FROM artifact WHERE run_id = ? ORDER BY relative_path",
                (run_id,),
            )
        )

    def stale_artifacts(self, run_id: str, root: Path) -> tuple[str, ...]:
        """Referenced artifacts whose bytes no longer match their recorded digest."""

        drifted: list[str] = []
        for row in self.artifacts(run_id):
            path = Path(root) / row["relative_path"]
            if not path.is_file():
                drifted.append(f"{row['relative_path']} (missing)")
                continue
            actual, _ = digest_file(path)
            if actual != row["sha256"]:
                drifted.append(f"{row['relative_path']} (changed)")
        return tuple(drifted)

    def _transaction(self):
        connection = self._connection

        class _Transaction:
            def __enter__(self) -> None:
                connection.execute("BEGIN")

            def __exit__(self, exc_type, *_rest: object) -> bool:
                connection.execute("ROLLBACK" if exc_type else "COMMIT")
                return False

        return _Transaction()


def iter_ledger_runs(path: str | Path) -> Iterator[dict[str, Any]]:
    """Every run in a ledger, newest first. Read-only convenience for reporting."""

    with Ledger(path) as ledger:
        rows = ledger._connection.execute(
            "SELECT * FROM cycle_run ORDER BY started_at DESC"
        ).fetchall()
        for row in rows:
            yield dict(row)
