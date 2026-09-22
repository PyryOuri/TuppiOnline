"""The incumbent `partner_aware_lead_v2`, constructed exactly as TuppiProject does."""

from __future__ import annotations

INCUMBENT = "partner_aware_lead_v2"


def incumbent_agents(profile_key: str = INCUMBENT) -> dict[int, object]:
    from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
    from tuppi_agents.improved_registry import (
        improved_agent_from_specification, improved_specifications_by_profile_key)

    improved = improved_specifications_by_profile_key()
    if profile_key in improved:
        spec = improved[profile_key]
        return {s: improved_agent_from_specification(spec, profile_key=profile_key, seat=s)
                for s in range(4)}
    spec = phase4_specifications_by_profile_key()[profile_key]
    return {s: construct_agent(spec, seat=s) for s in range(4)}
