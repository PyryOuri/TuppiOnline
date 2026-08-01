from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tuppi_engine import (
    ExplicitDeal,
    ExplicitMatchInput,
    FirstLegalActionAgent,
    EventType,
    CompletedTrick,
    ResearchDealResult,
    SerializationError,
    StateInvariantError,
    agent_script_from_data,
    agent_script_to_data,
    atomic_write_canonical_json,
    canonical_json_bytes,
    explicit_deal_from_data,
    explicit_deal_to_data,
    match_input_from_data,
    match_input_to_data,
    match_observation_for,
    observation_to_data,
    public_event_log_to_data,
    research_run_result_to_data,
    strict_json_load_file,
    strict_json_loads,
)
from tuppi_engine.runner import run_match_input
from tuppi_rules import (
    FULL_DECK,
    MatchScore,
    ShowAction as RulesShowAction,
    card_to_code,
    valid_show_cards,
)

from .conftest import apply_first_legal, start_match_deal, suit_block_hands


ALL_CODES = frozenset(card_to_code(card) for card in FULL_DECK)


def _match_input() -> ExplicitMatchInput:
    deal = ExplicitDeal(dealer=0, hands=suit_block_hands())
    return ExplicitMatchInput(
        match_ref="serialization-test",
        initial_score=MatchScore(),
        initial_dealer=0,
        deals=(deal,),
    )


def _run():
    return run_match_input(
        _match_input(), tuple(FirstLegalActionAgent() for _ in range(4))
    )


def _card_values(value) -> set[str]:
    result: set[str] = set()
    if isinstance(value, str) and value in ALL_CODES:
        result.add(value)
    elif isinstance(value, list):
        for item in value:
            result.update(_card_values(item))
    elif isinstance(value, dict):
        for item in value.values():
            result.update(_card_values(item))
    return result


def test_explicit_deal_round_trip_and_claimed_id_verification() -> None:
    original = ExplicitDeal(dealer=0, hands=suit_block_hands())
    data = explicit_deal_to_data(original)
    restored = explicit_deal_from_data(data)
    assert restored == original
    assert canonical_json_bytes(explicit_deal_to_data(restored)) == canonical_json_bytes(
        data
    )
    data["deal_id"] = "sha256:" + "0" * 64
    with pytest.raises(SerializationError, match="deal_id"):
        explicit_deal_from_data(data)
    data = explicit_deal_to_data(original)
    data["deal_id"] = None
    with pytest.raises(SerializationError, match="deal_id"):
        explicit_deal_from_data(data)


def test_match_input_round_trip_and_stable_identity() -> None:
    original = _match_input()
    data = match_input_to_data(original)
    restored = match_input_from_data(data)
    assert restored == original
    assert restored.match_input_id == original.match_input_id
    data["match_input_id"] = "sha256:" + "f" * 64
    with pytest.raises(SerializationError, match="match_input_id"):
        match_input_from_data(data)
    data = match_input_to_data(original)
    data["match_input_id"] = None
    with pytest.raises(SerializationError, match="match_input_id"):
        match_input_from_data(data)


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    with pytest.raises(SerializationError, match="duplicate"):
        strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(SerializationError, match="non-finite"):
        strict_json_loads('{"a":NaN}')


def test_file_loader_rejects_invalid_utf8_with_typed_error(tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"{\xff}")
    with pytest.raises(SerializationError, match="cannot read JSON"):
        strict_json_load_file(invalid)


def test_unknown_fields_and_noncanonical_card_codes_are_rejected() -> None:
    data = explicit_deal_to_data(ExplicitDeal(dealer=0, hands=suit_block_hands()))
    data["unknown"] = True
    with pytest.raises(SerializationError, match="unknown"):
        explicit_deal_from_data(data)

    for bad_code in ("2h", " 2H ", "H2"):
        data = explicit_deal_to_data(
            ExplicitDeal(dealer=0, hands=suit_block_hands())
        )
        data["hands"][0][0] = bad_code
        with pytest.raises(SerializationError, match="canonical"):
            explicit_deal_from_data(data)


def test_fixed_agent_script_round_trip_and_input_binding() -> None:
    match_input = _match_input()
    state = start_match_deal()
    actor = state.current_actor
    action = match_observation_for(state, actor).legal_actions[0]
    data = agent_script_to_data((action,), match_input_id=match_input.match_input_id)
    assert agent_script_from_data(
        data, expected_match_input_id=match_input.match_input_id
    ) == (action,)
    with pytest.raises(SerializationError, match="different match"):
        agent_script_from_data(
            data, expected_match_input_id="sha256:" + "0" * 64
        )
    with pytest.raises(SerializationError, match="nonempty"):
        agent_script_to_data((), match_input_id=match_input.match_input_id)
    with pytest.raises(SerializationError, match="sha256"):
        agent_script_to_data((action,), match_input_id="not-a-digest")


def test_repeated_execution_produces_byte_identical_research_result() -> None:
    first = canonical_json_bytes(research_run_result_to_data(_run()))
    second = canonical_json_bytes(research_run_result_to_data(_run()))
    assert first == second


def test_repeated_serialization_is_byte_identical() -> None:
    result = _run()
    data = research_run_result_to_data(result)
    assert canonical_json_bytes(data) == canonical_json_bytes(data)
    assert json.loads(canonical_json_bytes(data)) == data


def test_output_path_does_not_change_canonical_content(tmp_path) -> None:
    data = research_run_result_to_data(_run())
    first = tmp_path / "one.json"
    second = tmp_path / "two.json"
    atomic_write_canonical_json(first, data)
    atomic_write_canonical_json(second, data)
    assert first.read_bytes() == second.read_bytes()
    assert str(first) not in first.read_text(encoding="utf-8")
    assert str(second) not in second.read_text(encoding="utf-8")


def test_observation_calls_do_not_change_execution_or_events() -> None:
    baseline = _run()
    state = start_match_deal(match_ref="serialization-test")
    while state.phase.value in {"SHOWING", "TRICK_PLAY"}:
        actor = state.current_actor
        for seat in range(4):
            observation_to_data(match_observation_for(state, seat))
        action = match_observation_for(state, actor).legal_actions[0]
        state = apply_first_legal(state)
    observed_bytes = canonical_json_bytes(
        public_event_log_to_data(state.public_events, match_ref=state.match_ref)
    )
    baseline_bytes = canonical_json_bytes(
        public_event_log_to_data(
            baseline.public_events, match_ref=baseline.match_ref
        )
    )
    assert observed_bytes == baseline_bytes


def test_public_event_prefix_never_exposes_unshown_unplayed_cards() -> None:
    state = start_match_deal(match_ref="privacy-prefix")
    while True:
        active = state.active_deal
        shown = {action.shown_card for action in active.show_actions}
        played = {
            play.card
            for trick in active.completed_tricks
            for play in trick.plays
        } | {play.card for play in active.current_trick}
        data = public_event_log_to_data(
            state.public_events, match_ref=state.match_ref
        )
        assert _card_values(data) <= {
            card_to_code(card) for card in shown | played
        }
        if state.phase.value not in {"SHOWING", "TRICK_PLAY"}:
            break
        state = apply_first_legal(state)


def test_deal_started_event_contains_no_card_or_content_digest() -> None:
    state = start_match_deal()
    data = public_event_log_to_data(state.public_events, match_ref=state.match_ref)
    assert _card_values(data) == set()
    serialized = canonical_json_bytes(data)
    assert b"hands" not in serialized
    assert b"deal_id" not in serialized
    assert state.active_deal.deal_id.encode() not in serialized


def test_forged_public_event_payload_is_rejected() -> None:
    """A frozen-but-forged public event cannot disclose an unaccepted card."""

    result = _run()
    public = result.deals[0].public_result
    position = next(
        index
        for index, event in enumerate(public.events)
        if event.event_type is EventType.SHOW_ACCEPTED
    )
    event = public.events[position]
    hidden = next(
        card
        for card in result.deals[0].initial_hands[0]
        if card != event.payload.shown_card
    )
    forged_event = replace(
        event, payload=replace(event.payload, shown_card=hidden)
    )
    forged_events = public.events[:position] + (forged_event,) + public.events[position + 1 :]
    with pytest.raises(StateInvariantError, match="events disagree"):
        replace(public, events=forged_events)


def test_research_result_binds_initial_hands_and_match_input_identity() -> None:
    run = _run()
    public = run.deals[0].public_result
    hands = run.deals[0].initial_hands
    other_hands = (hands[1], hands[0], hands[2], hands[3])
    other = ExplicitDeal(dealer=public.dealer, hands=other_hands)
    with pytest.raises(StateInvariantError):
        ResearchDealResult(
            public_result=public,
            deal_id=other.deal_id,
            initial_hands=other.hands,
        )
    with pytest.raises(StateInvariantError, match="match_input_id"):
        replace(run, match_input_id="sha256:" + "0" * 64)


def test_forged_completed_trick_winner_is_revalidated() -> None:
    public = _run().deals[0].public_result
    original = public.completed_tricks[0]
    forged = object.__new__(CompletedTrick)
    object.__setattr__(forged, "trick_index", original.trick_index)
    object.__setattr__(forged, "leader", original.leader)
    object.__setattr__(forged, "plays", original.plays)
    object.__setattr__(forged, "winner", (original.winner + 2) % 4)
    with pytest.raises(StateInvariantError, match="completed trick"):
        replace(
            public,
            completed_tricks=(forged,) + public.completed_tricks[1:],
        )


def test_public_result_binds_shown_card_to_playing_seat() -> None:
    run = _run()
    public = run.deals[0].public_result
    original = public.show_actions[0]
    other_seat = (original.seat + 1) % 4
    other_hand = run.deals[0].initial_hands[other_seat]
    shown_card = next(iter(valid_show_cards(other_hand, original.declared_contract)))
    forged = RulesShowAction(
        seat=original.seat,
        hand=other_hand,
        shown_card=shown_card,
        declared_contract=original.declared_contract,
    )
    with pytest.raises(StateInvariantError, match="shown-card ownership"):
        replace(public, show_actions=(forged,) + public.show_actions[1:])
