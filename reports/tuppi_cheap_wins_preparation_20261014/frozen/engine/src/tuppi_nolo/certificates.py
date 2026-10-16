"""Research-only exhaustive verification of supplied NOLO continuation claims.

No optimization, policy ranking, sampling or N04 search. Every other seat,
including the partner, retains all legal choices. Failure witnesses are private
harness artifacts; diagnostics never contain hidden layouts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import json

from tuppi_engine import EnginePhase, PlayCardAction, PlayerObservation, apply_action, observation_for
from tuppi_exact.sampling import HiddenHandAssignment
from tuppi_rules import card_to_code

from .support import (SupportBudget, SupportResult, SupportStatus,
                      build_support, semantic_observation_key)

OBJECTIVE = "own_partnership_final_tricks_v1"


class ControlModel(str, Enum):
    SINGLE_SEAT = "single_seat_plan_all_other_seats_arbitrary_v1"
    ALL_ACTIONS = "all_seats_arbitrary_after_root_v1"


class ClaimType(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    UNIVERSAL = "UNIVERSAL"


class CheckStatus(str, Enum):
    EXACT_COMPLETE = "EXACT_COMPLETE"
    INVALID_INPUT = "INVALID_INPUT"
    INCOMPLETE_SUPPORT = "INCOMPLETE_SUPPORT"
    ILLEGAL_PLAN = "ILLEGAL_PLAN"
    DISPROVED_BOUND = "DISPROVED_BOUND"
    DISPROVED_UNIVERSAL = "DISPROVED_UNIVERSAL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SUPPORT_BUDGET = "SUPPORT_BUDGET"
    SEARCH_BUDGET = "SEARCH_BUDGET"


@dataclass(frozen=True, slots=True)
class PlanEntry:
    information_key: str
    action: PlayCardAction

    def __post_init__(self):
        if not isinstance(self.information_key, str) or not isinstance(self.action, PlayCardAction):
            raise TypeError("plan entries require an information key and immutable play action")


@dataclass(frozen=True, slots=True)
class CompletenessProvenance:
    support_status: SupportStatus
    world_count: int
    generation_budget: SupportBudget
    generation_engine_transitions: int

    def __post_init__(self):
        if not isinstance(self.generation_budget, SupportBudget):
            raise TypeError("provenance requires an immutable SupportBudget")


@dataclass(frozen=True, slots=True)
class Certificate:
    source_information_key: str
    root_seat: int
    root_action: PlayCardAction
    objective: str
    control_model: ControlModel
    complete_support_digest: str
    plan: tuple[PlanEntry, ...]
    claimed_terminal_bound: int
    provenance: CompletenessProvenance
    claim_type: ClaimType = ClaimType.UNCLASSIFIED
    baseline_action: PlayCardAction | None = None

    def __post_init__(self):
        if type(self.plan) is not tuple or any(not isinstance(e, PlanEntry) for e in self.plan):
            raise TypeError("certificate plan must be an immutable tuple of PlanEntry")
        if not isinstance(self.provenance, CompletenessProvenance):
            raise TypeError("certificate requires immutable completeness/budget provenance")
        if not isinstance(self.root_action, PlayCardAction):
            raise TypeError("certificate requires an immutable root play action")
        if self.baseline_action is not None and not isinstance(self.baseline_action, PlayCardAction):
            raise TypeError("baseline must be an immutable play action")


def complete_support_digest(result: SupportResult) -> str:
    """Commit to complete allocation contents, not count or hypothetical IDs."""
    if not isinstance(result, SupportResult) or result.status is not SupportStatus.EXACT_COMPLETE:
        raise ValueError("a support digest requires an exact support result")
    keys = sorted(w.content_key for w in result.research_worlds)
    data = {"source": result.decision_key, "allocations": keys, "schema": "nolo-support-v1"}
    return "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class TerminalOutcome:
    own_tricks: int
    score_state: tuple[int, int]


@dataclass(frozen=True, slots=True)
class ResearchPath:
    """An engine-replayable path from a privately held hypothetical allocation."""
    assignment: HiddenHandAssignment
    actions: tuple[PlayCardAction, ...]
    information_key: str | None
    outcome: TerminalOutcome | None


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: CheckStatus
    claim_type: ClaimType
    source_information_key: str | None
    root_action: PlayCardAction | None
    control_model: ControlModel
    world_count: int | None
    support_digest: str | None
    engine_transitions: int
    reason: str | None = None
    outcomes: frozenset[TerminalOutcome] = frozenset()
    terminal_paths: int = 0
    plan: tuple[PlanEntry, ...] = ()
    baseline_bounds: tuple[int, int] | None = None
    legal_actions: tuple[PlayCardAction, ...] = ()
    # One representative per (world, outcome), never a policy-facing artifact.
    research_paths: tuple[ResearchPath, ...] = field(default=(), repr=False)
    counterexample: ResearchPath | None = field(default=None, repr=False)
    comparison_path: ResearchPath | None = field(default=None, repr=False)

    @property
    def terminal_totals(self) -> frozenset[int]:
        return frozenset(o.own_tricks for o in self.outcomes)

    @property
    def score_states(self) -> frozenset[tuple[int, int]]:
        return frozenset(o.score_state for o in self.outcomes)

    @property
    def bounds(self) -> tuple[int, int] | None:
        totals = self.terminal_totals
        return (min(totals), max(totals)) if totals else None

    def diagnostics(self) -> dict:
        return {
            "status": self.status.value, "claim_type": self.claim_type.value,
            "source_information_key": self.source_information_key,
            "root_action": None if self.root_action is None else card_to_code(self.root_action.card),
            "root_seat": None if self.root_action is None else self.root_action.seat,
            "legal_actions": sorted(card_to_code(a.card) for a in self.legal_actions),
            "objective": OBJECTIVE, "control_model": self.control_model.value,
            "world_count": self.world_count, "support_digest": self.support_digest,
            "engine_transitions": self.engine_transitions, "fallback_reason": self.reason,
            "bounds": self.bounds, "terminal_totals": sorted(self.terminal_totals),
            "score_states": sorted(self.score_states), "terminal_paths": self.terminal_paths,
            "baseline_bounds": self.baseline_bounds,
            "plan": [(e.information_key, card_to_code(e.action.card)) for e in self.plan],
            "verifier": "nolo_exhaustive_certificate_v1",
        }


class _Limit(Exception):
    pass


class _BadPlan(Exception):
    def __init__(self, reason, path):
        self.reason, self.path = reason, path


class _Meter:
    def __init__(self, budget, already_used):
        self.limit = budget.max_engine_transitions
        self.calls = already_used

    def step(self, state, action):
        if self.calls >= self.limit:
            raise _Limit
        self.calls += 1
        return apply_action(state, action)


def _walk(worlds, root_action, control, table, meter):
    """Exhaust every permitted engine branch, retaining correlated leaf sets."""
    outcomes = Counter()
    representatives = {}
    used = set()
    seat = root_action.seat

    def visit(state, path, assignment):
        if state.phase is not EnginePhase.TRICK_PLAY:
            assert state.complete and len(state.completed_tricks) == 13
            outcome = TerminalOutcome(state.team_tricks[seat % 2], state.ending_score.as_tuple())
            outcomes[outcome] += 1
            representatives.setdefault((assignment.content_key(), outcome),
                ResearchPath(assignment, path, None, outcome))
            return
        obs = observation_for(state, state.current_actor)
        actions = obs.legal_actions
        if control is ControlModel.SINGLE_SEAT and state.current_actor == seat:
            key = semantic_observation_key(obs)
            chosen = table.get(key)
            witness = ResearchPath(assignment, path, key, None)
            if chosen is None:
                if len(actions) != 1:
                    raise _BadPlan("missing non-forced own decision", witness)
            else:
                used.add(key)
                if chosen not in actions:
                    raise _BadPlan("specified action is illegal at this information key", witness)
                actions = (chosen,)
        for action in actions:
            visit(meter.step(state, action), path + (action,), assignment)

    for world in worlds:
        state = world.continuation.state
        visit(meter.step(state, root_action), (root_action,), world.assignment)
    return frozenset(outcomes), sum(outcomes.values()), tuple(representatives.values()), used


def _base(observation, root_action, budget, control, plan=()):
    if not isinstance(observation, PlayerObservation):
        return CheckResult(CheckStatus.INVALID_INPUT, ClaimType.UNCLASSIFIED, None,
                           None, control, None, None, 0, "requires PlayerObservation")
    if not isinstance(budget, SupportBudget):
        raise TypeError("verification requires SupportBudget")
    key = semantic_observation_key(observation)
    result = CheckResult(CheckStatus.INVALID_INPUT, ClaimType.UNCLASSIFIED, key,
                         root_action if isinstance(root_action, PlayCardAction) else None,
                         control, None, None, 0, plan=plan,
                         legal_actions=observation.legal_actions)
    if observation.current_actor != observation.observing_seat:
        return replace(result, reason="root observer must be the acting seat")
    rebuilt = build_support(observation, budget)
    result = replace(result, engine_transitions=rebuilt.engine_transitions,
                     world_count=rebuilt.world_count)
    if rebuilt.status is not SupportStatus.EXACT_COMPLETE:
        return replace(result, status=CheckStatus(rebuilt.status.value), reason=rebuilt.reason)
    result = replace(result, support_digest=complete_support_digest(rebuilt))
    if not isinstance(root_action, PlayCardAction) or root_action not in observation.legal_actions:
        witness = ResearchPath(rebuilt.research_worlds[0].assignment, (), key, None)
        return replace(result, status=CheckStatus.ILLEGAL_PLAN, reason="illegal root action",
                       counterexample=witness)
    return rebuilt, result


def _exhaust(rebuilt, result, root_action, control, table, budget):
    meter = _Meter(budget, result.engine_transitions)
    try:
        outcomes, paths, witnesses, used = _walk(rebuilt.research_worlds, root_action, control, table, meter)
    except _Limit:
        return replace(result, status=CheckStatus.SEARCH_BUDGET,
                       engine_transitions=meter.calls, reason="engine transition limit"), set()
    except _BadPlan as exc:
        return replace(result, status=CheckStatus.ILLEGAL_PLAN,
                       engine_transitions=meter.calls, reason=exc.reason,
                       counterexample=exc.path), set()
    return replace(result, status=CheckStatus.EXACT_COMPLETE, outcomes=outcomes,
                   terminal_paths=paths, research_paths=witnesses,
                   engine_transitions=meter.calls, reason=None), used


def all_action_bounds(observation, root_action, budget) -> CheckResult:
    """All future seats, including root, choose arbitrarily. No plan is consulted."""
    prepared = _base(observation, root_action, budget, ControlModel.ALL_ACTIONS)
    if isinstance(prepared, CheckResult):
        return prepared
    rebuilt, result = prepared
    return _exhaust(rebuilt, result, root_action, ControlModel.ALL_ACTIONS, {}, budget)[0]


def verify_certificate(observation, certificate, budget) -> CheckResult:
    """Verify a supplied plan/bound and optional universal comparison from scratch.

    The certificate's support count and generation budget are assertions, never
    enumeration inputs. Comparator support replay and traversal consume the same
    caller's operation budget. Exhaustion discards partial terminal sets.
    """
    invalid = CheckResult(CheckStatus.INVALID_INPUT, ClaimType.UNCLASSIFIED, None,
                          None, ControlModel.ALL_ACTIONS, None, None, 0)
    if not isinstance(certificate, Certificate) or not isinstance(observation, PlayerObservation):
        return replace(invalid, reason="requires PlayerObservation and Certificate")
    c = certificate
    if (c.source_information_key != semantic_observation_key(observation) or
        type(c.root_seat) is not int or c.root_seat != observation.observing_seat or
        c.objective != OBJECTIVE or not isinstance(c.control_model, ControlModel) or
        not isinstance(c.claim_type, ClaimType) or type(c.claimed_terminal_bound) is not int or
        not 0 <= c.claimed_terminal_bound <= 13):
        return replace(invalid, reason="invalid source, seat, objective, control model or bound")
    prepared = _base(observation, c.root_action, budget, c.control_model, c.plan)
    if isinstance(prepared, CheckResult):
        return prepared
    rebuilt, result = prepared
    p = c.provenance
    if (p.support_status is not SupportStatus.EXACT_COMPLETE or
        type(p.world_count) is not int or p.world_count != rebuilt.world_count or
        c.complete_support_digest != result.support_digest or
        type(p.generation_engine_transitions) is not int or
        not rebuilt.engine_transitions <= p.generation_engine_transitions <= p.generation_budget.max_engine_transitions or
        p.world_count > p.generation_budget.max_worlds or
        13-len(observation.completed_tricks) > p.generation_budget.max_remaining_tricks):
        return replace(result, status=CheckStatus.INCOMPLETE_SUPPORT,
                       reason="support content/count/completeness provenance disagrees with rebuild")
    table = {}
    root_key = c.source_information_key
    for entry in c.plan:
        if entry.information_key in table and table[entry.information_key] != entry.action:
            return replace(result, status=CheckStatus.ILLEGAL_PLAN,
                           reason="conflicting actions at the same information key")
        table[entry.information_key] = entry.action
    if c.control_model is ControlModel.ALL_ACTIONS and table:
        return replace(result, status=CheckStatus.ILLEGAL_PLAN, reason="all-actions claims cannot restrict a plan")
    if root_key in table and table[root_key] != c.root_action:
        return replace(result, status=CheckStatus.ILLEGAL_PLAN, reason="plan conflicts with root action")
    table.pop(root_key, None)
    checked, used = _exhaust(rebuilt, result, c.root_action, c.control_model, table, budget)
    if checked.status is not CheckStatus.EXACT_COMPLETE:
        return checked
    if set(table) != used:
        return replace(result, status=CheckStatus.ILLEGAL_PLAN,
                       engine_transitions=checked.engine_transitions,
                       reason="plan contains unreachable/non-observation keys")
    if max(checked.terminal_totals) > c.claimed_terminal_bound:
        witness = next(w for w in checked.research_paths if w.outcome.own_tricks > c.claimed_terminal_bound)
        return replace(checked, status=CheckStatus.DISPROVED_BOUND,
                       reason="legal continuation exceeds claimed terminal bound", counterexample=witness)
    if c.claim_type is not ClaimType.UNIVERSAL:
        return checked
    if c.baseline_action not in observation.legal_actions:
        return replace(result, status=CheckStatus.INVALID_INPUT,
                       engine_transitions=checked.engine_transitions,
                       reason="universal claim requires a legal baseline action")
    remaining = replace(budget, max_engine_transitions=budget.max_engine_transitions-checked.engine_transitions)
    baseline = all_action_bounds(observation, c.baseline_action, remaining)
    total_calls = checked.engine_transitions + baseline.engine_transitions
    if baseline.status is not CheckStatus.EXACT_COMPLETE:
        # Even complete candidate leaves cannot turn an unfinished comparison
        # into a certificate. Retain no purported complete operation outcome set.
        return replace(result, status=baseline.status, engine_transitions=total_calls,
                       reason="universal comparator unresolved: " + str(baseline.reason))
    candidate_low, candidate_high = checked.bounds
    baseline_low, baseline_high = baseline.bounds
    checked = replace(checked, engine_transitions=total_calls, baseline_bounds=baseline.bounds)
    universal = candidate_high <= baseline_low and candidate_low < baseline_high
    if universal:
        strict = next(w for w in baseline.research_paths if w.outcome.own_tricks == baseline_high)
        return replace(checked, claim_type=ClaimType.UNIVERSAL, comparison_path=strict)
    # Prefer a single layout demonstrating reversal, with two legal continuations.
    pair = next(((a, b) for a in checked.research_paths for b in baseline.research_paths
                 if a.assignment.content_key() == b.assignment.content_key()
                 and a.outcome.own_tricks > b.outcome.own_tricks), None)
    if pair is None:
        pair = (max(checked.research_paths, key=lambda w: w.outcome.own_tricks),
                min(baseline.research_paths, key=lambda w: w.outcome.own_tricks))
    return replace(checked, status=CheckStatus.DISPROVED_UNIVERSAL,
                   reason="candidate upper bound exceeds baseline lower bound or no strict case exists",
                   counterexample=pair[0], comparison_path=pair[1])
