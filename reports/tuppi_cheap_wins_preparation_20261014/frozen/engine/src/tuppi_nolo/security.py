"""N04: an information-legal security continuation for one controlled seat.

The controlled seat commits to **one** action per information key. Every other
seat, partner included, is quantified over arbitrary legal actions. That is a
robust guarantee, not the cooperative team value and not an equilibrium: an
unhelpful partner is inside the model on purpose.

Why per-world minimisation is invalid, in one line: choosing separately in each
world lets the plan use information the seat does not have, so its value can
beat anything actually achievable. The recursion below therefore intersects
legal actions across an information class and picks a single action for the
class, while the adversary is free to differentiate.

    terminal:     V(S) = max own-team final tricks over S
    root's turn:  V(S) = min over actions legal in *every* state of S
    other turn:   V(S) = max over the union of legal actions, each filtered to
                  exactly the states where it is legal

``solve_late_game`` is deliberately not used: it sees the hidden hands and
assumes a cooperating partner, which is a different objective.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from tuppi_agents.void_lead import void_seeking_agents
from tuppi_engine import EnginePhase, PlayCardAction, PlayerObservation, apply_action
from tuppi_engine import observation_for

from .certificates import (
    OBJECTIVE,
    Certificate,
    CheckResult,
    ClaimType,
    CompletenessProvenance,
    ControlModel,
    PlanEntry,
    complete_support_digest,
    verify_certificate,
)
from .support import (
    SupportBudget,
    SupportResult,
    SupportStatus,
    build_support,
    semantic_observation_key,
)


class SecurityStatus(str, Enum):
    EXACT_COMPLETE = "EXACT_COMPLETE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SUPPORT_BUDGET = "SUPPORT_BUDGET"
    SEARCH_BUDGET = "SEARCH_BUDGET"
    INVALID_INPUT = "INVALID_INPUT"


class SecurityInvariantError(RuntimeError):
    """The search and its own exported plan disagree; never reported as noise."""


@dataclass(frozen=True, slots=True, order=True)
class RootValue:
    """One root action and the worst-case own total it can guarantee."""

    action: PlayCardAction = field(compare=False)
    security_value: int


@dataclass(frozen=True, slots=True)
class SecurityResult:
    status: SecurityStatus
    information_key: str | None
    root_values: tuple[RootValue, ...]
    selected_action: PlayCardAction | None
    plan: tuple[PlanEntry, ...]
    certificate: Certificate | None
    verification: CheckResult | None
    world_count: int | None
    search_engine_transitions: int
    verification_engine_transitions: int
    nodes_visited: int
    reason: str | None = None

    def diagnostics(self) -> dict:
        """Policy-safe explanation. Carries no world, hand or private path."""

        return {
            "status": self.status.value,
            "information_key": self.information_key,
            "objective": OBJECTIVE,
            "control_model": ControlModel.SINGLE_SEAT.value,
            "root_values": [
                {"action": str(v.action.card), "security_value": v.security_value}
                for v in self.root_values
            ],
            "selected_action": (
                None if self.selected_action is None else str(self.selected_action.card)
            ),
            "plan_size": len(self.plan),
            "world_count": self.world_count,
            "search_engine_transitions": self.search_engine_transitions,
            # Reported apart from the search: a caller's verification budget is
            # never free computation.
            "verification_engine_transitions": self.verification_engine_transitions,
            "nodes_visited": self.nodes_visited,
            "verifier_status": (
                None if self.verification is None else self.verification.status.value
            ),
            "claim_type": ClaimType.UNCLASSIFIED.value,
            "fallback_reason": self.reason,
        }


class _Budget(Exception):
    """Raised inward when the operation's transition allowance is spent."""


class _Meter:
    def __init__(self, limit: int, already_used: int) -> None:
        self.limit = limit
        self.calls = already_used
        self.nodes = 0

    def step(self, state, action):
        if self.calls >= self.limit:
            raise _Budget
        self.calls += 1
        return apply_action(state, action)


def _terminal_value(states, team: int) -> int:
    """Worst case inside the class: nature keeps the least favourable world."""

    return max(state.team_tricks[team] for state in states)


def _ranked_actions(agent, observation) -> tuple[PlayCardAction, ...]:
    """The inherited v2 preference order, used only to settle exact ties."""

    ranking = agent.decide(observation, diagnostics=False).scored
    return tuple(
        item.action for item in ranking.ranked() if isinstance(item.action, PlayCardAction)
    )


def _preference_index(order: tuple[PlayCardAction, ...], action: PlayCardAction) -> int:
    try:
        return order.index(action)
    except ValueError:
        return len(order)


def _search(states, *, seat: int, team: int, meter: _Meter, agents) -> tuple[int, dict]:
    """Value of one information class, and the own plan achieving it.

    ``states`` are the hypothetical states of every world still compatible with
    the public history. They necessarily share a current actor and, at an own
    turn, a single information key.
    """

    meter.nodes += 1
    if states[0].phase is not EnginePhase.TRICK_PLAY:
        return _terminal_value(states, team), {}

    actor = states[0].current_actor
    if actor != seat:
        # Every other seat, partner included, may do anything legal. Each public
        # action keeps exactly the worlds in which it was available.
        union: dict = {}
        for state in states:
            for action in observation_for(state, actor).legal_actions:
                union.setdefault(action, []).append(state)
        worst = -1
        merged: dict = {}
        for action, subset in union.items():
            successors = tuple(meter.step(state, action) for state in subset)
            value, plan = _search(
                successors, seat=seat, team=team, meter=meter, agents=agents
            )
            worst = max(worst, value)
            # Every adversary branch is reachable, so all of their own-plan
            # entries belong in the exported plan.
            for key, chosen in plan.items():
                if merged.setdefault(key, chosen) != chosen:
                    raise SecurityInvariantError(
                        "two reachable branches demand different actions at one key"
                    )
        return worst, merged

    # The controlled seat. Partition defensively: distinct observation classes
    # are distinct decisions, and nature picks the worst of them.
    classes: dict = {}
    for state in states:
        observation = observation_for(state, seat)
        classes.setdefault(semantic_observation_key(observation), []).append(
            (state, observation)
        )

    worst = -1
    merged = {}
    for key, members in classes.items():
        common = set(members[0][1].legal_actions)
        for _state, observation in members[1:]:
            common &= set(observation.legal_actions)
        if not common:
            raise SecurityInvariantError("an information class shares no legal action")
        order = _ranked_actions(agents[seat], members[0][1])
        best_value = None
        best_action = None
        best_plan: dict = {}
        # One action for the whole class. Never minimise per world.
        for action in sorted(common, key=lambda a: _preference_index(order, a)):
            successors = tuple(meter.step(state, action) for state, _obs in members)
            value, plan = _search(
                successors, seat=seat, team=team, meter=meter, agents=agents
            )
            if best_value is None or value < best_value:
                best_value, best_action, best_plan = value, action, plan
        for key_inner, chosen in best_plan.items():
            if merged.setdefault(key_inner, chosen) != chosen:
                raise SecurityInvariantError(
                    "two reachable branches demand different actions at one key"
                )
        # A forced action still belongs in the plan only if the verifier will
        # look for it; it consults every own node, so record every one.
        merged[key] = best_action
        worst = max(worst, best_value)
    return worst, merged


def _search_cached(states, *, seat, team, meter, agents, cache, root_key):
    """The memoised equivalent of :func:`_search`, in two passes.

    Values first, which is where repetition can be exploited, then a plan
    rebuilt for this history from the cached optimal sets. The tie rule is
    re-applied here rather than cached, so the chosen action matches the plain
    search rather than whichever history happened to fill the entry.
    """

    from .cache import extract_plan, search_value

    def prefer(observation, optimal):
        order = _ranked_actions(agents[seat], observation)
        return min(optimal, key=lambda a: _preference_index(order, a))

    value, _optimal = search_value(
        states, seat=seat, team=team, meter=meter, cache=cache, root_key=root_key
    )
    plan = extract_plan(
        states, seat=seat, team=team, meter=meter, cache=cache,
        root_key=root_key, prefer=prefer,
    )
    return value, plan


def solve_security(
    observation: PlayerObservation,
    budget: SupportBudget,
    *,
    verification_budget: SupportBudget | None = None,
    cache=None,
) -> SecurityResult:
    """Return every root action's security value, a plan, and its verification.

    The plan is checked by N03's independent verifier rather than trusted. The
    verification runs on its own budget and is reported separately, so it is
    never presented as free computation.

    Passing a ``SecurityCache`` selects the N06 memoised path. It must agree
    with the plain path on every value, label and action; the uncached search
    below stays the independent reference and remains the default.
    """

    if not isinstance(observation, PlayerObservation):
        raise TypeError("solve_security requires PlayerObservation, not a private state")
    if not isinstance(budget, SupportBudget):
        raise TypeError("solve_security requires SupportBudget")

    key = semantic_observation_key(observation)

    def unresolved(status: SecurityStatus, reason: str, used: int, nodes: int = 0):
        return SecurityResult(
            status, key, (), None, (), None, None, None, used, 0, nodes, reason
        )

    if observation.current_actor != observation.observing_seat:
        return unresolved(
            SecurityStatus.INVALID_INPUT, "root observer must be the acting seat", 0
        )

    support = build_support(observation, budget)
    if support.status is not SupportStatus.EXACT_COMPLETE:
        return unresolved(
            SecurityStatus(support.status.value),
            support.reason,
            support.engine_transitions,
        )

    seat = observation.observing_seat
    team = seat % 2
    agents = void_seeking_agents()
    meter = _Meter(budget.max_engine_transitions, support.engine_transitions)
    roots = tuple(
        action for action in observation.legal_actions if isinstance(action, PlayCardAction)
    )
    order = _ranked_actions(agents[seat], observation)

    values: list[RootValue] = []
    plans: dict = {}
    try:
        for action in roots:
            successors = tuple(
                meter.step(world.continuation.state, action)
                for world in support.research_worlds
            )
            if cache is None:
                value, plan = _search(
                    successors, seat=seat, team=team, meter=meter, agents=agents
                )
            else:
                value, plan = _search_cached(
                    successors, seat=seat, team=team, meter=meter,
                    agents=agents, cache=cache, root_key=key,
                )
            values.append(RootValue(action, value))
            plans[action] = plan
    except _Budget:
        return unresolved(
            SecurityStatus.SEARCH_BUDGET,
            "engine transition limit during security search",
            meter.calls,
            meter.nodes,
        )

    best = min(v.security_value for v in values)
    selected = min(
        (v for v in values if v.security_value == best),
        key=lambda v: _preference_index(order, v.action),
    ).action

    plan = tuple(
        PlanEntry(information_key=k, action=a) for k, a in sorted(plans[selected].items())
    )
    certificate = Certificate(
        source_information_key=key,
        root_seat=seat,
        root_action=selected,
        objective=OBJECTIVE,
        control_model=ControlModel.SINGLE_SEAT,
        complete_support_digest=complete_support_digest(support),
        plan=plan,
        claimed_terminal_bound=best,
        provenance=CompletenessProvenance(
            support_status=support.status,
            world_count=support.world_count,
            generation_budget=budget,
            generation_engine_transitions=support.engine_transitions,
        ),
    )
    checking = verification_budget or budget
    verification = verify_certificate(observation, certificate, checking)

    return SecurityResult(
        status=SecurityStatus.EXACT_COMPLETE,
        information_key=key,
        root_values=tuple(values),
        selected_action=selected,
        plan=plan,
        certificate=certificate,
        verification=verification,
        world_count=support.world_count,
        search_engine_transitions=meter.calls,
        verification_engine_transitions=verification.engine_transitions,
        nodes_visited=meter.nodes,
        reason=None,
    )
