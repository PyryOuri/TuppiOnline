"""Minimal multi-observer re-determinizing information-set search.

The implementation is intentionally narrower than a general MO-ISMCTS or
equilibrium method.  One tree is created for one real decision, nodes are
namespaced by physical observer seat, and all values are backed up for the real
root team's current-deal utility.  Non-root tree decisions use an observer-local
hard-feasible re-determination; the parent simulation is advanced only by the
selected legal card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import Action, EnginePhase, PlayCardAction, PlayerObservation
from tuppi_rules import Team, TRICKS_PER_DEAL, team_for_seat
from tuppi_eval.identities import AgentSpecification
from tuppi_eval.serialization import content_digest
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler, feasible_assignment_count
from tuppi_exact.sampling import HiddenHandAssignment, SAMPLER_ALGORITHM_ID

from .errors import (
    IllegalRolloutActionError,
    MultiObserverDecisionError,
    MultiObserverInvariantError,
    SearchConfigurationError,
)
from .fast_trick import FastTrickError, FastTrickState
from .information_state import root_information_state_key
from .multi_observer_information import multi_observer_information_state_key
from .random import canonical_action_id
from .root_info_uct import ROOT_INFO_UCT_ACTION_ORDERING_ID
from .utilities import (
    DealOutcomeSummary,
    OutcomeSource,
    UtilityId,
    is_registerable,
    utility_value,
)
from .worlds import world_identity


MULTI_OBSERVER_PROTOCOL_VERSION = "tuppi.search.redeterminizing_ismcts.v1"
MULTI_OBSERVER_CONFIGURATION_SCHEMA_VERSION = (
    "tuppi.search.redeterminizing_ismcts_configuration.v1"
)
MULTI_OBSERVER_DIAGNOSTICS_SCHEMA_VERSION = (
    "tuppi.search.redeterminizing_ismcts_diagnostics.v1"
)
MULTI_OBSERVER_SEED_PROTOCOL_VERSION = "tuppi.search.redeterminizing_ismcts_seed.v1"
MULTI_OBSERVER_ALGORITHM_ID = "redeterminizing_ismcts_v1"
MULTI_OBSERVER_SHOWING_POLICY = "partner_aware_v1"
MULTI_OBSERVER_FALLBACK_POLICY = "partner_aware_v1"
MULTI_OBSERVER_AVAILABILITY_RULE_ID = "availability_aware_uct_v1"
MULTI_OBSERVER_EXPANSION_RULE_ID = "one_unvisited_edge_then_continue_tree_v1"
MULTI_OBSERVER_REDETERMINIZATION_RULE_ID = "every_non_root_tree_decision_v1"
MULTI_OBSERVER_FINAL_ACTION_RULE_ID = (
    "highest_visits_then_mean_then_legal_order_v1"
)
MULTI_OBSERVER_NORMALIZATION_ID = "identity_bounded_minus_one_to_one_v1"
MULTI_OBSERVER_MAX_TREE_DEPTH = 64


class MultiObserverFailureKind:
    ROOT_SAMPLER_INCONSISTENCY = "root_sampler_inconsistency"
    OBSERVER_SAMPLER_INCONSISTENCY = "observer_sampler_inconsistency"
    OBSERVER_CONSTRUCTION = "observer_local_construction"
    ACTION_MAPPING = "observer_action_mapping"
    ROLLOUT_ILLEGAL_ACTION = "rollout_illegal_action"
    TREE_INVARIANT = "tree_invariant_failure"
    ENGINE_FAILURE = "engine_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"


@dataclass(frozen=True, slots=True)
class MultiObserverConfiguration:
    configuration_id: str
    simulation_budget: int
    exploration_constant: float
    fallback_policy_key: str
    showing_policy_key: str
    utility_id: UtilityId
    utility_normalization_id: str
    availability_rule_id: str
    expansion_rule_id: str
    redeterminization_rule_id: str
    final_action_rule_id: str
    action_ordering_id: str
    seed_protocol: str
    sampler_algorithm_id: str
    exact_tail_enabled: bool
    max_tree_depth: int
    failure_policy: str
    algorithm_id: str = field(default=MULTI_OBSERVER_ALGORITHM_ID, init=False)
    protocol_version: str = field(default=MULTI_OBSERVER_PROTOCOL_VERSION, init=False)
    schema_version: str = field(
        default=MULTI_OBSERVER_CONFIGURATION_SCHEMA_VERSION, init=False
    )

    @classmethod
    def build(
        cls,
        *,
        simulation_budget: int,
        exploration_constant: float = math.sqrt(2.0),
        fallback_policy_key: str = MULTI_OBSERVER_FALLBACK_POLICY,
        utility_id: UtilityId = UtilityId.MATCH_TRANSITION_V1,
        max_tree_depth: int = MULTI_OBSERVER_MAX_TREE_DEPTH,
    ) -> "MultiObserverConfiguration":
        values = {
            "simulation_budget": simulation_budget,
            "exploration_constant": exploration_constant,
            "fallback_policy_key": fallback_policy_key,
            "showing_policy_key": MULTI_OBSERVER_SHOWING_POLICY,
            "utility_id": utility_id,
            "utility_normalization_id": MULTI_OBSERVER_NORMALIZATION_ID,
            "availability_rule_id": MULTI_OBSERVER_AVAILABILITY_RULE_ID,
            "expansion_rule_id": MULTI_OBSERVER_EXPANSION_RULE_ID,
            "redeterminization_rule_id": MULTI_OBSERVER_REDETERMINIZATION_RULE_ID,
            "final_action_rule_id": MULTI_OBSERVER_FINAL_ACTION_RULE_ID,
            "action_ordering_id": ROOT_INFO_UCT_ACTION_ORDERING_ID,
            "seed_protocol": MULTI_OBSERVER_SEED_PROTOCOL_VERSION,
            "sampler_algorithm_id": SAMPLER_ALGORITHM_ID,
            "exact_tail_enabled": False,
            "max_tree_depth": max_tree_depth,
            "failure_policy": "strict",
        }
        provisional = object.__new__(cls)
        for key, value in values.items():
            object.__setattr__(provisional, key, value)
        object.__setattr__(provisional, "algorithm_id", MULTI_OBSERVER_ALGORITHM_ID)
        object.__setattr__(provisional, "protocol_version", MULTI_OBSERVER_PROTOCOL_VERSION)
        object.__setattr__(provisional, "schema_version", MULTI_OBSERVER_CONFIGURATION_SCHEMA_VERSION)
        return cls(
            configuration_id=f"moismctscfg:{content_digest(provisional.identity_data())}",
            **values,
        )

    def __post_init__(self) -> None:
        if type(self.simulation_budget) is not int or not 1 <= self.simulation_budget <= 4096:
            raise SearchConfigurationError("multi-observer simulation_budget must be in 1..4096")
        if (
            type(self.exploration_constant) not in (int, float)
            or not math.isfinite(self.exploration_constant)
            or self.exploration_constant <= 0
        ):
            raise SearchConfigurationError("multi-observer exploration constant must be positive")
        if self.fallback_policy_key != MULTI_OBSERVER_FALLBACK_POLICY:
            raise SearchConfigurationError("Phase 5E fallback must be partner_aware_v1")
        if self.showing_policy_key != MULTI_OBSERVER_SHOWING_POLICY:
            raise SearchConfigurationError("Phase 5E showing must be partner_aware_v1")
        if not isinstance(self.utility_id, UtilityId) or not is_registerable(self.utility_id):
            raise SearchConfigurationError("multi-observer search requires a registerable utility")
        if self.utility_normalization_id != MULTI_OBSERVER_NORMALIZATION_ID:
            raise SearchConfigurationError("unsupported multi-observer normalization")
        if self.availability_rule_id != MULTI_OBSERVER_AVAILABILITY_RULE_ID:
            raise SearchConfigurationError("unsupported availability rule")
        if self.expansion_rule_id != MULTI_OBSERVER_EXPANSION_RULE_ID:
            raise SearchConfigurationError("unsupported expansion rule")
        if self.redeterminization_rule_id != MULTI_OBSERVER_REDETERMINIZATION_RULE_ID:
            raise SearchConfigurationError("unsupported re-determinization rule")
        if self.final_action_rule_id != MULTI_OBSERVER_FINAL_ACTION_RULE_ID:
            raise SearchConfigurationError("unsupported final-action rule")
        if self.action_ordering_id != ROOT_INFO_UCT_ACTION_ORDERING_ID:
            raise SearchConfigurationError("unsupported action ordering")
        if self.sampler_algorithm_id != SAMPLER_ALGORITHM_ID:
            raise SearchConfigurationError("Phase 5E must use the Phase 5B sampler")
        if self.exact_tail_enabled:
            raise SearchConfigurationError("exact-tail is disabled in Phase 5E primary agents")
        if type(self.max_tree_depth) is not int or not 1 <= self.max_tree_depth <= 256:
            raise SearchConfigurationError("max_tree_depth must be in 1..256")
        if self.failure_policy != "strict":
            raise SearchConfigurationError("Phase 5E requires strict failures")
        if self.configuration_id != f"moismctscfg:{content_digest(self.identity_data())}":
            raise SearchConfigurationError("multi-observer configuration identity mismatch")

    def identity_data(self) -> dict[str, object]:
        return {
            "algorithm_id": self.algorithm_id,
            "action_ordering_id": self.action_ordering_id,
            "availability_rule_id": self.availability_rule_id,
            "exact_tail_enabled": self.exact_tail_enabled,
            "expansion_rule_id": self.expansion_rule_id,
            "exploration_constant": float(self.exploration_constant),
            "failure_policy": self.failure_policy,
            "fallback_policy_key": self.fallback_policy_key,
            "final_action_rule_id": self.final_action_rule_id,
            "max_tree_depth": self.max_tree_depth,
            "protocol_version": self.protocol_version,
            "redeterminization_rule_id": self.redeterminization_rule_id,
            "sampler_algorithm_id": self.sampler_algorithm_id,
            "schema_version": self.schema_version,
            "seed_protocol": self.seed_protocol,
            "showing_policy_key": self.showing_policy_key,
            "simulation_budget": self.simulation_budget,
            "utility_id": self.utility_id.value,
            "utility_normalization_id": self.utility_normalization_id,
        }

    def to_data(self) -> dict[str, object]:
        return {"configuration_id": self.configuration_id, **self.identity_data()}


@dataclass(slots=True)
class MultiObserverActionStatistics:
    action_id: str
    availability: int = 0
    visits: int = 0
    utility_sum: float = 0.0

    @property
    def mean_utility(self) -> float:
        return self.utility_sum / self.visits if self.visits else 0.0


@dataclass(slots=True)
class MultiObserverInformationNode:
    key: str
    seat: int
    action_ids: tuple[str, ...]
    actions: dict[str, MultiObserverActionStatistics]
    visits: int = 0
    revisits: int = 0

    @classmethod
    def from_observation(
        cls, *, key: str, seat: int, observation: PlayerObservation
    ) -> "MultiObserverInformationNode":
        action_ids = tuple(canonical_action_id(action) for action in observation.legal_actions)
        if not action_ids:
            raise MultiObserverInvariantError("multi-observer node needs legal actions")
        if len(set(action_ids)) != len(action_ids):
            raise MultiObserverInvariantError("multi-observer legal actions are duplicated")
        return cls(
            key=key,
            seat=seat,
            action_ids=action_ids,
            actions={action_id: MultiObserverActionStatistics(action_id) for action_id in action_ids},
        )

    def validate_observation(self, observation: PlayerObservation, seat: int) -> None:
        if seat != self.seat:
            raise MultiObserverInvariantError("information node was used by another seat")
        current = tuple(canonical_action_id(action) for action in observation.legal_actions)
        if current != self.action_ids:
            raise MultiObserverInvariantError("one observer key resolved to different legal actions")

    def observe(self, observation: PlayerObservation) -> None:
        self.validate_observation(observation, self.seat)
        for action_id in self.action_ids:
            self.actions[action_id].availability += 1

    def select(
        self, observation: PlayerObservation, exploration_constant: float
    ) -> tuple[Action, bool]:
        self.validate_observation(observation, self.seat)
        by_id = {canonical_action_id(action): action for action in observation.legal_actions}
        unvisited = [
            self.actions[action_id]
            for action_id in self.action_ids
            if self.actions[action_id].availability > 0
            and self.actions[action_id].visits == 0
        ]
        if unvisited:
            selected = unvisited[0]
            return by_id[selected.action_id], True
        log_parent = math.log(max(1, self.visits))
        best = max(
            (self.actions[action_id] for action_id in self.action_ids if self.actions[action_id].availability > 0),
            key=lambda item: (
                item.mean_utility
                + exploration_constant * math.sqrt(log_parent / item.visits),
                -self.action_ids.index(item.action_id),
            ),
        )
        return by_id[best.action_id], False

    def final_action(self, observation: PlayerObservation) -> Action:
        self.validate_observation(observation, self.seat)
        by_id = {canonical_action_id(action): action for action in observation.legal_actions}
        best = max(
            (self.actions[action_id] for action_id in self.action_ids),
            key=lambda item: (item.visits, item.mean_utility, -self.action_ids.index(item.action_id)),
        )
        return by_id[best.action_id]


class MultiObserverTree:
    """One-decision shared tree with separate physical-seat node namespaces."""

    __slots__ = (
        "nodes",
        "node_revisits_by_seat",
        "cross_world_node_merge_count",
        "_world_node_keys",
        "maximum_depth",
    )

    def __init__(self) -> None:
        self.nodes: dict[str, MultiObserverInformationNode] = {}
        self.node_revisits_by_seat = [0, 0, 0, 0]
        self.cross_world_node_merge_count = 0
        self._world_node_keys: set[str] = set()
        self.maximum_depth = 0

    def node_for(
        self, observation: PlayerObservation, seat: int
    ) -> tuple[MultiObserverInformationNode, bool]:
        key = multi_observer_information_state_key(observation)
        return self._node_for_key(key=key, observation=observation, seat=seat)

    def node_for_key(
        self, *, key: str, observation: PlayerObservation, seat: int
    ) -> tuple[MultiObserverInformationNode, bool]:
        """Resolve a node when the caller already computed its canonical key.

        Phase 5E computes the observer key before re-determinization to seed the
        exact sampler.  The observer-local projection preserves that same formal
        information state, so recomputing the digest immediately afterward is
        redundant.  Callers must obtain ``key`` from the parent formal
        observation and still pass the projected observation for legal-action
        validation.
        """

        return self._node_for_key(key=key, observation=observation, seat=seat)

    def _node_for_key(
        self, *, key: str, observation: PlayerObservation, seat: int
    ) -> tuple[MultiObserverInformationNode, bool]:
        node = self.nodes.get(key)
        created = node is None
        if node is None:
            node = MultiObserverInformationNode.from_observation(
                key=key, seat=seat, observation=observation
            )
            self.nodes[key] = node
        else:
            node.validate_observation(observation, seat)
            if node.visits:
                node.revisits += 1
                self.node_revisits_by_seat[seat] += 1
        node.observe(observation)
        return node, created

    def record_world_path(self, keys: tuple[str, ...]) -> None:
        self.maximum_depth = max(self.maximum_depth, len(keys))
        unique = set(keys)
        self.cross_world_node_merge_count += sum(
            1 for key in unique if key in self._world_node_keys
        )
        self._world_node_keys.update(unique)

    def backpropagate(
        self,
        path: tuple[tuple[MultiObserverInformationNode, str], ...],
        utility: float,
    ) -> None:
        if not -1.0 <= utility <= 1.0:
            raise MultiObserverInvariantError("utility is outside bounded normalization")
        for node, action_id in path:
            action = node.actions.get(action_id)
            if action is None:
                raise MultiObserverInvariantError("path references an absent action")
            node.visits += 1
            action.visits += 1
            action.utility_sum += utility

    def node_count_by_seat(self) -> tuple[int, int, int, int]:
        counts = [0, 0, 0, 0]
        for node in self.nodes.values():
            counts[node.seat] += 1
        return tuple(counts)

    def revisit_count_by_seat(self) -> tuple[int, int, int, int]:
        return tuple(self.node_revisits_by_seat)


@dataclass(frozen=True, slots=True)
class MultiObserverDecision:
    selected_action: Action
    root_information_state_id: str
    root_seat: int
    root_team: Team
    phase: str
    configuration: MultiObserverConfiguration
    decision_seed: str
    simulation_budget: int
    simulations_completed: int
    root_sampled_world_count: int
    feasible_world_count: int
    observer_redeterminization_count: int
    redeterminizations_by_seat: tuple[int, int, int, int]
    per_seat_information_node_count: tuple[int, int, int, int]
    per_seat_node_revisit_count: tuple[int, int, int, int]
    root_action_availability: tuple[tuple[str, int], ...]
    root_action_visits: tuple[tuple[str, int], ...]
    root_action_mean_utilities: tuple[tuple[str, float], ...]
    selected_action_visit_share: float
    selected_action_value_gap: float
    total_information_nodes: int
    maximum_tree_depth: int
    cross_world_node_merge_count: int
    fallback_rollout_count: int
    rollout_policy_ids: tuple[str, ...]
    showing_delegated: bool
    failures: tuple[tuple[str, int], ...]
    schema_version: str = field(default=MULTI_OBSERVER_DIAGNOSTICS_SCHEMA_VERSION, init=False)

    @property
    def selected_action_id(self) -> str:
        return canonical_action_id(self.selected_action)

    def to_data(self) -> dict[str, object]:
        visits = dict(self.root_action_visits)
        means = dict(self.root_action_mean_utilities)
        availability = dict(self.root_action_availability)
        ranking = sorted(
            visits,
            key=lambda action_id: (
                visits[action_id],
                means[action_id],
                -tuple(visits).index(action_id),
            ),
            reverse=True,
        )
        return {
            "algorithm_id": self.configuration.algorithm_id,
            "configuration": self.configuration.to_data(),
            "cross_world_node_merge_count": self.cross_world_node_merge_count,
            "decision_seed": self.decision_seed,
            "failures": dict(self.failures),
            "feasible_world_count": self.feasible_world_count,
            "final_action_rule_id": self.configuration.final_action_rule_id,
            "fallback_rollout_count": self.fallback_rollout_count,
            "information_set_node_count": self.total_information_nodes,
            "maximum_tree_depth_in_decisions": self.maximum_tree_depth,
            "node_revisit_count_by_seat": list(self.per_seat_node_revisit_count),
            "normalization_id": self.configuration.utility_normalization_id,
            "observer_redeterminization_count": self.observer_redeterminization_count,
            "redeterminizations_by_seat": list(self.redeterminizations_by_seat),
            "per_seat_information_node_count": list(self.per_seat_information_node_count),
            "phase": self.phase,
            "root_action_availability": availability,
            "root_action_mean_utilities": dict(self.root_action_mean_utilities),
            "root_action_value_ranking": ranking,
            "root_action_visit_counts": visits,
            "root_information_state_id": self.root_information_state_id,
            "root_sampled_world_count": self.root_sampled_world_count,
            "root_seat": self.root_seat,
            "root_team": self.root_team.value,
            "rollout_policy_ids": list(self.rollout_policy_ids),
            "schema_version": self.schema_version,
            "selected_action": self.selected_action_id,
            "selected_action_value_gap": round(self.selected_action_value_gap, 9),
            "selected_action_visit_share": round(self.selected_action_visit_share, 9),
            "showing_delegated": self.showing_delegated,
            "simulation_budget": self.simulation_budget,
            "simulations_completed": self.simulations_completed,
            "utility_id": self.configuration.utility_id.value,
        }


def _decision_seed(*, root_information_state_id: str, policy_seed: str, seat: int) -> str:
    return content_digest(
        {
            "policy_seed": policy_seed,
            "root_information_state_id": root_information_state_id,
            "schema_version": f"{MULTI_OBSERVER_PROTOCOL_VERSION}.decision_seed",
            "seat": seat,
        }
    )


def _root_sampling_seed(*, root_information_state_id: str, decision_seed: str) -> str:
    return content_digest(
        {
            "decision_seed": decision_seed,
            "root_information_state_id": root_information_state_id,
            "sample_domain": "root_determinization",
            "schema_version": MULTI_OBSERVER_SEED_PROTOCOL_VERSION,
        }
    )


def observer_redeterminization_seed(
    *,
    root_information_state_id: str,
    decision_seed: str,
    simulation_index: int,
    observer_seat: int,
    observer_information_state_id: str,
    observer_decision_index: int,
) -> str:
    return content_digest(
        {
            "algorithm_version": MULTI_OBSERVER_PROTOCOL_VERSION,
            "decision_seed": decision_seed,
            "observer_decision_index": observer_decision_index,
            "observer_information_state_id": observer_information_state_id,
            "observer_seat": observer_seat,
            "root_information_state_id": root_information_state_id,
            "sample_domain": "observer_redeterminization",
            "schema_version": MULTI_OBSERVER_SEED_PROTOCOL_VERSION,
            "simulation_index": simulation_index,
        }
    )


def redeterminize_observer(
    observation: PlayerObservation,
    *,
    root_information_state_id: str,
    decision_seed: str,
    simulation_index: int,
    observer_decision_index: int,
) -> HiddenHandAssignment:
    """Sample one observer-local world from only that observer's observation."""

    if not isinstance(observation, PlayerObservation):
        raise MultiObserverDecisionError("re-determinization requires an observation")
    observer_key = multi_observer_information_state_key(observation)
    model = HardConstraintModel.build(observation)
    seed = observer_redeterminization_seed(
        root_information_state_id=root_information_state_id,
        decision_seed=decision_seed,
        simulation_index=simulation_index,
        observer_seat=observation.observing_seat,
        observer_information_state_id=observer_key,
        observer_decision_index=observer_decision_index,
    )
    sampler = UniformFeasibleSampler.build(model, seed=seed)
    return sampler.sample_one(index=simulation_index)


def _frozen_policy_specification(policy_key: str) -> AgentSpecification:
    try:
        return phase4_specifications_by_profile_key()[policy_key]
    except KeyError as exc:
        raise SearchConfigurationError(f"unknown frozen policy {policy_key!r}") from exc


def _choose_rollout(agent: object, observation: PlayerObservation, actor: int) -> Action:
    action = agent.choose_action(observation)
    if (
        not isinstance(action, PlayCardAction)
        or action.seat != actor
        or action not in observation.legal_actions
    ):
        raise IllegalRolloutActionError(
            f"fallback policy at seat {actor} proposed an illegal action"
        )
    return action


def _summary(state: FastTrickState, root_seat: int) -> DealOutcomeSummary:
    return DealOutcomeSummary(
        contract=state.contract,
        declarer=state.declarer,
        team0_tricks=state.team_tricks[0],
        starting_score=state.starting_score,
        root_team=team_for_seat(root_seat),
        source=OutcomeSource.ROLLOUT,
        tricks_simulated=TRICKS_PER_DEAL,
    )


def _run_simulation(
    *,
    state: FastTrickState,
    root_seat: int,
    root_information_state_id: str,
    decision_seed: str,
    simulation_index: int,
    tree: MultiObserverTree,
    configuration: MultiObserverConfiguration,
    fallback_agents: tuple[object, ...],
    observer_model_cache: dict[str, HardConstraintModel],
    redeterminizations_by_seat: list[int],
) -> tuple[float, int]:
    path: list[tuple[MultiObserverInformationNode, str]] = []
    keys: list[str] = []
    occurrences = [0, 0, 0, 0]
    tree_active = True
    tree_depth = 0
    fallback_count = 0
    actions_simulated = 0
    maximum_actions = 4 + 4 * TRICKS_PER_DEAL

    while not state.complete:
        if actions_simulated > maximum_actions:
            raise MultiObserverDecisionError(
                "simulation exceeded maximum action count",
                failure_kind=MultiObserverFailureKind.RESOURCE_EXHAUSTION,
            )
        actor = state.current_actor
        if actor is None:
            raise MultiObserverDecisionError(
                "nonterminal state has no acting seat",
                failure_kind=MultiObserverFailureKind.ENGINE_FAILURE,
            )
        parent_observation = state.observation_for(actor)
        if tree_active and tree_depth < configuration.max_tree_depth:
            observer_observation = parent_observation
            if actor != root_seat:
                observer_key = multi_observer_information_state_key(parent_observation)
                model = observer_model_cache.get(observer_key)
                if model is None:
                    model = HardConstraintModel.build(parent_observation)
                    observer_model_cache[observer_key] = model
                seed = observer_redeterminization_seed(
                    root_information_state_id=root_information_state_id,
                    decision_seed=decision_seed,
                    simulation_index=simulation_index,
                    observer_seat=actor,
                    observer_information_state_id=observer_key,
                    observer_decision_index=occurrences[actor],
                )
                local_assignment = UniformFeasibleSampler.build(model, seed=seed).sample_one(
                    index=simulation_index
                )
                redeterminizations_by_seat[actor] += 1
                try:
                    local_state = FastTrickState.from_observation_assignment(
                        parent_observation, local_assignment
                    )
                    observer_observation = local_state.observation_for(actor)
                except Exception as exc:  # noqa: BLE001 - strict classification below
                    raise MultiObserverDecisionError(
                        f"observer-local state construction failed: {type(exc).__name__}: {exc}",
                        failure_kind=MultiObserverFailureKind.OBSERVER_CONSTRUCTION,
                    ) from exc
            occurrences[actor] += 1
            if actor != root_seat:
                node, _created = tree.node_for_key(
                    key=observer_key,
                    observation=observer_observation,
                    seat=actor,
                )
            else:
                node, _created = tree.node_for(observer_observation, actor)
            action, _edge_expanded = node.select(
                observer_observation, configuration.exploration_constant
            )
            action_id = canonical_action_id(action)
            path.append((node, action_id))
            keys.append(node.key)
            tree_depth += 1
            if action not in parent_observation.legal_actions:
                raise MultiObserverDecisionError(
                    "observer-local action is illegal in the parent observation",
                    failure_kind=MultiObserverFailureKind.ACTION_MAPPING,
                )
            # Expanding an edge does not end the simulation's tree traversal.
            # Later turns by the same root seat must continue through this
            # decision's shared information-set tree.  The fallback policy is
            # reserved for the explicit depth boundary.
            if tree_depth >= configuration.max_tree_depth:
                tree_active = False
        else:
            action = _choose_rollout(fallback_agents[actor], parent_observation, actor)
            fallback_count += 1
        try:
            state = state.apply(action)
        except FastTrickError as exc:
            raise MultiObserverDecisionError(
                f"parent simulation rejected action: {exc}",
                failure_kind=MultiObserverFailureKind.ENGINE_FAILURE,
            ) from exc
        actions_simulated += 1

    if len(state.completed_tricks) != TRICKS_PER_DEAL:
        raise MultiObserverDecisionError(
            "completed simulation did not contain 13 tricks",
            failure_kind=MultiObserverFailureKind.ENGINE_FAILURE,
        )
    utility = utility_value(configuration.utility_id, _summary(state, root_seat))
    tree.record_world_path(tuple(keys))
    tree.backpropagate(tuple(path), utility)
    return utility, fallback_count


def _showing_decision(
    observation: PlayerObservation,
    *,
    configuration: MultiObserverConfiguration,
    decision_seed: str,
    root_information_state_id: str,
) -> MultiObserverDecision:
    specification = _frozen_policy_specification(configuration.showing_policy_key)
    selected = construct_agent(specification, seat=observation.observing_seat).choose_action(
        observation
    )
    ids = tuple(specification.agent_id for _ in range(4))
    return MultiObserverDecision(
        selected_action=selected,
        root_information_state_id=root_information_state_id,
        root_seat=observation.observing_seat,
        root_team=team_for_seat(observation.observing_seat),
        phase=observation.phase.value,
        configuration=configuration,
        decision_seed=decision_seed,
        simulation_budget=configuration.simulation_budget,
        simulations_completed=0,
        root_sampled_world_count=0,
        feasible_world_count=0,
        observer_redeterminization_count=0,
        redeterminizations_by_seat=(0, 0, 0, 0),
        per_seat_information_node_count=(0, 0, 0, 0),
        per_seat_node_revisit_count=(0, 0, 0, 0),
        root_action_availability=((canonical_action_id(selected), 0),),
        root_action_visits=((canonical_action_id(selected), 0),),
        root_action_mean_utilities=((canonical_action_id(selected), 0.0),),
        selected_action_visit_share=0.0,
        selected_action_value_gap=0.0,
        total_information_nodes=0,
        maximum_tree_depth=0,
        cross_world_node_merge_count=0,
        fallback_rollout_count=0,
        rollout_policy_ids=ids,
        showing_delegated=True,
        failures=(),
    )


def decide(
    observation: PlayerObservation,
    *,
    configuration: MultiObserverConfiguration,
    decision_seed: str,
) -> MultiObserverDecision:
    if not isinstance(observation, PlayerObservation):
        raise MultiObserverDecisionError("multi-observer search requires a PlayerObservation")
    if not isinstance(configuration, MultiObserverConfiguration):
        raise MultiObserverDecisionError("multi-observer search requires its configuration")
    if not isinstance(decision_seed, str) or not decision_seed:
        raise MultiObserverDecisionError("multi-observer search requires a decision seed")
    if observation.current_actor != observation.observing_seat:
        raise MultiObserverDecisionError("multi-observer search requires the acting seat")
    if not observation.legal_actions:
        raise MultiObserverDecisionError("multi-observer search received no legal action")

    root_seat = observation.observing_seat
    root_team = team_for_seat(root_seat)
    root_key = root_information_state_key(observation)
    if observation.phase is EnginePhase.SHOWING:
        return _showing_decision(
            observation,
            configuration=configuration,
            decision_seed=decision_seed,
            root_information_state_id=root_key,
        )
    if observation.phase is not EnginePhase.TRICK_PLAY:
        raise MultiObserverDecisionError("multi-observer search supports showing and trick play only")

    try:
        root_model = HardConstraintModel.build(observation)
        feasible_count = feasible_assignment_count(root_model)
        if feasible_count < 1:
            raise MultiObserverDecisionError(
                "root hard constraints admit no feasible world",
                failure_kind=MultiObserverFailureKind.ROOT_SAMPLER_INCONSISTENCY,
            )
        root_sampler = UniformFeasibleSampler.build(
            root_model,
            seed=_root_sampling_seed(
                root_information_state_id=root_key, decision_seed=decision_seed
            ),
        )
        assignments = root_sampler.sample(configuration.simulation_budget)
    except MultiObserverDecisionError:
        raise
    except Exception as exc:  # noqa: BLE001 - strict classification below
        raise MultiObserverDecisionError(
            f"root Phase 5B sampler failed: {type(exc).__name__}: {exc}",
            failure_kind=MultiObserverFailureKind.ROOT_SAMPLER_INCONSISTENCY,
        ) from exc

    tree = MultiObserverTree()
    fallback_spec = _frozen_policy_specification(configuration.fallback_policy_key)
    fallback_agents = tuple(
        construct_agent(fallback_spec, seat=seat) for seat in range(4)
    )
    observer_model_cache: dict[str, HardConstraintModel] = {}
    redeterminizations_by_seat = [0, 0, 0, 0]
    fallback_count = 0
    completed = 0
    for simulation_index, assignment in enumerate(assignments):
        try:
            state = FastTrickState.from_observation_assignment(observation, assignment)
            _, used_fallback = _run_simulation(
                state=state,
                root_seat=root_seat,
                root_information_state_id=root_key,
                decision_seed=decision_seed,
                simulation_index=simulation_index,
                tree=tree,
                configuration=configuration,
                fallback_agents=fallback_agents,
                observer_model_cache=observer_model_cache,
                redeterminizations_by_seat=redeterminizations_by_seat,
            )
            fallback_count += used_fallback
            completed += 1
        except MultiObserverDecisionError:
            raise
        except IllegalRolloutActionError as exc:
            raise MultiObserverDecisionError(
                str(exc), failure_kind=MultiObserverFailureKind.ROLLOUT_ILLEGAL_ACTION
            ) from exc
        except MemoryError as exc:
            raise MultiObserverDecisionError(
                str(exc), failure_kind=MultiObserverFailureKind.RESOURCE_EXHAUSTION
            ) from exc
        except Exception as exc:  # noqa: BLE001 - all unexpected failures are fatal
            raise MultiObserverDecisionError(
                f"multi-observer simulation failed: {type(exc).__name__}: {exc}",
                failure_kind=MultiObserverFailureKind.ENGINE_FAILURE,
            ) from exc

    root_node = tree.nodes.get(multi_observer_information_state_key(observation))
    if root_node is None:
        raise MultiObserverDecisionError(
            "initial multi-observer root node was never created",
            failure_kind=MultiObserverFailureKind.TREE_INVARIANT,
        )
    selected = root_node.final_action(observation)
    action_ids = root_node.action_ids
    visits = tuple((item, root_node.actions[item].visits) for item in action_ids)
    means = tuple((item, root_node.actions[item].mean_utility) for item in action_ids)
    availability = tuple((item, root_node.actions[item].availability) for item in action_ids)
    selected_stats = root_node.actions[canonical_action_id(selected)]
    other_means = [
        root_node.actions[item].mean_utility
        for item in action_ids
        if item != canonical_action_id(selected)
    ]
    total_visits = sum(value for _, value in visits)
    return MultiObserverDecision(
        selected_action=selected,
        root_information_state_id=root_key,
        root_seat=root_seat,
        root_team=root_team,
        phase=observation.phase.value,
        configuration=configuration,
        decision_seed=decision_seed,
        simulation_budget=configuration.simulation_budget,
        simulations_completed=completed,
        root_sampled_world_count=len({world_identity(item) for item in assignments}),
        feasible_world_count=feasible_count,
        observer_redeterminization_count=sum(redeterminizations_by_seat),
        redeterminizations_by_seat=tuple(redeterminizations_by_seat),
        per_seat_information_node_count=tree.node_count_by_seat(),
        per_seat_node_revisit_count=tree.revisit_count_by_seat(),
        root_action_availability=availability,
        root_action_visits=visits,
        root_action_mean_utilities=means,
        selected_action_visit_share=(selected_stats.visits / total_visits if total_visits else 0.0),
        selected_action_value_gap=(
            selected_stats.mean_utility - max(other_means) if other_means else 0.0
        ),
        total_information_nodes=len(tree.nodes),
        maximum_tree_depth=tree.maximum_depth,
        cross_world_node_merge_count=tree.cross_world_node_merge_count,
        fallback_rollout_count=fallback_count,
        rollout_policy_ids=tuple(
            "multi_observer_information_set_tree_v1"
            if seat == root_seat
            else fallback_spec.agent_id
            for seat in range(4)
        ),
        showing_delegated=False,
        failures=(),
    )


class MultiObserverAgent:
    """Deployable one-seat Phase 5E agent."""

    __slots__ = ("_agent_id", "_configuration", "_seat", "_policy_seed")

    def __init__(
        self,
        *,
        agent_id: str,
        configuration: MultiObserverConfiguration,
        seat: int,
        policy_seed: str = "tuppi-phase5e-policy-seed-v1",
    ) -> None:
        if not isinstance(agent_id, str) or not agent_id.startswith("agent:"):
            raise MultiObserverDecisionError("multi-observer agent needs a canonical id")
        if type(seat) is not int or seat not in range(4):
            raise MultiObserverDecisionError("multi-observer seat must be in 0..3")
        self._agent_id = agent_id
        self._configuration = configuration
        self._seat = seat
        self._policy_seed = policy_seed

    @property
    def identity(self) -> str:
        return self._agent_id

    @property
    def configuration(self) -> MultiObserverConfiguration:
        return self._configuration

    @property
    def seat(self) -> int:
        return self._seat

    def decision_seed(self, observation: PlayerObservation) -> str:
        if observation.observing_seat != self._seat:
            raise MultiObserverDecisionError("agent received another seat's observation")
        return _decision_seed(
            root_information_state_id=root_information_state_key(observation),
            policy_seed=self._policy_seed,
            seat=self._seat,
        )

    def decide(self, observation: PlayerObservation) -> MultiObserverDecision:
        if observation.observing_seat != self._seat:
            raise MultiObserverDecisionError("agent received another seat's observation")
        return decide(
            observation,
            configuration=self._configuration,
            decision_seed=self.decision_seed(observation),
        )

    def choose_action(self, observation: PlayerObservation) -> Action:
        return self.decide(observation).selected_action

    def explain(self, observation: PlayerObservation) -> MultiObserverDecision:
        return self.decide(observation)


def construct_multi_observer_agent(
    specification: AgentSpecification,
    *,
    seat: int,
    configuration: MultiObserverConfiguration,
    policy_seed: str = "tuppi-phase5e-policy-seed-v1",
) -> MultiObserverAgent:
    if not isinstance(specification, AgentSpecification):
        raise MultiObserverDecisionError("construction needs an AgentSpecification")
    if specification.configuration.get("multi_observer_configuration_id") != configuration.configuration_id:
        raise MultiObserverDecisionError("specification and configuration disagree")
    return MultiObserverAgent(
        agent_id=specification.agent_id,
        configuration=configuration,
        seat=seat,
        policy_seed=policy_seed,
    )


__all__ = (
    "MULTI_OBSERVER_ALGORITHM_ID",
    "MULTI_OBSERVER_AVAILABILITY_RULE_ID",
    "MULTI_OBSERVER_CONFIGURATION_SCHEMA_VERSION",
    "MULTI_OBSERVER_DIAGNOSTICS_SCHEMA_VERSION",
    "MULTI_OBSERVER_EXPANSION_RULE_ID",
    "MULTI_OBSERVER_FINAL_ACTION_RULE_ID",
    "MULTI_OBSERVER_PROTOCOL_VERSION",
    "MULTI_OBSERVER_REDETERMINIZATION_RULE_ID",
    "MULTI_OBSERVER_SEED_PROTOCOL_VERSION",
    "MultiObserverAgent",
    "MultiObserverConfiguration",
    "MultiObserverDecision",
    "MultiObserverFailureKind",
    "MultiObserverInformationNode",
    "MultiObserverTree",
    "construct_multi_observer_agent",
    "decide",
    "observer_redeterminization_seed",
    "redeterminize_observer",
)
