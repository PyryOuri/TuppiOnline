"""The immutable Phase 4 baseline snapshot.

Phase 5A measures the Phase 4 agents; it must not move them. This module builds
a snapshot of exactly what was frozen and a *behaviour digest* that makes any
change detectable rather than merely forbidden by policy.

A behaviour digest is a SHA-256 over the complete ordered action sequence an
agent produces at all four seats across a fixed set of deterministic deals -
every showing decision and every card. It covers far more ground than a
position fixture: if any rule, threshold, tie-break, or ordering changes, the
digest changes.

None of these agents is a promoted champion. They are frozen *references*. A
role such as ``development_reference`` may be assigned later on the strength of
a calibration result, but that is a label for comparison bookkeeping, not a
promotion, and it can never be earned on an unsealed bank.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    action_to_data,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.serialization import content_digest
from tuppi_rules import MatchScore

from .errors import MatchValidationError
from .streams import MatchStream


FROZEN_SNAPSHOT_SCHEMA_VERSION = "tuppi.match.phase4_frozen_snapshot.v1"

#: The commit that froze these agents. Phase 5A adds no strategic behaviour.
PHASE4_IMPLEMENTATION_COMMIT = "b0d57b4"
PHASE4_AGENTS_VERSION = "0.4.0"

#: Fixed inputs for the behaviour digest. Changing any of these changes every
#: digest, so they are part of the frozen definition.
BEHAVIOUR_DIGEST_SEED = "tuppi-phase4-behaviour-digest-v1"
BEHAVIOUR_DIGEST_DEALS = 6
BEHAVIOUR_DIGEST_SCORES: tuple[tuple[int, int], ...] = ((0, 0), (48, 0), (0, 48))


@dataclass(frozen=True, slots=True)
class FrozenAgent:
    """One frozen Phase 4 agent, recorded in full."""

    profile_key: str
    agent_id: str
    profile_id: str
    agent_family: str
    configuration_digest: str
    configuration_version: str
    implementation_reference: str
    ruleset_compatibility: tuple[str, ...]
    observation_schema_compatibility: tuple[str, ...]
    action_ordering_id: str
    tie_break_id: str
    diagnostics_schema: str
    partner_convention_id: str | None
    determinism: str
    seed_policy: str
    search: None
    belief_model: None
    endgame_solver: None
    hidden_hand_sampling: None
    learning: None
    rollout_budget: None
    provenance: str
    behaviour_digest: str
    in_phase4_ladder: bool

    def to_data(self) -> dict[str, object]:
        return {
            "action_ordering_id": self.action_ordering_id,
            "agent_family": self.agent_family,
            "agent_id": self.agent_id,
            "behaviour_digest": self.behaviour_digest,
            "belief_model": None,
            "configuration_digest": self.configuration_digest,
            "configuration_version": self.configuration_version,
            "determinism": self.determinism,
            "diagnostics_schema": self.diagnostics_schema,
            "endgame_solver": None,
            "hidden_hand_sampling": None,
            "implementation_reference": self.implementation_reference,
            "in_phase4_ladder": self.in_phase4_ladder,
            "learning": None,
            "observation_schema_compatibility": list(
                self.observation_schema_compatibility
            ),
            "partner_convention_id": self.partner_convention_id,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
            "provenance": self.provenance,
            "rollout_budget": None,
            "ruleset_compatibility": list(self.ruleset_compatibility),
            "search": None,
            "seed_policy": self.seed_policy,
            "tie_break_id": self.tie_break_id,
        }


@lru_cache(maxsize=None)
def behaviour_actions(profile_key: str) -> tuple[str, ...]:
    """Return the agent's complete ordered action sequence over fixed deals.

    All four seats are occupied by the same agent so that every decision is the
    agent's own, and the deals are replayed from three explicit score states so
    that rising-score behaviour is covered too. The result is cached because it
    is a pure function of a frozen agent and frozen inputs.
    """

    from tuppi_agents import construct_agent, phase4_specifications_by_profile_key

    specification = phase4_specifications_by_profile_key()[profile_key]
    actions: list[dict[str, object]] = []
    for score_index, score in enumerate(BEHAVIOUR_DIGEST_SCORES):
        for deal_index in range(BEHAVIOUR_DIGEST_DEALS):
            stream = MatchStream.build(
                root_seed=BEHAVIOUR_DIGEST_SEED,
                stream_index=score_index,
                initial_dealer=deal_index % 4,
            )
            deal = stream.deal(deal_index)
            agents = tuple(
                construct_agent(specification, seat=seat) for seat in range(4)
            )
            state = create_match(
                initial_score=MatchScore(*score),
                initial_dealer=deal_index % 4,
                match_ref=f"freeze-{score_index}-{deal_index}",
            )
            state = begin_explicit_deal(
                state, ExplicitDeal(dealer=state.dealer, hands=deal.hands)
            )
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                actor = state.current_actor
                assert actor is not None
                observation = match_observation_for(state, actor)
                action = agents[actor].choose_action(observation)
                actions.append(action_to_data(action))
                state = apply_match_action(state, action)
    return tuple(
        f"{item.get('type')}:{item.get('seat')}:"
        f"{item.get('card') or item.get('shown_card')}:"
        f"{item.get('declared_contract', '')}"
        for item in actions
    )


def behaviour_digest(profile_key: str) -> str:
    """Digest the agent's complete action sequence.

    The profile key is *not* part of the digested content: two agents that make
    the same decisions must produce the same digest, so that an accidental
    duplicate is visible rather than hidden behind its name.
    """

    return content_digest(
        {
            "actions": list(behaviour_actions(profile_key)),
            "deals": BEHAVIOUR_DIGEST_DEALS,
            "schema_version": "tuppi.match.behaviour_digest.v1",
            "scores": [list(score) for score in BEHAVIOUR_DIGEST_SCORES],
            "seed": BEHAVIOUR_DIGEST_SEED,
        }
    )


def frozen_agent(profile_key: str) -> FrozenAgent:
    from tuppi_agents import (
        LADDER_PROFILE_KEYS,
        phase4_specifications_by_profile_key,
        registered_profiles,
    )

    specifications = phase4_specifications_by_profile_key()
    if profile_key not in specifications:
        raise MatchValidationError(f"unknown Phase 4 profile {profile_key!r}")
    specification = specifications[profile_key]
    profile = registered_profiles()[profile_key]
    configuration = specification.configuration
    return FrozenAgent(
        profile_key=profile_key,
        agent_id=specification.agent_id,
        profile_id=profile.profile_id,
        agent_family=specification.agent_family,
        configuration_digest=specification.configuration_digest,
        configuration_version=specification.configuration_version,
        implementation_reference=specification.implementation_reference,
        ruleset_compatibility=specification.ruleset_compatibility,
        observation_schema_compatibility=(
            specification.observation_schema_compatibility
        ),
        action_ordering_id=configuration["action_ordering_id"],
        tie_break_id=configuration["tie_break_id"],
        diagnostics_schema=configuration["diagnostics_schema"],
        partner_convention_id=specification.partner_convention_id,
        determinism=specification.determinism.value,
        seed_policy=specification.seed_policy.value,
        search=None,
        belief_model=None,
        endgame_solver=None,
        hidden_hand_sampling=None,
        learning=None,
        rollout_budget=None,
        provenance=(
            "Phase 4 transparent baseline; deterministic and observation-only. "
            "Not expert-validated and not a promoted champion."
        ),
        behaviour_digest=behaviour_digest(profile_key),
        in_phase4_ladder=profile_key in LADDER_PROFILE_KEYS,
    )


def build_snapshot() -> dict[str, object]:
    """Build the complete immutable Phase 4 baseline registry snapshot."""

    from tuppi_agents import STRATEGIC_PROFILE_KEYS, phase4_registry

    agents = [frozen_agent(key) for key in sorted(STRATEGIC_PROFILE_KEYS)]
    payload = {
        "agents": [item.to_data() for item in agents],
        "agents_version": PHASE4_AGENTS_VERSION,
        "behaviour_digest_inputs": {
            "deals_per_score": BEHAVIOUR_DIGEST_DEALS,
            "scores": [list(score) for score in BEHAVIOUR_DIGEST_SCORES],
            "seed": BEHAVIOUR_DIGEST_SEED,
            "stream_protocol": "tuppi.match.stream.v1",
        },
        "implementation_commit": PHASE4_IMPLEMENTATION_COMMIT,
        "phase4_registry_digest": phase4_registry().registry_digest,
        "promotion_status": (
            "None of these agents is a promoted champion. They are frozen "
            "references measured by Phase 5A on unsealed banks."
        ),
        "ruleset_id": "project_target_v1",
        "schema_version": FROZEN_SNAPSHOT_SCHEMA_VERSION,
    }
    payload["snapshot_digest"] = content_digest(payload)
    return payload


def verify_snapshot(snapshot: dict[str, object]) -> list[str]:
    """Return a list of drift descriptions; empty means nothing moved."""

    if type(snapshot) is not dict:
        raise MatchValidationError("snapshot must be a JSON object")
    if snapshot.get("schema_version") != FROZEN_SNAPSHOT_SCHEMA_VERSION:
        raise MatchValidationError("unsupported frozen snapshot schema_version")
    problems: list[str] = []
    current = {item["profile_key"]: item for item in build_snapshot()["agents"]}
    recorded = {item["profile_key"]: item for item in snapshot["agents"]}
    if set(current) != set(recorded):
        problems.append(
            f"agent set changed: added={sorted(set(current) - set(recorded))}, "
            f"removed={sorted(set(recorded) - set(current))}"
        )
    for key in sorted(set(current) & set(recorded)):
        for field_name in (
            "agent_id",
            "profile_id",
            "configuration_digest",
            "behaviour_digest",
            "partner_convention_id",
            "action_ordering_id",
            "tie_break_id",
        ):
            if current[key][field_name] != recorded[key][field_name]:
                problems.append(
                    f"{key}: {field_name} changed from "
                    f"{recorded[key][field_name]!r} to {current[key][field_name]!r}"
                )
    return problems
