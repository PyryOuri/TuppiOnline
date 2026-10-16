"""The benchmark heuristic opponent, constructed exactly as TuppiProject does.

Since 2026-10-02 (owner's decision) the benchmark is `partner_aware_lead_v3`
(docs/HEURISTIC_PLAN.md). Every result recorded before then is against
`partner_aware_lead_v2` (`PREVIOUS`); reproduce one with
`--opponent partner_aware_lead_v2` (and `heur:base=v2,...` for heuristic
variants).
"""

from __future__ import annotations

INCUMBENT = "partner_aware_lead_v3"
#: The benchmark until 2026-10-02.
PREVIOUS = "partner_aware_lead_v2"


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
