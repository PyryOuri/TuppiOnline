"""Deterministic execution of complete-match work units, serial or parallel.

A work unit is one complementary pair: ``(manifest, comparison, pair ordinal)``.
Every unit is a pure function of its manifest, its comparison, and its stream
index, so the worker count and the completion order cannot change any result.
That is a protocol requirement, not an optimisation detail, and
``tests/match/test_execution.py`` asserts it by running the same experiment at
several worker counts and comparing record identities.

Results are always reassembled in canonical ordinal order before analysis, so
even the *ordering* of the output is independent of scheduling.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
import os
from pathlib import Path
import sys

from .banks import StreamBank
from .errors import ExecutionError
from .manifest import MatchComparison, MatchManifest
from .protocol import run_pair
from .records import PairRecord


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """One complementary pair, fully addressed by immutable identities."""

    comparison_index: int
    pair_ordinal: int

    def __post_init__(self) -> None:
        for label, value in (
            ("comparison_index", self.comparison_index),
            ("pair_ordinal", self.pair_ordinal),
        ):
            if type(value) is not int or value < 0:
                raise ExecutionError(f"{label} must be a nonnegative integer")


def work_units(manifest: MatchManifest) -> tuple[WorkUnit, ...]:
    return tuple(
        WorkUnit(comparison_index=index, pair_ordinal=ordinal)
        for index in range(len(manifest.comparisons))
        for ordinal in range(manifest.pair_count)
    )


def default_worker_count() -> int:
    """Leave headroom so an interactive machine stays usable."""

    available = os.cpu_count() or 1
    return max(1, available - 2)


def parallel_available() -> bool:
    """Whether a process pool can be started in this interpreter.

    The default start method on macOS and Windows is ``spawn``, which re-imports
    the main module in each worker. That is impossible when the session was
    started from stdin or a REPL. Rather than fail there, the executor falls
    back to serial execution: the protocol guarantees identical results either
    way, so the only difference is wall-clock time.
    """

    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None)
    return bool(path) and Path(path).exists()


def _agent_builders(comparison: MatchComparison):
    """Resolve the two frozen agents named by a comparison.

    Imported lazily so that a worker process pays the import once and the
    module graph stays free of a build-time dependency on the agent package.
    """

    from tuppi_agents import construct_agent, phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    candidate = specifications[comparison.candidate_profile_key]
    opponent = specifications[comparison.opponent_profile_key]
    if candidate.agent_id != comparison.candidate_agent_id:
        raise ExecutionError(
            "the candidate profile no longer matches its committed agent identity"
        )
    if opponent.agent_id != comparison.opponent_agent_id:
        raise ExecutionError(
            "the opponent profile no longer matches its committed agent identity"
        )
    return (
        lambda seat: construct_agent(candidate, seat=seat),
        lambda seat: construct_agent(opponent, seat=seat),
    )


def execute_unit(
    *,
    bank: StreamBank,
    comparison: MatchComparison,
    safety_cap: int,
    pair_ordinal: int,
) -> PairRecord:
    """Run one work unit. Pure with respect to its arguments."""

    stream = bank.stream(pair_ordinal)
    build_candidate, build_opponent = _agent_builders(comparison)
    return run_pair(
        stream=stream,
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=pair_ordinal,
        build_candidate=build_candidate,
        build_opponent=build_opponent,
    )


def _worker(payload: tuple) -> tuple[int, int, dict]:
    """Process-pool entry point; returns canonical data, not live objects."""

    bank_data, comparison_data, safety_cap, comparison_index, pair_ordinal = payload
    bank = _bank_from_data(bank_data)
    comparison = _comparison_from_data(comparison_data)
    record = execute_unit(
        bank=bank,
        comparison=comparison,
        safety_cap=safety_cap,
        pair_ordinal=pair_ordinal,
    )
    return (comparison_index, pair_ordinal, record.to_data())


def _bank_from_data(data: dict) -> StreamBank:
    from .banks import BankRole

    return StreamBank.build(
        name=data["name"],
        role=BankRole(data["role"]),
        root_seed=data["root_seed"],
        initial_dealer=data["initial_dealer"],
        stream_count=data["stream_count"],
        first_stream_index=data["first_stream_index"],
        purpose=data["purpose"],
    )


def _comparison_from_data(data: dict) -> MatchComparison:
    return MatchComparison.build(
        name=data["name"],
        candidate_profile_key=data["candidate_profile_key"],
        opponent_profile_key=data["opponent_profile_key"],
        candidate_agent_id=data["candidate_agent_id"],
        opponent_agent_id=data["opponent_agent_id"],
        result_class=data["result_class"],
        hypothesis=data["hypothesis"],
        starting_score=tuple(data["starting_score"]),
    )


def run_experiment(
    manifest: MatchManifest,
    *,
    workers: int | None = None,
    progress=None,
    existing: dict[str, dict[int, PairRecord]] | None = None,
    on_unit=None,
) -> dict[str, tuple[PairRecord, ...]]:
    """Execute every outstanding work unit and return pairs by comparison.

    ``workers`` affects only wall-clock time. The returned records, their
    identities, and their order are identical for any worker count, and
    identical again to a run that resumed from partial results.

    ``existing`` supplies already-completed units keyed by comparison identity
    and pair ordinal; they are reused rather than replayed. ``on_unit`` is
    called with each freshly completed unit so a caller can checkpoint a long
    run without waiting for it to finish.
    """

    units = work_units(manifest)
    resolved = default_worker_count() if workers is None else workers
    if type(resolved) is not int or resolved < 1:
        raise ExecutionError("worker count must be a positive integer")
    if resolved > 1 and not parallel_available():
        resolved = 1

    reused = existing or {}
    collected: dict[tuple[int, int], PairRecord] = {}
    outstanding: list[WorkUnit] = []
    for unit in units:
        comparison = manifest.comparisons[unit.comparison_index]
        cached = reused.get(comparison.comparison_id, {}).get(unit.pair_ordinal)
        if cached is not None:
            collected[(unit.comparison_index, unit.pair_ordinal)] = cached
        else:
            outstanding.append(unit)

    total = len(units)
    if progress is not None and collected:
        progress(len(collected), total)

    def record(unit_key: tuple[int, int], value: PairRecord) -> None:
        collected[unit_key] = value
        if on_unit is not None:
            on_unit(manifest.comparisons[unit_key[0]].comparison_id, unit_key[1], value)
        if progress is not None:
            progress(len(collected), total)

    def run_serially(pending: list[WorkUnit]) -> None:
        for unit in pending:
            comparison = manifest.comparisons[unit.comparison_index]
            record(
                (unit.comparison_index, unit.pair_ordinal),
                execute_unit(
                    bank=manifest.bank,
                    comparison=comparison,
                    safety_cap=manifest.safety_cap,
                    pair_ordinal=unit.pair_ordinal,
                ),
            )

    if resolved == 1 or not outstanding:
        run_serially(outstanding)
    else:
        bank_data = {
            "first_stream_index": manifest.bank.first_stream_index,
            "initial_dealer": manifest.bank.initial_dealer,
            "name": manifest.bank.name,
            "purpose": manifest.bank.purpose,
            "role": manifest.bank.role.value,
            "root_seed": manifest.bank.root_seed,
            "stream_count": manifest.bank.stream_count,
        }
        submitted: dict[object, WorkUnit] = {}
        try:
            with ProcessPoolExecutor(max_workers=resolved) as pool:
                for unit in outstanding:
                    future = pool.submit(
                        _worker,
                        (
                            bank_data,
                            manifest.comparisons[unit.comparison_index].to_data(),
                            manifest.safety_cap,
                            unit.comparison_index,
                            unit.pair_ordinal,
                        ),
                    )
                    submitted[future] = unit
                for future in as_completed(submitted):
                    comparison_index, pair_ordinal, data = future.result()
                    record((comparison_index, pair_ordinal), _pair_from_data(data))
        except BrokenProcessPool:
            # A worker interpreter failed to start or died. The protocol makes
            # serial and parallel execution equivalent, so finishing serially
            # changes nothing except how long it takes.
            remaining = [
                unit
                for unit in outstanding
                if (unit.comparison_index, unit.pair_ordinal) not in collected
            ]
            run_serially(remaining)

    grouped: dict[str, list[PairRecord]] = {
        comparison.comparison_id: [] for comparison in manifest.comparisons
    }
    for index, comparison in enumerate(manifest.comparisons):
        for ordinal in range(manifest.pair_count):
            grouped[comparison.comparison_id].append(collected[(index, ordinal)])
    return {key: tuple(value) for key, value in grouped.items()}


def _pair_from_data(data: dict) -> PairRecord:
    """Rebuild a pair record from canonical worker output, revalidating it."""

    from .records import (
        LegIdentity,
        LegRecord,
        LegStatus,
        ScoreStateOccupancy,
    )

    def leg(payload: dict) -> LegRecord:
        occupancy = payload["occupancy"]
        return LegRecord.build(
            comparison_id=payload["comparison_id"],
            stream_id=payload["stream_id"],
            leg=LegIdentity(payload["leg"]),
            initial_dealer=payload["initial_dealer"],
            safety_cap=payload["safety_cap"],
            status=LegStatus(payload["status"]),
            deals_consumed=payload["deals_consumed"],
            consumed_deal_ids=tuple(payload["consumed_deal_ids"]),
            final_score=tuple(payload["final_score"]),
            winning_engine_team=payload["winning_engine_team"],
            even_partnership_won=payload["even_partnership_won"],
            candidate_won=payload["candidate_won"],
            resets=payload["resets"],
            rami_deals=payload["rami_deals"],
            nolo_deals=payload["nolo_deals"],
            successful_rami=payload["successful_rami"],
            stolen_rami=payload["stolen_rami"],
            declarer_seat_counts=tuple(payload["declarer_seat_counts"]),
            candidate_deal_points=payload["candidate_deal_points"],
            opponent_deal_points=payload["opponent_deal_points"],
            candidate_tricks=payload["candidate_tricks"],
            opponent_tricks=payload["opponent_tricks"],
            immediate_completion=payload["immediate_completion"],
            occupancy=ScoreStateOccupancy(
                deals_at_table=occupancy["deals_at_table"],
                deals_candidate_up=occupancy["deals_candidate_up"],
                deals_candidate_down=occupancy["deals_candidate_down"],
            ),
            action_count=payload["action_count"],
            duration_seconds=payload["duration_seconds"],
            failure_kind=payload["failure_kind"],
            failure_detail=payload["failure_detail"],
        )

    record = PairRecord.build(
        comparison_id=data["comparison_id"],
        stream_id=data["stream_id"],
        leg_even=leg(data["leg_even"]),
        leg_odd=leg(data["leg_odd"]),
    )
    if record.pair_record_id != data["pair_record_id"]:
        from .errors import IntegrityConflictError

        raise IntegrityConflictError(
            "a worker returned a pair whose identity does not survive a rebuild"
        )
    return record
