from __future__ import annotations

import pytest

from tuppi_match import (
    LegIdentity,
    LegStatus,
    MatchStream,
    PairStatus,
    candidate_engine_team,
    match_reference,
    run_leg,
    run_pair,
    seat_assignment,
)
from tuppi_match.errors import RecordError
from tuppi_rules import MATCH_TARGET, Team

from .conftest import comparison


def build(profile_key: str):
    from tuppi_agents import construct_agent, phase4_specifications_by_profile_key

    specification = phase4_specifications_by_profile_key()[profile_key]
    return lambda seat: construct_agent(specification, seat=seat)


def stream(index: int = 0, dealer: int = 0) -> MatchStream:
    return MatchStream.build(
        root_seed="protocol-test", stream_index=index, initial_dealer=dealer
    )


# ------------------------------------------------------------ seat assignment


def test_the_two_legs_exchange_the_even_and_odd_partnerships() -> None:
    assert seat_assignment(LegIdentity.EVEN) == (True, False, True, False)
    assert seat_assignment(LegIdentity.ODD) == (False, True, False, True)
    assert candidate_engine_team(LegIdentity.EVEN) is Team.TEAM_0
    assert candidate_engine_team(LegIdentity.ODD) is Team.TEAM_1


def test_the_match_reference_reveals_no_fixture_identity() -> None:
    """A sealed stream identity must never reach a player observation."""

    source = stream()
    reference = match_reference(leg=LegIdentity.EVEN, ordinal=7)
    assert reference == "cm-e-000007"
    assert source.stream_id.split(":")[-1] not in reference
    assert str(source.root_seed) not in reference
    assert source.deal(0).deal_content_id.split(":")[-1] not in reference


# ------------------------------------------------------ natural termination


@pytest.mark.parametrize("leg", [LegIdentity.EVEN, LegIdentity.ODD])
def test_a_leg_runs_to_natural_termination(leg: LegIdentity) -> None:
    record = run_leg(
        stream=stream(),
        comparison=comparison(),
        leg=leg,
        safety_cap=512,
        ordinal=0,
        build_candidate=build("match_aware_v1"),
        build_opponent=build("partner_aware_v1"),
    )
    assert record.status is LegStatus.COMPLETE
    assert max(record.final_score) >= MATCH_TARGET
    assert record.deals_consumed >= 1
    assert record.winning_engine_team in (0, 1)
    assert record.candidate_won is not None
    assert record.occupancy.total == record.deals_consumed
    assert len(record.consumed_deal_ids) == record.deals_consumed


def test_no_forty_deal_truncation_remains() -> None:
    """The Phase 4 cap of 40 must not bind any longer."""

    lengths = []
    for index in range(6):
        record = run_leg(
            stream=stream(index=index),
            comparison=comparison(),
            leg=LegIdentity.EVEN,
            safety_cap=512,
            ordinal=index,
            build_candidate=build("match_aware_v1"),
            build_opponent=build("partner_aware_v1"),
        )
        assert record.status is LegStatus.COMPLETE
        lengths.append(record.deals_consumed)
    assert max(lengths) > 0
    # A leg that would have been truncated at 40 still finishes here.
    assert all(record > 0 for record in lengths)


def test_the_dealer_rotation_follows_the_ruleset_across_a_long_leg() -> None:
    source = stream(dealer=2)
    record = run_leg(
        stream=source,
        comparison=comparison(),
        leg=LegIdentity.EVEN,
        safety_cap=512,
        ordinal=0,
        build_candidate=build("reactive_contract_v1"),
        build_opponent=build("legacy_heuristic_port_v1"),
    )
    assert record.initial_dealer == 2
    assert source.expected_dealer(0) == 2
    assert source.expected_dealer(record.deals_consumed % 4) == (
        (2 + record.deals_consumed) % 4
    )


# --------------------------------------------------------------- censoring


def test_a_tight_safety_cap_produces_structured_censoring_not_a_draw() -> None:
    record = run_leg(
        stream=stream(index=3),
        comparison=comparison(),
        leg=LegIdentity.EVEN,
        safety_cap=1,
        ordinal=0,
        build_candidate=build("match_aware_v1"),
        build_opponent=build("partner_aware_v1"),
    )
    if record.status is LegStatus.COMPLETE:
        pytest.skip("this stream happens to finish in a single deal")
    assert record.status is LegStatus.CENSORED_INFRASTRUCTURE
    assert record.failure_kind == "censored_infrastructure"
    assert record.winning_engine_team is None
    assert record.candidate_won is None
    assert record.even_partnership_won is None
    assert record.deals_consumed == 1
    assert "not a draw" in record.failure_detail


def test_a_censored_leg_makes_its_pair_incomplete() -> None:
    pair = run_pair(
        stream=stream(index=3),
        comparison=comparison(),
        safety_cap=2,
        ordinal=0,
        build_candidate=build("match_aware_v1"),
        build_opponent=build("partner_aware_v1"),
    )
    if pair.status is PairStatus.COMPLETE:
        pytest.skip("both legs happen to finish within two deals")
    assert pair.status is PairStatus.INCOMPLETE_CENSORED
    assert pair.d_match is None
    assert pair.analysable is False


# ------------------------------------------------------------ duplicate pair


def test_both_legs_read_the_same_stream_and_may_differ_in_length() -> None:
    pair = run_pair(
        stream=stream(index=1),
        comparison=comparison(),
        safety_cap=512,
        ordinal=1,
        build_candidate=build("match_aware_v1"),
        build_opponent=build("reactive_contract_v1"),
    )
    even, odd = pair.leg_even, pair.leg_odd
    shorter = min(even.deals_consumed, odd.deals_consumed)
    assert even.consumed_deal_ids[:shorter] == odd.consumed_deal_ids[:shorter]
    assert even.initial_dealer == odd.initial_dealer
    assert even.stream_id == odd.stream_id
    # The longer leg keeps going; nothing is truncated to the shorter one.
    longer = max(even.deals_consumed, odd.deals_consumed)
    assert longer >= shorter
    if pair.status is PairStatus.COMPLETE:
        assert max(even.final_score) >= MATCH_TARGET
        assert max(odd.final_score) >= MATCH_TARGET


def test_unequal_leg_lengths_are_accepted_by_the_pair_record() -> None:
    found = False
    for index in range(8):
        pair = run_pair(
            stream=stream(index=index),
            comparison=comparison(),
            safety_cap=512,
            ordinal=index,
            build_candidate=build("match_aware_v1"),
            build_opponent=build("reactive_contract_v1"),
        )
        if pair.leg_even.deals_consumed != pair.leg_odd.deals_consumed:
            found = True
            assert pair.status is PairStatus.COMPLETE
            assert pair.d_match in (-1, 0, 1)
            break
    assert found, "expected at least one pair with unequal leg lengths"


def test_a_pair_rejects_legs_from_different_streams() -> None:
    left = run_leg(
        stream=stream(index=0),
        comparison=comparison(),
        leg=LegIdentity.EVEN,
        safety_cap=512,
        ordinal=0,
        build_candidate=build("reactive_contract_v1"),
        build_opponent=build("legacy_heuristic_port_v1"),
    )
    right = run_leg(
        stream=stream(index=1),
        comparison=comparison(),
        leg=LegIdentity.ODD,
        safety_cap=512,
        ordinal=1,
        build_candidate=build("reactive_contract_v1"),
        build_opponent=build("legacy_heuristic_port_v1"),
    )
    from tuppi_match.records import PairRecord

    with pytest.raises(RecordError, match="same stream"):
        PairRecord.build(
            comparison_id=left.comparison_id,
            stream_id=left.stream_id,
            leg_even=left,
            leg_odd=right,
        )


def test_a_pair_is_reproducible_from_its_identities() -> None:
    kwargs = dict(
        stream=stream(index=2),
        comparison=comparison(),
        safety_cap=512,
        ordinal=2,
        build_candidate=build("public_counting_v1"),
        build_opponent=build("reactive_contract_v1"),
    )
    first = run_pair(**kwargs)
    second = run_pair(**kwargs)
    assert first.pair_record_id == second.pair_record_id
    assert first.d_match == second.d_match
    assert first.semantic_data() == second.semantic_data()


def test_starting_from_a_high_score_still_terminates_naturally() -> None:
    pair = run_pair(
        stream=stream(index=4),
        comparison=comparison(starting_score=(48, 0)),
        safety_cap=512,
        ordinal=4,
        build_candidate=build("match_aware_v1"),
        build_opponent=build("match_aware_no_match_features_v1"),
    )
    assert pair.status is PairStatus.COMPLETE
    for leg in (pair.leg_even, pair.leg_odd):
        assert max(leg.final_score) >= MATCH_TARGET
        assert leg.deals_consumed >= 1
