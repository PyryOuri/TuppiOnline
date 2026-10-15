"""Protocol controls exposed through the Phase 4 factory without duplication.

Phase 3 already owns the non-strategic evaluator fixtures - first legal, lowest
legal, highest legal, deterministic seeded random, and fixed scripted. Phase 4
does not reimplement them. This module re-exports their immutable
specifications and delegates construction to
:func:`tuppi_eval.agents.construct_agent`.

These agents remain *evaluator controls*, not strategic baselines. They are
included in cross-play so that a Phase 4 rung's result has a floor to be
measured against, and they must never be described as a rung of the ladder.
"""

from __future__ import annotations

from tuppi_engine import Action, Agent
from tuppi_eval.agents import construct_agent as _construct_phase3_agent
from tuppi_eval.identities import AgentSpecification
from tuppi_eval.registry import baseline_agent_specifications

from .errors import AgentConstructionError


CONTROL_FAMILIES: tuple[str, ...] = (
    "first_legal",
    "highest_legal_card",
    "lowest_legal_card",
    "seeded_random_legal",
    "show_selection_nolo_low",
)


def control_agent_specifications() -> tuple[AgentSpecification, ...]:
    """Return the unmodified Phase 3 control specifications."""

    specifications = baseline_agent_specifications()
    families = {item.agent_family for item in specifications}
    if families != set(CONTROL_FAMILIES):
        raise AgentConstructionError(
            "the Phase 3 control catalogue changed; Phase 4 expectations are stale"
        )
    return specifications


def control_specification(agent_family: str) -> AgentSpecification:
    for specification in control_agent_specifications():
        if specification.agent_family == agent_family:
            return specification
    raise AgentConstructionError(f"unknown control family {agent_family!r}")


def construct_control_agent(
    specification: AgentSpecification,
    *,
    seat: int,
    seed: str | None,
    scripted_actions: tuple[Action, ...] | None = None,
) -> Agent:
    """Construct a Phase 3 control agent through its own registered factory."""

    if not isinstance(specification, AgentSpecification):
        raise AgentConstructionError("a control requires an AgentSpecification")
    if specification.implementation_reference.startswith("tuppi_agents."):
        raise AgentConstructionError(
            "Phase 4 strategic agents are not protocol controls"
        )
    return _construct_phase3_agent(
        specification, seed=seed, seat=seat, scripted_actions=scripted_actions
    )
