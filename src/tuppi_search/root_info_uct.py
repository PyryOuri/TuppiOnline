"""Observation-safe root-player information-set UCT for Phase 5D-B.

This is deliberately narrower than multi-observer information-set search.  Only
the original acting seat owns a tree.  All other seats are independent frozen
observation-only Phase 4 policies, and the tree is discarded after the real
decision.  A sampled hidden world is therefore a simulation input, not a node-key
component: future root turns with the same observation share one node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Mapping

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    Action,
    DealState,
    EnginePhase,
    PlayerObservation,
    apply_action,
    observation_for,
)
from tuppi_engine.errors import EngineError
from tuppi_eval.identities import AgentSpecification, DeterminismClass, SeedPolicy
from tuppi_eval.serialization import content_digest
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler, feasible_assignment_count
from tuppi_exact.sampling import SAMPLER_ALGORITHM_ID
from tuppi_rules import Team, TRICKS_PER_DEAL, team_for_seat

from .errors import (
    IllegalRolloutActionError,
    RootInfoUctDecisionError,
    RootInfoUctInvariantError,
    SearchConfigurationError,
    SearchError,
    WorldSetError,
)
from .fast_trick import FastTrickError, FastTrickState
from .information_state import root_information_state_key
from .random import canonical_action_id
from .utilities import (
    OutcomeSource,
    DealOutcomeSummary,
    UtilityId,
    is_registerable,
    summary_from_completed_deal,
    utility_value,
)
from .worlds import world_identity


ROOT_INFO_UCT_PROTOCOL_VERSION = "tuppi.search.root_info_uct.v1"
ROOT_INFO_UCT_CONFIGURATION_SCHEMA_VERSION = "tuppi.search.root_info_uct_configuration.v1"
ROOT_INFO_UCT_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.search.root_info_uct_diagnostics.v1"
ROOT_INFO_UCT_SEED_PROTOCOL_VERSION = "tuppi.search.root_info_uct_seed.v1"
ROOT_INFO_UCT_NORMALIZATION_ID = "identity_bounded_minus_one_to_one_v1"
ROOT_INFO_UCT_EXPANSION_RULE_ID = "all_legal_actions_canonical_v1"
ROOT_INFO_UCT_FINAL_ACTION_RULE_ID = "highest_visits_then_mean_then_legal_order_v1"
ROOT_INFO_UCT_ACTION_ORDERING_ID = "tuppi.engine.legal_action_order.v1"
ROOT_INFO_UCT_SHOWING_POLICY = "partner_aware_v1"
ROOT_INFO_UCT_SUPPORTED_ROLLOUTS = ("partner_aware_v1", "public_counting_v1")


class RootInfoUctFailureKind:
    """Stable failure categories used in strict decision errors."""

    SAMPLER_INCONSISTENCY = "sampler_inconsistency"
    HYPOTHETICAL_CONSTRUCTION = "hypothetical_state_construction"
    ROLLOUT_ILLEGAL_ACTION = "rollout_illegal_action"
    TREE_INVARIANT = "tree_invariant_failure"
    IMPOSSIBLE_ROOT_ACTION = "impossible_root_action"
    ENGINE_FAILURE = "engine_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"


@dataclass(frozen=True, slots=True)
class RootInfoUctConfiguration:
    """One complete, immutable root-information UCT definition."""

    configuration_id: str
    simulation_budget: int
    exploration_constant: float
    rollout_policy_key: str
    showing_policy_key: str
    utility_id: UtilityId
    utility_normalization_id: str
    expansion_rule_id: str
    final_action_rule_id: str
    action_ordering_id: str
    seed_protocol: str
    sampler_algorithm_id: str
    exact_tail_enabled: bool
    failure_policy: str
    protocol_version: str = field(default=ROOT_INFO_UCT_PROTOCOL_VERSION, init=False)
    schema_version: str = field(
        default=ROOT_INFO_UCT_CONFIGURATION_SCHEMA_VERSION, init=False
    )

    @classmethod
    def build(
        cls,
        *,
        simulation_budget: int,
        exploration_constant: float = math.sqrt(2.0),
        rollout_policy_key: str = ROOT_INFO_UCT_SHOWING_POLICY,
        utility_id: UtilityId = UtilityId.MATCH_TRANSITION_V1,
    ) -> "RootInfoUctConfiguration":
        values = {
            "simulation_budget": simulation_budget,
            "exploration_constant": exploration_constant,
            "rollout_policy_key": rollout_policy_key,
            "showing_policy_key": ROOT_INFO_UCT_SHOWING_POLICY,
            "utility_id": utility_id,
            "utility_normalization_id": ROOT_INFO_UCT_NORMALIZATION_ID,
            "expansion_rule_id": ROOT_INFO_UCT_EXPANSION_RULE_ID,
            "final_action_rule_id": ROOT_INFO_UCT_FINAL_ACTION_RULE_ID,
            "action_ordering_id": ROOT_INFO_UCT_ACTION_ORDERING_ID,
            "seed_protocol": ROOT_INFO_UCT_SEED_PROTOCOL_VERSION,
            "sampler_algorithm_id": SAMPLER_ALGORITHM_ID,
            "exact_tail_enabled": False,
            "failure_policy": "strict",
        }
        provisional = object.__new__(cls)
        for key, value in values.items():
            object.__setattr__(provisional, key, value)
        object.__setattr__(provisional, "protocol_version", ROOT_INFO_UCT_PROTOCOL_VERSION)
        object.__setattr__(provisional, "schema_version", ROOT_INFO_UCT_CONFIGURATION_SCHEMA_VERSION)
        return cls(
            configuration_id=f"rootuctcfg:{content_digest(provisional.identity_data())}",
            **values,
        )

    def __post_init__(self) -> None:
        if type(self.simulation_budget) is not int or not 1 <= self.simulation_budget <= 4096:
            raise SearchConfigurationError("simulation_budget must be an integer in 1..4096")
        if type(self.exploration_constant) not in (int, float) or not math.isfinite(self.exploration_constant) or self.exploration_constant <= 0:
            raise SearchConfigurationError("exploration_constant must be finite and positive")
        if self.rollout_policy_key not in ROOT_INFO_UCT_SUPPORTED_ROLLOUTS:
            raise SearchConfigurationError(
                f"unsupported root-information rollout policy {self.rollout_policy_key!r}"
            )
        if self.showing_policy_key != ROOT_INFO_UCT_SHOWING_POLICY:
            raise SearchConfigurationError("showing must remain delegated to partner_aware_v1")
        if not isinstance(self.utility_id, UtilityId) or not is_registerable(self.utility_id):
            raise SearchConfigurationError("root-information UCT requires a registerable utility")
        if self.utility_normalization_id != ROOT_INFO_UCT_NORMALIZATION_ID:
            raise SearchConfigurationError("unsupported UCT utility normalization")
        if self.expansion_rule_id != ROOT_INFO_UCT_EXPANSION_RULE_ID:
            raise SearchConfigurationError("unsupported UCT expansion rule")
        if self.final_action_rule_id != ROOT_INFO_UCT_FINAL_ACTION_RULE_ID:
            raise SearchConfigurationError("unsupported UCT final-action rule")
        if self.action_ordering_id != ROOT_INFO_UCT_ACTION_ORDERING_ID:
            raise SearchConfigurationError("unsupported action ordering")
        if self.sampler_algorithm_id != SAMPLER_ALGORITHM_ID:
            raise SearchConfigurationError("root-information UCT must use the Phase 5B sampler")
        if self.exact_tail_enabled:
            raise SearchConfigurationError("exact-tail is disabled in the primary root-information UCT")
        if self.failure_policy != "strict":
            raise SearchConfigurationError("root-information UCT requires strict failures")
        if self.configuration_id != f"rootuctcfg:{content_digest(self.identity_data())}":
            raise SearchConfigurationError("configuration_id disagrees with root-information UCT content")

    def identity_data(self) -> dict[str, object]:
        return {
            "action_ordering_id": self.action_ordering_id,
            "exact_tail_enabled": self.exact_tail_enabled,
            "expansion_rule_id": self.expansion_rule_id,
            "exploration_constant": float(self.exploration_constant),
            "failure_policy": self.failure_policy,
            "final_action_rule_id": self.final_action_rule_id,
            "protocol_version": self.protocol_version,
            "rollout_policy_key": self.rollout_policy_key,
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
class UctActionStatistics:
    action_id: str
    visits: int = 0
    utility_sum: float = 0.0

    @property
    def mean_utility(self) -> float:
        return self.utility_sum / self.visits if self.visits else 0.0


@dataclass(slots=True)
class UctInformationNode:
    key: str
    action_ids: tuple[str, ...]
    actions: dict[str, UctActionStatistics]
    visits: int = 0

    @classmethod
    def from_observation(cls, key: str, observation: PlayerObservation) -> "UctInformationNode":
        action_ids = tuple(canonical_action_id(action) for action in observation.legal_actions)
        if not action_ids:
            raise RootInfoUctInvariantError("a root information node needs legal actions")
        if len(set(action_ids)) != len(action_ids):
            raise RootInfoUctInvariantError("legal actions have duplicate canonical ids")
        return cls(
            key=key,
            action_ids=action_ids,
            actions={action_id: UctActionStatistics(action_id) for action_id in action_ids},
        )

    def validate_observation(self, observation: PlayerObservation) -> None:
        current = tuple(canonical_action_id(action) for action in observation.legal_actions)
        if current != self.action_ids:
            raise RootInfoUctInvariantError(
                "one information-state key resolved to different legal actions"
            )

    def select(self, observation: PlayerObservation, exploration_constant: float) -> Action:
        self.validate_observation(observation)
        by_id = {canonical_action_id(action): action for action in observation.legal_actions}
        unvisited = [self.actions[action_id] for action_id in self.action_ids if self.actions[action_id].visits == 0]
        if unvisited:
            return by_id[unvisited[0].action_id]
        log_parent = math.log(max(1, self.visits))
        best = max(
            (self.actions[action_id] for action_id in self.action_ids),
            key=lambda item: (
                item.mean_utility + exploration_constant * math.sqrt(log_parent / item.visits),
                -self.action_ids.index(item.action_id),
            ),
        )
        return by_id[best.action_id]

    def final_action(self, observation: PlayerObservation) -> Action:
        self.validate_observation(observation)
        by_id = {canonical_action_id(action): action for action in observation.legal_actions}
        best = max(
            (self.actions[action_id] for action_id in self.action_ids),
            key=lambda item: (item.visits, item.mean_utility, -self.action_ids.index(item.action_id)),
        )
        return by_id[best.action_id]


class RootInfoUctTree:
    """Mutable, one-decision tree keyed only by root information states."""

    __slots__ = (
        "nodes",
        "node_revisit_count",
        "cross_world_node_merge_count",
        "_world_node_keys",
        "maximum_depth",
    )

    def __init__(self) -> None:
        self.nodes: dict[str, UctInformationNode] = {}
        self.node_revisit_count = 0
        self.cross_world_node_merge_count = 0
        self._world_node_keys: set[str] = set()
        self.maximum_depth = 0

    def node_for(self, observation: PlayerObservation) -> UctInformationNode:
        key = root_information_state_key(observation)
        node = self.nodes.get(key)
        if node is None:
            node = UctInformationNode.from_observation(key, observation)
            self.nodes[key] = node
        else:
            node.validate_observation(observation)
            if node.visits:
                self.node_revisit_count += 1
        return node

    def record_world_path(self, keys: tuple[str, ...]) -> None:
        if len(keys) > self.maximum_depth:
            self.maximum_depth = len(keys)
        unique = set(keys)
        self.cross_world_node_merge_count += sum(1 for key in unique if key in self._world_node_keys)
        self._world_node_keys.update(unique)

    def backpropagate(self, path: tuple[tuple[UctInformationNode, str], ...], utility: float) -> None:
        if not -1.0 <= utility <= 1.0:
            raise RootInfoUctInvariantError("backpropagated utility is outside [-1, 1]")
        for node, action_id in path:
            action = node.actions.get(action_id)
            if action is None:
                raise RootInfoUctInvariantError("path references an action absent from its node")
            node.visits += 1
            action.visits += 1
            action.utility_sum += utility


@dataclass(frozen=True, slots=True)
class RootInfoUctDecision:
    """Immutable, hidden-hand-free result and diagnostic of one real decision."""

    selected_action: Action
    root_information_state_id: str
    root_seat: int
    root_team: Team
    phase: str
    configuration: RootInfoUctConfiguration
    decision_seed: str
    simulation_budget: int
    simulations_completed: int
    unique_sampled_worlds: int
    feasible_world_count: int
    root_action_visits: tuple[tuple[str, int], ...]
    root_action_mean_utilities: tuple[tuple[str, float], ...]
    selected_action_visit_share: float
    selected_action_value_gap: float
    root_information_set_nodes: int
    maximum_tree_depth: int
    node_revisit_count: int
    cross_world_node_merge_count: int
    rollout_policy_ids: tuple[str, ...]
    showing_delegated: bool
    failures: tuple[tuple[str, int], ...]
    schema_version: str = field(default=ROOT_INFO_UCT_DIAGNOSTICS_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.selected_action, Action):
            raise RootInfoUctDecisionError("a root-information decision needs an action")
        if not self.root_information_state_id.startswith("rootinfo:"):
            raise RootInfoUctDecisionError("invalid root information-state identity")
        if len(self.rollout_policy_ids) != 4:
            raise RootInfoUctDecisionError("rollout policy ids must cover four seats")
        if self.simulations_completed < 0 or self.simulations_completed > self.simulation_budget:
            raise RootInfoUctDecisionError("simulation count is outside the configured budget")

    @property
    def selected_action_id(self) -> str:
        return canonical_action_id(self.selected_action)

    def to_data(self) -> dict[str, object]:
        visits = dict(self.root_action_visits)
        means = dict(self.root_action_mean_utilities)
        ranking = sorted(
            visits,
            key=lambda action_id: (visits[action_id], means[action_id], -tuple(visits).index(action_id)),
            reverse=True,
        )
        payload = {
            "algorithm_id": ROOT_INFO_UCT_PROTOCOL_VERSION,
            "configuration": self.configuration.to_data(),
            "cross_world_node_merge_count": self.cross_world_node_merge_count,
            "decision_seed": self.decision_seed,
            "failures": dict(self.failures),
            "feasible_world_count": self.feasible_world_count,
            "final_action_rule_id": self.configuration.final_action_rule_id,
            "information_set_node_count": self.root_information_set_nodes,
            "maximum_tree_depth_in_root_decisions": self.maximum_tree_depth,
            "node_revisit_count": self.node_revisit_count,
            "normalization_id": self.configuration.utility_normalization_id,
            "phase": self.phase,
            "root_action_mean_utilities": dict(self.root_action_mean_utilities),
            "root_action_visit_counts": visits,
            "root_action_value_ranking": ranking,
            "root_information_state_id": self.root_information_state_id,
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
            "unique_sampled_worlds": self.unique_sampled_worlds,
        }
        return payload


def _decision_seed(
    *, root_information_state_id: str, policy_seed: str, seat: int
) -> str:
    return content_digest(
        {
            "policy_seed": policy_seed,
            "root_information_state_id": root_information_state_id,
            "schema_version": "tuppi.search.root_info_uct_decision_seed.v1",
            "seat": seat,
        }
    )


def _world_sampling_seed(*, root_information_state_id: str, decision_seed: str) -> str:
    return content_digest(
        {
            "decision_seed": decision_seed,
            "protocol_version": ROOT_INFO_UCT_PROTOCOL_VERSION,
            "root_information_state_id": root_information_state_id,
            "schema_version": ROOT_INFO_UCT_SEED_PROTOCOL_VERSION,
        }
    )


def _frozen_policy_specification(policy_key: str) -> AgentSpecification:
    specifications = phase4_specifications_by_profile_key()
    try:
        return specifications[policy_key]
    except KeyError as exc:
        raise SearchConfigurationError(f"unknown frozen rollout policy {policy_key!r}") from exc


def _build_non_root_agents(*, configuration: RootInfoUctConfiguration, root_seat: int) -> tuple[object | None, ...]:
    specification = _frozen_policy_specification(configuration.rollout_policy_key)
    return tuple(
        None if seat == root_seat else construct_agent(specification, seat=seat)
        for seat in range(4)
    )


def _choose_non_root(agent: object, observation: PlayerObservation, actor: int) -> Action:
    if not isinstance(observation, PlayerObservation):
        raise RootInfoUctInvariantError("non-root policy did not receive a PlayerObservation")
    action = agent.choose_action(observation)
    if action is None or getattr(action, "seat", None) != actor or action not in observation.legal_actions:
        raise IllegalRolloutActionError(
            f"frozen rollout policy at seat {actor} proposed an illegal action"
        )
    return action


def _run_simulation_authoritative(
    *,
    state: DealState,
    root_seat: int,
    tree: RootInfoUctTree,
    configuration: RootInfoUctConfiguration,
) -> float:
    agents = _build_non_root_agents(configuration=configuration, root_seat=root_seat)
    path: list[tuple[UctInformationNode, str]] = []
    keys: list[str] = []
    actions_simulated = 0
    maximum_actions = 4 + 4 * TRICKS_PER_DEAL
    while not state.complete:
        if actions_simulated > maximum_actions:
            raise RootInfoUctDecisionError(
                "rollout exceeded the maximum possible action count",
                failure_kind=RootInfoUctFailureKind.RESOURCE_EXHAUSTION,
            )
        actor = state.current_actor
        if actor is None:
            raise RootInfoUctDecisionError(
                "nonterminal hypothetical state has no acting seat",
                failure_kind=RootInfoUctFailureKind.ENGINE_FAILURE,
            )
        observation = observation_for(state, actor)
        if actor == root_seat:
            key = root_information_state_key(observation)
            node = tree.node_for(observation)
            action = node.select(observation, configuration.exploration_constant)
            action_id = canonical_action_id(action)
            if action_id not in node.actions:
                raise RootInfoUctDecisionError(
                    "tree selected an action absent from the root node",
                    failure_kind=RootInfoUctFailureKind.IMPOSSIBLE_ROOT_ACTION,
                )
            path.append((node, action_id))
            keys.append(key)
        else:
            policy = agents[actor]
            if policy is None:
                raise RootInfoUctInvariantError("non-root policy slot is empty")
            action = _choose_non_root(policy, observation, actor)
        try:
            state = apply_action(state, action)
        except EngineError as exc:
            kind = (
                RootInfoUctFailureKind.IMPOSSIBLE_ROOT_ACTION
                if actor == root_seat
                else RootInfoUctFailureKind.ENGINE_FAILURE
            )
            raise RootInfoUctDecisionError(
                f"engine rejected a simulated action: {type(exc).__name__}: {exc}",
                failure_kind=kind,
            ) from exc
        actions_simulated += 1
    if len(state.completed_tricks) != TRICKS_PER_DEAL:
        raise RootInfoUctDecisionError(
            "a completed simulation did not contain 13 tricks",
            failure_kind=RootInfoUctFailureKind.ENGINE_FAILURE,
        )
    summary = summary_from_completed_deal(
        state,
        root_seat=root_seat,
        source=OutcomeSource.ROLLOUT,
        tricks_simulated=TRICKS_PER_DEAL,
    )
    utility = utility_value(configuration.utility_id, summary)
    tree.record_world_path(tuple(keys))
    tree.backpropagate(tuple(path), utility)
    return utility


def _run_simulation_fast(
    *,
    state: FastTrickState,
    root_seat: int,
    tree: RootInfoUctTree,
    configuration: RootInfoUctConfiguration,
) -> float:
    """Run one simulation on the validated search-local trick state."""

    agents = _build_non_root_agents(configuration=configuration, root_seat=root_seat)
    path: list[tuple[UctInformationNode, str]] = []
    keys: list[str] = []
    actions_simulated = 0
    maximum_actions = 4 + 4 * TRICKS_PER_DEAL
    while not state.complete:
        if actions_simulated > maximum_actions:
            raise RootInfoUctDecisionError(
                "rollout exceeded the maximum possible action count",
                failure_kind=RootInfoUctFailureKind.RESOURCE_EXHAUSTION,
            )
        actor = state.current_actor
        if actor is None:
            raise RootInfoUctDecisionError(
                "nonterminal fast state has no acting seat",
                failure_kind=RootInfoUctFailureKind.ENGINE_FAILURE,
            )
        observation = state.observation_for(actor)
        if actor == root_seat:
            key = root_information_state_key(observation)
            node = tree.node_for(observation)
            action = node.select(observation, configuration.exploration_constant)
            action_id = canonical_action_id(action)
            if action_id not in node.actions:
                raise RootInfoUctDecisionError(
                    "tree selected an action absent from the root node",
                    failure_kind=RootInfoUctFailureKind.IMPOSSIBLE_ROOT_ACTION,
                )
            path.append((node, action_id))
            keys.append(key)
        else:
            policy = agents[actor]
            if policy is None:
                raise RootInfoUctInvariantError("non-root policy slot is empty")
            action = _choose_non_root(policy, observation, actor)
        try:
            state = state.apply(action)
        except FastTrickError as exc:
            kind = (
                RootInfoUctFailureKind.IMPOSSIBLE_ROOT_ACTION
                if actor == root_seat
                else RootInfoUctFailureKind.ENGINE_FAILURE
            )
            raise RootInfoUctDecisionError(
                f"fast engine rejected a simulated action: {exc}",
                failure_kind=kind,
            ) from exc
        actions_simulated += 1
    if len(state.completed_tricks) != TRICKS_PER_DEAL:
        raise RootInfoUctDecisionError(
            "a completed fast simulation did not contain 13 tricks",
            failure_kind=RootInfoUctFailureKind.ENGINE_FAILURE,
        )
    summary = DealOutcomeSummary(
        contract=state.contract,
        declarer=state.declarer,
        team0_tricks=state.team_tricks[0],
        starting_score=state.starting_score,
        root_team=team_for_seat(root_seat),
        source=OutcomeSource.ROLLOUT,
        tricks_simulated=TRICKS_PER_DEAL,
    )
    utility = utility_value(configuration.utility_id, summary)
    tree.record_world_path(tuple(keys))
    tree.backpropagate(tuple(path), utility)
    return utility


def _failure(kind: str, message: str, cause: BaseException | None = None) -> RootInfoUctDecisionError:
    error = RootInfoUctDecisionError(message, failure_kind=kind)
    if cause is not None:
        error.__cause__ = cause
    return error


def decide(
    observation: PlayerObservation,
    *,
    configuration: RootInfoUctConfiguration,
    decision_seed: str,
    _fast_path: bool = True,
) -> RootInfoUctDecision:
    """Run one fresh root-information tree search from one observation."""

    if not isinstance(observation, PlayerObservation):
        raise RootInfoUctDecisionError("root-information UCT requires a PlayerObservation")
    if not isinstance(configuration, RootInfoUctConfiguration):
        raise RootInfoUctDecisionError("root-information UCT requires its own configuration")
    if not isinstance(decision_seed, str) or not decision_seed:
        raise RootInfoUctDecisionError("root-information UCT requires a nonempty decision seed")
    if observation.current_actor != observation.observing_seat:
        raise RootInfoUctDecisionError("root-information UCT may only decide for the acting seat")
    if not observation.legal_actions:
        raise RootInfoUctDecisionError("root-information UCT received no legal action")

    root_seat = observation.observing_seat
    root_team = team_for_seat(root_seat)
    root_key = root_information_state_key(observation)
    showing = observation.phase is EnginePhase.SHOWING
    if showing:
        specification = _frozen_policy_specification(configuration.showing_policy_key)
        selected = construct_agent(specification, seat=root_seat).choose_action(observation)
        policy_ids = tuple(
            specification.agent_id for _ in range(4)
        )
        return RootInfoUctDecision(
            selected_action=selected,
            root_information_state_id=root_key,
            root_seat=root_seat,
            root_team=root_team,
            phase=observation.phase.value,
            configuration=configuration,
            decision_seed=decision_seed,
            simulation_budget=configuration.simulation_budget,
            simulations_completed=0,
            unique_sampled_worlds=0,
            feasible_world_count=0,
            root_action_visits=((canonical_action_id(selected), 0),),
            root_action_mean_utilities=((canonical_action_id(selected), 0.0),),
            selected_action_visit_share=0.0,
            selected_action_value_gap=0.0,
            root_information_set_nodes=0,
            maximum_tree_depth=0,
            node_revisit_count=0,
            cross_world_node_merge_count=0,
            rollout_policy_ids=policy_ids,
            showing_delegated=True,
            failures=(),
        )

    if observation.phase is not EnginePhase.TRICK_PLAY:
        raise RootInfoUctDecisionError("root-information UCT supports showing and trick play only")

    try:
        model = HardConstraintModel.build(observation)
        feasible_count = feasible_assignment_count(model)
        if feasible_count < 1:
            raise _failure(
                RootInfoUctFailureKind.SAMPLER_INCONSISTENCY,
                "hard public constraints admit no feasible hidden world",
            )
        sampler = UniformFeasibleSampler.build(
            model,
            seed=_world_sampling_seed(
                root_information_state_id=root_key,
                decision_seed=decision_seed,
            ),
        )
        assignments = sampler.sample(configuration.simulation_budget)
    except RootInfoUctDecisionError:
        raise
    except Exception as exc:  # noqa: BLE001 - classified and made fatal below
        raise _failure(
            RootInfoUctFailureKind.SAMPLER_INCONSISTENCY,
            f"Phase 5B sampler failed: {type(exc).__name__}: {exc}",
            exc,
        ) from exc

    tree = RootInfoUctTree()
    completed = 0
    for assignment in assignments:
        try:
            if _fast_path:
                simulation_state = FastTrickState.from_observation_assignment(
                    observation, assignment
                )
            else:
                from tuppi_exact import hypothetical_continuation

                simulation_state = hypothetical_continuation(observation, assignment).state
        except Exception as exc:  # noqa: BLE001 - classified and fatal
            raise _failure(
                RootInfoUctFailureKind.HYPOTHETICAL_CONSTRUCTION,
                f"hypothetical continuation failed: {type(exc).__name__}: {exc}",
                exc,
            ) from exc
        try:
            if _fast_path:
                _run_simulation_fast(
                    state=simulation_state,
                    root_seat=root_seat,
                    tree=tree,
                    configuration=configuration,
                )
            else:
                _run_simulation_authoritative(
                    state=simulation_state,
                    root_seat=root_seat,
                    tree=tree,
                    configuration=configuration,
                )
        except RootInfoUctDecisionError:
            raise
        except IllegalRolloutActionError as exc:
            raise _failure(
                RootInfoUctFailureKind.ROLLOUT_ILLEGAL_ACTION,
                str(exc),
                exc,
            ) from exc
        except RootInfoUctInvariantError as exc:
            raise _failure(RootInfoUctFailureKind.TREE_INVARIANT, str(exc), exc) from exc
        except MemoryError as exc:
            raise _failure(RootInfoUctFailureKind.RESOURCE_EXHAUSTION, str(exc), exc) from exc
        except EngineError as exc:
            raise _failure(RootInfoUctFailureKind.ENGINE_FAILURE, str(exc), exc) from exc
        except FastTrickError as exc:
            raise _failure(RootInfoUctFailureKind.ENGINE_FAILURE, str(exc), exc) from exc
        completed += 1

    root = tree.nodes.get(root_key)
    if root is None:
        raise _failure(
            RootInfoUctFailureKind.TREE_INVARIANT,
            "the initial root information node was never created",
        )
    selected = root.final_action(observation)
    visits = tuple((action_id, root.actions[action_id].visits) for action_id in root.action_ids)
    means = tuple((action_id, root.actions[action_id].mean_utility) for action_id in root.action_ids)
    selected_stats = root.actions[canonical_action_id(selected)]
    other_means = [
        root.actions[action_id].mean_utility
        for action_id in root.action_ids
        if action_id != canonical_action_id(selected)
    ]
    unique_worlds = len({world_identity(assignment) for assignment in assignments})
    total_visits = sum(value for _, value in visits)
    return RootInfoUctDecision(
        selected_action=selected,
        root_information_state_id=root_key,
        root_seat=root_seat,
        root_team=root_team,
        phase=observation.phase.value,
        configuration=configuration,
        decision_seed=decision_seed,
        simulation_budget=configuration.simulation_budget,
        simulations_completed=completed,
        unique_sampled_worlds=unique_worlds,
        feasible_world_count=feasible_count,
        root_action_visits=visits,
        root_action_mean_utilities=means,
        selected_action_visit_share=selected_stats.visits / total_visits if total_visits else 0.0,
        selected_action_value_gap=(
            selected_stats.mean_utility - max(other_means) if other_means else 0.0
        ),
        root_information_set_nodes=len(tree.nodes),
        maximum_tree_depth=tree.maximum_depth,
        node_revisit_count=tree.node_revisit_count,
        cross_world_node_merge_count=tree.cross_world_node_merge_count,
        rollout_policy_ids=tuple(
            "root_information_set_tree_v1"
            if seat == root_seat
            else _frozen_policy_specification(configuration.rollout_policy_key).agent_id
            for seat in range(4)
        ),
        showing_delegated=False,
        failures=(),
    )


class RootInfoUctAgent:
    """Deployable one-seat root-information UCT agent."""

    __slots__ = ("_agent_id", "_configuration", "_seat", "_policy_seed")

    def __init__(
        self,
        *,
        agent_id: str,
        configuration: RootInfoUctConfiguration,
        seat: int,
        policy_seed: str = "tuppi-phase5d-b-policy-seed-v1",
    ) -> None:
        if not isinstance(agent_id, str) or not agent_id.startswith("agent:"):
            raise RootInfoUctDecisionError("root-information UCT requires a canonical agent id")
        if not isinstance(configuration, RootInfoUctConfiguration):
            raise RootInfoUctDecisionError("root-information UCT requires its own configuration")
        if type(seat) is not int or seat not in range(4):
            raise RootInfoUctDecisionError("root seat must be an integer in 0..3")
        if not isinstance(policy_seed, str) or not policy_seed:
            raise RootInfoUctDecisionError("policy_seed must be a nonempty string")
        self._agent_id = agent_id
        self._configuration = configuration
        self._seat = seat
        self._policy_seed = policy_seed

    @property
    def identity(self) -> str:
        return self._agent_id

    @property
    def configuration(self) -> RootInfoUctConfiguration:
        return self._configuration

    @property
    def seat(self) -> int:
        return self._seat

    def decision_seed(self, observation: PlayerObservation) -> str:
        if not isinstance(observation, PlayerObservation):
            raise RootInfoUctDecisionError("decision_seed requires a PlayerObservation")
        if observation.observing_seat != self._seat:
            raise RootInfoUctDecisionError("agent received another seat's observation")
        return _decision_seed(
            root_information_state_id=root_information_state_key(observation),
            policy_seed=self._policy_seed,
            seat=self._seat,
        )

    def decide(self, observation: PlayerObservation) -> RootInfoUctDecision:
        if not isinstance(observation, PlayerObservation):
            raise RootInfoUctDecisionError("root-information UCT requires a PlayerObservation")
        if observation.observing_seat != self._seat:
            raise RootInfoUctDecisionError("agent received another seat's observation")
        return decide(
            observation,
            configuration=self._configuration,
            decision_seed=self.decision_seed(observation),
        )

    def choose_action(self, observation: PlayerObservation) -> Action:
        return self.decide(observation).selected_action

    def explain(self, observation: PlayerObservation) -> RootInfoUctDecision:
        return self.decide(observation)


def construct_root_info_uct_agent(
    specification: AgentSpecification,
    *,
    seat: int,
    configuration: RootInfoUctConfiguration,
    policy_seed: str = "tuppi-phase5d-b-policy-seed-v1",
) -> RootInfoUctAgent:
    """Construct a root-information UCT agent from its immutable specification."""

    if not isinstance(specification, AgentSpecification):
        raise RootInfoUctDecisionError("construct_root_info_uct_agent requires an AgentSpecification")
    if specification.configuration.get("root_info_uct_configuration_id") != configuration.configuration_id:
        raise RootInfoUctDecisionError("specification and root-information configuration disagree")
    return RootInfoUctAgent(
        agent_id=specification.agent_id,
        configuration=configuration,
        seat=seat,
        policy_seed=policy_seed,
    )
