from __future__ import annotations

import json

import pytest

from tuppi_agents import (
    DIAGNOSTICS_SCHEMA_VERSION,
    LADDER_PROFILE_KEYS,
    DiagnosticsRecordingAgent,
    assert_no_foreign_cards,
    construct_agent,
    observation_digest,
    phase4_specifications_by_profile_key,
    require_rule,
)
from tuppi_agents.diagnostics import build_diagnostics
from tuppi_agents.errors import DiagnosticsError
from tuppi_engine import (
    EnginePhase,
    action_to_data,
    apply_match_action,
    match_observation_for,
)
from tuppi_rules import Contract, card_to_code

from .conftest import acting_observation, build_position, partition_deck, start_deal


ALL_NOLO = (Contract.NOLO,) * 4


def _decision(profile_key: str = "match_aware_v1"):
    specification = phase4_specifications_by_profile_key()[profile_key]
    hands = partition_deck({})
    state = build_position(hands, dealer=0, show_contracts=ALL_NOLO)
    observation = acting_observation(state)
    agent = construct_agent(specification, seat=observation.observing_seat)
    return agent, observation, agent.decide(observation, diagnostics=True)


@pytest.mark.parametrize("profile_key", LADDER_PROFILE_KEYS)
def test_candidate_scores_reconcile_with_the_selected_action(profile_key: str) -> None:
    _, observation, decision = _decision(profile_key)
    record = decision.diagnostics
    assert record is not None
    assert record.legal_action_count == len(observation.legal_actions)
    selected = [item for item in record.candidates if item.selected]
    assert len(selected) == 1
    best = max(
        record.candidates,
        key=lambda item: (tuple(item.score_vector), -item.action_order_index),
    )
    assert best.selected is True
    assert best.action == action_to_data(decision.action)
    assert record.selected_action == action_to_data(decision.action)


@pytest.mark.parametrize("profile_key", LADDER_PROFILE_KEYS)
def test_every_cited_rule_exists_in_the_catalogue(profile_key: str) -> None:
    _, _, decision = _decision(profile_key)
    record = decision.diagnostics
    assert record is not None
    assert record.invoked_rule_ids
    for rule_id in record.invoked_rule_ids:
        assert require_rule(rule_id).rule_id == rule_id
    cited = {rule for item in record.candidates for rule in item.rule_ids}
    assert cited == set(record.invoked_rule_ids)


@pytest.mark.parametrize("profile_key", LADDER_PROFILE_KEYS)
def test_diagnostics_record_identity_and_schema(profile_key: str) -> None:
    specification = phase4_specifications_by_profile_key()[profile_key]
    _, observation, decision = _decision(profile_key)
    record = decision.diagnostics
    assert record is not None
    assert record.schema_version == DIAGNOSTICS_SCHEMA_VERSION
    assert record.agent_id == specification.agent_id
    assert record.profile_key == profile_key
    assert record.profile_id.startswith("profile:sha256:")
    assert record.observation_digest == observation_digest(observation)
    assert record.action_ordering_id == "tuppi.agents.engine_legal_action_order.v1"
    assert record.tie_break_id == "lowest_engine_legal_action_index_v1"
    assert record.match_role in ("table", "up", "down")
    assert record.phase in ("SHOWING", "TRICK_PLAY")


def test_the_observation_digest_is_a_one_way_commitment() -> None:
    _, observation, decision = _decision()
    record = decision.diagnostics
    assert record is not None
    payload = json.dumps(record.to_data(), sort_keys=True)
    assert record.observation_digest in payload
    # No card code of the observing player's own hand is embedded in the digest.
    for held in observation.own_hand:
        assert card_to_code(held) not in record.observation_digest


def test_diagnostics_do_not_carry_the_full_own_hand() -> None:
    _, observation, decision = _decision()
    record = decision.diagnostics
    assert record is not None
    payload = json.dumps(record.to_data(), sort_keys=True)
    codes = {card_to_code(item) for item in observation.own_hand}
    legal = set()
    for action in observation.legal_actions:
        data = action_to_data(action)
        legal.add(data.get("card") or data.get("shown_card"))
    for code in codes - legal:
        assert f'"{code}"' not in payload
    assert record.own_hand_size == len(observation.own_hand)


def test_sentinel_rejects_a_record_that_names_a_hidden_card() -> None:
    _, observation, decision = _decision()
    record = decision.diagnostics
    assert record is not None
    visible = {card_to_code(item) for item in observation.own_hand}
    assert_no_foreign_cards(record, frozenset({"__not_a_card__"}))
    leaked = next(
        code for action in observation.legal_actions
        for code in [action_to_data(action).get("shown_card") or action_to_data(action).get("card")]
    )
    assert leaked in visible
    with pytest.raises(DiagnosticsError, match="leaked a card"):
        assert_no_foreign_cards(record, frozenset({leaked}))


def test_diagnostics_are_immutable_and_serialise_canonically() -> None:
    _, _, decision = _decision()
    record = decision.diagnostics
    assert record is not None
    with pytest.raises(Exception):
        record.agent_id = "other"  # type: ignore[misc]
    first = json.dumps(record.to_data(), sort_keys=True)
    second = json.dumps(record.to_data(), sort_keys=True)
    assert first == second


def test_building_diagnostics_rejects_a_non_ranking() -> None:
    _, observation, _ = _decision()
    with pytest.raises(DiagnosticsError):
        build_diagnostics(
            observation=observation,
            scored="not a ranking",  # type: ignore[arg-type]
            agent_id="agent:sha256:" + "0" * 64,
            profile_id="profile:sha256:" + "0" * 64,
            profile_key="x",
            match_role="table",
        )


def test_the_recording_wrapper_captures_one_record_per_decision() -> None:
    specification = phase4_specifications_by_profile_key()["partner_aware_v1"]
    hands = partition_deck({})
    wrappers = tuple(
        DiagnosticsRecordingAgent(construct_agent(specification, seat=seat))
        for seat in range(4)
    )
    plain = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    state = start_deal(hands)
    control = start_deal(hands)
    decisions = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        recorded = wrappers[actor].choose_action(observation)
        quiet = plain[actor].choose_action(match_observation_for(control, actor))
        assert recorded == quiet
        state = apply_match_action(state, recorded)
        control = apply_match_action(control, quiet)
        decisions += 1
    assert sum(len(wrapper.records) for wrapper in wrappers) == decisions
    assert state.completed_deals[-1].public_result.team_tricks == (
        control.completed_deals[-1].public_result.team_tricks
    )


def test_the_wrapper_rejects_a_non_policy_delegate() -> None:
    from tuppi_agents.errors import PolicyError

    with pytest.raises(PolicyError):
        DiagnosticsRecordingAgent(object())  # type: ignore[arg-type]


def test_reason_codes_are_short_machine_readable_tokens() -> None:
    for key in LADDER_PROFILE_KEYS:
        _, _, decision = _decision(key)
        record = decision.diagnostics
        assert record is not None
        for candidate in record.candidates:
            assert candidate.reason_codes
            for code in candidate.reason_codes:
                assert code == code.lower()
                assert code.replace("_", "").isalnum()
                assert len(code) <= 48
