from __future__ import annotations

from copy import deepcopy

import pytest
from hypothesis import given, strategies as st

from tuppi_eval.config import (
    SeedHierarchy,
    SequentialMode,
    SequentialProtocol,
    evaluation_config_from_data,
    evaluation_config_to_data,
)
from tuppi_eval.errors import ConfigurationError, EvaluationSerializationError, RegistryError
from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    TeamSpecification,
    agent_spec_from_data,
    agent_spec_to_data,
    team_spec_from_data,
    team_spec_to_data,
)
from tuppi_eval.registry import baseline_registry

from .support import evaluation_inputs


def test_stable_agent_and_team_ids_are_configuration_identities() -> None:
    registry = baseline_registry()
    spec = registry.specifications[0]
    restored = agent_spec_from_data(agent_spec_to_data(spec))
    assert restored == spec

    changed = AgentSpecification.build(
        agent_family=spec.agent_family,
        configuration_version=spec.configuration_version,
        implementation_reference=spec.implementation_reference,
        ruleset_compatibility=spec.ruleset_compatibility,
        observation_schema_compatibility=spec.observation_schema_compatibility,
        determinism=spec.determinism,
        seed_policy=spec.seed_policy,
        configuration={**spec.configuration, "variant": 1},
        model_checkpoint_id=spec.model_checkpoint_id,
        search_budget=spec.search_budget,
        partner_convention_id=spec.partner_convention_id,
        description=spec.description,
    )
    assert changed.agent_id != spec.agent_id
    assert "object at" not in spec.agent_id

    team = TeamSpecification.build(
        component_agent_ids=(spec.agent_id, changed.agent_id),
        partner_convention_id="test_v1",
        shared_instances=False,
        description="Heterogeneous test team.",
    )
    assert team_spec_from_data(team_spec_to_data(team)) == team
    reversed_team = TeamSpecification.build(
        component_agent_ids=(changed.agent_id, spec.agent_id),
        partner_convention_id="test_v1",
        shared_instances=False,
        description="Same display description does not define identity.",
    )
    assert team.team_id != reversed_team.team_id


def test_homogeneous_team_still_requires_distinct_runtime_instances() -> None:
    spec = baseline_registry().specifications[0]
    team = TeamSpecification.build(
        component_agent_ids=(spec.agent_id, spec.agent_id),
        partner_convention_id=None,
        shared_instances=False,
        description="Homogeneous team.",
    )
    assert team.homogeneous
    with pytest.raises(RegistryError, match="distinct runtime"):
        TeamSpecification.build(
            component_agent_ids=(spec.agent_id, spec.agent_id),
            partner_convention_id=None,
            shared_instances=True,
            description="Unsafe shared-state team.",
        )


def test_strict_config_rejects_unknown_fields_and_changed_digest() -> None:
    *_, config = evaluation_inputs()
    data = evaluation_config_to_data(config)
    unknown = deepcopy(data)
    unknown["output_path"] = "/tmp/does-not-belong-in-identity"
    with pytest.raises(EvaluationSerializationError, match="unknown"):
        evaluation_config_from_data(unknown)

    changed = deepcopy(data)
    changed["description"] = "different immutable comparison"
    with pytest.raises(ConfigurationError, match="identity"):
        evaluation_config_from_data(changed)


def test_output_path_never_enters_config_identity() -> None:
    *_, first = evaluation_inputs()
    *_, second = evaluation_inputs()
    assert first.evaluation_id == second.evaluation_id
    assert "output" not in first.identity_data()


def test_fixed_sample_protocol_forbids_opportunistic_interim_looks() -> None:
    with pytest.raises(ConfigurationError, match="forbids interim"):
        SequentialProtocol(
            mode=SequentialMode.FIXED_SAMPLE,
            maximum_base_deals=100,
            interim_checkpoints=(25, 50),
            stopping_boundaries=("favorable_ci",),
        )


@given(st.one_of(st.integers(), st.text(min_size=1)))
def test_seed_identity_is_stable_for_explicit_seed_values(seed: int | str) -> None:
    assert SeedHierarchy(seed, seed, seed).to_data() == SeedHierarchy(
        seed, seed, seed
    ).to_data()


def test_empty_seeds_and_malformed_agent_ids_are_rejected() -> None:
    with pytest.raises(ConfigurationError, match="must not be empty"):
        SeedHierarchy("", 1, 2)
    data = agent_spec_to_data(baseline_registry().specifications[0])
    data["agent_id"] = 12
    with pytest.raises(RegistryError, match="agent_id"):
        agent_spec_from_data(data)


def test_determinism_and_seed_policy_cannot_disagree() -> None:
    with pytest.raises(RegistryError, match="inconsistent"):
        AgentSpecification.build(
            agent_family="bad",
            configuration_version="1.0.0",
            implementation_reference="tests:bad",
            ruleset_compatibility=("project_target_v1",),
            observation_schema_compatibility=("tuppi.engine.player_observation.v1",),
            determinism=DeterminismClass.DETERMINISTIC,
            seed_policy=SeedPolicy.DERIVED_PER_ENTRY_SEAT,
            configuration={},
            model_checkpoint_id=None,
            search_budget=None,
            partner_convention_id=None,
            description="Invalid fixture.",
        )
