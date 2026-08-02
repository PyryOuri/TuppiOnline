from __future__ import annotations

import json

import pytest

from tuppi_agents import (
    LADDER_PROFILE_KEYS,
    LEGACY_CONVENTION_ID,
    STRATEGIC_PROFILE_KEYS,
    HeuristicProfile,
    PolicyFamily,
    ShowingPolicyId,
    control_agent_specifications,
    phase4_agent_specifications,
    phase4_registry,
    phase4_specifications_by_profile_key,
    phase4_team_specifications,
    profile_catalogue_to_data,
    profile_from_data,
    registered_profiles,
    require_profile,
    strategic_configuration,
)
from tuppi_agents.errors import AgentConstructionError, ProfileError
from tuppi_agents.factory import construct_registered_agent, profile_of
from tuppi_eval.registry import baseline_agent_specifications


def _profile(**overrides) -> HeuristicProfile:
    base = {
        "profile_key": "reactive_contract_v1",
        "family": PolicyFamily.REACTIVE_CONTRACT,
        "showing_policy": ShowingPolicyId.SIMPLE,
        "description": "test profile",
    }
    base.update(overrides)
    return HeuristicProfile.build(**base)


# ------------------------------------------------------------ strict validation


def test_unknown_parameter_is_rejected() -> None:
    with pytest.raises(ProfileError, match="unknown profile parameter"):
        _profile(parameters={"not_a_real_parameter": 1.0})


def test_wrong_parameter_type_is_rejected() -> None:
    with pytest.raises(ProfileError, match="must be a number"):
        _profile(parameters={"simple_rami_threshold": "15"})
    with pytest.raises(ProfileError, match="must be a boolean"):
        HeuristicProfile.build(
            profile_key="match_aware_v1",
            family=PolicyFamily.MATCH_AWARE,
            showing_policy=ShowingPolicyId.SIMPLE,
            parameters={"match_state_features_enabled": 1},
            description="bad",
        )


def test_out_of_range_parameter_is_rejected() -> None:
    with pytest.raises(ProfileError, match="at most"):
        _profile(parameters={"simple_rami_threshold": 1_000.0})
    with pytest.raises(ProfileError, match="at least"):
        _profile(parameters={"rami_lead_length_bonus": -1.0})


def test_showing_policy_parameters_do_not_leak_across_policies() -> None:
    with pytest.raises(ProfileError, match="unknown profile parameter"):
        _profile(parameters={"legacy_rami_ev_margin": 0.5})
    with pytest.raises(ProfileError, match="unknown profile parameter"):
        _profile(
            showing_policy=ShowingPolicyId.LEGACY,
            parameters={"simple_rami_threshold": 15.0},
        )


def test_family_rejects_an_unsupported_showing_policy() -> None:
    with pytest.raises(ProfileError, match="does not support showing policy"):
        HeuristicProfile.build(
            profile_key="legacy_heuristic_port_v1",
            family=PolicyFamily.LEGACY_HEURISTIC_PORT,
            showing_policy=ShowingPolicyId.SIMPLE,
            description="bad",
        )


def test_contradictory_legacy_thresholds_are_rejected() -> None:
    with pytest.raises(ProfileError, match="cannot lower the RAMI expected-value bar"):
        _profile(
            showing_policy=ShowingPolicyId.LEGACY,
            parameters={
                "legacy_rami_ev_minimum_table": 5.0,
                "legacy_rami_ev_minimum_protected": 4.0,
            },
        )
    with pytest.raises(ProfileError, match="cannot raise the RAMI expected-value bar"):
        _profile(
            showing_policy=ShowingPolicyId.LEGACY,
            parameters={
                "legacy_rami_ev_minimum_table": 4.0,
                "legacy_rami_ev_minimum_pressured": 5.0,
            },
        )


def test_contradictory_match_distances_are_rejected() -> None:
    with pytest.raises(ProfileError, match="protected distance must not exceed"):
        HeuristicProfile.build(
            profile_key="match_aware_v1",
            family=PolicyFamily.MATCH_AWARE,
            showing_policy=ShowingPolicyId.SIMPLE,
            parameters={"match_protect_distance": 20, "match_pressure_distance": 4},
            description="bad",
        )


def test_disabling_a_mechanical_rule_is_rejected() -> None:
    with pytest.raises(ProfileError, match="cannot be disabled"):
        _profile(disabled_rule_ids=("common.play.legal_actions_only.v1",))


def test_disabling_a_rule_from_another_family_is_rejected() -> None:
    with pytest.raises(ProfileError, match="not part of profile"):
        _profile(disabled_rule_ids=("match.show.protect_terminal_lead.v1",))


def test_unknown_rule_id_is_rejected() -> None:
    from tuppi_agents.errors import RuleCatalogueError

    with pytest.raises(RuleCatalogueError):
        _profile(disabled_rule_ids=("no.such.rule.v1",))


# ------------------------------------------------------------------- identities


def test_behaviourally_material_change_alters_the_profile_and_agent_id() -> None:
    base = require_profile("reactive_contract_v1")
    tweaked = _profile(parameters={"simple_rami_threshold": 16.0})
    assert tweaked.profile_id != base.profile_id

    from tuppi_agents.registry import specification_for_profile

    assert (
        specification_for_profile(tweaked).agent_id
        != specification_for_profile(base).agent_id
    )


def test_description_is_explicitly_nonbehavioural_for_profile_identity() -> None:
    first = _profile(description="one wording")
    second = _profile(description="a completely different wording")
    assert first.identity_data() == second.identity_data()
    assert first.profile_id == second.profile_id


def test_disabling_an_optional_rule_alters_the_identity() -> None:
    base = require_profile("partner_aware_v1")
    ablated = HeuristicProfile.build(
        profile_key="partner_aware_v1",
        family=PolicyFamily.PARTNER_AWARE,
        showing_policy=ShowingPolicyId.SIMPLE,
        disabled_rule_ids=("partner.rami.overtake_when_partner_beatable.v1",),
        description="ablation variant",
    )
    assert ablated.profile_id != base.profile_id
    assert "partner.rami.overtake_when_partner_beatable.v1" not in ablated.enabled_rule_ids


def test_registered_profile_ids_are_stable_and_unique() -> None:
    profiles = registered_profiles()
    assert set(profiles) == set(STRATEGIC_PROFILE_KEYS)
    ids = [profile.profile_id for profile in profiles.values()]
    assert len(set(ids)) == len(ids)
    for profile in profiles.values():
        assert profile.profile_id.startswith("profile:sha256:")
        rebuilt = profile_from_data(profile.to_data())
        assert rebuilt == profile


def test_legacy_convention_profile_declares_its_convention() -> None:
    plain = require_profile("partner_aware_v1")
    convention = require_profile("partner_aware_legacy_convention_v1")
    assert plain.partner_convention_id is None
    assert convention.partner_convention_id == LEGACY_CONVENTION_ID
    assert convention.rule_enabled("partner.legacy.minimum_information_show.v1")
    assert not plain.rule_enabled("partner.legacy.minimum_information_show.v1")
    assert convention.show_tie_break_id != plain.show_tie_break_id


def test_match_state_off_variant_switches_every_match_rule_off() -> None:
    enabled = require_profile("match_aware_v1")
    disabled = require_profile("match_aware_no_match_features_v1")
    assert enabled.match_state_enabled is True
    assert disabled.match_state_enabled is False
    assert any(rule.startswith("match.") for rule in enabled.enabled_rule_ids)
    assert not any(rule.startswith("match.") for rule in disabled.enabled_rule_ids)
    assert enabled.profile_id != disabled.profile_id


def test_profile_round_trip_rejects_unknown_and_missing_fields() -> None:
    data = require_profile("reactive_contract_v1").to_data()
    with pytest.raises(ProfileError, match="unknown="):
        profile_from_data({**data, "extra": 1})
    incomplete = dict(data)
    del incomplete["parameters"]
    with pytest.raises(ProfileError, match="missing="):
        profile_from_data(incomplete)
    with pytest.raises(ProfileError, match="schema_version"):
        profile_from_data({**data, "schema_version": "other"})


def test_profile_round_trip_rejects_a_forged_identity() -> None:
    data = require_profile("reactive_contract_v1").to_data()
    forged = dict(data)
    forged["parameters"] = {**data["parameters"], "simple_rami_threshold": 16.0}
    with pytest.raises(ProfileError, match="profile_id disagrees"):
        profile_from_data(forged)


# --------------------------------------------------------------------- registry


def test_phase4_registry_preserves_phase3_control_definitions() -> None:
    registry = phase4_registry()
    controls = {spec.agent_id: spec for spec in baseline_agent_specifications()}
    assert controls
    for agent_id, specification in controls.items():
        assert registry.get(agent_id) == specification
    assert control_agent_specifications() == baseline_agent_specifications()
    assert len(registry.specifications) == len(controls) + len(
        phase4_agent_specifications()
    )


def test_every_strategic_specification_declares_no_search_or_learning() -> None:
    for specification in phase4_agent_specifications():
        configuration = specification.configuration
        assert specification.search_budget is None
        assert specification.model_checkpoint_id is None
        assert specification.determinism.value == "deterministic"
        assert specification.seed_policy.value == "none"
        assert specification.ruleset_compatibility == ("project_target_v1",)
        assert specification.observation_schema_compatibility == (
            "tuppi.engine.player_observation.v1",
        )
        for field in (
            "belief_model",
            "endgame_solver",
            "hidden_hand_sampling",
            "learning",
            "rollout_budget",
            "search",
        ):
            assert configuration[field] is None, field
        assert configuration["observation_only"] is True
        assert configuration["profile_digest"] == configuration["profile_id"].removeprefix(
            "profile:"
        )
        assert configuration["diagnostics_schema"] == (
            "tuppi.agents.decision_diagnostics.v1"
        )


def test_specification_configuration_is_canonical_and_recomputable() -> None:
    for key, specification in phase4_specifications_by_profile_key().items():
        profile = profile_of(specification)
        assert profile.profile_key == key
        assert strategic_configuration(profile) == specification.configuration
        assert json.loads(specification.configuration_json) == specification.configuration


def test_factory_rejects_a_seed_and_a_bad_seat() -> None:
    specification = phase4_specifications_by_profile_key()["reactive_contract_v1"]
    with pytest.raises(AgentConstructionError, match="take no seed"):
        construct_registered_agent(specification, seat=0, seed="abc")
    with pytest.raises(AgentConstructionError, match="seat must be in"):
        construct_registered_agent(specification, seat=4)


def test_factory_rejects_a_specification_whose_configuration_was_edited() -> None:
    from tuppi_eval.identities import AgentSpecification

    specification = phase4_specifications_by_profile_key()["reactive_contract_v1"]
    tampered_configuration = dict(specification.configuration)
    tampered_configuration["search"] = 100
    tampered = AgentSpecification.build(
        agent_family=specification.agent_family,
        configuration_version=specification.configuration_version,
        implementation_reference=specification.implementation_reference,
        ruleset_compatibility=specification.ruleset_compatibility,
        observation_schema_compatibility=specification.observation_schema_compatibility,
        determinism=specification.determinism,
        seed_policy=specification.seed_policy,
        configuration=tampered_configuration,
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description=specification.description,
    )
    with pytest.raises(AgentConstructionError, match="disagrees with its declared profile"):
        construct_registered_agent(tampered, seat=0)


def test_every_seat_receives_a_distinct_runtime_object() -> None:
    specification = phase4_specifications_by_profile_key()["match_aware_v1"]
    agents = [construct_registered_agent(specification, seat=seat) for seat in range(4)]
    assert len({id(agent) for agent in agents}) == 4
    assert len({agent.identity for agent in agents}) == 1


def test_team_catalogue_covers_the_required_partnership_shapes() -> None:
    teams = phase4_team_specifications()
    for key in LADDER_PROFILE_KEYS:
        clone = teams[f"{key}_clone"]
        assert clone.homogeneous is True
        assert clone.shared_instances is False
    assert teams["heterogeneous_match_aware_with_reactive"].homogeneous is False
    assert teams["heterogeneous_match_aware_with_control"].homogeneous is False
    assert teams["control_first_legal_clone"].homogeneous is True
    assert len({team.team_id for team in teams.values()}) == len(teams)


def test_profile_catalogue_artifact_is_sorted_and_complete() -> None:
    data = profile_catalogue_to_data()
    keys = [item["profile_key"] for item in data["profiles"]]
    assert keys == sorted(keys)
    assert set(keys) == set(STRATEGIC_PROFILE_KEYS)
    assert data["ruleset_id"] == "project_target_v1"


def test_require_profile_rejects_an_unknown_key() -> None:
    with pytest.raises(ProfileError, match="unknown profile key"):
        require_profile("no_such_profile_v1")
