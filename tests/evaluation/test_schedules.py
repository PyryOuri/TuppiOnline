from __future__ import annotations

from collections import Counter

from hypothesis import given, settings, strategies as st

from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_eval.schedules import (
    CANONICAL_BLOCK_SIZE,
    CANONICAL_SCHEDULE_DESIGN,
    EvaluationMode,
    build_canonical_schedule,
    schedule_from_data,
    schedule_to_data,
)
from tuppi_rules import MatchScore

from .support import baseline_teams


@given(
    root_seed=st.integers(),
    initial_dealer=st.integers(min_value=0, max_value=3),
    count=st.integers(min_value=1, max_value=8),
)
@settings(max_examples=20)
def test_canonical_schedule_balance_is_a_property_of_every_base_deal(
    root_seed: int, initial_dealer: int, count: int
) -> None:
    _, team_a, team_b = baseline_teams()
    bank = generate_deal_bank(
        count=count,
        root_seed=root_seed,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=initial_dealer,
        starting_score=MatchScore(),
        creation_metadata={},
    )
    schedule = build_canonical_schedule(
        deal_bank=bank, team_a=team_a, team_b=team_b
    )
    assert schedule.design_id == CANONICAL_SCHEDULE_DESIGN
    assert schedule.block_size == CANONICAL_BLOCK_SIZE
    assert len(schedule.entries) == count * 8
    assert len({entry.entry_id for entry in schedule.entries}) == len(
        schedule.entries
    )
    assert schedule_from_data(schedule_to_data(schedule)) == schedule

    for block_index in range(count):
        rows = tuple(
            entry for entry in schedule.entries if entry.block_index == block_index
        )
        assert Counter(row.transformed_dealer for row in rows) == Counter(
            {0: 2, 1: 2, 2: 2, 3: 2}
        )
        assert Counter(row.transformed_forehand for row in rows) == Counter(
            {0: 2, 1: 2, 2: 2, 3: 2}
        )
        assert Counter(row.seat_external_teams[0] for row in rows) == Counter(
            {"A": 4, "B": 4}
        )
        for external in ("A", "B"):
            assert sum(
                row.seat_external_teams[row.transformed_dealer] == external
                for row in rows
            ) == 4
            assert sum(
                row.seat_external_teams[row.transformed_forehand] == external
                for row in rows
            ) == 4
        for agent_id in {agent for row in rows for agent in row.seat_agent_ids}:
            assert len(
                {
                    sum(row.seat_agent_ids[seat] == agent_id for row in rows)
                    for seat in range(4)
                }
            ) == 1


def test_match_schedule_groups_sequences_as_independent_units() -> None:
    _, team_a, team_b = baseline_teams()
    bank = generate_deal_bank(
        count=6,
        root_seed=100,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(40, 0),
        creation_metadata={},
    )
    schedule = build_canonical_schedule(
        deal_bank=bank,
        team_a=team_a,
        team_b=team_b,
        mode=EvaluationMode.MATCH,
        match_sequence_length=3,
    )
    assert len(schedule.entries) == 16
    assert len({entry.base_deal_id for entry in schedule.entries}) == 2
    assert all(len(entry.source_base_deal_ids) == 3 for entry in schedule.entries)
    assert all(entry.base_deal_id.startswith("sequence:sha256:") for entry in schedule.entries)


def test_schedule_order_and_ids_are_stable() -> None:
    registry, team_a, team_b = baseline_teams()
    bank = generate_deal_bank(
        count=2,
        root_seed=93,
        dealer_policy=DealerPolicy.DIGEST_DERIVED,
        initial_dealer=3,
        starting_score=MatchScore(),
        creation_metadata={"one": 1},
    )
    first = build_canonical_schedule(
        deal_bank=bank, team_a=team_a, team_b=team_b
    )
    second = build_canonical_schedule(
        deal_bank=bank, team_a=team_a, team_b=team_b
    )
    assert first.schedule_id == second.schedule_id
    assert [item.entry_id for item in first.entries] == [
        item.entry_id for item in second.entries
    ]
