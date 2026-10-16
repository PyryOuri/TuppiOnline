"""Match-aware rule diagnosis: which rule, and why.

Phase 5A established that the four ``match.*`` rules of ``match_aware_v1``
provide no measurable benefit over complete matches, and it deferred the
follow-up question: *which* rule is responsible, and is the protect threshold at
distance 4 simply mis-set. It also fixed the ground rules - a changed profile is a
new agent, and it belongs on fresh fixtures.

This module answers with four instruments, deliberately of different kinds, so a
weakness in one does not sink the diagnosis:

**1. An exhaustive proof, not a measurement.**
:func:`tuppi_exact.solver.monotonicity_certificate` enumerates every contract,
declarer, score state, and trick split and certifies that match utility is weakly
monotone in the trick split. Consequently *every trick-optimal card is also
match-optimal under perfect information*. Any rule that changes a **card** can
therefore only be justified by imperfect information, never by the score itself.
That is a structural verdict on two of the four rules before a single match runs.

**2. An exact activation census.**
Replaying deals with the frozen agent and re-deciding each position with one rule
switched off counts, exactly and cheaply, how often each rule *changes* a
decision, split by phase and score state. A rule that never changes a decision
cannot be responsible for anything; a rule that changes many is where the effect
must live if there is one. This measures influence, not value.

**3. Exact per-decision verdicts.**
Where a *play* rule changes the card and the position is inside the solver's exact
range, the solver says which card is better - exactly, on the real hands. The
verdict is perfect-information, so it answers "is this card a mistake against a
player who can see everything", which is the strongest form of "this rule loses
tricks it did not need to lose".

**4. Uniform-measure verdicts.**
The same comparison, but averaged over exactly-uniform samples of the feasible
hidden hands instead of the true deal. This is the imperfect-information reading,
and it is the honest one for a rule that trades expected points for probability of
a win. Its measure is uniform-over-feasible, which is *not* a posterior; the
caveat is stated wherever the number appears.

**5. A fresh-design match ablation.**
Per-rule variants played over the complete-match protocol on a **new** Phase 5B
bank, so no number here reuses a fixture that was visible while the rules were
written. This is the only instrument that measures the endpoint Phase 5A cared
about, and it is the most expensive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from tuppi_agents import (
    build_features,
    construct_agent,
    phase4_specifications_by_profile_key,
    showing_scalars,
)
from tuppi_engine import (
    DealState,
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    PlayerObservation,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.serialization import content_digest
from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.executor import _pair_from_data
from tuppi_match.records import PairRecord
from tuppi_match.statistics import pair_inference, secondary_metrics
from tuppi_match.streams import MatchStream
from tuppi_rules import (
    Contract,
    MatchScore,
    TRICKS_PER_DEAL,
    card_to_code,
)

from .constraints import HardConstraintModel
from .continuation import hypothetical_continuation
from .counting import feasible_assignment_count
from .errors import DiagnosisError, SolverBudgetError
from .sampling import UniformFeasibleSampler
from .solver import (
    DEFAULT_MAXIMUM_TRICKS_REMAINING,
    monotonicity_certificate,
    solve_late_game,
)
from .variants import (
    MATCH_PLAY_RULES,
    MATCH_RULES,
    MATCH_SHOW_RULES,
    BASE_PROFILE_KEY,
    DiagnosticVariant,
    composition_check,
    diagnostic_variants,
)


DIAGNOSIS_SCHEMA_VERSION = "tuppi.exact.match_rule_diagnosis.v1"

#: A brand-new root seed. Phase 5B must not reuse a Phase 5A bank: those fixtures
#: were inspected while the null was being interpreted.
CENSUS_ROOT_SEED = "tuppi-phase5b-census-v1"
ABLATION_ROOT_SEED = "tuppi-phase5b-rule-ablation-v1"
SAMPLING_ROOT_SEED = "tuppi-phase5b-uniform-sampling-v1"

#: The score-state grid, chosen to match the Phase 5A diagnostics so the two are
#: directly comparable.
CENSUS_SCORE_STATES: tuple[tuple[int, int], ...] = (
    (0, 0),
    (16, 0),
    (32, 0),
    (44, 0),
    (48, 0),
    (0, 16),
    (0, 32),
    (0, 44),
    (0, 48),
)

DEFAULT_CENSUS_DEALS = 24
DEFAULT_SAMPLES_PER_DECISION = 16
DEFAULT_ABLATION_PAIRS = 128
DEFAULT_SAFETY_CAP = 704
CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_REPLICATES = 2000
SIGN_FLIP_REPLICATES = 10000


def census_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5b_rule_census_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=CENSUS_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5B per-decision rule activation census and exact play-rule "
            "verdicts. A development bank: visible, reusable, and supporting no "
            "promotion claim."
        ),
    )


def ablation_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5b_rule_ablation_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=ABLATION_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5B per-rule complete-match ablation on fresh fixtures. A "
            "development bank; the promotion-sealed bank stays unopened."
        ),
    )


# ------------------------------------------------------------------ instruments


@dataclass(frozen=True, slots=True)
class DecisionDivergence:
    """One position where switching a single rule off changes the decision."""

    rule_id: str
    phase: str
    score_state: tuple[int, int]
    match_role: str
    contract: str | None
    acting_seat: int
    tricks_remaining: int
    base_action: str
    variant_action: str

    def to_data(self) -> dict[str, object]:
        return {
            "acting_seat": self.acting_seat,
            "base_action": self.base_action,
            "contract": self.contract,
            "match_role": self.match_role,
            "phase": self.phase,
            "rule_id": self.rule_id,
            "score_state": list(self.score_state),
            "tricks_remaining": self.tricks_remaining,
            "variant_action": self.variant_action,
        }


@dataclass(frozen=True, slots=True)
class ExactVerdict:
    """The exact perfect-information comparison of two candidate cards.

    The verdict is decided in **match utility**, because that is what a
    rising-score rule claims to optimize. Deal-point regret is recorded alongside
    it and is expected to disagree: a rule that stops competing for a margin the
    rising score discards costs deal points and costs the match nothing.
    """

    rule_id: str
    score_state: tuple[int, int]
    contract: str
    tricks_remaining: int
    base_card: str
    variant_card: str
    base_regret_points: int
    variant_regret_points: int
    base_match_utility: tuple[int, int]
    variant_match_utility: tuple[int, int]
    verdict: str
    deal_point_verdict: str

    def to_data(self) -> dict[str, object]:
        return {
            "base_card": self.base_card,
            "base_match_utility": list(self.base_match_utility),
            "base_regret_points": self.base_regret_points,
            "contract": self.contract,
            "deal_point_verdict": self.deal_point_verdict,
            "rule_id": self.rule_id,
            "score_state": list(self.score_state),
            "tricks_remaining": self.tricks_remaining,
            "variant_card": self.variant_card,
            "variant_match_utility": list(self.variant_match_utility),
            "variant_regret_points": self.variant_regret_points,
            "verdict": self.verdict,
        }


def _classify(base_regret: int, variant_regret: int) -> str:
    """Classify from two "lower is worse for the rule" regret values."""

    if base_regret == variant_regret:
        return "neutral"
    return "rule_helps" if base_regret < variant_regret else "rule_hurts"


def _classify_utility(
    base: tuple[int, int], variant: tuple[int, int]
) -> str:
    if base == variant:
        return "neutral"
    return "rule_helps" if base > variant else "rule_hurts"


def _action_label(action: object) -> str:
    if isinstance(action, PlayCardAction):
        return f"play:{card_to_code(action.card)}"
    if isinstance(action, ShowAction):
        return (
            f"show:{card_to_code(action.shown_card)}:"
            f"{action.declared_contract.value}"
        )
    raise DiagnosisError("unknown action type in a diagnosis record")


def _match_role(score: tuple[int, int], seat: int) -> str:
    team = seat % 2
    if score == (0, 0):
        return "table"
    up = 0 if score[0] > 0 else 1
    return "up" if up == team else "down"


def play_rule_preconditions(features) -> dict[str, bool]:
    """Evaluate each play rule's documented precondition, rule-free.

    This separates two very different reasons a rule can be invisible:

    * its condition never holds, so the rule is **inert**;
    * its condition holds but the preference it expresses coincides with what the
      policy would have chosen anyway, so the rule is **redundant**.

    A decision-change count alone cannot tell them apart, and the distinction
    decides whether a rule should be retuned or removed.
    """

    from tuppi_agents.match_aware import decisive_trick_pending, margin_is_worthless

    return {
        "match.play.coast_when_margin_worthless.v1": bool(
            margin_is_worthless(features)
        ),
        "match.play.secure_decisive_trick.v1": bool(decisive_trick_pending(features)),
    }


@dataclass(frozen=True, slots=True)
class CensusResult:
    """Everything the exact per-decision census produced."""

    decisions_by_phase: dict[str, int]
    divergences: tuple[DecisionDivergence, ...]
    exact_verdicts: tuple[ExactVerdict, ...]
    sampled_verdicts: tuple[dict[str, object], ...]
    out_of_range_play_divergences: int
    show_boundary_margins: tuple[dict[str, object], ...]
    precondition_holds: dict[str, int]
    deals_played: int
    schema_version: str = field(default=DIAGNOSIS_SCHEMA_VERSION, init=False)


def rule_activation_census(
    *,
    deals: int = DEFAULT_CENSUS_DEALS,
    score_states: tuple[tuple[int, int], ...] = CENSUS_SCORE_STATES,
    maximum_tricks_remaining: int = DEFAULT_MAXIMUM_TRICKS_REMAINING,
    samples_per_decision: int = DEFAULT_SAMPLES_PER_DECISION,
    variants: tuple[DiagnosticVariant, ...] | None = None,
    progress=None,
) -> CensusResult:
    """Replay fresh deals and re-decide every position with one rule off.

    The frozen ``match_aware_v1`` agent occupies all four seats, so every position
    visited is one the rules under test actually produce. Divergence is therefore
    measured *along the base trajectory*: it says how often a rule changes a
    decision the base agent would face, not what happens if a variant plays the
    whole match. The fresh-design ablation answers the latter.
    """

    if type(deals) is not int or deals <= 0:
        raise DiagnosisError("census deals must be a positive integer")
    if type(samples_per_decision) is not int or samples_per_decision < 0:
        raise DiagnosisError("samples_per_decision must be a nonnegative integer")
    chosen = diagnostic_variants() if variants is None else variants
    if not chosen:
        raise DiagnosisError("the census needs at least one variant")

    specifications = phase4_specifications_by_profile_key()
    base_specification = specifications[BASE_PROFILE_KEY]
    bank = census_bank(stream_count=max(deals, 1))

    decisions_by_phase: dict[str, int] = {"SHOWING": 0, "TRICK_PLAY": 0}
    divergences: list[DecisionDivergence] = []
    verdicts: list[ExactVerdict] = []
    sampled: list[dict[str, object]] = []
    boundaries: list[dict[str, object]] = []
    preconditions: dict[str, int] = {rule_id: 0 for rule_id in MATCH_PLAY_RULES}
    out_of_range = 0
    deals_played = 0

    total = len(score_states) * deals
    for state_index, score_state in enumerate(score_states):
        for deal_index in range(deals):
            stream = bank.stream(deal_index)
            stream_deal = stream.deal(state_index)
            state = create_match(
                initial_score=MatchScore(*score_state),
                initial_dealer=stream.initial_dealer,
                match_ref=f"census-{state_index:02d}-{deal_index:04d}",
            )
            state = begin_explicit_deal(
                state, ExplicitDeal(dealer=state.dealer, hands=stream_deal.hands)
            )
            base_agents = tuple(
                construct_agent(base_specification, seat=seat) for seat in range(4)
            )
            variant_agents = {
                item.label: tuple(
                    construct_agent(item.specification, seat=seat)
                    for seat in range(4)
                )
                for item in chosen
            }
            deals_played += 1
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                actor = state.current_actor
                observation = match_observation_for(state, actor)
                deal_state = state.active_deal
                base_action = base_agents[actor].choose_action(observation)
                decisions_by_phase[observation.phase.value] += 1
                if observation.phase is EnginePhase.SHOWING:
                    boundaries.append(
                        _show_boundary_record(
                            observation=observation,
                            score_state=score_state,
                            base_specification=base_specification,
                        )
                    )
                else:
                    features = build_features(observation, include_inference=True)
                    for rule_id, holds in play_rule_preconditions(features).items():
                        if holds:
                            preconditions[rule_id] += 1
                for item in chosen:
                    variant_action = variant_agents[item.label][actor].choose_action(
                        observation
                    )
                    if variant_action == base_action:
                        continue
                    rule_id = item.changed_rule_id or "all_match_rules"
                    divergences.append(
                        DecisionDivergence(
                            rule_id=rule_id,
                            phase=observation.phase.value,
                            score_state=score_state,
                            match_role=_match_role(score_state, actor),
                            contract=(
                                None
                                if observation.contract is None
                                else observation.contract.value
                            ),
                            acting_seat=actor,
                            tricks_remaining=(
                                TRICKS_PER_DEAL - len(observation.completed_tricks)
                            ),
                            base_action=_action_label(base_action),
                            variant_action=_action_label(variant_action),
                        )
                    )
                    if not (
                        isinstance(base_action, PlayCardAction)
                        and isinstance(variant_action, PlayCardAction)
                        and deal_state is not None
                    ):
                        continue
                    exact = _exact_verdict(
                        deal_state=deal_state,
                        rule_id=rule_id,
                        score_state=score_state,
                        base_card=base_action.card,
                        variant_card=variant_action.card,
                        maximum_tricks_remaining=maximum_tricks_remaining,
                    )
                    if exact is None:
                        out_of_range += 1
                    else:
                        verdicts.append(exact)
                        if samples_per_decision:
                            sampled.append(
                                _sampled_verdict(
                                    observation=observation,
                                    rule_id=rule_id,
                                    score_state=score_state,
                                    base_card=base_action.card,
                                    variant_card=variant_action.card,
                                    samples=samples_per_decision,
                                    maximum_tricks_remaining=(
                                        maximum_tricks_remaining
                                    ),
                                )
                            )
                state = apply_match_action(state, base_action)
            if progress is not None:
                progress(state_index * deals + deal_index + 1, total)

    return CensusResult(
        decisions_by_phase=decisions_by_phase,
        divergences=tuple(divergences),
        exact_verdicts=tuple(verdicts),
        sampled_verdicts=tuple(sampled),
        out_of_range_play_divergences=out_of_range,
        show_boundary_margins=tuple(boundaries),
        precondition_holds=dict(preconditions),
        deals_played=deals_played,
    )


def _show_boundary_record(
    *,
    observation: PlayerObservation,
    score_state: tuple[int, int],
    base_specification,
) -> dict[str, object]:
    """Record how far a showing decision sits from its RAMI threshold.

    The two show rules move a threshold. Whether they *can* matter depends on how
    many hands fall inside the shift, which is a property of the score state and
    the hand distribution, not of the rule's rationale.
    """

    from tuppi_agents import registered_profiles

    profile = registered_profiles()[BASE_PROFILE_KEY]
    features = build_features(observation, include_inference=True)
    scalars = dict(showing_scalars(features, profile))
    score = scalars.get("simple_rami_score")
    threshold = scalars.get("simple_rami_threshold")
    return {
        "acting_seat": observation.observing_seat,
        "distance_to_threshold": (
            None if score is None or threshold is None else round(score - threshold, 6)
        ),
        "match_role": _match_role(score_state, observation.observing_seat),
        "rami_score": score,
        "rami_threshold": threshold,
        "score_state": list(score_state),
    }


def _exact_verdict(
    *,
    deal_state: DealState,
    rule_id: str,
    score_state: tuple[int, int],
    base_card,
    variant_card,
    maximum_tricks_remaining: int,
) -> ExactVerdict | None:
    """Solve the real position exactly and compare the two candidate cards."""

    try:
        solution = solve_late_game(
            deal_state, maximum_tricks_remaining=maximum_tricks_remaining
        )
    except SolverBudgetError:
        return None
    base_regret = solution.regret_in_deal_points(base_card)
    variant_regret = solution.regret_in_deal_points(variant_card)
    base_utility = solution.match_utility_for(base_card)
    variant_utility = solution.match_utility_for(variant_card)
    return ExactVerdict(
        rule_id=rule_id,
        score_state=score_state,
        contract=solution.contract.value,
        tricks_remaining=solution.tricks_remaining,
        base_card=card_to_code(base_card),
        variant_card=card_to_code(variant_card),
        base_regret_points=base_regret,
        variant_regret_points=variant_regret,
        base_match_utility=base_utility,
        variant_match_utility=variant_utility,
        verdict=_classify_utility(base_utility, variant_utility),
        deal_point_verdict=_classify(base_regret, variant_regret),
    )


def _sampled_verdict(
    *,
    observation: PlayerObservation,
    rule_id: str,
    score_state: tuple[int, int],
    base_card,
    variant_card,
    samples: int,
    maximum_tricks_remaining: int,
) -> dict[str, object]:
    """Compare two cards over exactly-uniform samples of the hidden hands.

    Every sample is solved exactly, so the only inexactness is the measure over
    worlds - and that measure is uniform-over-feasible, which is a neutral
    reference and *not* a posterior over the opponents' hands.
    """

    model = HardConstraintModel.build(observation)
    if not model.unknown_cards:
        return {
            "base_mean_points": None,
            "note": "the hidden hands are fully determined by public information",
            "rule_id": rule_id,
            "samples_solved": 0,
            "score_state": list(score_state),
            "variant_mean_points": None,
            "verdict": "fully_determined",
        }
    sampler = UniformFeasibleSampler.build(
        model,
        seed=content_digest(
            {
                "deal_ref": observation.deal_ref,
                "match_ref": observation.match_ref,
                "root_seed": SAMPLING_ROOT_SEED,
                "tricks_completed": len(observation.completed_tricks),
            }
        ),
    )
    base_total = 0
    variant_total = 0
    base_better = 0
    variant_better = 0
    solved = 0
    for assignment in sampler.sample(samples):
        continuation = hypothetical_continuation(observation, assignment)
        try:
            solution = solve_late_game(
                continuation.state,
                maximum_tricks_remaining=maximum_tricks_remaining,
            )
        except SolverBudgetError:
            continue
        base_total -= solution.regret_in_deal_points(base_card)
        variant_total -= solution.regret_in_deal_points(variant_card)
        # The verdict counts worlds in which one card reaches a strictly better
        # *match* state. Deal points are recorded below as description only: a
        # rule that deliberately spends a worthless margin must not be scored
        # down for spending it.
        base_utility = solution.match_utility_for(base_card)
        variant_utility = solution.match_utility_for(variant_card)
        if base_utility > variant_utility:
            base_better += 1
        elif base_utility < variant_utility:
            variant_better += 1
        solved += 1
    if not solved:
        return {
            "base_mean_points": None,
            "note": "every sampled world was outside the exact solver budget",
            "rule_id": rule_id,
            "samples_solved": 0,
            "score_state": list(score_state),
            "variant_mean_points": None,
            "verdict": "out_of_range",
        }
    return {
        "base_mean_points": float(Fraction(base_total, solved)),
        "feasible_assignment_count": feasible_assignment_count(model),
        "measure": "uniform_over_feasible_assignments",
        "measure_caveat": (
            "Uniform over feasible assignments is a neutral reference measure, "
            "not a posterior over opponent hands."
        ),
        "rule_id": rule_id,
        "samples_solved": solved,
        "score_state": list(score_state),
        "variant_mean_points": float(Fraction(variant_total, solved)),
        "verdict": (
            "neutral"
            if base_better == variant_better
            else ("rule_helps" if base_better > variant_better else "rule_hurts")
        ),
        "verdict_basis": "match_utility_per_sampled_world",
        "worlds_base_better": base_better,
        "worlds_variant_better": variant_better,
    }


def _rule_status(precondition_held: int | None, decision_changes: int) -> str:
    """Name why a rule is invisible, when it is.

    ``inert`` - the condition never held, so the rule had no opportunity.
    ``redundant`` - the condition held but the policy chose the same action anyway.
    ``active`` - the rule changed at least one decision.
    ``not_measured`` - no precondition was evaluated (a showing rule).
    """

    if precondition_held is None:
        return "not_measured"
    if decision_changes:
        return "active"
    return "inert" if precondition_held == 0 else "redundant"


def summarize_census(result: CensusResult) -> dict[str, object]:
    """Turn the raw census into per-rule aggregates."""

    if not isinstance(result, CensusResult):
        raise DiagnosisError("summarize_census requires a CensusResult")
    per_rule: dict[str, dict[str, object]] = {}
    for rule_id in MATCH_RULES:
        changes = [item for item in result.divergences if item.rule_id == rule_id]
        exact = [item for item in result.exact_verdicts if item.rule_id == rule_id]
        sampled = [
            item for item in result.sampled_verdicts if item["rule_id"] == rule_id
        ]
        by_state: dict[str, int] = {}
        for item in changes:
            key = f"{item.score_state[0]}-{item.score_state[1]}"
            by_state[key] = by_state.get(key, 0) + 1
        holds = result.precondition_holds.get(rule_id)
        per_rule[rule_id] = {
            "decision_changes": len(changes),
            "precondition_held": holds,
            "status": _rule_status(holds, len(changes)),
            "decision_changes_by_score_state": dict(sorted(by_state.items())),
            "exact_verdicts": {
                "deal_point_neutral": sum(
                    1 for item in exact if item.deal_point_verdict == "neutral"
                ),
                "deal_points_spent_by_rule": sum(
                    1 for item in exact if item.deal_point_verdict == "rule_hurts"
                ),
                "neutral": sum(1 for item in exact if item.verdict == "neutral"),
                "rule_helps": sum(1 for item in exact if item.verdict == "rule_helps"),
                "rule_hurts": sum(1 for item in exact if item.verdict == "rule_hurts"),
                "total": len(exact),
            },
            "phase": (
                "SHOWING" if rule_id in MATCH_SHOW_RULES else "TRICK_PLAY"
            ),
            "sampled_verdicts": {
                "neutral": sum(1 for item in sampled if item["verdict"] == "neutral"),
                "rule_helps": sum(
                    1 for item in sampled if item["verdict"] == "rule_helps"
                ),
                "rule_hurts": sum(
                    1 for item in sampled if item["verdict"] == "rule_hurts"
                ),
                "total": len(sampled),
            },
        }
    margins = [
        item["distance_to_threshold"]
        for item in result.show_boundary_margins
        if item["distance_to_threshold"] is not None
    ]
    return {
        "deals_played": result.deals_played,
        "decisions_by_phase": dict(sorted(result.decisions_by_phase.items())),
        "out_of_range_play_divergences": result.out_of_range_play_divergences,
        "per_rule": per_rule,
        "schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "show_threshold_margin": {
            "count": len(margins),
            "mean": round(sum(margins) / len(margins), 6) if margins else None,
            "within_3_points_of_threshold": sum(
                1 for value in margins if abs(value) <= 3.0
            ),
        },
        "trajectory_caveat": (
            "Divergence is counted along the frozen agent's own trajectory. It "
            "measures how often a rule changes a decision, not what happens if a "
            "variant plays every decision of a match."
        ),
    }


def show_rule_census(
    *,
    deals: int = 256,
    score_states: tuple[tuple[int, int], ...] = CENSUS_SCORE_STATES,
    variants: tuple[DiagnosticVariant, ...] | None = None,
) -> dict[str, object]:
    """Census the two showing rules over showing decisions only.

    A deal contains at most four showing decisions and up to fifty-two card
    plays, so a census driven by full deals spends almost all its time on
    positions the showing rules cannot touch. This instrument replays only the
    showing phase, which buys roughly two orders of magnitude more showing
    decisions for the same cost - and the showing rules are the two whose
    threshold Phase 5A actually suspected.
    """

    if type(deals) is not int or deals <= 0:
        raise DiagnosisError("show census deals must be a positive integer")
    chosen = tuple(
        item
        for item in (diagnostic_variants() if variants is None else variants)
        if item.changed_rule_id in MATCH_SHOW_RULES
    )
    if not chosen:
        raise DiagnosisError("the show census needs at least one showing variant")

    specifications = phase4_specifications_by_profile_key()
    base_specification = specifications[BASE_PROFILE_KEY]
    bank = census_bank(stream_count=max(deals, 1))

    decisions = 0
    contract_flips: dict[str, int] = {item.label: 0 for item in chosen}
    card_only_changes: dict[str, int] = {item.label: 0 for item in chosen}
    eligible: dict[str, int] = {item.label: 0 for item in chosen}
    margins: list[float] = []
    for state_index, score_state in enumerate(score_states):
        for deal_index in range(deals):
            stream = bank.stream(deal_index % bank.stream_count)
            stream_deal = stream.deal(state_index + 1)
            state = create_match(
                initial_score=MatchScore(*score_state),
                initial_dealer=stream.initial_dealer,
                match_ref=f"showcensus-{state_index:02d}-{deal_index:05d}",
            )
            state = begin_explicit_deal(
                state, ExplicitDeal(dealer=state.dealer, hands=stream_deal.hands)
            )
            base_agents = tuple(
                construct_agent(base_specification, seat=seat) for seat in range(4)
            )
            variant_agents = {
                item.label: tuple(
                    construct_agent(item.specification, seat=seat)
                    for seat in range(4)
                )
                for item in chosen
            }
            while state.phase is EnginePhase.SHOWING:
                actor = state.current_actor
                observation = match_observation_for(state, actor)
                base_action = base_agents[actor].choose_action(observation)
                decisions += 1
                record = _show_boundary_record(
                    observation=observation,
                    score_state=score_state,
                    base_specification=base_specification,
                )
                if record["distance_to_threshold"] is not None:
                    margins.append(float(record["distance_to_threshold"]))
                for item in chosen:
                    variant_action = variant_agents[item.label][actor].choose_action(
                        observation
                    )
                    if variant_action == base_action:
                        continue
                    if (
                        isinstance(base_action, ShowAction)
                        and isinstance(variant_action, ShowAction)
                        and base_action.declared_contract
                        is not variant_action.declared_contract
                    ):
                        contract_flips[item.label] += 1
                    else:
                        card_only_changes[item.label] += 1
                for item in chosen:
                    role = _match_role(score_state, actor)
                    if item.changed_rule_id == "match.show.protect_terminal_lead.v1":
                        if role == "up" and max(score_state) >= 48:
                            eligible[item.label] += 1
                    elif role == "down" and max(score_state) >= 44:
                        eligible[item.label] += 1
                state = apply_match_action(state, base_action)

    return {
        "decisions": decisions,
        "interpretation": (
            "A contract flip is the only change that can move a match: the shown "
            "card is public information but does not change the contract, the "
            "leader, or any trick."
        ),
        "per_variant": {
            item.label: {
                "card_only_changes": card_only_changes[item.label],
                "changed_rule_id": item.changed_rule_id,
                "contract_flips": contract_flips[item.label],
                "eligible_decisions": eligible[item.label],
            }
            for item in chosen
        },
        "schema_version": "tuppi.exact.show_rule_census.v1",
        "threshold_margin": {
            "count": len(margins),
            "mean": round(sum(margins) / len(margins), 6) if margins else None,
            "within_2_points": sum(1 for value in margins if abs(value) <= 2.0),
            "within_3_points": sum(1 for value in margins if abs(value) <= 3.0),
        },
    }


def reachable_positive_scores() -> tuple[int, ...]:
    """Every rising score a partnership can actually hold mid-match.

    Derived, not assumed: every deal-point value under ``project_target_v1`` is a
    multiple of four, an unreset score is a sum of such values, and the match ends
    at 52. So the reachable positive nonterminal scores are exactly the multiples
    of four from 4 to 48.
    """

    from tuppi_rules import MATCH_TARGET

    from .solver import deal_outcome_for_split

    values: set[int] = set()
    for split in range(TRICKS_PER_DEAL + 1):
        values.add(
            deal_outcome_for_split(
                contract=Contract.NOLO, declarer=None, team0_tricks=split
            ).points
        )
        values.add(
            deal_outcome_for_split(
                contract=Contract.RAMI, declarer=0, team0_tricks=split
            ).points
        )
    step = min(values)
    if any(value % step for value in values):
        raise DiagnosisError(
            "deal points are not all multiples of the smallest award; the score "
            "lattice argument does not hold for this ruleset"
        )
    return tuple(range(step, MATCH_TARGET, step))


def protect_threshold_lattice(
    distances: tuple[int, ...] = (0, 2, 4, 6, 8, 12)
) -> dict[str, object]:
    """Group protect distances by the scores at which the rule can actually fire.

    ``match.show.protect_terminal_lead.v1`` fires when the own partnership is up
    and within ``match_protect_distance`` of the target. Because the reachable
    scores form a lattice of multiples of four, most distances are
    *indistinguishable*: a distance of 0 or 2 can never fire at all, and 4 and 6
    both fire only at 48. The parameter therefore has far fewer distinct
    behaviours than its range suggests, which changes what "the threshold is
    mis-set" can even mean.
    """

    from tuppi_rules import MATCH_TARGET

    reachable = reachable_positive_scores()
    firings: dict[int, tuple[int, ...]] = {}
    for distance in distances:
        firings[distance] = tuple(
            score for score in reachable if MATCH_TARGET - score <= distance
        )
    classes: dict[tuple[int, ...], list[int]] = {}
    for distance, scores in firings.items():
        classes.setdefault(scores, []).append(distance)
    return {
        "distinct_behaviours": len(classes),
        "equivalence_classes": [
            {
                "distances": sorted(members),
                "firing_scores": list(scores),
                "is_equivalent_to_rule_off": not scores,
            }
            for scores, members in sorted(
                classes.items(), key=lambda item: (len(item[0]), item[0])
            )
        ],
        "firings_by_distance": {
            str(distance): list(scores) for distance, scores in sorted(firings.items())
        },
        "reachable_positive_scores": list(reachable),
        "schema_version": "tuppi.exact.protect_threshold_lattice.v1",
        "why_it_matters": (
            "Sweeping the protected distance cannot explore a continuum. Only the "
            "scores in the lattice exist, so several distances are behaviourally "
            "identical and a null result at one of them is a null result at all of "
            "its class."
        ),
    }


# ------------------------------------------------------------ match-level design


def rule_ablation_comparisons(
    variants: tuple[DiagnosticVariant, ...] | None = None,
) -> tuple[tuple[MatchComparison, DiagnosticVariant], ...]:
    """Build one complete-match comparison per variant.

    The candidate is always the frozen ``match_aware_v1``; the opponent is the
    variant. A positive ``p_win`` therefore means *the rule helps*, which keeps
    the sign convention identical to the Phase 5A ablation.
    """

    specifications = phase4_specifications_by_profile_key()
    base = specifications[BASE_PROFILE_KEY]
    chosen = diagnostic_variants() if variants is None else variants
    built: list[tuple[MatchComparison, DiagnosticVariant]] = []
    for item in chosen:
        built.append(
            (
                MatchComparison.build(
                    name=f"phase5b_{item.label}",
                    candidate_profile_key=BASE_PROFILE_KEY,
                    opponent_profile_key=f"{BASE_PROFILE_KEY}::{item.label}",
                    candidate_agent_id=base.agent_id,
                    opponent_agent_id=item.specification.agent_id,
                    result_class="ablation",
                    hypothesis=item.rationale,
                ),
                item,
            )
        )
    return tuple(built)


def _ablation_unit(payload: tuple) -> tuple[str, int, dict]:
    """Process-pool entry point. Returns canonical data, never live objects.

    The variant is rebuilt from its label inside the worker rather than pickled,
    which keeps the deterministic identity derivation - and its validation - inside
    the process that uses it.
    """

    label, comparison_data, stream_count, safety_cap, ordinal = payload
    from .variants import variants_by_label

    variant = variants_by_label()[label]
    comparison = MatchComparison.build(
        name=comparison_data["name"],
        candidate_profile_key=comparison_data["candidate_profile_key"],
        opponent_profile_key=comparison_data["opponent_profile_key"],
        candidate_agent_id=comparison_data["candidate_agent_id"],
        opponent_agent_id=comparison_data["opponent_agent_id"],
        result_class=comparison_data["result_class"],
        hypothesis=comparison_data["hypothesis"],
        starting_score=tuple(comparison_data["starting_score"]),
    )
    base = phase4_specifications_by_profile_key()[BASE_PROFILE_KEY]
    bank = ablation_bank(stream_count=stream_count)
    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=lambda seat: construct_agent(base, seat=seat),
        build_opponent=variant.agent_builder(),
    )
    return (label, ordinal, record.to_data())


def run_rule_ablation(
    *,
    pairs: int = DEFAULT_ABLATION_PAIRS,
    safety_cap: int = DEFAULT_SAFETY_CAP,
    variants: tuple[DiagnosticVariant, ...] | None = None,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Run the per-rule complete-match ablation on a fresh Phase 5B bank.

    Execution reuses the frozen Phase 5A protocol - :func:`run_pair`, the same
    complementary legs, the same censoring policy, the same paired inference - and
    supplies its own agent builders, which is the one thing Phase 5A's executor
    cannot do for a profile outside the Phase 4 registry. Nothing in
    ``tuppi_match`` is modified.

    ``workers`` only changes wall-clock time. Every pair is a pure function of
    (bank, comparison, safety cap, ordinal), so the worker count cannot change a
    single recorded result.
    """

    if type(pairs) is not int or pairs <= 0:
        raise DiagnosisError("ablation pair count must be a positive integer")
    comparisons = rule_ablation_comparisons(variants)
    bank = ablation_bank(stream_count=pairs)

    units = [
        (
            variant.label,
            comparison.to_data(),
            pairs,
            safety_cap,
            ordinal,
        )
        for comparison, variant in comparisons
        for ordinal in range(pairs)
    ]
    collected: dict[str, dict[int, PairRecord]] = {
        variant.label: {} for _, variant in comparisons
    }
    total = len(units)
    done = 0
    if workers is None or workers <= 1:
        for unit in units:
            label, ordinal, data = _ablation_unit(unit)
            collected[label][ordinal] = _pair_from_data(data)
            done += 1
            if progress is not None:
                progress(done, total)
    else:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            for label, ordinal, data in pool.map(_ablation_unit, units, chunksize=1):
                collected[label][ordinal] = _pair_from_data(data)
                done += 1
                if progress is not None:
                    progress(done, total)

    results: list[dict[str, object]] = []
    for comparison, variant in comparisons:
        frozen_records = tuple(
            collected[variant.label][ordinal] for ordinal in range(pairs)
        )
        results.append(
            {
                "comparison_id": comparison.comparison_id,
                "hypothesis": comparison.hypothesis,
                "name": comparison.name,
                "primary_match_inference": pair_inference(
                    frozen_records,
                    confidence_level=CONFIDENCE_LEVEL,
                    analysis_seed=ABLATION_ROOT_SEED,
                    bootstrap_replicates=BOOTSTRAP_REPLICATES,
                    sign_flip_replicates=SIGN_FLIP_REPLICATES,
                ),
                "secondary_metrics": secondary_metrics(frozen_records),
                "variant": variant.to_data(),
            }
        )
    return {
        "bank": bank.to_data(),
        "comparisons": results,
        "pair_count": pairs,
        "safety_cap": safety_cap,
        "schema_version": "tuppi.exact.rule_ablation_report.v1",
        "worker_independence": (
            "Every pair is a pure function of the bank, comparison, safety cap, "
            "and ordinal, so the worker count changes wall-clock time only."
        ),
        "sign_convention": (
            "The candidate is always the frozen match_aware_v1 and the opponent is "
            "the variant, so p_win above 0.5 means the changed rule helps."
        ),
    }


# ------------------------------------------------------------------- top report


def diagnose(
    *,
    census_deals: int = DEFAULT_CENSUS_DEALS,
    samples_per_decision: int = DEFAULT_SAMPLES_PER_DECISION,
    show_census_deals: int = 0,
    ablation_pairs: int | None = None,
    maximum_tricks_remaining: int = DEFAULT_MAXIMUM_TRICKS_REMAINING,
    progress=None,
) -> dict[str, object]:
    """Run the whole diagnosis and return one canonical report.

    ``ablation_pairs`` of ``None`` skips the expensive match-level instrument, so
    the exact instruments can be produced and checked on their own.
    """

    certificate = monotonicity_certificate()
    composition = composition_check()
    census = rule_activation_census(
        deals=census_deals,
        samples_per_decision=samples_per_decision,
        maximum_tricks_remaining=maximum_tricks_remaining,
        progress=progress,
    )
    report: dict[str, object] = {
        "census": summarize_census(census),
        "instruments": [
            "exhaustive monotonicity certificate",
            "exact reachable-score lattice for the protect threshold",
            "exact activation census along the frozen trajectory",
            "exact perfect-information per-decision verdicts",
            "uniform-measure per-decision verdicts",
        ]
        + (["fresh-design complete-match per-rule ablation"] if ablation_pairs else []),
        "monotonicity_certificate": certificate,
        "protect_threshold_lattice": protect_threshold_lattice(),
        "schema_version": DIAGNOSIS_SCHEMA_VERSION,
        "structural_verdict": {
            "claim": (
                "Under perfect information no rule that changes a card can improve "
                "the match outcome, because match utility is weakly monotone in "
                "the trick split and the trick-optimal action set is therefore "
                "contained in the match-optimal one."
            ),
            "holds": bool(certificate["holds"]),
            "rules_covered": list(MATCH_PLAY_RULES),
            "scope": (
                "Perfect information. Under imperfect information a step-shaped "
                "utility can justify trading expected points for a higher "
                "probability of a win, which these rules do not compute."
            ),
        },
        "variant_composition_check": composition,
    }
    if show_census_deals:
        report["show_rule_census"] = show_rule_census(deals=show_census_deals)
    if ablation_pairs:
        report["rule_ablation"] = run_rule_ablation(
            pairs=ablation_pairs, progress=progress
        )
    return report
