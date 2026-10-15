"""Strict, privacy-safe PIMC decision diagnostics.

A diagnostics record explains a search decision to a human without telling that
human anything the agent did not know. It therefore carries:

* the information-state digest, never the information state's cards beyond the
  observation's own legal actions;
* world *identities* and counts, never a sampled hand;
* candidate value summaries, the selection gap, and work counters.

It must never carry the true hidden hands, the true deal identifier, the evaluator
fixture identity, the real full state, a sealed seed, or - the subtle one - any
marker of which sampled world happened to match reality. The agent never computes
that last quantity at all; only the restricted oracle in
:mod:`tuppi_search.oracle` does, and it is not an agent.

Diagnostics never change play
----------------------------

``choose_action`` and ``decide`` compute the identical ranking; diagnostics are
built afterwards from the finished decision. Turning them on cannot change the
selected action, and :mod:`tests.search.test_pimc_core` asserts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import PlayerObservation
from tuppi_rules import card_to_code

from .errors import SearchDiagnosticsError
from .pimc import PimcDecision
from .random import canonical_action_id
from .utilities import utility_description, utility_range


DIAGNOSTICS_SCHEMA_VERSION = "tuppi.search.pimc_decision_diagnostics.v1"

#: Keys that must never appear anywhere in a diagnostics payload.
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "deal_id",
        "evaluator_fixture_id",
        "hidden_hands",
        "initial_hands",
        "matched_truth",
        "real_state",
        "sampled_hands",
        "sealed_seed",
        "true_deal_id",
        "true_hands",
        "true_world_index",
    }
)


@dataclass(frozen=True, slots=True)
class PimcDecisionDiagnostics:
    """One immutable, privacy-safe explanation of a PIMC decision."""

    agent_id: str
    decision: PimcDecision
    rollout_policy_agent_ids: tuple[str, ...]
    schema_version: str = field(default=DIAGNOSTICS_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PimcDecision):
            raise SearchDiagnosticsError("diagnostics wrap a PimcDecision")
        if not isinstance(self.agent_id, str) or not self.agent_id.startswith(
            "agent:"
        ):
            raise SearchDiagnosticsError("diagnostics require a canonical agent id")
        if len(self.rollout_policy_agent_ids) != 4:
            raise SearchDiagnosticsError(
                "rollout policy identities must cover four seats"
            )

    def to_data(self) -> dict[str, object]:
        decision = self.decision
        configuration = decision.configuration
        world_set = decision.world_set
        payload: dict[str, object] = {
            "agent_id": self.agent_id,
            "candidate_count": len(decision.candidates),
            "candidates": [item.to_data() for item in decision.candidates],
            "decision_seed": decision.decision_seed,
            "exact_tail": (
                {
                    "enabled": True,
                    "max_tricks_remaining": (
                        configuration.exact_tail_max_tricks_remaining
                    ),
                    "node_budget": configuration.exact_tail_node_budget,
                    "solver_algorithm_id": configuration.solver_algorithm_id,
                }
                if configuration.exact_tail_enabled
                else {"enabled": False}
            ),
            "failure_counts": {
                "candidate_failures": 0,
                "rollout_failures": 0,
                "world_construction_failures": 0,
            },
            "information_state": decision.information_state,
            "legal_actions": [
                item.action_id for item in decision.candidates
            ],
            "phase": decision.phase,
            "pimc_configuration_id": configuration.configuration_id,
            "pimc_protocol_version": configuration.pimc_protocol_version,
            "rollout_policy_agent_ids": list(self.rollout_policy_agent_ids),
            "rollout_policy_key": configuration.rollout_policy_key,
            "root_seat": decision.root_seat,
            "root_team": decision.root_team.value,
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "selected_action": canonical_action_id(decision.selected_action),
            "selected_action_order_index": decision.selected_index,
            "selection_gap": round(decision.selection_gap, 9),
            "selected_mean_utility": round(decision.selected_value, 9),
            "semantic_work_budget": {
                "rollout_replicas": configuration.rollout_replicas,
                "rollouts_per_candidate": (
                    configuration.total_rollouts_per_candidate
                ),
                "stopping_rule": "deterministic_work_budget",
                "world_count": configuration.world_count,
            },
            "simulation_counts": {
                "actions_simulated": sum(
                    item.actions_simulated for item in decision.candidates
                ),
                "evaluations": sum(
                    item.evaluations for item in decision.candidates
                ),
                "exact_tail_evaluations": sum(
                    item.exact_tail_evaluations for item in decision.candidates
                ),
                "solver_calls": sum(
                    item.solver_calls for item in decision.candidates
                ),
                "solver_nodes": sum(
                    item.solver_nodes for item in decision.candidates
                ),
            },
            "single_legal_action_shortcut": decision.single_legal_action_shortcut,
            "tie_break_id": configuration.tie_break_id,
            "utility": {
                "description": utility_description(configuration.utility_id),
                "range": list(utility_range(configuration.utility_id)),
                "utility_id": configuration.utility_id.value,
            },
        }
        if world_set is None:
            payload["world_set"] = {
                "reason": "single legal action; no world set was built",
                "requested_world_count": 0,
            }
        else:
            payload["world_set"] = world_set.to_data()
        require_privacy_safe(payload)
        return payload


def require_privacy_safe(payload: object) -> None:
    """Reject a diagnostics payload that carries a forbidden key.

    A key-name check is a coarse net, so :mod:`tests.search.test_diagnostics` adds
    the sharp one: it asserts that no card code outside the observation's own hand
    and public history appears anywhere in the serialized record.
    """

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_KEYS:
                raise SearchDiagnosticsError(
                    f"diagnostics must not contain the key {key!r}"
                )
            require_privacy_safe(value)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            require_privacy_safe(item)


def observation_visible_card_codes(observation: PlayerObservation) -> frozenset[str]:
    """Every card code the observing seat may legitimately name.

    Its own hand, plus every card that is already public: shown cards and played
    cards. A diagnostics record that mentions any other card has leaked.
    """

    if not isinstance(observation, PlayerObservation):
        raise SearchDiagnosticsError(
            "observation_visible_card_codes requires a PlayerObservation"
        )
    codes = {card_to_code(card) for card in observation.own_hand}
    codes |= {card_to_code(card) for _, card in observation.publicly_shown_cards}
    for trick in observation.completed_tricks:
        codes |= {card_to_code(play.card) for play in trick.plays}
    codes |= {card_to_code(play.card) for play in observation.current_trick}
    return frozenset(codes)
