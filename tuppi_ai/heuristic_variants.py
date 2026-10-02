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


class LayeredAgent:
    """The incumbent's choice, overridden in trick play by the first rule layer that fires
    (tuppi_ai/heuristic_rules.py). Everything else is the base agent's."""

    def __init__(self, base, layers: list[str]):
        self.base, self.layers = base, list(layers)
        self.fired = 0

    def choose_action(self, observation):
        action = self.base.choose_action(observation)
        if not self.layers or observation.phase.value != "TRICK_PLAY" or len(observation.legal_actions) < 2:
            return action
        from .bridge import action_id, engine_action, obs_from_player_observation
        from .heuristic_rules import apply_layers, view_from_tcobs

        obs = obs_from_player_observation(observation)
        legal = [action_id(a) for a in observation.legal_actions]
        new = apply_layers(self.layers, view_from_tcobs(obs, legal, action_id(action)))
        if new is None:
            return action
        if new not in legal:
            raise ValueError(f"rule layer chose an illegal card {new}")
        self.fired += 1
        return engine_action(new, int(obs.seat))

    def __getattr__(self, name):
        return getattr(self.base, name)


def parse_spec(spec: str) -> tuple[dict, list[str]]:
    """'heur:a=1.5,b=2,layers=underlead+cash_singleton_late' -> ({'a': 1.5, 'b': 2.0}, [layers])."""
    body = spec.split(":", 1)[1] if ":" in spec else ""
    out, layers = {}, []
    for part in filter(None, body.split(",")):
        name, value = part.split("=")
        if name == "layers":
            layers = [x for x in value.split("+") if x]
        else:
            out[name] = float(value)
    return out, layers


def spec_agents(spec: str) -> dict[int, object]:
    overrides, layers = parse_spec(spec)
    agents = variant_agents(overrides)
    return {s: LayeredAgent(a, layers) for s, a in agents.items()} if layers else agents
