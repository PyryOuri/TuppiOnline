"""Observation-only paired RAMI/NOLO evaluation for close live bot decisions.

The evaluator receives a :class:`PlayerObservation`, never authoritative match
state. Hidden hands are sampled uniformly from the hard-feasible set implied by
that observation. Each sampled assignment is used twice so RAMI and NOLO are
compared on the same possible world. Only aggregate outcomes leave this module;
sampled cards and assignments are never persisted or projected.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import statistics
from typing import Mapping

from tuppi_agents import RuleBasedPolicy, build_features, showing_scalars
from tuppi_engine import (
    Action,
    PlayerObservation,
    ShowAction,
    apply_action,
    deal_result_from_state,
    observation_for,
    observation_to_data,
)
from tuppi_exact import HardConstraintModel, UniformFeasibleSampler, hypothetical_continuation
from tuppi_rules import Contract, team_for_seat


CONTRACT_EVALUATION_SCHEMA_VERSION = "tuppi.server.contract_evaluation.v1"
CONTRACT_EVALUATOR_ID = "uniform_feasible_paired_partner_aware_v1"
CONTRACT_EVALUATION_MEASURE = "uniform_over_hard_feasible_assignments"
RAMI_BOUNDARY_MARGIN = 2.0
NOLO_BOUNDARY_MARGIN = 2.0
MINIMUM_MEAN_UTILITY_ADVANTAGE = 1.0
STABLE_PAIR_SHARE = 0.75
MAXIMUM_SAMPLES = 64


@dataclass(frozen=True, slots=True)
class ContractEvaluationDecision:
    action: Action
    record: dict[str, object]


@dataclass(frozen=True, slots=True)
class _BranchOutcome:
    utility: float
    tricks: int
    won: bool
    points_scored: int
    points_conceded: int
    resolved_contract: Contract
    made_rami: bool
    stolen_rami: bool


def evaluate_contract_choice(
    observation: PlayerObservation,
    *,
    policy: RuleBasedPolicy,
    agents: Mapping[int, object],
    deal_number: int,
    event_index: int,
    sample_count: int,
) -> ContractEvaluationDecision:
    """Return the live action and a privacy-safe explanatory record.

    Failures in the optional rollout layer are deliberately fail-open to the
    frozen heuristic action. The failure class is not projected because it can
    reveal implementation details; the stable fallback code is sufficient.
    """

    if not isinstance(observation, PlayerObservation):
        raise ValueError("contract evaluation requires a PlayerObservation")
    if not isinstance(policy, RuleBasedPolicy):
        raise ValueError("contract evaluation requires a rule-based policy")
    if type(deal_number) is not int or deal_number < 0:
        raise ValueError("contract evaluation deal_number is invalid")
    if type(event_index) is not int or event_index < 0:
        raise ValueError("contract evaluation event_index is invalid")
    if type(sample_count) is not int or not 0 <= sample_count <= MAXIMUM_SAMPLES:
        raise ValueError("contract evaluation sample_count is invalid")

    decision = policy.decide(observation, diagnostics=False)
    heuristic_action = decision.action
    if not isinstance(heuristic_action, ShowAction):
        raise ValueError("contract evaluation is available only during showing")
    features = build_features(
        observation, include_inference=policy.profile.uses_public_inference
    )
    scalars = dict(showing_scalars(features, policy.profile))
    heuristic = {
        "selected_contract": heuristic_action.declared_contract.value,
        "metrics": [
            {"name": name, "value": float(value)}
            for name, value in sorted(scalars.items())
        ],
        "rami_boundary_distance": float(
            scalars["simple_rami_score"] - scalars["simple_rami_threshold"]
        ),
        "nolo_veto_headroom": float(
            scalars["simple_nolo_veto_threshold"] - scalars["simple_nolo_score"]
        ),
    }
    actions_by_contract = _best_actions_by_contract(decision.scored.ranked())
    close = (
        set(actions_by_contract) == {Contract.RAMI, Contract.NOLO}
        and abs(heuristic["rami_boundary_distance"]) <= RAMI_BOUNDARY_MARGIN
        and abs(heuristic["nolo_veto_headroom"]) <= NOLO_BOUNDARY_MARGIN
    )
    base = _base_record(
        observation=observation,
        deal_number=deal_number,
        event_index=event_index,
        heuristic=heuristic,
        selected_contract=heuristic_action.declared_contract,
    )
    if sample_count == 0:
        return ContractEvaluationDecision(
            heuristic_action,
            validate_contract_evaluation_record(
                {**base, "fallback_reason": "evaluation_disabled"}
            ),
        )
    if not close:
        return ContractEvaluationDecision(
            heuristic_action,
            validate_contract_evaluation_record(
                {**base, "fallback_reason": "outside_boundary"}
            ),
        )

    seed = _semantic_seed(observation)
    try:
        model = HardConstraintModel.build(observation)
        assignments = UniformFeasibleSampler.build(model, seed=seed).sample(sample_count)
        samples: dict[Contract, list[_BranchOutcome]] = {
            Contract.RAMI: [],
            Contract.NOLO: [],
        }
        for assignment in assignments:
            continuation = hypothetical_continuation(observation, assignment)
            for contract in (Contract.RAMI, Contract.NOLO):
                samples[contract].append(
                    _run_branch(
                        continuation.state,
                        forced_action=actions_by_contract[contract],
                        agents=agents,
                        acting_seat=observation.observing_seat,
                    )
                )
    except Exception:
        return ContractEvaluationDecision(
            heuristic_action,
            validate_contract_evaluation_record(
                {**base, "fallback_reason": "evaluation_failed"}
            ),
        )

    rami = samples[Contract.RAMI]
    nolo = samples[Contract.NOLO]
    differences = [
        left.utility - right.utility for left, right in zip(rami, nolo, strict=True)
    ]
    rami_better = sum(value > 0 for value in differences)
    nolo_better = sum(value < 0 for value in differences)
    ties = len(differences) - rami_better - nolo_better
    mean_difference = statistics.fmean(differences)
    required = math.ceil(sample_count * STABLE_PAIR_SHARE)
    recommended = heuristic_action.declared_contract
    stable = False
    if mean_difference >= MINIMUM_MEAN_UTILITY_ADVANTAGE and rami_better >= required:
        recommended = Contract.RAMI
        stable = True
    elif mean_difference <= -MINIMUM_MEAN_UTILITY_ADVANTAGE and nolo_better >= required:
        recommended = Contract.NOLO
        stable = True
    selected = actions_by_contract[recommended] if stable else heuristic_action
    record = {
        **base,
        "triggered": True,
        "sample_count": sample_count,
        "seed_id": seed,
        "rami": _aggregate(Contract.RAMI, rami),
        "nolo": _aggregate(Contract.NOLO, nolo),
        "paired": {
            "rami_minus_nolo_mean_utility": float(mean_difference),
            "standard_error": float(_standard_error(differences)),
            "rami_better_count": rami_better,
            "nolo_better_count": nolo_better,
            "tie_count": ties,
            "stable": stable,
        },
        "recommended_contract": recommended.value,
        "selected_contract": selected.declared_contract.value,
        "selection_source": "paired_rollout" if stable else "heuristic",
        "fallback_reason": None if stable else "rollout_inconclusive",
    }
    return ContractEvaluationDecision(selected, validate_contract_evaluation_record(record))


def validate_contract_evaluation_record(value: object) -> dict[str, object]:
    """Fail-closed validation for persistence and post-deal projection."""

    if type(value) is not dict:
        raise ValueError("contract evaluation record must be an object")
    required = {
        "schema_version", "evaluator_id", "measure", "deal_number", "event_index",
        "seat", "heuristic", "triggered", "sample_count", "seed_id", "rami",
        "nolo", "paired", "recommended_contract", "selected_contract",
        "selection_source", "fallback_reason",
    }
    if set(value) != required:
        raise ValueError("contract evaluation fields are invalid")
    if value["schema_version"] != CONTRACT_EVALUATION_SCHEMA_VERSION:
        raise ValueError("contract evaluation schema is invalid")
    if value["evaluator_id"] != CONTRACT_EVALUATOR_ID:
        raise ValueError("contract evaluator identity is invalid")
    if value["measure"] != CONTRACT_EVALUATION_MEASURE:
        raise ValueError("contract evaluation measure is invalid")
    for key, maximum in (("deal_number", None), ("event_index", None), ("seat", 3)):
        item = value[key]
        if type(item) is not int or item < 0 or (maximum is not None and item > maximum):
            raise ValueError(f"contract evaluation {key} is invalid")
    if type(value["triggered"]) is not bool:
        raise ValueError("contract evaluation triggered is invalid")
    count = value["sample_count"]
    if type(count) is not int or not 0 <= count <= MAXIMUM_SAMPLES:
        raise ValueError("contract evaluation sample_count is invalid")
    heuristic = value["heuristic"]
    if type(heuristic) is not dict or set(heuristic) != {
        "selected_contract", "metrics", "rami_boundary_distance", "nolo_veto_headroom"
    }:
        raise ValueError("contract evaluation heuristic is invalid")
    _contract(heuristic["selected_contract"])
    _finite(heuristic["rami_boundary_distance"])
    _finite(heuristic["nolo_veto_headroom"])
    metrics = heuristic["metrics"]
    if type(metrics) is not list or not metrics:
        raise ValueError("contract evaluation metrics are invalid")
    names: set[str] = set()
    for metric in metrics:
        if type(metric) is not dict or set(metric) != {"name", "value"}:
            raise ValueError("contract evaluation metric is invalid")
        name = metric["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("contract evaluation metric name is invalid")
        names.add(name)
        _finite(metric["value"])
    for key in ("recommended_contract", "selected_contract"):
        _contract(value[key])
    if value["selection_source"] not in {"heuristic", "paired_rollout"}:
        raise ValueError("contract evaluation selection_source is invalid")
    fallback = value["fallback_reason"]
    if fallback not in {
        None, "evaluation_disabled", "outside_boundary", "evaluation_failed",
        "rollout_inconclusive",
    }:
        raise ValueError("contract evaluation fallback_reason is invalid")
    if value["triggered"]:
        if (
            count <= 0
            or not isinstance(value["seed_id"], str)
            or not value["seed_id"].startswith("contract-eval-v1:")
            or len(value["seed_id"]) != len("contract-eval-v1:") + 64
        ):
            raise ValueError("triggered contract evaluation metadata is invalid")
        _validate_outcome(value["rami"], Contract.RAMI, count)
        _validate_outcome(value["nolo"], Contract.NOLO, count)
        _validate_paired(value["paired"], count)
        paired = value["paired"]
        assert isinstance(paired, dict)
        if paired["stable"]:
            if (
                value["selection_source"] != "paired_rollout"
                or value["fallback_reason"] is not None
                or value["selected_contract"] != value["recommended_contract"]
            ):
                raise ValueError("stable contract evaluation selection is invalid")
        elif (
            value["selection_source"] != "heuristic"
            or value["fallback_reason"] != "rollout_inconclusive"
            or value["selected_contract"] != heuristic["selected_contract"]
            or value["recommended_contract"] != heuristic["selected_contract"]
        ):
            raise ValueError("inconclusive contract evaluation selection is invalid")
    elif any(value[key] is not None for key in ("seed_id", "rami", "nolo", "paired")):
        raise ValueError("untriggered contract evaluation contains rollout data")
    elif (
        value["selection_source"] != "heuristic"
        or value["selected_contract"] != heuristic["selected_contract"]
        or value["recommended_contract"] != heuristic["selected_contract"]
        or value["fallback_reason"]
        not in {"evaluation_disabled", "outside_boundary", "evaluation_failed"}
    ):
        raise ValueError("untriggered contract evaluation selection is invalid")
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _base_record(
    *, observation: PlayerObservation, deal_number: int, event_index: int,
    heuristic: dict[str, object], selected_contract: Contract,
) -> dict[str, object]:
    return {
        "schema_version": CONTRACT_EVALUATION_SCHEMA_VERSION,
        "evaluator_id": CONTRACT_EVALUATOR_ID,
        "measure": CONTRACT_EVALUATION_MEASURE,
        "deal_number": deal_number,
        "event_index": event_index,
        "seat": observation.observing_seat,
        "heuristic": heuristic,
        "triggered": False,
        "sample_count": 0,
        "seed_id": None,
        "rami": None,
        "nolo": None,
        "paired": None,
        "recommended_contract": selected_contract.value,
        "selected_contract": selected_contract.value,
        "selection_source": "heuristic",
        "fallback_reason": "outside_boundary",
    }


def _best_actions_by_contract(ranked: tuple[object, ...]) -> dict[Contract, ShowAction]:
    result: dict[Contract, ShowAction] = {}
    for candidate in ranked:
        action = candidate.action
        if isinstance(action, ShowAction):
            result.setdefault(action.declared_contract, action)
    return result


def _run_branch(
    state,
    *,
    forced_action: ShowAction,
    agents: Mapping[int, object],
    acting_seat: int,
) -> _BranchOutcome:
    state = apply_action(state, forced_action)
    accepted = 1
    while not state.complete:
        actor = state.current_actor
        if actor is None or actor not in agents:
            raise RuntimeError("contract rollout has no configured acting bot")
        state = apply_action(state, agents[actor].choose_action(observation_for(state, actor)))
        accepted += 1
        if accepted > 56:
            raise RuntimeError("contract rollout exceeded a complete deal")
    result = deal_result_from_state(state)
    team = team_for_seat(acting_seat)
    won = result.deal_score.winner_team is team
    points = result.deal_score.points
    return _BranchOutcome(
        utility=float(points if won else -points),
        tricks=result.team_tricks[team.value],
        won=won,
        points_scored=points if won else 0,
        points_conceded=0 if won else points,
        resolved_contract=result.contract,
        made_rami=result.outcome.value == "MADE_RAMI",
        stolen_rami=result.outcome.value == "STOLEN_RAMI",
    )


def _aggregate(contract: Contract, outcomes: list[_BranchOutcome]) -> dict[str, object]:
    count = len(outcomes)
    return {
        "requested_contract": contract.value,
        "sample_count": count,
        "expected_deal_utility": float(statistics.fmean(item.utility for item in outcomes)),
        "expected_tricks": float(statistics.fmean(item.tricks for item in outcomes)),
        "deal_win_probability": sum(item.won for item in outcomes) / count,
        "expected_points_scored": statistics.fmean(item.points_scored for item in outcomes),
        "expected_points_conceded": statistics.fmean(item.points_conceded for item in outcomes),
        "rami_success_probability": sum(item.made_rami for item in outcomes) / count,
        "stolen_rami_probability": sum(item.stolen_rami for item in outcomes) / count,
        "resolved_rami_probability": sum(
            item.resolved_contract is Contract.RAMI for item in outcomes
        )
        / count,
        "resolved_nolo_probability": sum(
            item.resolved_contract is Contract.NOLO for item in outcomes
        )
        / count,
    }


def _semantic_seed(observation: PlayerObservation) -> str:
    data = observation_to_data(observation)
    for key in ("match_ref", "deal_ref"):
        data.pop(key, None)
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"contract-eval-v1:{hashlib.sha256(encoded).hexdigest()}"


def _standard_error(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.stdev(values) / math.sqrt(len(values))


def _validate_outcome(value: object, contract: Contract, count: int) -> None:
    if type(value) is not dict:
        raise ValueError("contract rollout outcome is invalid")
    expected = {
        "requested_contract", "sample_count", "expected_deal_utility", "expected_tricks",
        "deal_win_probability", "expected_points_scored", "expected_points_conceded",
        "rami_success_probability", "stolen_rami_probability",
        "resolved_rami_probability", "resolved_nolo_probability",
    }
    if (
        set(value) != expected
        or value["requested_contract"] != contract.value
        or value["sample_count"] != count
    ):
        raise ValueError("contract rollout outcome fields are invalid")
    for key in expected - {"requested_contract", "sample_count"}:
        number = _finite(value[key])
        if "probability" in key and not 0 <= number <= 1:
            raise ValueError("contract rollout probability is invalid")


def _validate_paired(value: object, count: int) -> None:
    if type(value) is not dict or set(value) != {
        "rami_minus_nolo_mean_utility", "standard_error", "rami_better_count",
        "nolo_better_count", "tie_count", "stable",
    }:
        raise ValueError("paired contract evaluation is invalid")
    _finite(value["rami_minus_nolo_mean_utility"])
    if _finite(value["standard_error"]) < 0:
        raise ValueError("paired contract standard error is invalid")
    counts = [value[key] for key in ("rami_better_count", "nolo_better_count", "tie_count")]
    if any(type(item) is not int or item < 0 for item in counts) or sum(counts) != count:
        raise ValueError("paired contract counts are invalid")
    if type(value["stable"]) is not bool:
        raise ValueError("paired contract stability is invalid")


def _contract(value: object) -> Contract:
    if value not in {Contract.RAMI.value, Contract.NOLO.value}:
        raise ValueError("contract evaluation contract is invalid")
    return Contract(value)


def _finite(value: object) -> float:
    if (
        type(value) not in {int, float}
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError("contract evaluation number is invalid")
    return float(value)
