"""Run the Phase 5G-B synthetic belief evaluation.

The output is an aggregate research report.  Full hidden-hand labels remain in
memory only and are never serialized.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics
import time

from tuppi_belief import (
    BehavioralBeliefConfiguration,
    EpsilonSmoothedPolicyModel,
    build_belief,
    build_uniform_belief,
    default_policy_family_mixture,
)
from tuppi_belief.exact_reference import (
    ExactEnumerationLimit,
    enumerate_feasible_assignments,
    exact_behavioral_posterior,
)
from tuppi_exact.constraints import HardConstraintModel
from tuppi_belief.metrics import marginal_total_variation, owner_metrics, reliability_bins
from tuppi_belief.resampling import systematic_resample
from tuppi_belief.synthetic import SyntheticBeliefPosition, generate_synthetic_positions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/phase5g-b-results.json"),
    )
    parser.add_argument("--candidate-count", type=int, default=32)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    if args.candidate_count <= 0:
        raise SystemExit("candidate count must be positive")

    started = time.perf_counter()
    splits = {
        "development": ("phase5g-b-development-v1", (0,)),
        "calibration": ("phase5g-b-calibration-v1", (1,)),
        "heldout": ("phase5g-b-heldout-v1", (2, 3) if not args.quick else (2,)),
    }
    positions: list[SyntheticBeliefPosition] = []
    for split, (root_seed, streams) in splits.items():
        for stream_index in streams:
            for profile_key in (
                "reactive_contract_v1",
                "public_counting_v1",
                "partner_aware_v1",
            ):
                generated = generate_synthetic_positions(
                    profile_key=profile_key,
                    root_seed=root_seed,
                    stream_index=stream_index,
                    deal_indices=(0,),
                    split=split,
                    initial_dealer=stream_index % 4,
                )
                positions.extend(_select_balanced(generated))
    heldout = tuple(item for item in positions if item.split == "heldout")
    development = tuple(item for item in positions if item.split == "development")
    calibration = tuple(item for item in positions if item.split == "calibration")

    fixed_epsilon = 0.10
    evaluation = {}
    performance = {}
    for label, model_factory in (
        ("matched_smoothed", lambda position: EpsilonSmoothedPolicyModel(
            position.generating_profile_key, epsilon=fixed_epsilon
        )),
        ("misspecified_reactive", lambda _position: EpsilonSmoothedPolicyModel(
            "reactive_contract_v1", epsilon=fixed_epsilon
        )),
        ("robust_equal_mixture", lambda _position: default_policy_family_mixture(
            epsilon=fixed_epsilon
        )),
    ):
        evaluation[label], performance[label] = _evaluate(
            heldout,
            model_factory,
            candidate_count=args.candidate_count,
            seed_prefix="shared-heldout",
        )
    evaluation["hard_uniform"] = _evaluate_uniform(
        heldout,
        candidate_count=args.candidate_count,
        seed_prefix="shared-heldout",
    )

    ablations = _ablations(heldout[: (6 if args.quick else 12)], fixed_epsilon)
    convergence = _candidate_convergence(heldout[: (3 if args.quick else 6)], fixed_epsilon)
    exact_validation = _exact_validation(heldout, fixed_epsilon)
    calibration_summary = _calibration_summary(heldout, fixed_epsilon, args.candidate_count)
    resampling = _resampling_summary(heldout, fixed_epsilon, args.candidate_count)
    generator_breakdown = _generator_breakdown(heldout, fixed_epsilon, args.candidate_count)

    report = {
        "phase": "5G-B",
        "schema_version": "tuppi.belief.phase5g_b_results.v1",
        "configuration": {
            "candidate_count": args.candidate_count,
            "epsilon": fixed_epsilon,
            "mixture_weights": [1 / 3, 1 / 3, 1 / 3],
            "parameter_tuning": "none; fixed before held-out evaluation",
            "search_integration": False,
        },
        "dataset": {
            "manifest_version": "tuppi.belief.synthetic_manifest.v1",
            "positions_total": len(positions),
            "split_counts": {
                "development": len(development),
                "calibration": len(calibration),
                "heldout": len(heldout),
            },
            "generator_profiles": [
                "reactive_contract_v1",
                "public_counting_v1",
                "partner_aware_v1",
            ],
            "private_labels_serialized": False,
        },
        "evaluation": evaluation,
        "generator_breakdown": generator_breakdown,
        "ablations": ablations,
        "candidate_convergence": convergence,
        "exact_tiny_validation": exact_validation,
        "calibration": calibration_summary,
        "resampling": resampling,
        "performance": performance,
        "decision": _decision(evaluation, calibration_summary, performance, exact_validation),
        "sealed_bank_opened": False,
        "elapsed_seconds": time.perf_counter() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "split_counts": report["dataset"]["split_counts"],
        "decision": report["decision"],
        "elapsed_seconds": report["elapsed_seconds"],
    }, sort_keys=True))


def _select_balanced(positions: tuple[SyntheticBeliefPosition, ...]) -> tuple[SyntheticBeliefPosition, ...]:
    seen: set[str] = set()
    selected: list[SyntheticBeliefPosition] = []
    for position in positions:
        key = position.phase_depth
        if key in seen:
            continue
        seen.add(key)
        selected.append(position)
    return tuple(selected)


def _evaluate(positions, model_factory, *, candidate_count: int, seed_prefix: str):
    records = []
    timings = []
    for position in positions:
        started = time.perf_counter()
        belief = build_belief(
            position.public_input(),
            model_factory(position),
            configuration=BehavioralBeliefConfiguration(
                candidate_count=candidate_count,
                seed=f"{seed_prefix}-{position.position_id}",
            ),
        )
        elapsed = time.perf_counter() - started
        metric = owner_metrics(belief, position.true_current_hands)
        records.append((metric, belief))
        timings.append(elapsed)
    return _aggregate(records), {
        "positions": len(positions),
        "median_seconds_per_position": statistics.median(timings) if timings else 0.0,
        "p90_seconds_per_position": _quantile(timings, 0.90),
        "candidate_evaluations_per_second": (
            len(positions) * candidate_count / sum(timings) if timings and sum(timings) else 0.0
        ),
    }


def _evaluate_uniform(positions, *, candidate_count: int, seed_prefix: str):
    records = []
    for position in positions:
        belief = build_uniform_belief(
            position.public_input(),
            candidate_count=candidate_count,
            seed=f"{seed_prefix}-{position.position_id}",
        )
        records.append((owner_metrics(belief, position.true_current_hands), belief))
    return _aggregate(records)


def _aggregate(records):
    if not records:
        return {"positions": 0}
    metrics = [item[0] for item in records]
    return {
        "positions": len(metrics),
        "card_count_mean": statistics.mean(item.card_count for item in metrics),
        "nll_mean": statistics.mean(item.nll for item in metrics),
        "brier_mean": statistics.mean(item.brier for item in metrics),
        "top_owner_accuracy_mean": statistics.mean(item.top_owner_accuracy for item in metrics),
        "mean_true_owner_probability": statistics.mean(item.mean_true_owner_probability for item in metrics),
        "entropy_mean": statistics.mean(item.entropy for item in metrics),
        "ess_mean": statistics.mean(item[1].effective_sample_size for item in records),
        "ess_min": min(item[1].effective_sample_size for item in records),
        "zero_weight_position_count": sum(item[1].diagnostics.zero_weight_count > 0 for item in records),
    }


def _ablations(positions, epsilon):
    output = {}
    for label, showing, trick, seats in (
        ("showing_only", True, False, None),
        ("trick_only", False, True, None),
        ("partner_only", True, True, "partner"),
        ("opponents_only", True, True, "opponents"),
        ("showing_and_trick", True, True, None),
    ):
        records = []
        for position in positions:
            observer = position.observation.observing_seat
            if seats == "partner":
                actor_seats = (position.observation.partner_seat,)
            elif seats == "opponents":
                actor_seats = tuple(seat for seat in range(4) if seat not in (observer, position.observation.partner_seat))
            else:
                actor_seats = None
            belief = build_belief(
                position.public_input(),
                EpsilonSmoothedPolicyModel(position.generating_profile_key, epsilon=epsilon),
                configuration=BehavioralBeliefConfiguration(
                    candidate_count=16,
                    seed=f"ablation-{label}-{position.position_id}",
                    include_showing=showing,
                    include_trick_play=trick,
                    actor_seats=actor_seats,
                ),
            )
            records.append((owner_metrics(belief, position.true_current_hands), belief))
        output[label] = _aggregate(records)
    return output


def _candidate_convergence(positions, epsilon):
    result = {}
    marginals_by_count = {}
    for count in (16, 32, 64, 128):
        values = []
        for position in positions:
            belief = build_belief(
                position.public_input(),
                EpsilonSmoothedPolicyModel(position.generating_profile_key, epsilon=epsilon),
                configuration=BehavioralBeliefConfiguration(
                    candidate_count=count,
                    seed=f"convergence-{position.position_id}",
                ),
            )
            values.append(belief)
        marginals_by_count[count] = [belief.owner_marginals() for belief in values]
        result[str(count)] = {
            "mean_ess": statistics.mean(item.effective_sample_size for item in values),
            "mean_normalized_entropy": statistics.mean(item.diagnostics.normalized_entropy for item in values),
        }
    for count in (32, 64, 128):
        left = marginals_by_count[count // 2]
        right = marginals_by_count[count]
        result[str(count)]["adjacent_marginal_tv"] = statistics.mean(
            marginal_total_variation(a, b) for a, b in zip(left, right, strict=True)
        )
    return result


def _exact_validation(positions, epsilon):
    records = []
    matched_metrics = []
    mixture_metrics = []
    uniform_metrics = []
    for position in positions:
        if len(HardConstraintModel.build(position.public_input()).unknown_cards) > 9:
            continue
        try:
            feasible = enumerate_feasible_assignments(
                position.public_input(), max_assignments=101
            )
        except ExactEnumerationLimit:
            continue
        if not 1 < len(feasible) <= 100:
            continue
        exact = exact_behavioral_posterior(
            position.public_input(),
            EpsilonSmoothedPolicyModel(position.generating_profile_key, epsilon=epsilon),
        )
        approximate = build_belief(
            position.public_input(),
            EpsilonSmoothedPolicyModel(position.generating_profile_key, epsilon=epsilon),
            configuration=BehavioralBeliefConfiguration(
                candidate_count=128,
                seed=f"exact-validation-{position.position_id}",
            ),
        )
        exact_like = _belief_from_exact(position, exact)
        uniform = _uniform_from_exact(position, exact)
        exact_mixture = exact_behavioral_posterior(
            position.public_input(),
            default_policy_family_mixture(epsilon=epsilon),
        )
        mixture = _belief_from_exact(position, exact_mixture)
        records.append(marginal_total_variation(exact_like.owner_marginals(), approximate.owner_marginals()))
        matched_metrics.append(owner_metrics(exact_like, position.true_current_hands))
        mixture_metrics.append(owner_metrics(mixture, position.true_current_hands))
        uniform_metrics.append(owner_metrics(uniform, position.true_current_hands))
        if len(records) >= 8:
            break
    summary = {
        "positions": len(records),
        "mean_marginal_total_variation": statistics.mean(records) if records else None,
        "max_marginal_total_variation": max(records) if records else None,
        "independent_enumerator": True,
    }
    if records:
        summary.update(
            {
                "uniform_nll_mean": statistics.mean(item.nll for item in uniform_metrics),
                "matched_exact_nll_mean": statistics.mean(item.nll for item in matched_metrics),
                "mixture_exact_nll_mean": statistics.mean(item.nll for item in mixture_metrics),
                "matched_exact_nll_gain_over_uniform": statistics.mean(item.nll for item in uniform_metrics) - statistics.mean(item.nll for item in matched_metrics),
                "mixture_exact_nll_gain_over_uniform": statistics.mean(item.nll for item in uniform_metrics) - statistics.mean(item.nll for item in mixture_metrics),
            }
        )
    return summary


def _belief_from_exact(position, exact):
    from tuppi_belief.posterior import BeliefDiagnostics, WeightedBelief
    weights = exact.normalized_weights
    diagnostics = BeliefDiagnostics(
        finite_candidate_count=len(weights),
        zero_weight_count=sum(value == 0 for value in weights),
        effective_sample_size=1.0 / sum(value * value for value in weights),
        normalized_entropy=0.0,
        max_log_weight=max(value for value in exact.log_weights if value != float("-inf")),
        min_finite_log_weight=min(value for value in exact.log_weights if value != float("-inf")),
        history_action_count=0,
        scored_action_count=0,
        replay_count=len(weights),
    )
    return WeightedBelief(
        observation=position.observation,
        model_id="exact-reference",
        candidate_ids=tuple(str(index) for index in range(len(weights))),
        assignments=exact.assignments,
        log_weights=exact.log_weights,
        normalized_weights=weights,
        feasible_world_count=exact.feasible_world_count,
        diagnostics=diagnostics,
    )


def _uniform_from_exact(position, exact):
    from tuppi_belief.posterior import BeliefDiagnostics, WeightedBelief
    count = len(exact.assignments)
    weights = tuple(1.0 / count for _ in range(count))
    diagnostics = BeliefDiagnostics(
        finite_candidate_count=count,
        zero_weight_count=0,
        effective_sample_size=float(count),
        normalized_entropy=1.0 if count > 1 else 0.0,
        max_log_weight=0.0,
        min_finite_log_weight=0.0,
        history_action_count=0,
        scored_action_count=0,
        replay_count=count,
    )
    return WeightedBelief(
        observation=position.observation,
        model_id="hard-uniform-exact-reference",
        candidate_ids=tuple(str(index) for index in range(count)),
        assignments=exact.assignments,
        log_weights=tuple(0.0 for _ in range(count)),
        normalized_weights=weights,
        feasible_world_count=count,
        diagnostics=diagnostics,
    )


def _calibration_summary(positions, epsilon, candidate_count):
    records = []
    for position in positions:
        belief = build_belief(
            position.public_input(),
            default_policy_family_mixture(epsilon=epsilon),
            configuration=BehavioralBeliefConfiguration(
                candidate_count=candidate_count,
                seed=f"calibration-{position.position_id}",
            ),
        )
        true_owner = {
            card.to_code(): seat
            for seat, hand in enumerate(position.true_current_hands)
            for card in hand
        }
        for code, probabilities in belief.owner_marginals().items():
            owner = true_owner[code]
            for seat, probability in probabilities.items():
                records.append((probability, seat == owner))
    bins = reliability_bins(records)
    return {"fixed_epsilon": epsilon, "reliability_bins": bins, "records": len(records)}


def _resampling_summary(positions, epsilon, candidate_count):
    if not positions:
        return {}
    position = positions[0]
    belief = build_belief(
        position.public_input(),
        default_policy_family_mixture(epsilon=epsilon),
        configuration=BehavioralBeliefConfiguration(candidate_count=candidate_count, seed="resampling-summary"),
    )
    result = systematic_resample(
        belief.normalized_weights,
        count=candidate_count,
        seed="phase5g-b-resampling",
    )
    return {"algorithm_id": result.algorithm_id, **result.to_data()}


def _generator_breakdown(positions, epsilon, candidate_count):
    output = {}
    for profile in sorted({position.generating_profile_key for position in positions}):
        subset = tuple(position for position in positions if position.generating_profile_key == profile)
        result, _timing = _evaluate(
            subset,
            lambda position: EpsilonSmoothedPolicyModel(profile, epsilon=epsilon),
            candidate_count=candidate_count,
            seed_prefix=f"breakdown-{profile}",
        )
        output[profile] = result
    return output


def _decision(evaluation, calibration, performance, exact_validation):
    uniform = evaluation.get("hard_uniform", {})
    matched = evaluation.get("matched_smoothed", {})
    mixture = evaluation.get("robust_equal_mixture", {})
    if not uniform or not matched:
        return {"path": "B4", "reason": "no held-out positions"}
    matched_gain = uniform["nll_mean"] - matched["nll_mean"]
    mixture_gain = uniform["nll_mean"] - mixture["nll_mean"]
    exact_matched_gain = exact_validation.get("matched_exact_nll_gain_over_uniform")
    exact_mixture_gain = exact_validation.get("mixture_exact_nll_gain_over_uniform")
    if matched_gain > 0.02 and mixture_gain > 0.0 and matched["ess_mean"] >= 2.0:
        path = "B1"
        reason = "matched and robust action-likelihood beliefs improve held-out owner NLL with workable ESS"
    elif exact_matched_gain is not None and exact_matched_gain > 0.02 and (
        exact_mixture_gain is None or exact_mixture_gain <= 0.0
    ):
        path = "B2"
        reason = "the matched policy is informative in complete tiny posteriors, but the fixed policy-unknown mixture is not robust"
    elif exact_matched_gain is not None and exact_matched_gain > 0.02 and matched_gain <= 0.0:
        path = "B4"
        reason = "the exact signal is present, but the finite candidate posterior remains too concentrated at the practical candidate budget"
    elif matched_gain > 0.02 and mixture_gain <= 0.0:
        path = "B2"
        reason = "matched policy helps but the fixed robust mixture does not improve uniformly"
    elif abs(matched_gain) <= 0.02:
        path = "B3"
        reason = "matched behavioural weighting adds little owner-information over hard uniform"
    else:
        path = "B4"
        reason = "belief signal is present but the finite evaluation is too concentrated or costly"
    return {
        "path": path,
        "reason": reason,
        "matched_nll_gain_over_uniform": matched_gain,
        "mixture_nll_gain_over_uniform": mixture_gain,
    }


def _quantile(values, quantile):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(quantile * (len(ordered) - 1)))
    return ordered[index]


if __name__ == "__main__":
    main()
