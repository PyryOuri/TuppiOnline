"""Immutable leg and pair records for the complete-match duplicate protocol.

Two record types matter, and only one of them is a statistical unit.

A :class:`LegRecord` describes one complete match played from 0-0 on one
stream with one seat assignment. It is *not* an independent observation: the
two legs of a pair share their deals by construction and are strongly
correlated.

A :class:`PairRecord` joins the two complementary legs of one stream. It is
the independent unit, and it carries the primary quantity ``d_match``.

Censoring is a third thing again. A leg that hits the infrastructure safety cap
is ``censored_infrastructure``: not a draw, not a policy loss, not a policy win.
Its pair is ``incomplete`` and cannot enter the primary analysis at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from tuppi_eval.serialization import content_digest

from .errors import RecordError


LEG_RECORD_SCHEMA_VERSION = "tuppi.match.leg_record.v1"
PAIR_RECORD_SCHEMA_VERSION = "tuppi.match.pair_record.v1"


class LegIdentity(StrEnum):
    """Which partnership the candidate occupies in this leg."""

    EVEN = "E"
    ODD = "O"


class LegStatus(StrEnum):
    COMPLETE = "complete"
    CENSORED_INFRASTRUCTURE = "censored_infrastructure"
    FAILED = "failed"


class PairStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE_CENSORED = "incomplete_censored"
    INCOMPLETE_FAILED = "incomplete_failed"


#: Statuses whose pairs may enter the primary match-win analysis.
ANALYSABLE_LEG_STATUSES = frozenset({LegStatus.COMPLETE})


@dataclass(frozen=True, slots=True)
class ScoreStateOccupancy:
    """How many deals the candidate spent at the table, up, and down."""

    deals_at_table: int
    deals_candidate_up: int
    deals_candidate_down: int

    def __post_init__(self) -> None:
        for label, value in (
            ("deals_at_table", self.deals_at_table),
            ("deals_candidate_up", self.deals_candidate_up),
            ("deals_candidate_down", self.deals_candidate_down),
        ):
            if type(value) is not int or value < 0:
                raise RecordError(f"{label} must be a nonnegative integer")

    @property
    def total(self) -> int:
        return self.deals_at_table + self.deals_candidate_up + self.deals_candidate_down

    def to_data(self) -> dict[str, object]:
        return {
            "deals_at_table": self.deals_at_table,
            "deals_candidate_down": self.deals_candidate_down,
            "deals_candidate_up": self.deals_candidate_up,
        }


@dataclass(frozen=True, slots=True)
class LegRecord:
    """One complete-match leg, played to natural termination or censored."""

    leg_record_id: str
    comparison_id: str
    stream_id: str
    leg: LegIdentity
    initial_dealer: int
    safety_cap: int
    status: LegStatus
    deals_consumed: int
    consumed_deal_ids: tuple[str, ...]
    final_score: tuple[int, int]
    winning_engine_team: int | None
    even_partnership_won: bool | None
    candidate_won: bool | None
    resets: int
    rami_deals: int
    nolo_deals: int
    successful_rami: int
    stolen_rami: int
    declarer_seat_counts: tuple[int, int, int, int]
    candidate_deal_points: int
    opponent_deal_points: int
    candidate_tricks: int
    opponent_tricks: int
    immediate_completion: bool
    occupancy: ScoreStateOccupancy
    action_count: int
    duration_seconds: float
    failure_kind: str | None
    failure_detail: str | None
    schema_version: str = field(default=LEG_RECORD_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.leg, LegIdentity):
            raise RecordError("leg must be a LegIdentity value")
        if not isinstance(self.status, LegStatus):
            raise RecordError("status must be a LegStatus value")
        if type(self.deals_consumed) is not int or self.deals_consumed < 0:
            raise RecordError("deals_consumed must be a nonnegative integer")
        if len(self.consumed_deal_ids) != self.deals_consumed:
            raise RecordError("consumed deal identifiers disagree with the count")
        if len(set(self.consumed_deal_ids)) != len(self.consumed_deal_ids):
            raise RecordError("a leg cannot consume the same deal twice")
        if type(self.safety_cap) is not int or self.safety_cap <= 0:
            raise RecordError("safety_cap must be a positive integer")
        if self.deals_consumed > self.safety_cap:
            raise RecordError("a leg cannot exceed its own safety cap")
        if len(self.final_score) != 2 or any(
            type(value) is not int or value < 0 for value in self.final_score
        ):
            raise RecordError("final_score must be a pair of nonnegative integers")
        if self.occupancy.total != self.deals_consumed:
            raise RecordError("score-state occupancy must cover every consumed deal")

        if self.status is LegStatus.COMPLETE:
            if max(self.final_score) < 52:
                raise RecordError("a complete leg must reach at least 52")
            for label, value in (
                ("winning_engine_team", self.winning_engine_team),
                ("even_partnership_won", self.even_partnership_won),
                ("candidate_won", self.candidate_won),
            ):
                if value is None:
                    raise RecordError(f"a complete leg requires {label}")
            if self.winning_engine_team not in (0, 1):
                raise RecordError("winning_engine_team must be 0 or 1")
            expected_even = self.winning_engine_team == 0
            if self.even_partnership_won is not expected_even:
                raise RecordError("even_partnership_won disagrees with the winner")
            expected_candidate = (
                expected_even
                if self.leg is LegIdentity.EVEN
                else not expected_even
            )
            if self.candidate_won is not expected_candidate:
                raise RecordError("candidate_won disagrees with the leg orientation")
            if self.failure_kind is not None:
                raise RecordError("a complete leg cannot carry a failure kind")
            if self.immediate_completion is not (self.deals_consumed == 1):
                raise RecordError("immediate_completion disagrees with the deal count")
        else:
            for label, value in (
                ("winning_engine_team", self.winning_engine_team),
                ("even_partnership_won", self.even_partnership_won),
                ("candidate_won", self.candidate_won),
            ):
                if value is not None:
                    raise RecordError(
                        f"an unfinished leg must not claim {label}; "
                        "censoring is never a policy outcome"
                    )
            if self.immediate_completion:
                raise RecordError("an unfinished leg cannot be an immediate completion")
            if self.failure_kind is None:
                raise RecordError("an unfinished leg must record why")
        if self.status is LegStatus.CENSORED_INFRASTRUCTURE and (
            self.failure_kind != "censored_infrastructure"
        ):
            raise RecordError("a censored leg must record the infrastructure kind")
        expected = f"leg:{content_digest(self.semantic_data())}"
        if self.leg_record_id != expected:
            raise RecordError("leg_record_id disagrees with its semantic content")

    @classmethod
    def build(cls, **values) -> "LegRecord":
        provisional = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "schema_version", LEG_RECORD_SCHEMA_VERSION)
        record_id = f"leg:{content_digest(provisional.semantic_data())}"
        return cls(leg_record_id=record_id, **values)

    def semantic_data(self) -> dict[str, object]:
        """Everything that defines the result; never timing or storage."""

        return {
            "candidate_deal_points": self.candidate_deal_points,
            "candidate_tricks": self.candidate_tricks,
            "candidate_won": self.candidate_won,
            "comparison_id": self.comparison_id,
            "consumed_deal_ids": list(self.consumed_deal_ids),
            "deals_consumed": self.deals_consumed,
            "declarer_seat_counts": list(self.declarer_seat_counts),
            "even_partnership_won": self.even_partnership_won,
            "failure_detail": self.failure_detail,
            "failure_kind": self.failure_kind,
            "final_score": list(self.final_score),
            "immediate_completion": self.immediate_completion,
            "initial_dealer": self.initial_dealer,
            "leg": self.leg.value,
            "nolo_deals": self.nolo_deals,
            "occupancy": self.occupancy.to_data(),
            "opponent_deal_points": self.opponent_deal_points,
            "opponent_tricks": self.opponent_tricks,
            "rami_deals": self.rami_deals,
            "resets": self.resets,
            "safety_cap": self.safety_cap,
            "schema_version": LEG_RECORD_SCHEMA_VERSION,
            "status": self.status.value,
            "stolen_rami": self.stolen_rami,
            "stream_id": self.stream_id,
            "successful_rami": self.successful_rami,
            "winning_engine_team": self.winning_engine_team,
        }

    def to_data(self) -> dict[str, object]:
        return {
            **self.semantic_data(),
            "action_count": self.action_count,
            "duration_seconds": self.duration_seconds,
            "leg_record_id": self.leg_record_id,
        }

    @property
    def y_even(self) -> int | None:
        """``+1`` when the even partnership won this leg, ``-1`` when it lost."""

        if self.even_partnership_won is None:
            return None
        return 1 if self.even_partnership_won else -1


@dataclass(frozen=True, slots=True)
class PairRecord:
    """One complementary duplicate pair: the independent statistical unit."""

    pair_record_id: str
    comparison_id: str
    stream_id: str
    leg_even: LegRecord
    leg_odd: LegRecord
    status: PairStatus
    d_match: int | None
    schema_version: str = field(default=PAIR_RECORD_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.leg_even.leg is not LegIdentity.EVEN:
            raise RecordError("leg_even must carry the even orientation")
        if self.leg_odd.leg is not LegIdentity.ODD:
            raise RecordError("leg_odd must carry the odd orientation")
        if self.leg_even.stream_id != self.stream_id or (
            self.leg_odd.stream_id != self.stream_id
        ):
            raise RecordError("both legs of a pair must read the same stream")
        if self.leg_even.initial_dealer != self.leg_odd.initial_dealer:
            raise RecordError("both legs of a pair must share the initial dealer")
        if self.leg_even.comparison_id != self.comparison_id or (
            self.leg_odd.comparison_id != self.comparison_id
        ):
            raise RecordError("both legs must belong to the same comparison")
        prefix = min(self.leg_even.deals_consumed, self.leg_odd.deals_consumed)
        if (
            self.leg_even.consumed_deal_ids[:prefix]
            != self.leg_odd.consumed_deal_ids[:prefix]
        ):
            raise RecordError(
                "complementary legs must consume the same stream prefix"
            )

        complete = (
            self.leg_even.status is LegStatus.COMPLETE
            and self.leg_odd.status is LegStatus.COMPLETE
        )
        if complete:
            if self.status is not PairStatus.COMPLETE:
                raise RecordError("two complete legs make a complete pair")
            expected = (self.leg_even.y_even - self.leg_odd.y_even) // 2
            if self.d_match != expected:
                raise RecordError("d_match disagrees with the two leg outcomes")
            if self.d_match not in (-1, 0, 1):
                raise RecordError("d_match must be -1, 0, or +1")
        else:
            if self.status is PairStatus.COMPLETE:
                raise RecordError("a pair with an unfinished leg is not complete")
            if self.d_match is not None:
                raise RecordError(
                    "an incomplete pair has no d_match; censoring is never a draw"
                )
            censored = LegStatus.CENSORED_INFRASTRUCTURE in (
                self.leg_even.status,
                self.leg_odd.status,
            )
            expected_status = (
                PairStatus.INCOMPLETE_CENSORED
                if censored
                else PairStatus.INCOMPLETE_FAILED
            )
            if self.status is not expected_status:
                raise RecordError("pair status disagrees with its leg statuses")
        if self.pair_record_id != f"pair:{content_digest(self.semantic_data())}":
            raise RecordError("pair_record_id disagrees with its semantic content")

    @classmethod
    def build(
        cls, *, comparison_id: str, stream_id: str, leg_even: LegRecord, leg_odd: LegRecord
    ) -> "PairRecord":
        complete = (
            leg_even.status is LegStatus.COMPLETE
            and leg_odd.status is LegStatus.COMPLETE
        )
        if complete:
            status = PairStatus.COMPLETE
            d_match = (leg_even.y_even - leg_odd.y_even) // 2
        else:
            censored = LegStatus.CENSORED_INFRASTRUCTURE in (
                leg_even.status,
                leg_odd.status,
            )
            status = (
                PairStatus.INCOMPLETE_CENSORED
                if censored
                else PairStatus.INCOMPLETE_FAILED
            )
            d_match = None
        values = {
            "comparison_id": comparison_id,
            "stream_id": stream_id,
            "leg_even": leg_even,
            "leg_odd": leg_odd,
            "status": status,
            "d_match": d_match,
        }
        provisional = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "schema_version", PAIR_RECORD_SCHEMA_VERSION)
        return cls(
            pair_record_id=f"pair:{content_digest(provisional.semantic_data())}",
            **values,
        )

    def semantic_data(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "d_match": self.d_match,
            "leg_even": self.leg_even.semantic_data(),
            "leg_odd": self.leg_odd.semantic_data(),
            "schema_version": PAIR_RECORD_SCHEMA_VERSION,
            "status": self.status.value,
            "stream_id": self.stream_id,
        }

    def to_data(self) -> dict[str, object]:
        return {
            "comparison_id": self.comparison_id,
            "d_match": self.d_match,
            "leg_even": self.leg_even.to_data(),
            "leg_odd": self.leg_odd.to_data(),
            "pair_record_id": self.pair_record_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "stream_id": self.stream_id,
        }

    @property
    def analysable(self) -> bool:
        return self.status is PairStatus.COMPLETE

    @property
    def total_deals(self) -> int:
        return self.leg_even.deals_consumed + self.leg_odd.deals_consumed
