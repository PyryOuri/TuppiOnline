"""The phase-gated PIMC variants, and the frozen Phase 5C baseline they explain."""

from __future__ import annotations

import pytest

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import EnginePhase, PlayCardAction, ShowAction

from tuppi_search.config import PimcConfiguration
from tuppi_search.errors import PimcDecisionError, SearchConfigurationError
from tuppi_search.hybrid import (
    PhaseGatedConfiguration,
    PhaseGatedPimcAgent,
    SearchedPhase,
    construct_gated_agent,
)
from tuppi_search.registry import (
    NEGATIVE_BASELINE_DESIGNATION,
    PHASE5D_A_GATES,
    PRIMARY_PROFILE_KEY,
    build_phase5d_a_agent,
    configuration_for,
    gate_for,
    negative_baseline_designation,
    phase5c_specifications,
    phase5d_a_specification,
    phase5d_a_specifications,
    registry_snapshot,
    specification_for,
)

from .conftest import walk_deal


PLAY_ONLY = "uniform_feasible_pimc_play_only_v1"
SHOW_ONLY = "uniform_feasible_pimc_show_only_v1"


def _reference_agent(seat: int):
    specification = phase4_specifications_by_profile_key()["partner_aware_v1"]
    return construct_agent(specification, seat=seat)


# ----------------------------------------------------------------- the gate


def test_the_gate_routes_each_phase_to_the_right_engine():
    play = gate_for(PLAY_ONLY)
    show = gate_for(SHOW_ONLY)
    assert play.searches(EnginePhase.TRICK_PLAY) is True
    assert play.searches(EnginePhase.SHOWING) is False
    assert show.searches(EnginePhase.SHOWING) is True
    assert show.searches(EnginePhase.TRICK_PLAY) is False


def test_the_gate_refuses_a_phase_that_has_no_decision():
    with pytest.raises(SearchConfigurationError):
        gate_for(PLAY_ONLY).searches(EnginePhase.DEAL_COMPLETE)


def test_the_gate_composes_the_unmodified_primary_configuration():
    primary = configuration_for(PRIMARY_PROFILE_KEY)
    for key in (PLAY_ONLY, SHOW_ONLY):
        gate = gate_for(key)
        assert gate.pimc.configuration_id == primary.configuration_id
        assert gate.delegate_policy_key == "partner_aware_v1"
        assert gate.gate_id.startswith("gate:sha256:")


def test_the_two_gates_have_distinct_identities():
    assert gate_for(PLAY_ONLY).gate_id != gate_for(SHOW_ONLY).gate_id


def test_a_show_only_gate_requires_showing_search_enabled():
    without = PimcConfiguration.build(world_count=2, showing_search_enabled=False)
    with pytest.raises(SearchConfigurationError):
        PhaseGatedConfiguration.build(
            searched_phase=SearchedPhase.SHOWING_ONLY, pimc=without
        )


def test_the_gate_validates_its_inputs():
    primary = configuration_for(PRIMARY_PROFILE_KEY)
    with pytest.raises(SearchConfigurationError):
        PhaseGatedConfiguration.build(
            searched_phase=SearchedPhase.TRICK_PLAY_ONLY,
            pimc=primary,
            delegate_policy_key="not_a_policy",
        )
    with pytest.raises(SearchConfigurationError):
        PhaseGatedConfiguration.build(
            searched_phase="not a phase", pimc=primary  # type: ignore[arg-type]
        )
    with pytest.raises(SearchConfigurationError):
        PhaseGatedConfiguration.build(
            searched_phase=SearchedPhase.TRICK_PLAY_ONLY,
            pimc="not a configuration",  # type: ignore[arg-type]
        )


# -------------------------------------------------------- exact delegation


def test_play_only_uses_the_frozen_reference_showing_policy_exactly():
    """Every delegated showing action must equal the reference agent's own."""

    checked = 0
    for position in walk_deal(stream_index=0):
        if position.observation.phase is not EnginePhase.SHOWING:
            continue
        seat = position.observation.observing_seat
        agent = build_phase5d_a_agent(PLAY_ONLY, seat=seat)
        assert agent.searches(position.observation) is False
        assert agent.choose_action(position.observation) == _reference_agent(
            seat
        ).choose_action(position.observation)
        checked += 1
    assert checked >= 1


def test_show_only_uses_the_frozen_reference_card_policy_exactly():
    checked = 0
    for position in walk_deal(stream_index=0):
        if position.observation.phase is not EnginePhase.TRICK_PLAY:
            continue
        seat = position.observation.observing_seat
        agent = build_phase5d_a_agent(SHOW_ONLY, seat=seat)
        assert agent.searches(position.observation) is False
        assert agent.choose_action(position.observation) == _reference_agent(
            seat
        ).choose_action(position.observation)
        checked += 1
        if checked >= 12:
            break
    assert checked >= 12


def test_show_only_never_searches_during_trick_play():
    """The delegated phase must have no search to explain."""

    for position in walk_deal(stream_index=0):
        if position.observation.phase is not EnginePhase.TRICK_PLAY:
            continue
        agent = build_phase5d_a_agent(
            SHOW_ONLY, seat=position.observation.observing_seat
        )
        assert agent.decide(position.observation) is None
        with pytest.raises(PimcDecisionError):
            agent.explain(position.observation)
        return
    raise AssertionError("no trick-play position was reached")


def test_play_only_never_searches_during_showing():
    for position in walk_deal(stream_index=0):
        if position.observation.phase is not EnginePhase.SHOWING:
            continue
        agent = build_phase5d_a_agent(
            PLAY_ONLY, seat=position.observation.observing_seat
        )
        assert agent.decide(position.observation) is None
        with pytest.raises(PimcDecisionError):
            agent.explain(position.observation)
        return
    raise AssertionError("no showing position was reached")


def test_the_searched_phase_does_search_and_returns_a_legal_action():
    play_checked = show_checked = 0
    for position in walk_deal(stream_index=0):
        observation = position.observation
        seat = observation.observing_seat
        if observation.phase is EnginePhase.SHOWING and show_checked < 1:
            agent = build_phase5d_a_agent(SHOW_ONLY, seat=seat)
            assert agent.searches(observation) is True
            decision = agent.decide(observation)
            assert decision is not None
            assert isinstance(decision.selected_action, ShowAction)
            assert decision.selected_action in observation.legal_actions
            show_checked += 1
        if (
            observation.phase is EnginePhase.TRICK_PLAY
            and play_checked < 1
            and len(observation.legal_actions) >= 2
        ):
            agent = build_phase5d_a_agent(PLAY_ONLY, seat=seat)
            assert agent.searches(observation) is True
            decision = agent.decide(observation)
            assert decision is not None
            assert isinstance(decision.selected_action, PlayCardAction)
            assert decision.selected_action in observation.legal_actions
            play_checked += 1
    assert play_checked == 1 and show_checked == 1


def test_the_two_variants_partition_full_pimc_decisions():
    """Between them the variants search exactly the decisions full PIMC searches."""

    searched_by_play = searched_by_show = both = neither = 0
    for position in walk_deal(stream_index=1):
        observation = position.observation
        seat = observation.observing_seat
        play = build_phase5d_a_agent(PLAY_ONLY, seat=seat).searches(observation)
        show = build_phase5d_a_agent(SHOW_ONLY, seat=seat).searches(observation)
        searched_by_play += int(play)
        searched_by_show += int(show)
        both += int(play and show)
        neither += int(not play and not show)
    assert both == 0, "the variants must not both search the same decision"
    assert neither == 0, "every decision must be searched by exactly one variant"
    assert searched_by_play > 0 and searched_by_show > 0


# ------------------------------------------------------------ determinism


def test_the_gated_agents_are_deterministic(mid_position):
    seat = mid_position.observation.observing_seat
    first = build_phase5d_a_agent(PLAY_ONLY, seat=seat)
    second = build_phase5d_a_agent(PLAY_ONLY, seat=seat)
    assert first.choose_action(mid_position.observation) == second.choose_action(
        mid_position.observation
    )
    left = first.decide(mid_position.observation)
    right = second.decide(mid_position.observation)
    assert [item.mean_utility for item in left.candidates] == [
        item.mean_utility for item in right.candidates
    ]


def test_play_only_matches_full_pimc_on_a_trick_play_observation(mid_position):
    """The gate changes *which* decisions are searched, not how a search runs."""

    from tuppi_search.registry import build_agent

    seat = mid_position.observation.observing_seat
    gated = build_phase5d_a_agent(PLAY_ONLY, seat=seat)
    full = build_agent(PRIMARY_PROFILE_KEY, seat=seat)
    assert gated.choose_action(mid_position.observation) == full.choose_action(
        mid_position.observation
    )


def test_the_gated_agent_refuses_a_foreign_seat_or_a_non_observation(mid_position):
    seat = mid_position.observation.observing_seat
    agent = build_phase5d_a_agent(PLAY_ONLY, seat=(seat + 1) % 4)
    with pytest.raises(PimcDecisionError):
        agent.choose_action(mid_position.observation)
    own = build_phase5d_a_agent(PLAY_ONLY, seat=seat)
    with pytest.raises(PimcDecisionError):
        own.choose_action(mid_position.deal_state)
    with pytest.raises(PimcDecisionError):
        own.choose_action("not an observation")


def test_the_gated_agent_satisfies_the_observation_only_protocol(mid_position):
    from tuppi_agents import ObservationOnlyAgent

    agent = build_phase5d_a_agent(
        PLAY_ONLY, seat=mid_position.observation.observing_seat
    )
    assert isinstance(agent, ObservationOnlyAgent)
    assert agent.identity.startswith("agent:sha256:")
    assert agent.delegate_identity.startswith("agent:sha256:")


def test_the_gated_agent_has_no_parameter_for_a_full_state():
    import inspect

    parameters = set(inspect.signature(PhaseGatedPimcAgent.__init__).parameters)
    assert parameters == {"self", "agent_id", "gate", "seat", "policy_seed"}
    assert set(inspect.signature(PhaseGatedPimcAgent.choose_action).parameters) == {
        "self",
        "observation",
    }


def test_construction_refuses_a_specification_gate_mismatch():
    specification = phase5d_a_specification(PLAY_ONLY)
    with pytest.raises(PimcDecisionError):
        construct_gated_agent(
            specification, seat=0, gate=gate_for(SHOW_ONLY)
        )


def test_gated_agent_construction_validates_its_arguments():
    specification = phase5d_a_specification(PLAY_ONLY)
    gate = gate_for(PLAY_ONLY)
    with pytest.raises(PimcDecisionError):
        PhaseGatedPimcAgent(agent_id="nope", gate=gate, seat=0)
    with pytest.raises(PimcDecisionError):
        PhaseGatedPimcAgent(agent_id=specification.agent_id, gate=gate, seat=9)
    with pytest.raises(PimcDecisionError):
        PhaseGatedPimcAgent(
            agent_id=specification.agent_id, gate=gate, seat=0, policy_seed=""
        )
    with pytest.raises(PimcDecisionError):
        PhaseGatedPimcAgent(
            agent_id=specification.agent_id, gate="not a gate", seat=0
        )


# ------------------------------------------------------------- identities


def test_the_new_identities_are_distinct_from_every_phase5c_identity():
    phase5c = {item.agent_id for item in phase5c_specifications().values()}
    phase5d = {item.agent_id for item in phase5d_a_specifications().values()}
    assert len(phase5d) == len(PHASE5D_A_GATES)
    assert phase5c.isdisjoint(phase5d)


def test_the_phase5c_registry_digest_is_unchanged():
    """Adding diagnostic agents must not touch the committed Phase 5C artifact."""

    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    committed = json.loads(
        (root / "reports" / "phase5c" / "pimc_registry.json").read_text()
    )
    assert registry_snapshot()["registry_digest"] == committed["registry_digest"]


def test_the_specification_records_the_frozen_delegate_and_the_gate():
    for key in (PLAY_ONLY, SHOW_ONLY):
        configuration = phase5d_a_specification(key).configuration
        assert configuration["frozen_delegate_policy_key"] == "partner_aware_v1"
        assert configuration["phase_gate_id"] == gate_for(key).gate_id
        assert configuration["pimc_configuration_id"] == configuration_for(
            PRIMARY_PROFILE_KEY
        ).configuration_id
        assert configuration["recursive_search"] is None
        assert configuration["information_set_search"] is None
        assert configuration["learned_world_weighting"] is None
        assert configuration["persistent_search_tree"] is None
        assert configuration["self_play_training"] is None
        assert configuration["observation_only"] is True
        assert configuration["world_count"] == 4
        assert configuration["searched_phase"] in (
            "trick_play_only",
            "showing_only",
        )


def test_the_delegated_phase_is_recorded_correctly():
    play = phase5d_a_specification(PLAY_ONLY).configuration
    show = phase5d_a_specification(SHOW_ONLY).configuration
    assert play["delegated_phase"] == "SHOWING"
    assert show["delegated_phase"] == "TRICK_PLAY"


# ------------------------------------------------- the frozen negative baseline


def test_the_negative_baseline_designation_changes_no_identity():
    designation = negative_baseline_designation()
    assert designation["designation"] == NEGATIVE_BASELINE_DESIGNATION
    assert designation["identity_unchanged"] is True
    assert designation["agent_id"] == specification_for(PRIMARY_PROFILE_KEY).agent_id
    assert designation["pimc_configuration_id"] == configuration_for(
        PRIMARY_PROFILE_KEY
    ).configuration_id


def test_the_designation_states_its_scope_limit_and_its_uses():
    designation = negative_baseline_designation()
    assert "Rejected as a development improvement" in designation["statement"]
    assert "No strength claim" in designation["statement"]
    assert "one configuration was measured" in designation["scope_limit"].lower()
    assert any("regression" in use for use in designation["uses"])
    assert any("comparator" in use for use in designation["uses"])


def test_the_designation_quotes_the_measured_result():
    statement = negative_baseline_designation()["statement"]
    for fragment in ("0.156", "32 complementary", "0 wins / 10 ties / 22 losses"):
        assert fragment in statement, fragment
