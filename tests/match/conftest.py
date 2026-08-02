from __future__ import annotations

import pytest

from tuppi_match import (
    LegIdentity,
    LegRecord,
    LegStatus,
    MatchComparison,
    PairRecord,
    ScoreStateOccupancy,
    StreamBank,
)
from tuppi_match.banks import BankRole


def comparison(
    *,
    candidate: str = "match_aware_v1",
    opponent: str = "partner_aware_v1",
    starting_score: tuple[int, int] = (0, 0),
    result_class: str = "calibration",
) -> MatchComparison:
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    return MatchComparison.build(
        name=f"test_{candidate}_vs_{opponent}",
        candidate_profile_key=candidate,
        opponent_profile_key=opponent,
        candidate_agent_id=specifications[candidate].agent_id,
        opponent_agent_id=specifications[opponent].agent_id,
        result_class=result_class,
        hypothesis="A comparison built for the test suite.",
        starting_score=starting_score,
    )


def bank(
    *,
    role: BankRole = BankRole.DEVELOPMENT,
    streams: int = 4,
    name: str = "test_bank",
    seed: str = "tuppi-test-bank-v1",
) -> StreamBank:
    return StreamBank.build(
        name=name,
        role=role,
        root_seed=seed,
        initial_dealer=0,
        stream_count=streams,
        purpose="A bank built for the test suite.",
    )


def synthetic_leg(
    *,
    leg: LegIdentity,
    winner: int | None,
    stream_id: str = "stream:sha256:" + "0" * 64,
    comparison_id: str = "cmp:sha256:" + "1" * 64,
    deals: int = 3,
    status: LegStatus | None = None,
    safety_cap: int = 512,
    deal_ids: tuple[str, ...] | None = None,
) -> LegRecord:
    """Build a leg record directly, bypassing execution.

    Used to test the inference layer against hand-constructed outcomes, so a
    statistical bug cannot hide behind an engine bug.
    """

    resolved = status or (
        LegStatus.COMPLETE if winner is not None else LegStatus.CENSORED_INFRASTRUCTURE
    )
    complete = resolved is LegStatus.COMPLETE
    identifiers = deal_ids or tuple(f"streamdeal:test:{index}" for index in range(deals))
    score = (52, 0) if winner == 0 else ((0, 52) if winner == 1 else (12, 0))
    even_won = None if not complete else winner == 0
    candidate_won = (
        None
        if not complete
        else (even_won if leg is LegIdentity.EVEN else not even_won)
    )
    failure_kind = None
    failure_detail = None
    if resolved is LegStatus.CENSORED_INFRASTRUCTURE:
        failure_kind = "censored_infrastructure"
        failure_detail = "synthetic censoring"
    elif resolved is LegStatus.FAILED:
        failure_kind = "SyntheticFailure"
        failure_detail = "synthetic failure"
    return LegRecord.build(
        comparison_id=comparison_id,
        stream_id=stream_id,
        leg=leg,
        initial_dealer=0,
        safety_cap=safety_cap,
        status=resolved,
        deals_consumed=len(identifiers),
        consumed_deal_ids=identifiers,
        final_score=score,
        winning_engine_team=winner if complete else None,
        even_partnership_won=even_won,
        candidate_won=candidate_won,
        resets=0,
        rami_deals=len(identifiers),
        nolo_deals=0,
        successful_rami=len(identifiers),
        stolen_rami=0,
        declarer_seat_counts=(len(identifiers), 0, 0, 0),
        candidate_deal_points=52 if candidate_won else 0,
        opponent_deal_points=0 if candidate_won else 52,
        candidate_tricks=7 * len(identifiers),
        opponent_tricks=6 * len(identifiers),
        immediate_completion=complete and len(identifiers) == 1,
        occupancy=ScoreStateOccupancy(
            deals_at_table=1,
            deals_candidate_up=len(identifiers) - 1,
            deals_candidate_down=0,
        ),
        action_count=56 * len(identifiers),
        duration_seconds=0.0,
        failure_kind=failure_kind,
        failure_detail=failure_detail,
    )


def synthetic_pair(
    *,
    even_winner: int | None,
    odd_winner: int | None,
    index: int = 0,
    comparison_id: str = "cmp:sha256:" + "1" * 64,
) -> PairRecord:
    """Build a pair from two synthetic legs with a distinct stream identity."""

    stream_id = f"stream:sha256:{index:064d}"
    deals = tuple(f"streamdeal:test:{index}:{position}" for position in range(3))
    return PairRecord.build(
        comparison_id=comparison_id,
        stream_id=stream_id,
        leg_even=synthetic_leg(
            leg=LegIdentity.EVEN,
            winner=even_winner,
            stream_id=stream_id,
            comparison_id=comparison_id,
            deal_ids=deals,
        ),
        leg_odd=synthetic_leg(
            leg=LegIdentity.ODD,
            winner=odd_winner,
            stream_id=stream_id,
            comparison_id=comparison_id,
            deal_ids=deals,
        ),
    )


@pytest.fixture(scope="session")
def ladder_keys() -> tuple[str, ...]:
    from tuppi_agents import LADDER_PROFILE_KEYS

    return LADDER_PROFILE_KEYS
