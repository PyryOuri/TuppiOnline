"""Classical root Perfect-Information Monte Carlo over uniform feasible worlds.

The algorithm, exactly as implemented:

1. Take the acting seat's :class:`PlayerObservation` and nothing else.
2. Enumerate its legal actions in the engine's canonical order.
3. Build the Phase 5B hard constraint set and one indexed set of uniformly sampled
   feasible worlds. **The world set is built before any candidate is considered**
   and is shared by all of them.
4. For every candidate, for every world index: apply the candidate to that world,
   then complete the deal with observation-only rollout policies (optionally
   handing the endgame to the Phase 5B exact solver).
5. Score each completed outcome for the *root team* through one versioned utility
   adapter.
6. Average per candidate, select the highest mean, break exact ties by lowest
   canonical legal-action index.

What this is not
----------------

This is a PIMC baseline. It is **not** an equilibrium solver and must not be
described as optimal imperfect-information play. Every sampled world is solved or
rolled out as if all four hands were common knowledge, and the averaging happens
afterwards, so PIMC can combine strategies that are individually sensible in one
world and mutually incompatible across worlds. That is *strategy fusion*, it is
structural, and no number of samples removes it - more samples only shrink Monte
Carlo error around the fused value. See `docs/search/uniform_feasible_pimc.md`.

One ply, deliberately
---------------------

After the forced root action, every seat - including the root seat's own later
turns - plays the configured rollout policy. The PIMC agent is never invoked
recursively inside its own rollout. Anything else would be a different algorithm
with a different cost and a different name.

The single-legal-action shortcut
--------------------------------

When the observation offers exactly one legal action, that action is returned
without sampling. This cannot change what is played - there is nothing to choose -
and it matters in practice: 24 % of trick-play decisions in measured deals are
forced. The shortcut is recorded in diagnostics and
:mod:`tests.search.test_pimc_core` verifies that disabling it selects the same
action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import statistics

from tuppi_engine import (
    Action,
    PlayerObservation,
    apply_action,
)
from tuppi_engine.errors import EngineError
from tuppi_rules import Team, team_for_seat

from .config import PimcConfiguration
from .errors import PimcDecisionError, RolloutError, SearchError
from .exact_tail import ExactTail
from .random import (
    SearchSeedHierarchy,
    canonical_action_id,
    information_state_digest,
)
from .rollout import SeatPolicies, complete_deal
from .utilities import utility_value
from .worlds import SampledWorldSet, WorldSetMode, build_world_set


PIMC_DECISION_SCHEMA_VERSION = "tuppi.search.pimc_decision.v1"


@dataclass(frozen=True, slots=True)
class WorldEvaluation:
    """One (candidate, world, replica) evaluation."""

    sample_index: int
    replica: int
    utility: float
    exact_tail_used: bool
    actions_simulated: int
    solver_calls: int
    solver_nodes: int
    root_team_wins_deal: bool
    match_terminal: bool


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    """The aggregate value of one legal root action over the common world set."""

    action: Action
    action_id: str
    action_order_index: int
    evaluations: int
    unique_worlds: int
    mean_utility: float
    standard_deviation: float
    standard_error: float
    minimum: float
    maximum: float
    median: float
    lower_quartile: float
    upper_quartile: float
    root_team_deal_wins: int
    match_terminal_outcomes: int
    exact_tail_evaluations: int
    solver_calls: int
    solver_nodes: int
    actions_simulated: int
    failures: int
    schema_version: str = field(default=PIMC_DECISION_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.evaluations <= 0:
            raise PimcDecisionError(
                "a candidate summary requires at least one completed evaluation"
            )
        if self.failures:
            raise PimcDecisionError(
                "a candidate summary must not be built from a failed evaluation set"
            )

    @property
    def exact_tail_rate(self) -> float:
        return self.exact_tail_evaluations / self.evaluations

    @property
    def root_team_deal_win_rate(self) -> float:
        return self.root_team_deal_wins / self.evaluations

    def to_data(self) -> dict[str, object]:
        return {
            "action": self.action_id,
            "action_order_index": self.action_order_index,
            "actions_simulated": self.actions_simulated,
            "evaluations": self.evaluations,
            "exact_tail_evaluations": self.exact_tail_evaluations,
            "exact_tail_rate": round(self.exact_tail_rate, 6),
            "failures": self.failures,
            "lower_quartile": round(self.lower_quartile, 9),
            "match_terminal_outcomes": self.match_terminal_outcomes,
            "maximum": round(self.maximum, 9),
            "mean_utility": round(self.mean_utility, 9),
            "median": round(self.median, 9),
            "minimum": round(self.minimum, 9),
            "root_team_deal_win_rate": round(self.root_team_deal_win_rate, 6),
            "root_team_deal_wins": self.root_team_deal_wins,
            "solver_calls": self.solver_calls,
            "solver_nodes": self.solver_nodes,
            "standard_deviation": round(self.standard_deviation, 9),
            "standard_error": round(self.standard_error, 9),
            "unique_worlds": self.unique_worlds,
            "upper_quartile": round(self.upper_quartile, 9),
        }


@dataclass(frozen=True, slots=True)
class PimcDecision:
    """The complete result of one PIMC decision."""

    selected_action: Action
    selected_index: int
    root_seat: int
    root_team: Team
    phase: str
    candidates: tuple[CandidateSummary, ...]
    world_set: SampledWorldSet | None
    configuration: PimcConfiguration
    information_state: str
    decision_seed: str
    single_legal_action_shortcut: bool
    schema_version: str = field(default=PIMC_DECISION_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.candidates:
            raise PimcDecisionError("a decision requires at least one candidate")
        if self.selected_index not in range(len(self.candidates)):
            raise PimcDecisionError("selected_index is out of range")
        if self.candidates[self.selected_index].action != self.selected_action:
            raise PimcDecisionError("selected_index disagrees with selected_action")
        if not self.single_legal_action_shortcut:
            best = _best_index(self.candidates)
            if best != self.selected_index:
                raise PimcDecisionError(
                    "selected_index is not the deterministic tie-broken maximum"
                )

    @property
    def selected_value(self) -> float:
        return self.candidates[self.selected_index].mean_utility

    @property
    def selection_gap(self) -> float:
        """Mean-utility distance from the selected action to the runner-up.

        Zero when a tie was broken by canonical order, which is the signal that the
        sample could not separate the top actions.
        """

        if len(self.candidates) == 1:
            return 0.0
        others = [
            item.mean_utility
            for index, item in enumerate(self.candidates)
            if index != self.selected_index
        ]
        return self.selected_value - max(others)


def _best_index(candidates: tuple[CandidateSummary, ...]) -> int:
    """Highest mean utility, then lowest canonical legal-action index.

    No confidence bonus, no variance term. Both were considered and rejected: an
    unrecorded exploration bonus would make the agent's behaviour depend on a
    constant nobody registered, and a variance preference is only defensible if it
    is preregistered and named in the identity.
    """

    best = max(
        candidates,
        key=lambda item: (item.mean_utility, -item.action_order_index),
    )
    return best.action_order_index


def decide(
    observation: PlayerObservation,
    *,
    configuration: PimcConfiguration,
    decision_seed: str,
    world_set_mode: WorldSetMode = WorldSetMode.UNIFORM_SAMPLING,
    use_single_action_shortcut: bool = True,
    reuse_world_set: SampledWorldSet | None = None,
) -> PimcDecision:
    """Run one complete PIMC decision from one observation.

    ``reuse_world_set`` exists for the action-stability study, which evaluates
    nested prefixes of one world set. It is never used by a deployed agent, and it
    cannot smuggle information in: a reused set is checked to belong to the same
    information state.
    """

    if not isinstance(observation, PlayerObservation):
        raise PimcDecisionError("PIMC requires a PlayerObservation")
    if not isinstance(configuration, PimcConfiguration):
        raise PimcDecisionError("PIMC requires a PimcConfiguration")
    if not isinstance(decision_seed, str) or not decision_seed:
        raise PimcDecisionError("PIMC requires a nonempty decision seed")
    legal = observation.legal_actions
    if not legal:
        raise PimcDecisionError("the observation offers no legal action")
    if observation.current_actor != observation.observing_seat:
        raise PimcDecisionError(
            "PIMC may only decide for the acting seat's own observation"
        )

    root_seat = observation.observing_seat
    root_team = team_for_seat(root_seat)
    state_digest = information_state_digest(observation)
    seeds = SearchSeedHierarchy(
        pimc_protocol=configuration.pimc_protocol_version,
        information_state=state_digest,
        decision_seed=decision_seed,
    )

    if use_single_action_shortcut and len(legal) == 1:
        return PimcDecision(
            selected_action=legal[0],
            selected_index=0,
            root_seat=root_seat,
            root_team=root_team,
            phase=observation.phase.value,
            candidates=(_forced_summary(legal[0]),),
            world_set=None,
            configuration=configuration,
            information_state=state_digest,
            decision_seed=decision_seed,
            single_legal_action_shortcut=True,
        )

    if not configuration.showing_search_enabled and observation.phase.value == (
        "SHOWING"
    ):
        raise PimcDecisionError(
            "this configuration disables showing search, so it must not be asked "
            "for a showing decision"
        )

    if reuse_world_set is not None:
        if reuse_world_set.information_state != state_digest:
            raise PimcDecisionError(
                "a reused world set belongs to a different information state"
            )
        world_set = reuse_world_set
    else:
        world_set = build_world_set(
            observation,
            configuration=configuration,
            seeds=seeds,
            mode=world_set_mode,
        )

    tail = ExactTail.from_configuration(configuration)
    policies = SeatPolicies(configuration=configuration, root_seat=root_seat)

    summaries: list[CandidateSummary] = []
    for order_index, action in enumerate(legal):
        summaries.append(
            _evaluate_candidate(
                observation=observation,
                action=action,
                action_order_index=order_index,
                world_set=world_set,
                configuration=configuration,
                policies=policies,
                tail=tail,
                root_seat=root_seat,
            )
        )
    candidates = tuple(summaries)
    selected_index = _best_index(candidates)
    return PimcDecision(
        selected_action=candidates[selected_index].action,
        selected_index=selected_index,
        root_seat=root_seat,
        root_team=root_team,
        phase=observation.phase.value,
        candidates=candidates,
        world_set=world_set,
        configuration=configuration,
        information_state=state_digest,
        decision_seed=decision_seed,
        single_legal_action_shortcut=False,
    )


def _forced_summary(action: Action) -> CandidateSummary:
    """The summary of a decision that had no alternative.

    The utility is reported as zero and explicitly carries one evaluation, because
    inventing a value for an unsearched action would be worse than reporting that
    no search happened.
    """

    return CandidateSummary(
        action=action,
        action_id=canonical_action_id(action),
        action_order_index=0,
        evaluations=1,
        unique_worlds=0,
        mean_utility=0.0,
        standard_deviation=0.0,
        standard_error=0.0,
        minimum=0.0,
        maximum=0.0,
        median=0.0,
        lower_quartile=0.0,
        upper_quartile=0.0,
        root_team_deal_wins=0,
        match_terminal_outcomes=0,
        exact_tail_evaluations=0,
        solver_calls=0,
        solver_nodes=0,
        actions_simulated=0,
        failures=0,
    )


def _evaluate_candidate(
    *,
    observation: PlayerObservation,
    action: Action,
    action_order_index: int,
    world_set: SampledWorldSet,
    configuration: PimcConfiguration,
    policies: SeatPolicies,
    tail: ExactTail | None,
    root_seat: int,
) -> CandidateSummary:
    """Evaluate one candidate on every world of the common set."""

    evaluations: list[WorldEvaluation] = []
    for world in world_set.worlds:
        try:
            forced = apply_action(world.state, action)
        except EngineError as exc:
            raise PimcDecisionError(
                f"candidate {canonical_action_id(action)} is illegal in sampled "
                f"world {world.sample_index}, which a valid hard-feasible world "
                f"cannot be: {type(exc).__name__}: {exc}"
            ) from exc
        for replica in range(configuration.rollout_replicas):
            try:
                outcome = complete_deal(
                    forced,
                    policies=policies,
                    root_seat=root_seat,
                    exact_tail=tail,
                    actions_already_simulated=1,
                )
            except (RolloutError, SearchError) as exc:
                raise PimcDecisionError(
                    f"world {world.sample_index} replica {replica} failed for "
                    f"candidate {canonical_action_id(action)}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            summary = outcome.summary
            evaluations.append(
                WorldEvaluation(
                    sample_index=world.sample_index,
                    replica=replica,
                    utility=utility_value(configuration.utility_id, summary),
                    exact_tail_used=outcome.exact_tail_used,
                    actions_simulated=outcome.actions_simulated,
                    solver_calls=outcome.solver_calls,
                    solver_nodes=outcome.solver_nodes,
                    root_team_wins_deal=summary.root_team_wins_deal,
                    match_terminal=bool(summary.to_data()["match_terminal"]),
                )
            )
    return _aggregate(
        action=action,
        action_order_index=action_order_index,
        evaluations=tuple(evaluations),
        unique_worlds=world_set.unique_world_count,
    )


def _aggregate(
    *,
    action: Action,
    action_order_index: int,
    evaluations: tuple[WorldEvaluation, ...],
    unique_worlds: int,
) -> CandidateSummary:
    """Aggregate one candidate's evaluations.

    Aggregation is order-invariant by construction: every statistic below is a
    function of the multiset of utilities, so the order in which worlds completed -
    which a worker pool does not guarantee - cannot change the result.
    """

    if not evaluations:
        raise PimcDecisionError("a candidate produced no evaluation")
    values = sorted(item.utility for item in evaluations)
    count = len(values)
    mean = math.fsum(values) / count
    deviation = statistics.pstdev(values) if count > 1 else 0.0
    return CandidateSummary(
        action=action,
        action_id=canonical_action_id(action),
        action_order_index=action_order_index,
        evaluations=count,
        unique_worlds=unique_worlds,
        mean_utility=mean,
        standard_deviation=deviation,
        standard_error=deviation / math.sqrt(count) if count > 1 else 0.0,
        minimum=values[0],
        maximum=values[-1],
        median=_quantile(values, 0.5),
        lower_quartile=_quantile(values, 0.25),
        upper_quartile=_quantile(values, 0.75),
        root_team_deal_wins=sum(1 for item in evaluations if item.root_team_wins_deal),
        match_terminal_outcomes=sum(1 for item in evaluations if item.match_terminal),
        exact_tail_evaluations=sum(1 for item in evaluations if item.exact_tail_used),
        solver_calls=sum(item.solver_calls for item in evaluations),
        solver_nodes=sum(item.solver_nodes for item in evaluations),
        actions_simulated=sum(item.actions_simulated for item in evaluations),
        failures=0,
    )


def _quantile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise PimcDecisionError("a quantile needs at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = probability * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
