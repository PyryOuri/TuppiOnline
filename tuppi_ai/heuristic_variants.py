"""Experimental variants of the incumbent heuristic (partner_aware_lead_v2), built from TuppiAI.

TuppiProject is not modified: a variant is the incumbent's own policy class
with its profile rebuilt with some parameters overridden. A variant that
passes its tests is then implemented as a registered profile in TuppiProject
(docs/HEURISTIC_PLAN.md).

    agents = variant_agents({"simple_rami_threshold": 12.0})

`tuppi_ai.evaluate` accepts these as `heur:<name>=<value>[,<name>=<value>...]`.
"""

from __future__ import annotations

from .incumbent import INCUMBENT, incumbent_agents


def variant_profile(base, overrides: dict):
    from tuppi_agents.profiles import HeuristicProfile

    unknown = set(overrides) - set(base.parameters)
    if unknown:
        raise ValueError(f"unknown parameters {sorted(unknown)}; the profile has {sorted(base.parameters)}")
    return HeuristicProfile.build(
        profile_key=base.profile_key, family=base.family, profile_version=base.profile_version,
        showing_policy=base.showing_policy, parameters={**base.parameters, **overrides},
        disabled_rule_ids=tuple(base.disabled_rule_ids), description=base.description)


def variant_agents(overrides: dict) -> dict[int, object]:
    """The incumbent on four seats with its profile parameters overridden."""
    base_agents = incumbent_agents(INCUMBENT)
    if not overrides:
        return base_agents
    out = {}
    for seat, agent in base_agents.items():
        profile = variant_profile(agent.profile, overrides)
        out[seat] = type(agent)(agent_id=f"{INCUMBENT}-variant-seat{seat}", profile=profile)
    return out


def parse_spec(spec: str) -> dict:
    """'heur:a=1.5,b=2' -> {'a': 1.5, 'b': 2.0}."""
    body = spec.split(":", 1)[1] if ":" in spec else ""
    out = {}
    for part in filter(None, body.split(",")):
        name, value = part.split("=")
        out[name] = float(value)
    return out
