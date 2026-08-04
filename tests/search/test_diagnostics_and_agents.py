"""Diagnostics privacy, agent identity, and configuration materiality."""

from __future__ import annotations

import json

import pytest

from tuppi_eval.identities import DeterminismClass, SeedPolicy
from tuppi_rules import card_to_code, team_for_seat

from tuppi_search.agents import (
    DEFAULT_POLICY_SEED,
    UniformFeasiblePimcAgent,
    construct_pimc_agent,
)
from tuppi_search.config import (
    ExactTailFailurePolicy,
    PimcConfiguration,
    RootContinuation,
)
from tuppi_search.diagnostics import (
    FORBIDDEN_KEYS,
    PimcDecisionDiagnostics,
    observation_visible_card_codes,
    require_privacy_safe,
)
from tuppi_search.errors import (
    PimcDecisionError,
    SearchConfigurationError,
    SearchDiagnosticsError,
)
from tuppi_search.registry import (
    PRIMARY_PROFILE_KEY,
    REGISTERED_CONFIGURATIONS,
    build_agent,
    configuration_for,
    homogeneous_team,
    phase5c_specifications,
    registry_snapshot,
    specification_for,
)
from tuppi_search.utilities import UtilityId


# --------------------------------------------------------------- diagnostics


def _diagnostics(position, profile_key=PRIMARY_PROFILE_KEY):
    seat = position.observation.observing_seat
    agent = build_agent(profile_key, seat=seat)
    return agent.explain(position.observation)


def test_diagnostics_contain_every_required_field(mid_position):
    payload = _diagnostics(mid_position).to_data()
    for key in (
        "agent_id",
        "candidates",
        "exact_tail",
        "failure_counts",
        "information_state",
        "legal_actions",
        "phase",
        "pimc_configuration_id",
        "pimc_protocol_version",
        "rollout_policy_agent_ids",
        "root_seat",
        "root_team",
        "schema_version",
        "selected_action",
        "selection_gap",
        "semantic_work_budget",
        "simulation_counts",
        "tie_break_id",
        "utility",
        "world_set",
    ):
        assert key in payload, key
    assert payload["root_team"] == team_for_seat(payload["root_seat"]).value
    assert payload["world_set"]["exact_feasible_assignment_count"] >= 1
    assert payload["utility"]["utility_id"] == UtilityId.MATCH_TRANSITION_V1.value


def test_diagnostics_never_name_a_card_the_seat_cannot_see(mid_position):
    """The sharp privacy test: no card code outside the information set appears."""

    payload = _diagnostics(mid_position).to_data()
    serialized = json.dumps(payload, sort_keys=True)
    visible = observation_visible_card_codes(mid_position.observation)
    from tuppi_rules import FULL_DECK

    for card in FULL_DECK:
        code = card_to_code(card)
        if code in visible:
            continue
        # Two-character codes could collide with digest hex, so search for the
        # code as a standalone token inside the serialized record.
        assert f'"{code}"' not in serialized, code


def test_diagnostics_contain_no_forbidden_key(mid_position):
    payload = _diagnostics(mid_position).to_data()
    require_privacy_safe(payload)
    serialized = json.dumps(payload, sort_keys=True)
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in serialized, key


def test_diagnostics_do_not_reveal_the_true_deal_identifier(mid_position):
    payload = _diagnostics(mid_position).to_data()
    serialized = json.dumps(payload, sort_keys=True)
    assert mid_position.deal_state.deal_id not in serialized
    assert mid_position.deal_state.deal_id.removeprefix("sha256:") not in serialized


def test_a_forbidden_key_is_rejected_wherever_it_hides():
    with pytest.raises(SearchDiagnosticsError):
        require_privacy_safe({"a": [{"b": {"true_hands": []}}]})
    with pytest.raises(SearchDiagnosticsError):
        require_privacy_safe({"world_set": {"true_world_index": 3}})
    require_privacy_safe({"safe": [1, 2, {"also_safe": True}]})


def test_requesting_diagnostics_cannot_change_the_action(mid_position):
    seat = mid_position.observation.observing_seat
    agent = build_agent(PRIMARY_PROFILE_KEY, seat=seat)
    played = agent.choose_action(mid_position.observation)
    explained = agent.explain(mid_position.observation)
    assert explained.decision.selected_action == played
    # And a second explanation is identical, so explaining has no side effect.
    assert explained.to_data() == agent.explain(mid_position.observation).to_data()


def test_diagnostics_require_a_canonical_agent_and_four_policies(mid_position):
    diagnostics = _diagnostics(mid_position)
    with pytest.raises(SearchDiagnosticsError):
        PimcDecisionDiagnostics(
            agent_id="not-canonical",
            decision=diagnostics.decision,
            rollout_policy_agent_ids=diagnostics.rollout_policy_agent_ids,
        )
    with pytest.raises(SearchDiagnosticsError):
        PimcDecisionDiagnostics(
            agent_id=diagnostics.agent_id,
            decision=diagnostics.decision,
            rollout_policy_agent_ids=("only-one",),
        )
    with pytest.raises(SearchDiagnosticsError):
        PimcDecisionDiagnostics(
            agent_id=diagnostics.agent_id,
            decision="not a decision",  # type: ignore[arg-type]
            rollout_policy_agent_ids=diagnostics.rollout_policy_agent_ids,
        )


def test_a_forced_decision_reports_no_world_set(forced_position):
    payload = _diagnostics(forced_position).to_data()
    assert payload["single_legal_action_shortcut"] is True
    assert payload["world_set"]["requested_world_count"] == 0
    assert "single legal action" in payload["world_set"]["reason"]


def test_the_exact_tail_agent_reports_its_threshold(late_position):
    payload = _diagnostics(
        late_position, profile_key="uniform_feasible_pimc_exact_tail_v1"
    ).to_data()
    assert payload["exact_tail"]["enabled"] is True
    assert payload["exact_tail"]["max_tricks_remaining"] == 4
    assert payload["simulation_counts"]["solver_calls"] > 0


# ------------------------------------------------------------------- agents


def test_the_agent_satisfies_the_engine_protocol(mid_position):
    """Structural check: ``tuppi_engine.Agent`` is a Protocol, not a base class."""

    from tuppi_agents import ObservationOnlyAgent

    agent = build_agent(
        PRIMARY_PROFILE_KEY, seat=mid_position.observation.observing_seat
    )
    assert isinstance(agent, ObservationOnlyAgent)
    assert hasattr(agent, "identity")
    assert callable(agent.choose_action)
    assert agent.identity.startswith("agent:sha256:")


def test_the_agent_refuses_another_seats_observation(mid_position):
    seat = mid_position.observation.observing_seat
    agent = build_agent(PRIMARY_PROFILE_KEY, seat=(seat + 1) % 4)
    with pytest.raises(PimcDecisionError):
        agent.choose_action(mid_position.observation)


def test_the_agent_refuses_anything_that_is_not_an_observation(mid_position):
    agent = build_agent(PRIMARY_PROFILE_KEY, seat=0)
    with pytest.raises(PimcDecisionError):
        agent.choose_action(mid_position.deal_state)
    with pytest.raises(PimcDecisionError):
        agent.choose_action("not an observation")


def test_agent_construction_validates_its_arguments():
    configuration = configuration_for(PRIMARY_PROFILE_KEY)
    specification = specification_for(PRIMARY_PROFILE_KEY)
    with pytest.raises(PimcDecisionError):
        UniformFeasiblePimcAgent(
            agent_id="nope", configuration=configuration, seat=0
        )
    with pytest.raises(PimcDecisionError):
        UniformFeasiblePimcAgent(
            agent_id=specification.agent_id, configuration=configuration, seat=9
        )
    with pytest.raises(PimcDecisionError):
        UniformFeasiblePimcAgent(
            agent_id=specification.agent_id,
            configuration=configuration,
            seat=0,
            policy_seed="",
        )


def test_construction_refuses_a_specification_configuration_mismatch():
    specification = specification_for(PRIMARY_PROFILE_KEY)
    other = configuration_for("uniform_feasible_pimc_standard_v1")
    with pytest.raises(PimcDecisionError):
        construct_pimc_agent(specification, seat=0, configuration=other)


def test_the_policy_seed_changes_the_decision_seed(mid_position):
    seat = mid_position.observation.observing_seat
    first = build_agent(PRIMARY_PROFILE_KEY, seat=seat, policy_seed="alpha")
    second = build_agent(PRIMARY_PROFILE_KEY, seat=seat, policy_seed="beta")
    assert first.decision_seed(mid_position.observation) != second.decision_seed(
        mid_position.observation
    )
    assert DEFAULT_POLICY_SEED


def test_the_seat_changes_the_decision_seed(mid_position):
    """Two seats of one partnership must not share a world stream by accident."""

    configuration = configuration_for(PRIMARY_PROFILE_KEY)
    specification = specification_for(PRIMARY_PROFILE_KEY)
    seeds = {
        UniformFeasiblePimcAgent(
            agent_id=specification.agent_id,
            configuration=configuration,
            seat=seat,
            policy_seed="same",
        ).decision_seed(mid_position.observation)
        for seat in range(4)
    }
    assert len(seeds) == 4


# ------------------------------------------------------------------ identity


def test_every_registered_agent_has_a_distinct_identity():
    specifications = phase5c_specifications()
    assert len(specifications) == len(REGISTERED_CONFIGURATIONS)
    assert len({item.agent_id for item in specifications.values()}) == len(
        specifications
    )
    for specification in specifications.values():
        assert specification.determinism is DeterminismClass.DETERMINISTIC
        assert specification.seed_policy is SeedPolicy.NONE
        assert specification.search_budget is not None


@pytest.mark.parametrize(
    "field,value",
    [
        ("world_count", 7),
        ("rollout_policy_key", "public_counting_v1"),
        ("utility_id", UtilityId.DEAL_RESULT_V1),
        ("showing_search_enabled", False),
    ],
)
def test_every_behaviourally_material_field_changes_the_identity(field, value):
    base = PimcConfiguration.build(world_count=4)
    changed = PimcConfiguration.build(**{"world_count": 4, field: value})
    assert changed.configuration_id != base.configuration_id


def test_the_exact_tail_switch_and_threshold_change_the_identity():
    base = PimcConfiguration.build(world_count=4)
    enabled = PimcConfiguration.build(
        world_count=4, exact_tail_enabled=True, exact_tail_max_tricks_remaining=4
    )
    tighter = PimcConfiguration.build(
        world_count=4, exact_tail_enabled=True, exact_tail_max_tricks_remaining=2
    )
    fallback = PimcConfiguration.build(
        world_count=4,
        exact_tail_enabled=True,
        exact_tail_max_tricks_remaining=4,
        exact_tail_failure_policy=ExactTailFailurePolicy.FALLBACK_ROLLOUT,
    )
    assert len(
        {
            base.configuration_id,
            enabled.configuration_id,
            tighter.configuration_id,
            fallback.configuration_id,
        }
    ) == 4


def test_the_root_continuation_mode_changes_the_identity():
    base = PimcConfiguration.build(world_count=4)
    alternate = PimcConfiguration.build(
        world_count=4,
        root_continuation=RootContinuation.ALTERNATE_ROLLOUT_POLICY,
        root_rollout_policy_key="public_counting_v1",
    )
    assert alternate.configuration_id != base.configuration_id


def test_replicas_beyond_one_are_refused_for_deterministic_policies():
    """Averaging identical rollouts would burn compute for no information."""

    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(world_count=4, rollout_replicas=2)


def test_malformed_configurations_are_refused():
    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(world_count=0)
    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(world_count=4, rollout_policy_key="not_a_policy")
    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(
            world_count=4,
            root_continuation=RootContinuation.ALTERNATE_ROLLOUT_POLICY,
        )
    with pytest.raises(SearchConfigurationError):
        PimcConfiguration.build(
            world_count=4, root_rollout_policy_key="public_counting_v1"
        )


def test_the_configuration_records_its_deterministic_budget():
    configuration = configuration_for(PRIMARY_PROFILE_KEY)
    data = configuration.to_data()
    budget = data["semantic_work_budget"]
    assert budget["stopping_rule"] == "deterministic_work_budget"
    assert budget["world_count"] == configuration.world_count
    assert budget["rollouts_per_candidate"] == (
        configuration.total_rollouts_per_candidate
    )
    assert "wall_clock" not in json.dumps(data)


def test_the_registry_snapshot_is_canonical_and_disclaims_promotion():
    snapshot = registry_snapshot()
    assert snapshot["registry_digest"].startswith("sha256:")
    assert snapshot["primary_profile_key"] == PRIMARY_PROFILE_KEY
    assert snapshot["promotion_status"].startswith("No Phase 5C agent is a")
    assert "promoted champion" in snapshot["promotion_status"]
    assert snapshot["development_reference_policy"] == "partner_aware_v1"
    for entry in snapshot["agents"]:
        assert entry["configuration"]["belief_model"] is None
        assert entry["configuration"]["information_set_search"] is None
        assert entry["configuration"]["learned_world_weighting"] is None
        assert entry["configuration"]["persistent_search_tree"] is None
        assert entry["configuration"]["self_play_training"] is None
        assert entry["configuration"]["observation_only"] is True


def test_a_homogeneous_team_uses_two_independent_instances():
    team = homogeneous_team(PRIMARY_PROFILE_KEY)
    assert team.shared_instances is False
    assert len(set(team.component_agent_ids)) == 1
    assert len(team.component_agent_ids) == 2
