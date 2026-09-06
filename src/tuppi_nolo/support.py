"""Complete observation-only NOLO support; private worlds stay in research.

No weights or behavioural exclusions. No real DealState or initial deal enters
build_support. The engine replay is authoritative; a rejected model assignment
raises SupportInvariantError rather than silently reducing the denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import hashlib
import json
from types import FunctionType, MappingProxyType
from typing import Iterator

from tuppi_agents.errors import AgentsValidationError
from tuppi_engine import EnginePhase, PlayCardAction, PlayerObservation, observation_for
from tuppi_engine.errors import EngineValidationError, StateInvariantError
from tuppi_exact.constraints import HardConstraintModel, own_show_exclusion_is_consistent
from tuppi_exact.continuation import HypotheticalContinuation, hypothetical_continuation
from tuppi_exact.counting import feasible_assignment_count
from tuppi_exact.errors import ConstraintError, ContinuationError
from tuppi_exact.sampling import HiddenHandAssignment
from tuppi_rules import Contract, card_to_index, legal_cards, trick_winner
from tuppi_rules.errors import RulesError

MAX_REMAINING_TRICKS = 3
MAX_WORLDS = 100
MAX_ENGINE_TRANSITIONS = 100_000
INDEPENDENT_PARTITION_LIMIT = 2_000


class SupportStatus(str, Enum):
    EXACT_COMPLETE = "EXACT_COMPLETE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SUPPORT_BUDGET = "SUPPORT_BUDGET"
    SEARCH_BUDGET = "SEARCH_BUDGET"
    INVALID_INPUT = "INVALID_INPUT"


class SupportInvariantError(RuntimeError):
    """FAILED_CHECK: model, enumerator or replay disagrees; blocks certificates."""


@dataclass(frozen=True, slots=True)
class SupportBudget:
    max_remaining_tricks: int = MAX_REMAINING_TRICKS
    max_worlds: int = MAX_WORLDS
    max_engine_transitions: int = MAX_ENGINE_TRANSITIONS

    def __post_init__(self):
        for name, ceiling in (("max_remaining_tricks", MAX_REMAINING_TRICKS),
                              ("max_worlds", MAX_WORLDS),
                              ("max_engine_transitions", MAX_ENGINE_TRANSITIONS)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer in 0..{ceiling}")


def _public_value(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {f.name: _public_value(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [_public_value(v) for v in value]
    return value


def semantic_observation_key(observation: PlayerObservation) -> str:
    """Own hand/action order and public history, with protocol identities absent.

    Mirrors the field design of tuppi_search/information_state.py without a
    dependency on that research layer. Public voids are derivable from history.
    No assignment, sample metadata, private owner map or hidden hand is accepted.
    """
    if not isinstance(observation, PlayerObservation):
        raise TypeError("semantic_observation_key requires PlayerObservation")
    names = (
        "observing_seat", "team", "partner_seat", "dealer", "forehand", "phase",
        "current_actor", "own_hand", "show_actions", "publicly_shown_cards",
        "contract", "declarer", "first_leader", "completed_tricks", "current_trick",
        "team_tricks", "match_score", "legal_actions", "deal_terminal",
        "match_terminal", "ruleset_id", "schema_version",
    )
    data = {name: _public_value(getattr(observation, name)) for name in names}
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return "nolo-observation-v1:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchWorld:
    assignment: HiddenHandAssignment
    continuation: HypotheticalContinuation

    @property
    def content_key(self) -> tuple[tuple[int, ...], ...]:
        """Private allocation identity, independent of sample/protocol metadata."""
        return tuple(tuple(sorted(map(card_to_index, hand)))
                     for hand in self.assignment.hands)


@dataclass(frozen=True, slots=True)
class SupportResult:
    """Research-private result. Only diagnostics() is suitable for explanations."""
    status: SupportStatus
    decision_key: str | None
    world_count: int | None
    counted_candidates: int | None
    assignments_attempted: int
    engine_transitions: int
    reason: str | None
    # Not included in diagnostic output; this object must not enter a policy.
    research_worlds: tuple[ResearchWorld, ...] = field(default=(), repr=False)

    def __post_init__(self):
        if self.status is SupportStatus.EXACT_COMPLETE:
            if not self.research_worlds or self.world_count != len(self.research_worlds):
                raise SupportInvariantError("exact support must contain every world")
        elif self.world_count is not None or self.research_worlds:
            raise SupportInvariantError("unresolved support must not expose a partial set")

    def diagnostics(self) -> dict:
        return {
            "status": self.status.value, "decision_key": self.decision_key,
            "world_count": self.world_count, "counted_candidates": self.counted_candidates,
            "assignments_attempted": self.assignments_attempted,
            "engine_transitions": self.engine_transitions, "fallback_reason": self.reason,
            "claim_type": "UNCLASSIFIED",
        }


class _TransitionLimit(Exception):
    pass


class _ReplayMeter:
    def __init__(self, limit):
        self.limit = limit
        self.calls = 0
        # The existing replay has no transition hook. Rebind only this call's
        # globals, keeping its code/defaults/closure and helper functions intact.
        # Unlike monkeypatching, this cannot alter concurrent callers' engine.
        original = hypothetical_continuation
        namespace = dict(original.__globals__)
        apply = namespace["apply_action"]

        def counted_apply(state, action):
            if self.calls >= self.limit:
                raise _TransitionLimit
            self.calls += 1  # Includes attempted engine calls that reject input.
            return apply(state, action)

        namespace["apply_action"] = counted_apply
        self.replay = FunctionType(original.__code__, namespace, original.__name__,
                                   original.__defaults__, original.__closure__)
        self.replay.__kwdefaults__ = original.__kwdefaults__


def _assignments(model: HardConstraintModel, obs: PlayerObservation) -> Iterator[HiddenHandAssignment]:
    cards = sorted(model.unknown_cards,
                   key=lambda c: (len(model.allowed_seats(c)), card_to_index(c)))
    hands = [set(h) for h in model.known_held]
    capacity = list(model.capacity)
    owners = {}
    index = 0

    def visit(position):
        nonlocal index
        if position == len(cards):
            if any(capacity):
                raise SupportInvariantError("enumeration left unfilled capacity")
            ordered = tuple(obs.own_hand if s == obs.observing_seat else
                            tuple(sorted(hand, key=card_to_index))
                            for s, hand in enumerate(hands))
            yield HiddenHandAssignment(obs.observing_seat, ordered,
                                       MappingProxyType(dict(owners)), index)
            index += 1
            return
        card = cards[position]
        for seat in sorted(model.allowed_seats(card)):
            if capacity[seat]:
                hands[seat].add(card)
                owners[card] = seat
                capacity[seat] -= 1
                yield from visit(position + 1)
                capacity[seat] += 1
                del owners[card]
                hands[seat].remove(card)

    yield from visit(0)


def _validate_public_record(obs):
    """Check public consistency before interpreting replay rejection as a bug."""
    obs.__post_init__()
    if obs.declarer is not None or len(obs.show_actions) != 4 or any(
        a.declared_contract is not Contract.NOLO for a in obs.show_actions
    ):
        raise ConstraintError("inconsistent resolved NOLO showing")
    if obs.forehand != (obs.dealer + 1) % 4 or obs.first_leader != obs.forehand:
        raise ConstraintError("inconsistent first leader/forehand")
    if [a.seat for a in obs.show_actions] != [(obs.forehand + i) % 4 for i in range(4)]:
        raise ConstraintError("showing order contradicts dealer")
    played_owner = {}
    voids = [set() for _ in range(4)]
    groups = tuple(t.plays for t in obs.completed_tricks) + (obs.current_trick,)
    for plays in groups:
        if not plays:
            continue
        led = plays[0].card.suit
        for play in plays:
            if play.card in played_owner or play.card.suit in voids[play.seat]:
                raise ConstraintError("repeated card or play after a proven void")
            played_owner[play.card] = play.seat
            if play.card.suit is not led:
                voids[play.seat].add(led)
    if len({a.shown_card for a in obs.show_actions}) != 4:
        raise ConstraintError("a card cannot be shown by two seats")
    for action in obs.show_actions:
        owner = played_owner.get(action.shown_card)
        if owner is not None and owner != action.seat:
            raise ConstraintError("shown card was played by a different owner")
    leader = obs.first_leader
    totals = [0, 0]
    for index, trick in enumerate(obs.completed_tricks):
        winner = trick_winner(trick.plays)
        if (trick.trick_index != index or trick.leader != leader or
                trick.plays[0].seat != leader or trick.winner != winner):
            raise ConstraintError("contradictory completed trick")
        totals[winner % 2] += 1
        leader = winner
    if tuple(totals) != obs.team_tricks or len(obs.current_trick) > 3:
        raise ConstraintError("contradictory trick totals/partial trick")
    if any(p.seat != (leader + i) % 4 for i, p in enumerate(obs.current_trick)):
        raise ConstraintError("invalid partial trick seat order")
    if obs.current_actor != (leader + len(obs.current_trick)) % 4:
        raise ConstraintError("wrong current actor")
    if obs.deal_terminal or obs.match_terminal:
        raise ConstraintError("an open NOLO position cannot be terminal")
    if not own_show_exclusion_is_consistent(obs):
        raise ConstraintError("own hand contradicts showing/history")
    expected = ()
    if obs.observing_seat == obs.current_actor:
        led = obs.current_trick[0].card.suit if obs.current_trick else None
        legal = legal_cards(obs.own_hand, led)
        expected = tuple(PlayCardAction(obs.observing_seat, c)
                         for c in obs.own_hand if c in legal)
    if obs.legal_actions != expected:
        raise ConstraintError("legal actions contradict own hand/public trick")


def build_support(observation: PlayerObservation, budget: SupportBudget) -> SupportResult:
    """Return the complete hard support or a typed unresolved result, never a sample.

    Wrong entry-point types are programmer errors. Contradictory evidence returns
    INVALID_INPUT. Rejection/count disagreement within exact enumeration raises
    SupportInvariantError, and unexpected errors propagate unchanged.
    """
    if not isinstance(observation, PlayerObservation):
        raise TypeError("build_support requires PlayerObservation, not a private state/fixture")
    if not isinstance(budget, SupportBudget):
        raise TypeError("build_support requires SupportBudget")
    key = semantic_observation_key(observation)
    counted = None
    attempted = 0
    meter = _ReplayMeter(budget.max_engine_transitions)

    def unresolved(status, reason):
        return SupportResult(status, key, None, counted, attempted, meter.calls, reason)

    if observation.phase is not EnginePhase.TRICK_PLAY or observation.contract is not Contract.NOLO:
        return unresolved(SupportStatus.OUT_OF_SCOPE, "requires resolved NOLO trick play")
    remaining = 13 - len(observation.completed_tricks)
    if not 1 <= remaining <= budget.max_remaining_tricks:
        return unresolved(SupportStatus.OUT_OF_SCOPE, "remaining-trick limit")
    try:
        _validate_public_record(observation)
        model = HardConstraintModel.build(observation)
    except (ConstraintError, AgentsValidationError, RulesError, StateInvariantError) as exc:
        return unresolved(SupportStatus.INVALID_INPUT, str(exc))
    counted = feasible_assignment_count(model)
    if counted == 0:
        return unresolved(SupportStatus.INVALID_INPUT, "no hard-feasible assignments")
    if counted > budget.max_worlds:
        return unresolved(SupportStatus.SUPPORT_BUDGET, "complete count exceeds world limit")
    worlds = []
    seen = set()
    for assignment in _assignments(model, observation):
        attempted += 1
        try:
            continuation = meter.replay(observation, assignment)
        except _TransitionLimit:
            return unresolved(SupportStatus.SEARCH_BUDGET, "engine transition limit during replay")
        except (EngineValidationError, RulesError, ContinuationError) as exc:
            raise SupportInvariantError(
                f"hard-model candidate {assignment.content_key()} rejected after "
                f"{meter.calls} engine calls: {exc}"
            ) from exc
        replayed_key = semantic_observation_key(observation_for(continuation.state, observation.observing_seat))
        if replayed_key != key:
            raise SupportInvariantError("replay changed semantic observation")
        world = ResearchWorld(assignment, continuation)
        if world.content_key in seen:
            raise SupportInvariantError("duplicate assignment")
        seen.add(world.content_key)
        worlds.append(world)
    if len(worlds) != counted:
        raise SupportInvariantError(f"enumerated {len(worlds)} assignments, counted {counted}")
    return SupportResult(SupportStatus.EXACT_COMPLETE, key, counted, counted,
                         attempted, meter.calls, None, tuple(worlds))
