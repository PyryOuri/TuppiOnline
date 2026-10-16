"""Immutable match coordination around one explicit deal at a time."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from tuppi_rules import (
    SUPPORTED_RULESETS,
    MatchScore,
    RulesetId,
    Team,
    is_match_terminal,
    match_winner,
    validate_seat,
)

from .actions import Action
from .agents import Agent
from .deal import ExplicitDeal, create_deal_state
from .errors import (
    AgentProtocolError,
    DealSequenceError,
    InvalidConstructionError,
    StateInvariantError,
    TerminalStateError,
    WrongPhaseError,
)
from .events import PublicEvent
from .observations import PlayerObservation, _observation_for_validated
from .results import DealResult, MatchResult, ResearchDealResult
from .state import ACTIVE_PHASES, DealState, EnginePhase, validate_deal_state
from .trusted import is_trusted
from .transitions import _apply_action_validated, research_deal_result_from_state
from .validation import is_valid_match_ref


@dataclass(frozen=True, slots=True)
class MatchState:
    match_ref: str
    initial_score: MatchScore
    initial_dealer: int
    score: MatchScore
    dealer: int
    phase: EnginePhase
    active_deal: DealState | None
    completed_deals: tuple[ResearchDealResult, ...]
    public_events: tuple[PublicEvent, ...]
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1

    def __post_init__(self) -> None:
        # Implicit revalidation of a state this engine just produced. Elided
        # inside ``trusted.trusted_transitions``; see that module.
        if not is_trusted():
            _validate_match_state(self)

    @property
    def current_actor(self) -> int | None:
        return None if self.active_deal is None else self.active_deal.current_actor

    @property
    def terminal(self) -> bool:
        return self.phase is EnginePhase.MATCH_COMPLETE


def create_match(
    *,
    initial_score: MatchScore,
    initial_dealer: int,
    match_ref: str,
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1,
) -> MatchState:
    if not isinstance(initial_score, MatchScore):
        raise InvalidConstructionError("initial_score must be a MatchScore")
    try:
        checked_score = MatchScore(initial_score.team0, initial_score.team1)
    except ValueError as exc:
        raise InvalidConstructionError(f"invalid initial_score: {exc}") from exc
    if is_match_terminal(checked_score):
        raise InvalidConstructionError("match cannot start from a terminal score")
    try:
        dealer = validate_seat(initial_dealer)
    except ValueError as exc:
        raise InvalidConstructionError("initial_dealer must be an integer in 0..3") from exc
    if not is_valid_match_ref(match_ref):
        raise InvalidConstructionError("match_ref does not match the public schema")
    return MatchState(
        match_ref=match_ref,
        initial_score=checked_score,
        initial_dealer=dealer,
        score=checked_score,
        dealer=dealer,
        phase=EnginePhase.AWAITING_DEAL,
        active_deal=None,
        completed_deals=(),
        public_events=(),
        ruleset_id=ruleset_id,
    )


def begin_explicit_deal(state: MatchState, explicit_deal: ExplicitDeal) -> MatchState:
    validate_match_state(state)
    if state.terminal:
        raise TerminalStateError("completed match accepts no additional deals")
    if state.phase not in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
        raise WrongPhaseError("cannot begin a deal while another deal is active")
    if not isinstance(explicit_deal, ExplicitDeal):
        raise InvalidConstructionError("explicit_deal must be an ExplicitDeal")
    if explicit_deal.dealer != state.dealer:
        raise DealSequenceError(
            f"explicit dealer {explicit_deal.dealer} does not match expected dealer {state.dealer}"
        )
    deal_number = len(state.completed_deals)
    deal_ref = f"{state.match_ref}/deal:{deal_number}"
    active = create_deal_state(
        explicit_deal,
        starting_score=state.score,
        match_ref=state.match_ref,
        deal_ref=deal_ref,
        deal_number=deal_number,
        event_start_index=len(state.public_events),
        ruleset_id=state.ruleset_id,
    )
    return MatchState(
        match_ref=state.match_ref,
        initial_score=state.initial_score,
        initial_dealer=state.initial_dealer,
        score=state.score,
        dealer=state.dealer,
        phase=EnginePhase.SHOWING,
        active_deal=active,
        completed_deals=state.completed_deals,
        public_events=state.public_events + active.events,
        ruleset_id=state.ruleset_id,
    )


def apply_match_action(state: MatchState, action: Action) -> MatchState:
    # The entry revalidation is implicit: the caller is handing back a state
    # this engine produced. Elided in a trusted block, where the type check is
    # kept so the error contract for a genuinely wrong argument survives.
    if is_trusted():
        if not isinstance(state, MatchState):
            raise StateInvariantError("state must be a MatchState")
    else:
        validate_match_state(state)
    if state.terminal:
        raise TerminalStateError("completed match accepts no actions")
    if state.phase is EnginePhase.DEAL_COMPLETE:
        raise TerminalStateError(
            "completed deal accepts no actions; begin the next explicit deal"
        )
    if state.phase not in ACTIVE_PHASES:
        raise WrongPhaseError("no active deal action is currently expected")
    if state.active_deal is None:
        raise StateInvariantError("active phase has no private deal state")
    old_event_count = len(state.active_deal.events)
    # validate_match_state above already revalidated this active deal, so the
    # dispatcher below repeats neither that work nor any of its own checks.
    active = _apply_action_validated(state.active_deal, action)
    new_public_events = state.public_events + active.events[old_event_count:]
    completed = state.completed_deals
    score = state.score
    dealer = state.dealer
    if active.complete:
        research_result = research_deal_result_from_state(active)
        completed = completed + (research_result,)
        if active.ending_score is None:
            raise StateInvariantError("completed deal has no ending score")
        score = active.ending_score
        dealer = active.dealer if active.next_dealer is None else active.next_dealer
    return MatchState(
        match_ref=state.match_ref,
        initial_score=state.initial_score,
        initial_dealer=state.initial_dealer,
        score=score,
        dealer=dealer,
        phase=active.phase,
        active_deal=active,
        completed_deals=completed,
        public_events=new_public_events,
        ruleset_id=state.ruleset_id,
    )


def match_observation_for(state: MatchState, observing_seat: int) -> PlayerObservation:
    if is_trusted():
        if not isinstance(state, MatchState):
            raise StateInvariantError("state must be a MatchState")
    else:
        validate_match_state(state)
    if state.active_deal is None:
        raise WrongPhaseError("there is no active deal to observe")
    # The match validation above revalidated the active deal; the seat check is
    # the same one ``observation_for`` performs, in the same order.
    return _observation_for_validated(
        state.active_deal, validate_seat(observing_seat)
    )


def play_active_deal(
    state: MatchState,
    agents: tuple[Agent, Agent, Agent, Agent],
    *,
    action_audit: Callable[[Action], None] | None = None,
) -> MatchState:
    """Run one finite deal, exposing only the current actor's observation."""

    validate_match_state(state)
    if state.phase not in ACTIVE_PHASES:
        raise WrongPhaseError("play_active_deal requires an active deal")
    if type(agents) is not tuple or len(agents) != 4:
        raise AgentProtocolError("runner requires exactly four agents")
    if len({id(agent) for agent in agents}) != 4:
        raise AgentProtocolError(
            "each seat requires a distinct agent object to preserve observation isolation"
        )
    if any(not callable(getattr(agent, "choose_action", None)) for agent in agents):
        raise AgentProtocolError("every agent must implement choose_action")

    current = state
    accepted_actions = 0
    while current.phase in ACTIVE_PHASES:
        actor = current.current_actor
        if actor is None:
            raise StateInvariantError("active deal has no current actor")
        observation = match_observation_for(current, actor)
        action = agents[actor].choose_action(observation)
        if action_audit is not None:
            action_audit(action)
        current = apply_match_action(current, action)
        accepted_actions += 1
        if accepted_actions > 60:
            raise StateInvariantError("deal exceeded 4 shows, 2 sooli answers, 2 exchanges and 52 plays")
    return current


def match_result_from_state(state: MatchState) -> MatchResult:
    validate_match_state(state)
    if not state.terminal:
        raise WrongPhaseError("MatchResult is available only after reaching the target")
    winner = match_winner(state.score)
    if winner is None:
        raise StateInvariantError("terminal match has no winner")
    return MatchResult(
        match_ref=state.match_ref,
        initial_score=state.initial_score,
        initial_dealer=state.initial_dealer,
        final_score=state.score,
        winner_team=winner,
        deals=tuple(item.public_result for item in state.completed_deals),
        events=state.public_events,
    )


def validate_match_state(state: MatchState) -> MatchState:
    if not isinstance(state, MatchState):
        raise StateInvariantError("state must be a MatchState")
    _validate_match_state(state)
    return state


def _validate_match_state(state: MatchState) -> None:
    if state.ruleset_id not in SUPPORTED_RULESETS:
        raise StateInvariantError("match supports project_target_v1 and project_target_v2")
    if state.active_deal is not None and state.active_deal.ruleset_id is not state.ruleset_id:
        raise StateInvariantError("active deal ruleset disagrees with the match")
    if not is_valid_match_ref(state.match_ref):
        raise StateInvariantError("match_ref does not match the public schema")
    if not isinstance(state.initial_score, MatchScore):
        raise StateInvariantError("initial score must be nonterminal")
    try:
        checked_initial_score = MatchScore(
            state.initial_score.team0, state.initial_score.team1
        )
        checked_score = MatchScore(state.score.team0, state.score.team1)
    except (AttributeError, ValueError) as exc:
        raise StateInvariantError("match score contains invalid fields") from exc
    if checked_initial_score != state.initial_score or is_match_terminal(
        checked_initial_score
    ):
        raise StateInvariantError("initial score must be valid and nonterminal")
    for label, value in (("initial_dealer", state.initial_dealer), ("dealer", state.dealer)):
        if type(value) is not int or value not in range(4):
            raise StateInvariantError(f"{label} must be an integer in 0..3")
    if (
        not isinstance(state.score, MatchScore)
        or checked_score != state.score
        or not isinstance(state.phase, EnginePhase)
    ):
        raise StateInvariantError("match score or phase is malformed")
    if type(state.completed_deals) is not tuple or any(
        not isinstance(result, ResearchDealResult) for result in state.completed_deals
    ):
        raise StateInvariantError("completed_deals must be immutable research results")
    if type(state.public_events) is not tuple or any(
        not isinstance(event, PublicEvent) for event in state.public_events
    ):
        raise StateInvariantError("public_events must be an immutable event tuple")
    if tuple(event.event_index for event in state.public_events) != tuple(
        range(len(state.public_events))
    ):
        raise StateInvariantError("match event indices must be contiguous from zero")
    if any(event.match_ref != state.match_ref for event in state.public_events):
        raise StateInvariantError("event match_ref disagrees with match state")

    for deal_number, research in enumerate(state.completed_deals):
        public = research.public_result
        if public.deal_number != deal_number or public.match_ref != state.match_ref:
            raise StateInvariantError("completed deal order or match reference is invalid")
        if deal_number == 0:
            if public.dealer != state.initial_dealer or public.score_before != state.initial_score:
                raise StateInvariantError("first result disagrees with initial match state")
        else:
            previous = state.completed_deals[deal_number - 1].public_result
            if previous.match_terminal:
                raise StateInvariantError("completed result exists after terminal match")
            if public.dealer != previous.next_dealer or public.score_before != previous.score_after:
                raise StateInvariantError("completed deal sequence is discontinuous")

    completed_events = tuple(
        event
        for research in state.completed_deals
        for event in research.public_result.events
    )
    if state.phase is EnginePhase.AWAITING_DEAL:
        if state.active_deal is not None or state.completed_deals or state.public_events:
            raise StateInvariantError("AWAITING_DEAL is only the pristine match state")
        if state.score != state.initial_score or state.dealer != state.initial_dealer:
            raise StateInvariantError("pristine match fields disagree with initial state")
        return

    if state.active_deal is None:
        raise StateInvariantError("non-pristine match requires an active deal state")
    validate_deal_state(state.active_deal)
    if state.active_deal.match_ref != state.match_ref:
        raise StateInvariantError("active deal belongs to a different match")
    if state.active_deal.deal_number != len(state.completed_deals) - (
        1 if state.active_deal.complete else 0
    ):
        raise StateInvariantError("active deal number is inconsistent")
    if state.phase is not state.active_deal.phase:
        raise StateInvariantError("match phase disagrees with active deal phase")

    if state.active_deal.complete:
        if not state.completed_deals:
            raise StateInvariantError("completed active deal is absent from results")
        latest = state.completed_deals[-1]
        expected_latest = research_deal_result_from_state(state.active_deal)
        if latest != expected_latest:
            raise StateInvariantError("latest research result disagrees with active deal")
        expected_events = completed_events
        if state.score != state.active_deal.ending_score:
            raise StateInvariantError("match score disagrees with completed deal")
        if state.phase is EnginePhase.MATCH_COMPLETE:
            if not is_match_terminal(state.score) or state.dealer != state.active_deal.dealer:
                raise StateInvariantError("terminal match score or dealer is inconsistent")
        elif state.phase is EnginePhase.DEAL_COMPLETE:
            if is_match_terminal(state.score) or state.dealer != state.active_deal.next_dealer:
                raise StateInvariantError("nonterminal completed match fields are inconsistent")
        else:
            raise StateInvariantError("completed active deal has an active phase")
    else:
        expected_events = completed_events + state.active_deal.events
        if state.score != state.active_deal.starting_score or state.dealer != state.active_deal.dealer:
            raise StateInvariantError("active match score or dealer changed prematurely")
        if is_match_terminal(state.score):
            raise StateInvariantError("active deal cannot start from terminal match score")
    if state.public_events != expected_events:
        raise StateInvariantError("aggregated public event history is inconsistent")
