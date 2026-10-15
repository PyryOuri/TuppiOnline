"""Immutable agent registry and baseline specification catalog."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import RegistryError
from .identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
    agent_spec_to_data,
)
from .serialization import content_digest


REGISTRY_SCHEMA_VERSION = "tuppi.eval.agent_registry.v1"
RULESET_ID = "project_target_v1"
OBSERVATION_SCHEMA_ID = "tuppi.engine.player_observation.v1"


@dataclass(frozen=True, slots=True)
class AgentRegistry:
    specifications: tuple[AgentSpecification, ...]
    registry_digest: str
    schema_version: str = field(default=REGISTRY_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.specifications) is not tuple or not self.specifications:
            raise RegistryError("registry must contain at least one specification")
        if any(
            not isinstance(specification, AgentSpecification)
            for specification in self.specifications
        ):
            raise RegistryError("registry contains a non-AgentSpecification value")
        ids = tuple(specification.agent_id for specification in self.specifications)
        if len(set(ids)) != len(ids):
            raise RegistryError("registry contains duplicate agent IDs")
        if ids != tuple(sorted(ids)):
            raise RegistryError("registry specifications must be sorted by agent ID")
        expected = content_digest(
            {
                "schema_version": self.schema_version,
                "specifications": [
                    agent_spec_to_data(specification)
                    for specification in self.specifications
                ],
            }
        )
        if self.registry_digest != expected:
            raise RegistryError("registry_digest disagrees with registry content")

    @classmethod
    def build(
        cls,
        specifications: tuple[AgentSpecification, ...],
        *,
        claimed_registry_digest: str | None = None,
    ) -> "AgentRegistry":
        ordered = tuple(sorted(specifications, key=lambda item: item.agent_id))
        digest = content_digest(
            {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "specifications": [agent_spec_to_data(item) for item in ordered],
            }
        )
        return cls(
            specifications=ordered,
            registry_digest=claimed_registry_digest or digest,
        )

    def get(self, agent_id: str) -> AgentSpecification:
        for specification in self.specifications:
            if specification.agent_id == agent_id:
                return specification
        raise RegistryError(f"unknown agent ID {agent_id!r}")


def _baseline_spec(
    *,
    family: str,
    implementation: str,
    configuration: dict[str, object],
    description: str,
    stochastic: bool = False,
) -> AgentSpecification:
    return AgentSpecification.build(
        agent_family=family,
        configuration_version="1.0.0",
        implementation_reference=implementation,
        ruleset_compatibility=(RULESET_ID,),
        observation_schema_compatibility=(OBSERVATION_SCHEMA_ID,),
        determinism=(
            DeterminismClass.SEEDED_STOCHASTIC
            if stochastic
            else DeterminismClass.DETERMINISTIC
        ),
        seed_policy=(
            SeedPolicy.DERIVED_PER_ENTRY_SEAT if stochastic else SeedPolicy.NONE
        ),
        configuration=configuration,
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=None,
        description=description,
    )


def baseline_agent_specifications() -> tuple[AgentSpecification, ...]:
    """Return the non-strategic Phase 3 evaluator fixture specifications."""

    return (
        _baseline_spec(
            family="first_legal",
            implementation="tuppi_eval.agents:first_legal_v1",
            configuration={"selection": "engine_order_first"},
            description="Chooses the first action in the engine's stable legal order.",
        ),
        _baseline_spec(
            family="lowest_legal_card",
            implementation="tuppi_eval.agents:lowest_legal_v1",
            configuration={
                "card_order": "project_target_v1_card_index_ascending",
                "show_contract_order": ["NOLO", "RAMI"],
            },
            description="Chooses a rules-valid show and the lowest legal card.",
        ),
        _baseline_spec(
            family="highest_legal_card",
            implementation="tuppi_eval.agents:highest_legal_v1",
            configuration={
                "card_order": "project_target_v1_card_index_descending",
                "show_contract_order": ["NOLO", "RAMI"],
            },
            description="Chooses a rules-valid show and the highest legal card.",
        ),
        _baseline_spec(
            family="seeded_random_legal",
            implementation="tuppi_eval.agents:seeded_random_legal_v1",
            configuration={"sampler": "sha256_counter_modulo_v1"},
            description="Chooses among legal actions using a derived explicit seed.",
            stochastic=True,
        ),
        _baseline_spec(
            family="show_selection_nolo_low",
            implementation="tuppi_eval.agents:show_selection_v1",
            configuration={
                "card_order": "project_target_v1_card_index_ascending",
                "preferred_contract": "NOLO",
            },
            description="Prefers a legal NOLO show and otherwise chooses legally.",
        ),
    )


def baseline_registry() -> AgentRegistry:
    return AgentRegistry.build(baseline_agent_specifications())
