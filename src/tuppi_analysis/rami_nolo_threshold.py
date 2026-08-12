"""Controlled RAMI-versus-NOLO showing-threshold experiment.

This module is deliberately an evaluator, not an agent profile.  It reads the
registered ``partner_aware_v1`` profile, forces one of that policy's legal
showing actions at an immutable decision state, and then lets four ordinary
``partner_aware_v1`` instances finish the deal.  It never constructs, opens,
or reads a fixture bank; deals are generated directly from independent,
declared seeds with :func:`tuppi_eval.deals.generate_base_deal`.

The experiment's independent sampling cluster is the generated source deal.
A source deal can contain several showing decisions, so confidence intervals
resample whole source deals rather than treating those decisions as
independent.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import math
import random
from statistics import fmean

from tuppi_agents import (
    build_features,
    construct_registered_agent,
    phase4_specifications_by_profile_key,
    registered_profiles,
)
from tuppi_agents.action_scoring import ScoredActions
from tuppi_agents.features import PublicFeatures
from tuppi_agents.showing import simple_nolo_score, simple_rami_score
from tuppi_engine import (
    EnginePhase,
    MatchState,
    PlayerObservation,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    play_active_deal,
)
from tuppi_engine.results import DealResult
from tuppi_eval.deals import DealerPolicy, generate_base_deal
from tuppi_eval.serialization import canonical_json_bytes, content_digest
from tuppi_rules import (
    Contract,
    MatchScore,
    SUIT_ORDER,
    Team,
    card_to_code,
    partner_for_seat,
    score_nolo,
    score_rami_for_declarer,
    team_for_seat,
)


EXPERIMENT_SCHEMA_VERSION = "tuppi.analysis.rami_nolo_threshold.v1"
DECISION_RECORD_SCHEMA_VERSION = "tuppi.analysis.rami_nolo_decision.v1"
PRODUCTION_PROFILE_KEY = "partner_aware_v1"
SOURCE_KIND = "direct_deterministic_unsealed_generation"
DEFAULT_TUNING_SEED = "rami-nolo-threshold-tuning-v1"
DEFAULT_VALIDATION_SEED = "rami-nolo-threshold-validation-v1"
DEFAULT_ANALYSIS_SEED = "rami-nolo-threshold-analysis-v1"

# Match score is not active in partner_aware_v1, but a deterministic spread is
# retained so that this fact can be checked rather than assumed.  Every score
# is nonterminal and covers table, up-team, down-team, and near-target states.
DEFAULT_MATCH_SCORE_PATTERN: tuple[tuple[int, int], ...] = (
    (0, 0),
    (20, 0),
    (0, 20),
    (44, 0),
    (0, 44),
)


class ExperimentError(ValueError):
    """The experiment configuration or an internal invariant is invalid."""


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Immutable configuration for one tuning/validation run."""

    tuning_decisions: int = 4_096
    validation_decisions: int = 4_096
    tuning_seed: str = DEFAULT_TUNING_SEED
    validation_seed: str = DEFAULT_VALIDATION_SEED
    analysis_seed: str = DEFAULT_ANALYSIS_SEED
    bootstrap_replicates: int = 5_000
    workers: int = 1
    match_score_pattern: tuple[tuple[int, int], ...] = DEFAULT_MATCH_SCORE_PATTERN

    def __post_init__(self) -> None:
        for label, value in (
            ("tuning_decisions", self.tuning_decisions),
            ("validation_decisions", self.validation_decisions),
            ("bootstrap_replicates", self.bootstrap_replicates),
            ("workers", self.workers),
        ):
            if type(value) is not int or value <= 0:
                raise ExperimentError(f"{label} must be a positive integer")
        for label, value in (
            ("tuning_seed", self.tuning_seed),
            ("validation_seed", self.validation_seed),
            ("analysis_seed", self.analysis_seed),
        ):
            if not isinstance(value, str) or not value:
                raise ExperimentError(f"{label} must be a nonempty string")
        if self.tuning_seed == self.validation_seed:
            raise ExperimentError("tuning and validation seeds must be distinct")
        if type(self.match_score_pattern) is not tuple or not self.match_score_pattern:
            raise ExperimentError("match_score_pattern must be a nonempty tuple")
        for value in self.match_score_pattern:
            if type(value) is not tuple or len(value) != 2:
                raise ExperimentError("each match-score pattern item must be a pair")
            try:
                MatchScore(value[0], value[1])
            except Exception as exc:  # converted to a configuration-level error
                raise ExperimentError("match_score_pattern contains an invalid score") from exc

    def to_data(self) -> dict[str, object]:
        return {
            "analysis_seed": self.analysis_seed,
            "bootstrap_replicates": self.bootstrap_replicates,
            "generator": {
                "dealer_policy": DealerPolicy.ROUND_ROBIN.value,
                "initial_dealer": 0,
                "source_kind": SOURCE_KIND,
            },
            "match_score_pattern": [list(value) for value in self.match_score_pattern],
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
            "sealed_bank_opened": False,
            "tuning_decisions": self.tuning_decisions,
            "tuning_seed": self.tuning_seed,
            "validation_decisions": self.validation_decisions,
            "validation_seed": self.validation_seed,
            "workers": self.workers,
        }


def current_production_rule() -> dict[str, object]:
    """Return the registered rule actually used by ``partner_aware_v1``."""

    profile = registered_profiles()[PRODUCTION_PROFILE_KEY]
    threshold = float(profile.parameter("simple_rami_threshold"))
    veto = float(profile.parameter("simple_nolo_veto_threshold"))
    return {
        "card_selection": (
            "Within the selected contract, maximize (-shown rank, -HDCS suit "
            "index): the lowest eligible rank, then hearts/diamonds/clubs/spades."
        ),
        "decision": "RAMI iff simple_rami_score >= threshold AND simple_nolo_score <= veto",
        "match_score_affects_decision": bool(profile.match_state_enabled),
        "nolo_score": {
            "formula": (
                "1.5*low_card_count + 3*void_count + 2*singleton_count + "
                "doubleton_count - top_five_count - 0.5*honour_count"
            ),
            "low_card_definition": "rank <= 4",
            "top_five_definition": "rank >= 10",
            "honour_definition": "rank >= jack",
            "veto_operator": ">",
            "veto_threshold": veto,
        },
        "profile_id": profile.profile_id,
        "profile_key": profile.profile_key,
        "rami_score": {
            "control_cards_definition": "aces + kings",
            "formula": (
                "HCP + 0.5*aces + 0.25*control_cards + "
                "0.5*max(0, longest_suit_length-4)"
            ),
            "hcp_weights": {"ace": 4, "king": 3, "queen": 2, "jack": 1},
            "operator": ">=",
            "threshold": threshold,
        },
        "showing_eligibility": {
            "eligible_ranks": [3, 4, 5, 6, 7, 8, 9],
            "fallback_hierarchy": [
                "eligible card of the contract colour",
                "any eligible 3-9 card with a verbal declaration",
                "any hand card with a verbal declaration",
            ],
            "nolo_colour": "black (clubs or spades)",
            "rami_colour": "red (hearts or diamonds)",
        },
    }


@lru_cache(maxsize=1)
def _partner_agents() -> tuple[object, object, object, object]:
    specification = phase4_specifications_by_profile_key()[PRODUCTION_PROFILE_KEY]
    return tuple(
        construct_registered_agent(specification, seat=seat) for seat in range(4)
    )  # type: ignore[return-value]


def _initial_state(
    *, split: str, root_seed: str, source_deal_index: int, score: MatchScore
) -> tuple[object, MatchState]:
    base_deal = generate_base_deal(
        root_seed=root_seed,
        index=source_deal_index,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=score,
    )
    match_ref = f"rn-{split}-{source_deal_index}"
    state = begin_explicit_deal(
        create_match(
            initial_score=score,
            initial_dealer=base_deal.dealer,
            match_ref=match_ref,
        ),
        base_deal.explicit_deal(),
    )
    return base_deal, state


def _score_for_index(
    index: int, pattern: tuple[tuple[int, int], ...]
) -> MatchScore:
    pair = pattern[index % len(pattern)]
    return MatchScore(pair[0], pair[1])


def _rank_showing(
    state: MatchState,
) -> tuple[PlayerObservation, PublicFeatures, ScoredActions]:
    actor = state.current_actor
    if actor is None or state.phase is not EnginePhase.SHOWING:
        raise ExperimentError("a showing decision requires a current showing actor")
    observation = match_observation_for(state, actor)
    features = build_features(observation, include_inference=True)
    agent = _partner_agents()[actor]
    decision = agent.decide(observation, diagnostics=False)  # type: ignore[attr-defined]
    if not isinstance(decision.action, ShowAction):
        raise ExperimentError("partner_aware_v1 returned a non-showing action")
    return observation, features, decision.scored


def forced_action_for_contract(
    scored: ScoredActions, contract: Contract
) -> ShowAction:
    """Select the policy's own best legal card conditional on a contract."""

    if not isinstance(scored, ScoredActions):
        raise ExperimentError("forced contract selection requires ScoredActions")
    if not isinstance(contract, Contract):
        raise ExperimentError("forced contract must be a Contract")
    candidates = tuple(
        candidate
        for candidate in scored.candidates
        if isinstance(candidate.action, ShowAction)
        and candidate.action.declared_contract is contract
    )
    if not candidates:
        raise ExperimentError(f"no legal {contract.value} showing action")
    action = max(candidates, key=lambda item: item.selection_key).action
    if not isinstance(action, ShowAction):  # narrowed above; defensive boundary
        raise ExperimentError("conditional showing candidate is malformed")
    return action


def apply_forced_choice(
    state: MatchState, contract: Contract
) -> tuple[MatchState, ShowAction]:
    """Apply one legal forced contract without mutating the input state."""

    observation, _features, scored = _rank_showing(state)
    action = forced_action_for_contract(scored, contract)
    if action not in observation.legal_actions:
        raise ExperimentError("forced action is outside the engine legal set")
    return apply_match_action(state, action), action


def _show_action_data(action: object) -> dict[str, object]:
    return {
        "contract": action.declared_contract.value,  # type: ignore[attr-defined]
        "seat": action.seat,  # type: ignore[attr-defined]
        "shown_card": card_to_code(action.shown_card),  # type: ignore[attr-defined]
        "shown_rank": int(action.shown_card.rank.value),  # type: ignore[attr-defined]
        "verbal_required": bool(getattr(action, "verbal_required", False)),
    }


def _engine_action_data(
    action: ShowAction, *, verbal_required: bool
) -> dict[str, object]:
    return {
        "contract": action.declared_contract.value,
        "seat": action.seat,
        "shown_card": card_to_code(action.shown_card),
        "shown_rank": int(action.shown_card.rank.value),
        "verbal_required": verbal_required,
    }


def _state_identity_data(state: MatchState) -> dict[str, object]:
    active = state.active_deal
    if active is None:
        raise ExperimentError("counterfactual state has no active deal")
    return {
        "current_actor": state.current_actor,
        "deal_id": active.deal_id,
        "dealer": active.dealer,
        "hands": [
            [card_to_code(card) for card in hand] for hand in active.hands
        ],
        "match_score": list(active.starting_score.as_tuple()),
        "phase": state.phase.value,
        "show_actions": [_show_action_data(action) for action in active.show_actions],
    }


def counterfactual_state_digest(state: MatchState) -> str:
    """Digest every private/public field that can affect the forced branch."""

    return content_digest(
        {
            "schema_version": "tuppi.analysis.counterfactual_state.v1",
            "state": _state_identity_data(state),
        }
    )


def _finish_from_action(state: MatchState, action: ShowAction) -> DealResult:
    branch = apply_match_action(state, action)
    branch = play_active_deal(branch, _partner_agents())  # type: ignore[arg-type]
    if not branch.completed_deals:
        raise ExperimentError("counterfactual branch produced no completed deal")
    return branch.completed_deals[-1].public_result


def _finish_active_state(state: MatchState) -> DealResult:
    completed = play_active_deal(state, _partner_agents())  # type: ignore[arg-type]
    if not completed.completed_deals:
        raise ExperimentError("baseline continuation produced no completed deal")
    return completed.completed_deals[-1].public_result


def _outcome_data(
    result: DealResult,
    *, acting_team: Team,
    forced_action: ShowAction,
) -> dict[str, object]:
    expected_score = (
        score_nolo(*result.team_tricks)
        if result.contract is Contract.NOLO
        else score_rami_for_declarer(result.declarer, *result.team_tricks)
    )
    if result.deal_score != expected_score:
        raise ExperimentError("counterfactual score disagrees with production scoring")
    acting_won = result.deal_score.winner_team is acting_team
    utility = result.deal_score.points if acting_won else -result.deal_score.points
    declaring_team = (
        None if result.declarer is None else team_for_seat(result.declarer)
    )
    accepted = next(
        action
        for action in result.show_actions
        if action.seat == forced_action.seat
    )
    if (
        accepted.shown_card != forced_action.shown_card
        or accepted.declared_contract is not forced_action.declared_contract
    ):
        raise ExperimentError("forced show is absent from the completed transcript")
    return {
        "acting_team_tricks": result.team_tricks[acting_team.value],
        "acting_team_won": acting_won,
        "choice": forced_action.declared_contract.value,
        "deal_outcome": result.outcome.value,
        "deal_points": result.deal_score.points,
        "declaring_team": None if declaring_team is None else int(declaring_team.value),
        "declarer": result.declarer,
        "final_deal_winner": int(result.deal_score.winner_team.value),
        "final_contract": result.contract.value,
        "opponent_team_tricks": result.team_tricks[1 - acting_team.value],
        "partnership_utility": utility,
        "points_conceded": 0 if acting_won else result.deal_score.points,
        "positive_points": result.deal_score.points if acting_won else 0,
        "rami_succeeded": (
            None
            if result.contract is Contract.NOLO
            else not result.deal_score.stolen_rami
        ),
        "show_action_count": len(result.show_actions),
        "shown_card": card_to_code(accepted.shown_card),
        "shown_rank": int(accepted.shown_card.rank.value),
        "stolen_rami": (
            None
            if result.contract is Contract.NOLO
            else result.deal_score.stolen_rami
        ),
        "team_tricks": list(result.team_tricks),
        "verbal_required": accepted.verbal_required,
    }


@dataclass(frozen=True, slots=True)
class _ShowingSnapshot:
    state: MatchState
    observation: PlayerObservation
    features: PublicFeatures
    scored: ScoredActions
    selected: ShowAction
    forced_rami: ShowAction
    forced_nolo: ShowAction


def _showing_snapshots(state: MatchState) -> tuple[tuple[_ShowingSnapshot, ...], MatchState]:
    snapshots: list[_ShowingSnapshot] = []
    current = state
    while current.phase is EnginePhase.SHOWING:
        observation, features, scored = _rank_showing(current)
        selected = scored.action
        if not isinstance(selected, ShowAction):
            raise ExperimentError("showing ranking selected a non-show action")
        rami = forced_action_for_contract(scored, Contract.RAMI)
        nolo = forced_action_for_contract(scored, Contract.NOLO)
        snapshots.append(
            _ShowingSnapshot(
                state=current,
                observation=observation,
                features=features,
                scored=scored,
                selected=selected,
                forced_rami=rami,
                forced_nolo=nolo,
            )
        )
        current = apply_match_action(current, selected)
    return tuple(snapshots), current


def _accepted_verbal(snapshot: _ShowingSnapshot, action: ShowAction) -> bool:
    context = snapshot.features.require_showing()
    return context.verbal_required(action.declared_contract)


def _record_from_snapshot(
    *,
    split: str,
    root_seed: str,
    source_deal_index: int,
    base_deal: object,
    snapshot: _ShowingSnapshot,
    baseline_result: DealResult,
) -> dict[str, object]:
    state = snapshot.state
    active = state.active_deal
    if active is None:
        raise ExperimentError("snapshot lacks an active deal")
    actor = snapshot.observation.observing_seat
    acting_team = team_for_seat(actor)
    digest_before = counterfactual_state_digest(state)

    outcomes: dict[str, dict[str, object]] = {}
    branch_digests: dict[str, str] = {}
    forced_actions = {
        Contract.RAMI: snapshot.forced_rami,
        Contract.NOLO: snapshot.forced_nolo,
    }
    for contract in (Contract.RAMI, Contract.NOLO):
        # MatchState and DealState are immutable.  Re-digest before each branch
        # to make accidental mutation a hard experimental failure.
        branch_digest = counterfactual_state_digest(state)
        if branch_digest != digest_before:
            raise ExperimentError("counterfactual input state changed between branches")
        branch_digests[contract.value] = branch_digest
        action = forced_actions[contract]
        if action == snapshot.selected:
            result = baseline_result
        else:
            result = _finish_from_action(state, action)
        outcomes[contract.value] = _outcome_data(
            result, acting_team=acting_team, forced_action=action
        )
    if len(set(branch_digests.values())) != 1:
        raise ExperimentError("RAMI and NOLO did not start from the same state")

    hand = snapshot.features.hand
    showing = snapshot.features.require_showing()
    rami_score = simple_rami_score(snapshot.features)
    nolo_score = simple_nolo_score(snapshot.features)
    production = current_production_rule()
    threshold = float(production["rami_score"]["threshold"])  # type: ignore[index]
    veto = float(production["nolo_score"]["veto_threshold"])  # type: ignore[index]
    selected_contract = threshold_choice(
        rami_score=rami_score,
        nolo_score=nolo_score,
        threshold=threshold,
        nolo_veto_threshold=veto,
    )
    if snapshot.selected.declared_contract is not selected_contract:
        raise ExperimentError("reconstructed production threshold choice disagrees with policy")

    history = [_show_action_data(action) for action in active.show_actions]
    decision_id = content_digest(
        {
            "pre_state_digest": digest_before,
            "root_seed": root_seed,
            "schema_version": "tuppi.analysis.rami_nolo_decision_identity.v1",
            "source_deal_index": source_deal_index,
            "split": split,
        }
    )
    selected_verbal = _accepted_verbal(snapshot, snapshot.selected)
    forced_action_data = {
        contract.value: {
            **_engine_action_data(
                forced_actions[contract],
                verbal_required=_accepted_verbal(snapshot, forced_actions[contract]),
            ),
            "pre_state_digest": branch_digests[contract.value],
        }
        for contract in (Contract.RAMI, Contract.NOLO)
    }
    suit_lengths = {
        suit.value: hand.suit_lengths[index]
        for index, suit in enumerate(SUIT_ORDER)
    }
    role = snapshot.features.deal.match_role.value
    return {
        "base_deal_id": base_deal.base_deal_id,  # type: ignore[attr-defined]
        "counterfactuals": outcomes,
        "current_threshold_selection": {
            **_engine_action_data(snapshot.selected, verbal_required=selected_verbal),
            "nolo_veto_threshold": veto,
            "rami_threshold": threshold,
        },
        "deal_id": active.deal_id,
        "dealer": active.dealer,
        "decision_id": decision_id,
        "features": {
            "aces": hand.aces,
            "control_cards": hand.control_cards,
            "doubleton_count": hand.doubleton_count,
            "hand_hcp": hand.high_card_points,
            "honour_count": hand.honour_count,
            "longest_suit_length": hand.longest_suit_length,
            "low_card_count": hand.low_card_count,
            "nolo_fallback_category": showing.nolo_fallback_category.value,
            "nolo_score": nolo_score,
            "nolo_veto_pass": nolo_score <= veto,
            "rami_fallback_category": showing.rami_fallback_category.value,
            "rami_score": rami_score,
            "shortest_suit_length": hand.shortest_suit_length,
            "singleton_count": hand.singleton_count,
            "suit_lengths": suit_lengths,
            "top_five_count": hand.top_five_count,
            "void_count": hand.void_count,
        },
        "forced_actions": forced_action_data,
        "forehand": active.forehand,
        "hand": [card_to_code(card) for card in snapshot.observation.own_hand],
        "match_role": role,
        "match_score": list(active.starting_score.as_tuple()),
        "partnership": [actor, partner_for_seat(actor)],
        "pre_state_digest": digest_before,
        "previous_nolo_shows": showing.previous_nolo_count,
        "public_showing_history": history,
        "schema_version": DECISION_RECORD_SCHEMA_VERSION,
        "seat": actor,
        "showing_position": showing.showing_position,
        "source_deal_index": source_deal_index,
        "split": split,
        "team": int(acting_team.value),
    }


def evaluate_source_deal(
    *,
    split: str,
    root_seed: str,
    source_deal_index: int,
    match_score_pattern: tuple[tuple[int, int], ...] = DEFAULT_MATCH_SCORE_PATTERN,
) -> tuple[dict[str, object], ...]:
    """Evaluate every production-reachable showing state in one source deal."""

    if split not in ("tuning", "validation", "test"):
        raise ExperimentError("split must be tuning, validation, or test")
    score = _score_for_index(source_deal_index, match_score_pattern)
    base_deal, initial = _initial_state(
        split=split,
        root_seed=root_seed,
        source_deal_index=source_deal_index,
        score=score,
    )
    snapshots, after_showing = _showing_snapshots(initial)
    baseline_result = _finish_active_state(after_showing)
    records = tuple(
        _record_from_snapshot(
            split=split,
            root_seed=root_seed,
            source_deal_index=source_deal_index,
            base_deal=base_deal,
            snapshot=snapshot,
            baseline_result=baseline_result,
        )
        for snapshot in snapshots
    )
    if not records:
        raise ExperimentError("generated deal produced no showing decisions")
    return records


def _count_source_decisions(payload: tuple[str, str, int, tuple[tuple[int, int], ...]]) -> int:
    split, root_seed, index, pattern = payload
    score = _score_for_index(index, pattern)
    _base, initial = _initial_state(
        split=split,
        root_seed=root_seed,
        source_deal_index=index,
        score=score,
    )
    snapshots, _after = _showing_snapshots(initial)
    return len(snapshots)


def _evaluate_payload(
    payload: tuple[str, str, int, tuple[tuple[int, int], ...]]
) -> tuple[dict[str, object], ...]:
    split, root_seed, index, pattern = payload
    return evaluate_source_deal(
        split=split,
        root_seed=root_seed,
        source_deal_index=index,
        match_score_pattern=pattern,
    )


def _source_plan(
    *,
    split: str,
    root_seed: str,
    target_decisions: int,
    pattern: tuple[tuple[int, int], ...],
) -> tuple[tuple[str, str, int, tuple[tuple[int, int], ...]], ...]:
    payloads: list[tuple[str, str, int, tuple[tuple[int, int], ...]]] = []
    decisions = 0
    index = 0
    while decisions < target_decisions:
        payload = (split, root_seed, index, pattern)
        decisions += _count_source_decisions(payload)
        payloads.append(payload)
        index += 1
    return tuple(payloads)


def collect_corpus(
    *,
    split: str,
    root_seed: str,
    target_decisions: int,
    workers: int = 1,
    match_score_pattern: tuple[tuple[int, int], ...] = DEFAULT_MATCH_SCORE_PATTERN,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    """Collect an exact-size deterministic corpus from direct random deals."""

    if split not in ("tuning", "validation", "test"):
        raise ExperimentError("split must be tuning, validation, or test")
    if not isinstance(root_seed, str) or not root_seed:
        raise ExperimentError("root_seed must be a nonempty string")
    if type(target_decisions) is not int or target_decisions <= 0:
        raise ExperimentError("target_decisions must be positive")
    if type(workers) is not int or workers <= 0:
        raise ExperimentError("workers must be positive")
    plan = _source_plan(
        split=split,
        root_seed=root_seed,
        target_decisions=target_decisions,
        pattern=match_score_pattern,
    )
    if workers == 1:
        iterator: Iterable[tuple[dict[str, object], ...]] = map(_evaluate_payload, plan)
        pool = None
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        iterator = pool.map(_evaluate_payload, plan, chunksize=1)
    records: list[dict[str, object]] = []
    try:
        for position, source_records in enumerate(iterator, start=1):
            records.extend(source_records)
            if progress is not None:
                progress(split, position, len(plan))
    finally:
        if pool is not None:
            pool.shutdown()
    retained = records[:target_decisions]
    for ordinal, record in enumerate(retained):
        record["decision_ordinal"] = ordinal
    source_indices = {int(record["source_deal_index"]) for record in retained}
    manifest = {
        "decisions": len(retained),
        "direct_generator_seed": root_seed,
        "generated_source_deals": len(plan),
        "retained_source_deals": len(source_indices),
        "schema_version": "tuppi.analysis.rami_nolo_corpus.v1",
        "sealed_bank_opened": False,
        "source_kind": SOURCE_KIND,
        "split": split,
        "truncated_decisions_from_final_deal": len(records) - len(retained),
    }
    return tuple(retained), manifest


def threshold_choice(
    *,
    rami_score: float,
    nolo_score: float,
    threshold: float,
    nolo_veto_threshold: float,
) -> Contract:
    """Apply the production scalar rule with an experimental RAMI threshold."""

    values = (rami_score, nolo_score, threshold, nolo_veto_threshold)
    if any(type(value) not in (int, float) or not math.isfinite(float(value)) for value in values):
        raise ExperimentError("threshold inputs must be finite numbers")
    return (
        Contract.RAMI
        if rami_score >= threshold and nolo_score <= nolo_veto_threshold
        else Contract.NOLO
    )


def _record_scores(record: dict[str, object]) -> tuple[float, float]:
    features = record["features"]
    if not isinstance(features, dict):
        raise ExperimentError("decision record features are malformed")
    return float(features["rami_score"]), float(features["nolo_score"])


def _choice_for_policy(
    record: dict[str, object], policy: float | str, *, veto: float
) -> Contract:
    if policy == "always_rami":
        return Contract.RAMI
    if policy == "always_nolo":
        return Contract.NOLO
    if type(policy) not in (int, float):
        raise ExperimentError("unknown threshold policy")
    rami_score, nolo_score = _record_scores(record)
    return threshold_choice(
        rami_score=rami_score,
        nolo_score=nolo_score,
        threshold=float(policy),
        nolo_veto_threshold=veto,
    )


def _outcome_for(
    record: dict[str, object], policy: float | str, *, veto: float
) -> tuple[Contract, dict[str, object]]:
    choice = _choice_for_policy(record, policy, veto=veto)
    outcomes = record["counterfactuals"]
    if not isinstance(outcomes, dict) or not isinstance(outcomes[choice.value], dict):
        raise ExperimentError("decision record counterfactuals are malformed")
    return choice, outcomes[choice.value]  # type: ignore[return-value]


def _source_groups(
    records: Sequence[dict[str, object]], values: Sequence[float]
) -> dict[int, list[float]]:
    if len(records) != len(values):
        raise ExperimentError("records and values differ in length")
    groups: dict[int, list[float]] = defaultdict(list)
    for record, value in zip(records, values, strict=True):
        groups[int(record["source_deal_index"])].append(float(value))
    return dict(groups)


def _cluster_robust_se(
    records: Sequence[dict[str, object]], values: Sequence[float]
) -> float | None:
    if len(values) < 2:
        return None
    groups = _source_groups(records, values)
    if len(groups) < 2:
        return None
    mean_value = fmean(values)
    score_sums = [sum(value - mean_value for value in group) for group in groups.values()]
    correction = len(groups) / (len(groups) - 1)
    variance = correction * sum(value * value for value in score_sums) / (len(values) ** 2)
    return math.sqrt(max(0.0, variance))


def _threshold_metrics(
    records: Sequence[dict[str, object]], policy: float | str, *, veto: float
) -> dict[str, object]:
    if not records:
        raise ExperimentError("threshold metrics require decision records")
    choices: list[Contract] = []
    utilities: list[float] = []
    tricks: list[float] = []
    wins: list[bool] = []
    positive: list[float] = []
    conceded: list[float] = []
    rami_success: list[bool] = []
    for record in records:
        choice, outcome = _outcome_for(record, policy, veto=veto)
        choices.append(choice)
        utilities.append(float(outcome["partnership_utility"]))
        tricks.append(float(outcome["acting_team_tricks"]))
        wins.append(bool(outcome["acting_team_won"]))
        positive.append(float(outcome["positive_points"]))
        conceded.append(float(outcome["points_conceded"]))
        if choice is Contract.RAMI:
            rami_success.append(bool(outcome["rami_succeeded"]))
    groups = _source_groups(records, utilities)
    per_deal_means = [fmean(group) for group in groups.values()]
    rami_count = sum(choice is Contract.RAMI for choice in choices)
    return {
        "decisions": len(records),
        "expected_points_conceded": fmean(conceded),
        "expected_positive_points": fmean(positive),
        "expected_tricks": fmean(tricks),
        "mean_partnership_utility": fmean(utilities),
        "mean_source_deal_utility": fmean(per_deal_means),
        "rami_count": rami_count,
        "rami_frequency": rami_count / len(records),
        "rami_success_rate": fmean(rami_success) if rami_success else None,
        "source_deals": len(groups),
        "stolen_rami_rate": (
            1.0 - fmean(rami_success) if rami_success else None
        ),
        "win_probability": fmean(wins),
    }


def candidate_thresholds(
    records: Sequence[dict[str, object]], *, production_threshold: float
) -> tuple[float, ...]:
    """Dense quarter-point grid spanning and extending the observed scores."""

    if not records:
        raise ExperimentError("candidate thresholds require decision records")
    scores = [_record_scores(record)[0] for record in records]
    lower = math.floor(min(scores)) - 2
    upper = math.ceil(max(scores)) + 2
    ticks = set(range(int(lower * 4), int(upper * 4) + 1))
    ticks.add(round(production_threshold * 4))
    return tuple(value / 4.0 for value in sorted(ticks))


def threshold_sweep(
    records: Sequence[dict[str, object]],
    *,
    production_threshold: float,
    nolo_veto_threshold: float,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for threshold in candidate_thresholds(
        records, production_threshold=production_threshold
    ):
        metrics = _threshold_metrics(records, threshold, veto=nolo_veto_threshold)
        rows.append(
            {
                **metrics,
                "control": None,
                "is_current": threshold == production_threshold,
                "threshold": threshold,
            }
        )
    for control in ("always_rami", "always_nolo"):
        rows.append(
            {
                **_threshold_metrics(records, control, veto=nolo_veto_threshold),
                "control": control,
                "is_current": False,
                "threshold": None,
            }
        )
    return tuple(rows)


def _utility_values(
    records: Sequence[dict[str, object]], policy: float | str, *, veto: float
) -> list[float]:
    return [
        float(_outcome_for(record, policy, veto=veto)[1]["partnership_utility"])
        for record in records
    ]


def select_tuning_candidate(
    records: Sequence[dict[str, object]],
    sweep: Sequence[dict[str, object]],
    *,
    production_threshold: float,
    nolo_veto_threshold: float,
) -> dict[str, object]:
    """Select the central value of a paired one-SE near-optimal plateau."""

    numeric = [row for row in sweep if row["threshold"] is not None]
    if not numeric:
        raise ExperimentError("threshold sweep contains no numeric rows")
    best = max(
        numeric,
        key=lambda row: (
            float(row["mean_partnership_utility"]),
            -abs(float(row["threshold"]) - production_threshold),
        ),
    )
    best_threshold = float(best["threshold"])
    best_values = _utility_values(records, best_threshold, veto=nolo_veto_threshold)
    near: list[float] = []
    comparisons: list[dict[str, object]] = []
    for row in numeric:
        threshold = float(row["threshold"])
        values = _utility_values(records, threshold, veto=nolo_veto_threshold)
        losses = [best_value - value for best_value, value in zip(best_values, values, strict=True)]
        mean_loss = fmean(losses)
        se_loss = _cluster_robust_se(records, losses)
        qualifies = mean_loss <= (0.0 if se_loss is None else se_loss) + 1e-12
        comparisons.append(
            {
                "mean_utility_loss_from_best": mean_loss,
                "paired_cluster_standard_error": se_loss,
                "threshold": threshold,
                "within_one_paired_se": qualifies,
            }
        )
        if qualifies:
            near.append(threshold)
    near_set = set(near)
    runs: list[list[float]] = []
    current_run: list[float] = []
    for threshold in sorted(float(row["threshold"]) for row in numeric):
        if threshold in near_set:
            current_run.append(threshold)
        elif current_run:
            runs.append(current_run)
            current_run = []
    if current_run:
        runs.append(current_run)
    if not runs:
        runs = [[best_threshold]]
    plateau = max(
        runs,
        key=lambda run: (
            best_threshold in run,
            len(run),
            -abs(fmean((run[0], run[-1])) - production_threshold),
        ),
    )
    midpoint = (plateau[0] + plateau[-1]) / 2.0
    selected = min(
        plateau,
        key=lambda threshold: (
            abs(threshold - midpoint),
            abs(threshold - production_threshold),
            threshold,
        ),
    )
    return {
        "numeric_best_threshold": best_threshold,
        "numeric_best_utility": best["mean_partnership_utility"],
        "plateau_definition": (
            "contiguous thresholds no more than one paired source-deal-cluster "
            "standard error below the numerical tuning maximum"
        ),
        "plateau_high": plateau[-1],
        "plateau_low": plateau[0],
        "production_threshold_in_plateau": production_threshold in plateau,
        "selected_candidate_threshold": selected,
        "selection_rule": "central quarter-point value of the tuning-only one-SE plateau",
        "threshold_comparisons_to_best": comparisons,
    }


def _analysis_integer(seed: str, *parts: object) -> int:
    return int.from_bytes(
        hashlib.sha256(
            canonical_json_bytes(
                {
                    "parts": [str(part) for part in parts],
                    "schema_version": "tuppi.analysis.rami_nolo_rng.v1",
                    "seed": seed,
                }
            )
        ).digest(),
        "big",
    )


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ExperimentError("quantile requires values")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _cluster_bootstrap_interval(
    records: Sequence[dict[str, object]],
    values: Sequence[float],
    *,
    seed: str,
    replicates: int,
) -> list[float]:
    groups = _source_groups(records, values)
    source_ids = sorted(groups)
    if not source_ids:
        raise ExperimentError("bootstrap requires at least one source deal")
    if len(source_ids) == 1:
        value = fmean(groups[source_ids[0]])
        return [value, value]
    generator = random.Random(_analysis_integer(seed, "cluster-bootstrap"))
    means: list[float] = []
    for _replicate in range(replicates):
        total = 0.0
        count = 0
        for _position in source_ids:
            sampled = source_ids[generator.randrange(len(source_ids))]
            group = groups[sampled]
            total += sum(group)
            count += len(group)
        means.append(total / count)
    return [_quantile(means, 0.025), _quantile(means, 0.975)]


def _wtl(values: Sequence[float]) -> dict[str, int]:
    wins = sum(value > 0 for value in values)
    losses = sum(value < 0 for value in values)
    return {"loss": losses, "tie": len(values) - wins - losses, "win": wins}


def paired_threshold_comparison(
    records: Sequence[dict[str, object]],
    *,
    candidate_threshold: float,
    current_threshold: float,
    nolo_veto_threshold: float,
    bootstrap_replicates: int,
    analysis_seed: str,
) -> dict[str, object]:
    candidate = _utility_values(
        records, candidate_threshold, veto=nolo_veto_threshold
    )
    current = _utility_values(records, current_threshold, veto=nolo_veto_threshold)
    differences = [left - right for left, right in zip(candidate, current, strict=True)]
    candidate_choices = [
        _choice_for_policy(record, candidate_threshold, veto=nolo_veto_threshold)
        for record in records
    ]
    current_choices = [
        _choice_for_policy(record, current_threshold, veto=nolo_veto_threshold)
        for record in records
    ]
    changed = [left is not right for left, right in zip(candidate_choices, current_choices, strict=True)]
    groups = _source_groups(records, differences)
    per_deal_by_id = {
        source_deal_id: fmean(group)
        for source_deal_id, group in groups.items()
    }
    per_deal = list(per_deal_by_id.values())
    changed_deals = {
        int(record["source_deal_index"])
        for record, value in zip(records, changed, strict=True)
        if value
    }
    return {
        "analysis_seed": analysis_seed,
        "bootstrap_95_ci": _cluster_bootstrap_interval(
            records,
            differences,
            seed=analysis_seed,
            replicates=bootstrap_replicates,
        ),
        "bootstrap_replicates": bootstrap_replicates,
        "candidate_metrics": _threshold_metrics(
            records, candidate_threshold, veto=nolo_veto_threshold
        ),
        "candidate_threshold": candidate_threshold,
        "changed_decisions": sum(changed),
        "changed_source_deals": len(changed_deals),
        "cluster_robust_standard_error": _cluster_robust_se(records, differences),
        "current_metrics": _threshold_metrics(
            records, current_threshold, veto=nolo_veto_threshold
        ),
        "current_threshold": current_threshold,
        "changed_decision_win_tie_loss": _wtl(
            [
                difference
                for difference, differs in zip(differences, changed, strict=True)
                if differs
            ]
        ),
        "changed_source_deal_win_tie_loss": _wtl(
            [per_deal_by_id[source_deal_id] for source_deal_id in sorted(changed_deals)]
        ),
        "decision_level_win_tie_loss": _wtl(differences),
        "mean_utility_difference": fmean(differences),
        "source_deal_level_win_tie_loss": _wtl(per_deal),
        "source_deals": len(groups),
        "unit_of_inference": "generated source deal; bootstrap resamples source deals",
    }


def probability_by_score(
    records: Sequence[dict[str, object]], *, nolo_veto_threshold: float
) -> tuple[dict[str, object], ...]:
    groups: dict[float, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        score, _nolo = _record_scores(record)
        groups[score].append(record)
    rows: list[dict[str, object]] = []
    for score in sorted(groups):
        subset = groups[score]
        rami_utilities: list[float] = []
        nolo_utilities: list[float] = []
        successes: list[bool] = []
        veto_pass_differences: list[float] = []
        veto_pass_successes: list[bool] = []
        for record in subset:
            _rami_choice, rami = _outcome_for(record, "always_rami", veto=nolo_veto_threshold)
            _nolo_choice, nolo = _outcome_for(record, "always_nolo", veto=nolo_veto_threshold)
            rami_utilities.append(float(rami["partnership_utility"]))
            nolo_utilities.append(float(nolo["partnership_utility"]))
            successes.append(bool(rami["rami_succeeded"]))
            if _record_scores(record)[1] <= nolo_veto_threshold:
                veto_pass_differences.append(
                    float(rami["partnership_utility"])
                    - float(nolo["partnership_utility"])
                )
                veto_pass_successes.append(bool(rami["rami_succeeded"]))
        differences = [left - right for left, right in zip(rami_utilities, nolo_utilities, strict=True)]
        rows.append(
            {
                "decisions": len(subset),
                "mean_nolo_utility": fmean(nolo_utilities),
                "mean_rami_minus_nolo_utility": fmean(differences),
                "mean_rami_utility": fmean(rami_utilities),
                "nolo_veto_pass_count": len(veto_pass_differences),
                "rami_score": score,
                "rami_success_probability": fmean(successes),
                "stolen_rami_probability": 1.0 - fmean(successes),
                "veto_pass_mean_rami_minus_nolo_utility": (
                    fmean(veto_pass_differences) if veto_pass_differences else None
                ),
                "veto_pass_rami_success_probability": (
                    fmean(veto_pass_successes) if veto_pass_successes else None
                ),
                "veto_pass_stolen_rami_probability": (
                    1.0 - fmean(veto_pass_successes)
                    if veto_pass_successes
                    else None
                ),
            }
        )
    return tuple(rows)


def _stratum_key(record: dict[str, object], dimension: str) -> str:
    features = record["features"]
    if not isinstance(features, dict):
        raise ExperimentError("stratum record features are malformed")
    hcp = int(features["hand_hcp"])
    if dimension == "rami_score_band":
        score = float(features["rami_score"])
        low = math.floor(score / 2.0) * 2
        return f"{low:.0f}-{low + 1.99:.2f}"
    if dimension == "hand_hcp":
        if hcp <= 6:
            return "0-6"
        if hcp <= 9:
            return "7-9"
        if hcp <= 12:
            return "10-12"
        if hcp <= 15:
            return "13-15"
        return "16+"
    if dimension == "longest_suit_length":
        return str(features["longest_suit_length"])
    if dimension == "suit_shape":
        lengths = features["suit_lengths"]
        if not isinstance(lengths, dict):
            raise ExperimentError("suit lengths are malformed")
        return "-".join(str(value) for value in sorted(lengths.values(), reverse=True))
    if dimension == "shown_card_rank":
        selection = record["current_threshold_selection"]
        if not isinstance(selection, dict):
            raise ExperimentError("current selection is malformed")
        return str(selection["shown_rank"])
    if dimension == "dealer_forehand_position":
        labels = ("forehand", "second", "third", "dealer")
        return labels[int(record["showing_position"])]
    if dimension == "previous_nolo_shows":
        return str(record["previous_nolo_shows"])
    if dimension == "match_score_category":
        return str(record["match_role"])
    if dimension == "nolo_veto_status":
        return "pass" if bool(features["nolo_veto_pass"]) else "vetoed"
    raise ExperimentError(f"unknown stratum dimension {dimension}")


def _stratum_summary(
    records: Sequence[dict[str, object]], *, dimension: str, veto: float
) -> tuple[dict[str, object], ...]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in records:
        groups[_stratum_key(record, dimension)].append(record)
    rows: list[dict[str, object]] = []
    for key in sorted(groups):
        subset = groups[key]
        rami_values = _utility_values(subset, "always_rami", veto=veto)
        nolo_values = _utility_values(subset, "always_nolo", veto=veto)
        differences = [left - right for left, right in zip(rami_values, nolo_values, strict=True)]
        successes = [
            bool(_outcome_for(record, "always_rami", veto=veto)[1]["rami_succeeded"])
            for record in subset
        ]
        se = _cluster_robust_se(subset, differences)
        mean_difference = fmean(differences)
        interval = (
            None
            if se is None
            else [mean_difference - 1.96 * se, mean_difference + 1.96 * se]
        )
        rows.append(
            {
                "approximate_cluster_95_ci": interval,
                "decisions": len(subset),
                "mean_nolo_utility": fmean(nolo_values),
                "mean_rami_minus_nolo_utility": mean_difference,
                "mean_rami_score": fmean(_record_scores(record)[0] for record in subset),
                "mean_rami_utility": fmean(rami_values),
                "rami_success_probability": fmean(successes),
                "source_deals": len({int(record["source_deal_index"]) for record in subset}),
                "stratum": key,
            }
        )
    return tuple(rows)


def stratified_analysis(
    records: Sequence[dict[str, object]],
    *,
    plateau_low: float,
    plateau_high: float,
    nolo_veto_threshold: float,
) -> dict[str, object]:
    dimensions = (
        "rami_score_band",
        "hand_hcp",
        "longest_suit_length",
        "suit_shape",
        "shown_card_rank",
        "dealer_forehand_position",
        "previous_nolo_shows",
        "match_score_category",
        "nolo_veto_status",
    )
    boundary = [
        record
        for record in records
        if plateau_low - 1.0 <= _record_scores(record)[0] <= plateau_high + 1.0
        and _record_scores(record)[1] <= nolo_veto_threshold
    ]
    all_strata = {
        dimension: _stratum_summary(records, dimension=dimension, veto=nolo_veto_threshold)
        for dimension in dimensions
    }
    boundary_dimensions = tuple(
        dimension
        for dimension in dimensions
        if dimension not in ("rami_score_band", "nolo_veto_status")
    )
    boundary_strata = {
        dimension: _stratum_summary(
            boundary, dimension=dimension, veto=nolo_veto_threshold
        )
        if boundary
        else ()
        for dimension in boundary_dimensions
    }
    reversals: list[dict[str, object]] = []
    for dimension, rows in boundary_strata.items():
        supported_positive = [
            row
            for row in rows
            if row["decisions"] >= 100
            and row["approximate_cluster_95_ci"] is not None
            and row["approximate_cluster_95_ci"][0] > 0  # type: ignore[index]
        ]
        supported_negative = [
            row
            for row in rows
            if row["decisions"] >= 100
            and row["approximate_cluster_95_ci"] is not None
            and row["approximate_cluster_95_ci"][1] < 0  # type: ignore[index]
        ]
        if supported_positive and supported_negative:
            reversals.append(
                {
                    "dimension": dimension,
                    "nolo_favoured": [row["stratum"] for row in supported_negative],
                    "rami_favoured": [row["stratum"] for row in supported_positive],
                }
            )
    if reversals:
        adequacy = "no"
        reason = "supported sign reversals across adequately populated boundary strata"
    elif len(boundary) >= 500:
        adequacy = "yes"
        reason = "no supported boundary-region sign reversal in the prespecified strata"
    else:
        adequacy = "uncertain"
        reason = "fewer than 500 veto-passing boundary decisions"
    return {
        "all_decisions": all_strata,
        "boundary_definition": (
            "RAMI score within one point of the tuning plateau and production NOLO veto passes"
        ),
        "boundary_decisions": len(boundary),
        "boundary_strata": boundary_strata,
        "context_sign_reversals": reversals,
        "single_global_threshold_adequate": adequacy,
        "single_threshold_reason": reason,
    }


def payoff_analysis(
    records: Sequence[dict[str, object]],
    probability_rows: Sequence[dict[str, object]],
    *,
    plateau_low: float,
    plateau_high: float,
    nolo_veto_threshold: float,
) -> dict[str, object]:
    boundary = [
        record
        for record in records
        if plateau_low - 1.0 <= _record_scores(record)[0] <= plateau_high + 1.0
        and _record_scores(record)[1] <= nolo_veto_threshold
    ]
    successes: list[bool] = []
    made_points: list[float] = []
    stolen_points: list[float] = []
    nolo_utilities: list[float] = []
    rami_utilities: list[float] = []
    for record in boundary:
        rami = _outcome_for(record, "always_rami", veto=nolo_veto_threshold)[1]
        nolo = _outcome_for(record, "always_nolo", veto=nolo_veto_threshold)[1]
        success = bool(rami["rami_succeeded"])
        successes.append(success)
        rami_utilities.append(float(rami["partnership_utility"]))
        nolo_utilities.append(float(nolo["partnership_utility"]))
        if success:
            made_points.append(float(rami["deal_points"]))
        else:
            stolen_points.append(float(rami["deal_points"]))
    gain = fmean(made_points) if made_points else None
    loss = fmean(stolen_points) if stolen_points else None
    nolo_utility = fmean(nolo_utilities) if nolo_utilities else None
    break_even = None
    if gain is not None and loss is not None and nolo_utility is not None:
        break_even = (nolo_utility + loss) / (gain + loss)
    eligible_score_rows = [
        row
        for row in probability_rows
        if plateau_low - 2.0 <= float(row["rami_score"]) <= plateau_high + 2.0
        and row["decisions"] >= 30 and row["nolo_veto_pass_count"] >= 15
        and row["veto_pass_mean_rami_minus_nolo_utility"] is not None
    ]
    first_advantage = next(
        (
            row
            for row in eligible_score_rows
            if float(row["veto_pass_mean_rami_minus_nolo_utility"]) >= 0
        ),
        None,
    )
    return {
        "boundary_decisions": len(boundary),
        "boundary_mean_nolo_utility": nolo_utility,
        "boundary_mean_rami_minus_nolo_utility": (
            fmean(left - right for left, right in zip(rami_utilities, nolo_utilities, strict=True))
            if boundary
            else None
        ),
        "boundary_rami_success_probability": fmean(successes) if successes else None,
        "empirical_first_nonnegative_score_bin": (
            None if first_advantage is None else first_advantage["rami_score"]
        ),
        "empirical_success_probability_at_first_nonnegative_bin": (
            None
            if first_advantage is None
            else first_advantage["veto_pass_rami_success_probability"]
        ),
        "mean_points_if_rami_made": gain,
        "mean_points_if_rami_stolen": loss,
        "payoff_implied_break_even_success_probability": break_even,
        "stolen_rami_scoring_multiplier": 8,
        "successful_rami_scoring_multiplier": 4,
    }


def _decision_gate(
    validation: dict[str, object], tuning_selection: dict[str, object]
) -> tuple[str, str]:
    candidate = float(validation["candidate_threshold"])
    current = float(validation["current_threshold"])
    changed = int(validation["changed_decisions"])
    interval = validation["bootstrap_95_ci"]
    if candidate == current or changed == 0:
        return "KEEP CURRENT THRESHOLD", "candidate and current policies are decision-identical"
    if isinstance(interval, list) and interval[0] > 0:
        return "CHANGE SUPPORTED", "fresh held-out cluster-bootstrap interval excludes zero in favour of the candidate"
    if bool(tuning_selection["production_threshold_in_plateau"]):
        return "KEEP CURRENT THRESHOLD", "current threshold lies in the tuning plateau and held-out improvement is not credible"
    return "INCONCLUSIVE", "held-out interval does not establish a credible improvement"


def run_experiment(
    config: ExperimentConfig,
    *,
    progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, object]:
    """Tune once, freeze the candidate, then evaluate one fresh validation set."""

    if not isinstance(config, ExperimentConfig):
        raise ExperimentError("run_experiment requires ExperimentConfig")
    production = current_production_rule()
    current_threshold = float(production["rami_score"]["threshold"])  # type: ignore[index]
    veto = float(production["nolo_score"]["veto_threshold"])  # type: ignore[index]
    tuning, tuning_manifest = collect_corpus(
        split="tuning",
        root_seed=config.tuning_seed,
        target_decisions=config.tuning_decisions,
        workers=config.workers,
        match_score_pattern=config.match_score_pattern,
        progress=progress,
    )
    tuning_sweep = threshold_sweep(
        tuning,
        production_threshold=current_threshold,
        nolo_veto_threshold=veto,
    )
    selection = select_tuning_candidate(
        tuning,
        tuning_sweep,
        production_threshold=current_threshold,
        nolo_veto_threshold=veto,
    )
    candidate = float(selection["selected_candidate_threshold"])

    # The candidate is frozen above.  Nothing derived from validation can
    # alter it, and validation is evaluated exactly once below.
    validation, validation_manifest = collect_corpus(
        split="validation",
        root_seed=config.validation_seed,
        target_decisions=config.validation_decisions,
        workers=config.workers,
        match_score_pattern=config.match_score_pattern,
        progress=progress,
    )
    comparison = paired_threshold_comparison(
        validation,
        candidate_threshold=candidate,
        current_threshold=current_threshold,
        nolo_veto_threshold=veto,
        bootstrap_replicates=config.bootstrap_replicates,
        analysis_seed=config.analysis_seed,
    )
    probabilities = probability_by_score(
        validation, nolo_veto_threshold=veto
    )
    strata = stratified_analysis(
        validation,
        plateau_low=float(selection["plateau_low"]),
        plateau_high=float(selection["plateau_high"]),
        nolo_veto_threshold=veto,
    )
    payoff = payoff_analysis(
        validation,
        probabilities,
        plateau_low=float(selection["plateau_low"]),
        plateau_high=float(selection["plateau_high"]),
        nolo_veto_threshold=veto,
    )
    gate, gate_reason = _decision_gate(comparison, selection)
    return {
        "config": config.to_data(),
        "decision_gate": gate,
        "decision_gate_reason": gate_reason,
        "payoff_analysis": payoff,
        "production_agent_modified": False,
        "production_rule": production,
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "sealed_bank_opened": False,
        "stratified_analysis": strata,
        "tuning_corpus": tuning,
        "tuning_manifest": tuning_manifest,
        "tuning_selection": selection,
        "tuning_threshold_sweep": tuning_sweep,
        "validation_comparison": comparison,
        "validation_corpus": validation,
        "validation_manifest": validation_manifest,
        "validation_probability_by_score": probabilities,
    }


__all__ = (
    "DEFAULT_ANALYSIS_SEED",
    "DEFAULT_MATCH_SCORE_PATTERN",
    "DEFAULT_TUNING_SEED",
    "DEFAULT_VALIDATION_SEED",
    "EXPERIMENT_SCHEMA_VERSION",
    "ExperimentConfig",
    "ExperimentError",
    "SOURCE_KIND",
    "apply_forced_choice",
    "candidate_thresholds",
    "collect_corpus",
    "counterfactual_state_digest",
    "current_production_rule",
    "evaluate_source_deal",
    "forced_action_for_contract",
    "paired_threshold_comparison",
    "payoff_analysis",
    "probability_by_score",
    "run_experiment",
    "select_tuning_candidate",
    "stratified_analysis",
    "threshold_choice",
    "threshold_sweep",
)
