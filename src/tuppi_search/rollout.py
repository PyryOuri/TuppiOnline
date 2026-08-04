"""Observation-only continuation of a hypothetical world.

The rollout is where Phase 5C could most easily cheat, so it is built so that
cheating is not expressible. At every simulated decision the loop does exactly
three things:

1. project the hypothetical :class:`DealState` to the acting seat's
   :class:`PlayerObservation` using the engine's own ``observation_for``;
2. hand **only that observation** to the rollout policy;
3. apply the returned action through the engine's ``apply_action``, which
   validates it against the rules.

The policy never receives the hypothetical state, so a rollout policy physically
cannot see the cards the sampler placed in the other seats. That is not a
convention to be respected; the state is never passed, and
:mod:`tests.search.test_rollout_security` asserts it by recording every argument
the policy is called with.

Why the engine validates every action
-------------------------------------

An illegal action from a rollout policy is never repaired. Substituting a legal
card would hide the defect and quietly change the estimator; the legacy emulator
did exactly that and Phase 0B recorded it as a fidelity failure. Here it raises
:class:`IllegalRolloutActionError` and invalidates the decision.

Cost
----

``apply_action`` revalidates the whole deal state on every transition, so a
rollout is O(remaining actions x history length). Measured: 86 ms from a showing
root, 36 ms with four tricks left, roughly 6.8 ms per remaining trick. That figure
is the reason Phase 5C's world budgets are small, and it is reported rather than
worked around: the validation is what makes a rollout trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
from tuppi_rules import TRICKS_PER_DEAL

from .config import PimcConfiguration, RootContinuation
from .errors import IllegalRolloutActionError, RolloutError
from .utilities import (
    DealOutcomeSummary,
    OutcomeSource,
    summary_from_completed_deal,
)


ROLLOUT_SCHEMA_VERSION = "tuppi.search.rollout.v1"

#: A deal is at most 4 showing actions plus 52 card plays. The bound exists only to
#: turn a hypothetical non-terminating loop into an explicit error.
MAXIMUM_ROLLOUT_ACTIONS = 4 + 4 * TRICKS_PER_DEAL


@dataclass(frozen=True, slots=True)
class RolloutOutcome:
    """The result of completing one hypothetical world."""

    summary: DealOutcomeSummary
    actions_simulated: int
    exact_tail_used: bool
    solver_calls: int
    solver_nodes: int
    schema_version: str = field(default=ROLLOUT_SCHEMA_VERSION, init=False)


class SeatPolicies:
    """Four distinct runtime rollout agents, one per seat.

    Distinct objects per seat, never shared: a shared object could accumulate
    state across seats and make one simulated partner's decision depend on the
    other's, which is exactly the coupling a partnership convention must not get
    for free.

    Fresh agents are constructed per rollout rather than reused across rollouts.
    Phase 4 policies are stateless, so reuse would be safe today; constructing
    fresh costs about 0.2 % of a rollout and removes the need to rely on that.
    """

    __slots__ = ("_specifications", "_root_seat", "_root_specification")

    def __init__(
        self, *, configuration: PimcConfiguration, root_seat: int
    ) -> None:
        if not isinstance(configuration, PimcConfiguration):
            raise RolloutError("SeatPolicies requires a PimcConfiguration")
        if type(root_seat) is not int or root_seat not in range(4):
            raise RolloutError("root_seat must be an integer in 0..3")
        specifications = phase4_specifications_by_profile_key()
        try:
            self._specifications = specifications[configuration.rollout_policy_key]
        except KeyError as exc:  # pragma: no cover - config validates the key
            raise RolloutError(
                f"unknown rollout policy {configuration.rollout_policy_key!r}"
            ) from exc
        self._root_seat = root_seat
        if configuration.root_continuation is RootContinuation.ROLLOUT_POLICY:
            self._root_specification = self._specifications
        else:
            self._root_specification = specifications[
                str(configuration.root_rollout_policy_key)
            ]

    def build(self) -> tuple:
        agents = tuple(
            construct_agent(
                self._root_specification
                if seat == self._root_seat
                else self._specifications,
                seat=seat,
            )
            for seat in range(4)
        )
        if len({id(agent) for agent in agents}) != 4:
            raise RolloutError("rollout constructed a shared runtime agent object")
        return agents

    @property
    def policy_agent_ids(self) -> tuple[str, ...]:
        return tuple(
            (
                self._root_specification.agent_id
                if seat == self._root_seat
                else self._specifications.agent_id
            )
            for seat in range(4)
        )


def complete_deal(
    state: DealState,
    *,
    policies: SeatPolicies,
    root_seat: int,
    exact_tail=None,
    actions_already_simulated: int = 0,
) -> RolloutOutcome:
    """Play a hypothetical deal to completion, or to the exact tail.

    ``exact_tail`` is an optional :class:`tuppi_search.exact_tail.ExactTail`. When
    supplied it is consulted *before* each trick-play decision, so a forced root
    action that itself brings the position into range is handled by the same check
    as a position reached later in the rollout.
    """

    if not isinstance(state, DealState):
        raise RolloutError("complete_deal requires a DealState")
    if not isinstance(policies, SeatPolicies):
        raise RolloutError("complete_deal requires SeatPolicies")
    agents = policies.build()
    simulated = actions_already_simulated
    solver_calls = 0
    solver_nodes = 0

    while not state.complete:
        if simulated > MAXIMUM_ROLLOUT_ACTIONS:
            raise RolloutError(
                "rollout exceeded the maximum possible action count for a deal"
            )
        if exact_tail is not None and state.phase is EnginePhase.TRICK_PLAY:
            verdict = exact_tail.consider(state, root_seat=root_seat)
            if verdict is not None:
                solver_calls += verdict.solver_calls
                solver_nodes += verdict.solver_nodes
                if verdict.summary is not None:
                    return RolloutOutcome(
                        summary=verdict.summary,
                        actions_simulated=simulated,
                        exact_tail_used=True,
                        solver_calls=solver_calls,
                        solver_nodes=solver_nodes,
                    )
        actor = state.current_actor
        if actor is None:
            raise RolloutError("a nonterminal hypothetical state has no acting seat")
        observation = observation_for(state, actor)
        action = _choose(agents[actor], observation, actor)
        try:
            state = apply_action(state, action)
        except EngineError as exc:
            raise IllegalRolloutActionError(
                f"rollout policy at seat {actor} proposed an action the engine "
                f"rejected: {type(exc).__name__}: {exc}"
            ) from exc
        simulated += 1

    if len(state.completed_tricks) != TRICKS_PER_DEAL:
        raise RolloutError(
            f"a completed rollout must contain {TRICKS_PER_DEAL} tricks, not "
            f"{len(state.completed_tricks)}"
        )
    return RolloutOutcome(
        summary=summary_from_completed_deal(
            state,
            root_seat=root_seat,
            source=OutcomeSource.ROLLOUT,
            tricks_simulated=TRICKS_PER_DEAL,
        ),
        actions_simulated=simulated,
        exact_tail_used=False,
        solver_calls=solver_calls,
        solver_nodes=solver_nodes,
    )


def _choose(agent, observation: PlayerObservation, actor: int) -> Action:
    """Ask one rollout policy for an action, passing only its observation."""

    if not isinstance(observation, PlayerObservation):  # pragma: no cover
        raise RolloutError("rollout projection produced a non-observation")
    action = agent.choose_action(observation)
    if action is None:
        raise IllegalRolloutActionError(
            f"rollout policy at seat {actor} returned no action"
        )
    if getattr(action, "seat", None) != actor:
        raise IllegalRolloutActionError(
            f"rollout policy at seat {actor} returned an action for another seat"
        )
    if action not in observation.legal_actions:
        raise IllegalRolloutActionError(
            f"rollout policy at seat {actor} returned an action outside the legal "
            "set the engine offered it"
        )
    return action
