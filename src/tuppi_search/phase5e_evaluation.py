"""Unsealed Phase 5E complete-match evaluation instruments."""

from __future__ import annotations

import time

from tuppi_agents import phase4_specifications_by_profile_key
from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.records import PairRecord
from tuppi_match.statistics import pair_inference, secondary_metrics

from .errors import SearchError
from .multi_observer_registry import (
    MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
    REGISTERED_MULTI_OBSERVER_CONFIGURATIONS,
    build_agent as build_multi_observer_agent,
    specification_for as multi_observer_specification_for,
)
from .phase5d_b_evaluation import (
    phase5d_b_agent_builder,
    phase5d_b_agent_identity,
    run_root_info_uct_behavior_comparison,
)


PHASE5E_MATCH_ROOT_SEED = "tuppi-phase5e-match-v1"
PHASE5E_HETERO_ROOT_SEED = "tuppi-phase5e-heterogeneous-v1"
PHASE5E_EVALUATION_SCHEMA_VERSION = "tuppi.search.phase5e_evaluation.v1"
PHASE5E_DEFAULT_SAFETY_CAP = 704
CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_REPLICATES = 2000
SIGN_FLIP_REPLICATES = 10000


def phase5e_match_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5e_match_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5E_MATCH_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5E multi-observer re-determinizing search complete-match "
            "development bank; unsealed and separate from all earlier banks."
        ),
    )


def phase5e_hetero_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5e_heterogeneous_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5E_HETERO_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5E seat-balanced heterogeneous development bank; unsealed "
            "and separate from all earlier banks."
        ),
    )


def phase5e_agent_builder(profile_key: str):
    if profile_key == "development_reference_v1":
        profile_key = "partner_aware_v1"
    if profile_key in phase4_specifications_by_profile_key():
        return phase5d_b_agent_builder(profile_key)
    try:
        multi_observer_specification_for(profile_key)
    except SearchError:
        return phase5d_b_agent_builder(profile_key)
    return lambda seat: build_multi_observer_agent(profile_key, seat=seat)


def phase5e_agent_identity(profile_key: str) -> str:
    if profile_key == "development_reference_v1":
        profile_key = "partner_aware_v1"
    try:
        return multi_observer_specification_for(profile_key).agent_id
    except SearchError:
        return phase5d_b_agent_identity(profile_key)


def _comparison(
    *, candidate_profile_key: str, opponent_profile_key: str, name: str
) -> MatchComparison:
    return MatchComparison.build(
        name=name,
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=phase5e_agent_identity(candidate_profile_key),
        opponent_agent_id=phase5e_agent_identity(opponent_profile_key),
        result_class="development",
        hypothesis=(
            f"Does {candidate_profile_key} beat {opponent_profile_key} over "
            "complete matches from 0-0?"
        ),
    )


def _pair_from_data(data: dict) -> PairRecord:
    from tuppi_match.executor import _pair_from_data as rebuild

    return rebuild(data)


def _unit(payload: tuple) -> tuple[int, dict]:
    candidate_key, opponent_key, comparison_data, stream_count, safety_cap, ordinal = payload
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
    record = run_pair(
        stream=phase5e_match_bank(stream_count=stream_count).stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=phase5e_agent_builder(candidate_key),
        build_opponent=phase5e_agent_builder(opponent_key),
    )
    return ordinal, record.to_data()


def _run_units(
    *, candidate_key: str, opponent_key: str, comparison: MatchComparison,
    pairs: int, safety_cap: int, workers: int | None, progress=None,
) -> tuple[PairRecord, ...]:
    units = [
        (candidate_key, opponent_key, comparison.to_data(), pairs, safety_cap, ordinal)
        for ordinal in range(pairs)
    ]
    collected: dict[int, PairRecord] = {}
    if workers is None or workers <= 1:
        iterator = map(_unit, units)
    else:
        from concurrent.futures import ProcessPoolExecutor

        pool = ProcessPoolExecutor(max_workers=workers)
        iterator = pool.map(_unit, units, chunksize=1)
    try:
        for index, (ordinal, data) in enumerate(iterator):
            collected[ordinal] = _pair_from_data(data)
            if progress is not None:
                progress(index + 1, len(units))
    finally:
        if workers is not None and workers > 1:
            pool.shutdown()
    return tuple(collected[index] for index in range(pairs))


def run_phase5e_match_comparison(
    *, candidate_profile_key: str = MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
    opponent_profile_key: str = "development_reference_v1",
    pairs: int,
    safety_cap: int = PHASE5E_DEFAULT_SAFETY_CAP,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    if opponent_profile_key == "development_reference_v1":
        opponent_profile_key = "partner_aware_v1"
    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be positive")
    comparison = _comparison(
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        name=f"phase5e_{candidate_profile_key}_vs_{opponent_profile_key}",
    )
    records = _run_units(
        candidate_key=candidate_profile_key,
        opponent_key=opponent_profile_key,
        comparison=comparison,
        pairs=pairs,
        safety_cap=safety_cap,
        workers=workers,
        progress=progress,
    )
    return {
        "bank": phase5e_match_bank(stream_count=pairs).to_data(),
        "candidate_agent_id": phase5e_agent_identity(candidate_profile_key),
        "candidate_profile_key": candidate_profile_key,
        "comparison_id": comparison.comparison_id,
        "design": "homogeneous_partnership",
        "hypothesis": comparison.hypothesis,
        "name": comparison.name,
        "opponent_agent_id": phase5e_agent_identity(opponent_profile_key),
        "opponent_profile_key": opponent_profile_key,
        "pair_count": pairs,
        "primary_match_inference": pair_inference(
            records,
            confidence_level=CONFIDENCE_LEVEL,
            analysis_seed=PHASE5E_MATCH_ROOT_SEED,
            bootstrap_replicates=BOOTSTRAP_REPLICATES,
            sign_flip_replicates=SIGN_FLIP_REPLICATES,
        ),
        "safety_cap": safety_cap,
        "schema_version": PHASE5E_EVALUATION_SCHEMA_VERSION,
        "secondary_metrics": secondary_metrics(records),
        "sealed_bank_opened": False,
        "worker_independence": "Each pair is a pure function of the fresh Phase 5E bank, comparison, cap, and ordinal.",
    }


def _hetero_unit(payload: tuple) -> tuple[int, dict]:
    search_key, partner_key, opponent_key, arrangement, comparison_data, stream_count, safety_cap, ordinal = payload
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
    search_builder = phase5e_agent_builder(search_key)
    partner_builder = phase5e_agent_builder(partner_key)
    opponent_builder = phase5e_agent_builder(opponent_key)

    def build_candidate(seat: int):
        lower = seat in (0, 1)
        use_search = lower if arrangement == 0 else not lower
        return search_builder(seat) if use_search else partner_builder(seat)

    record = run_pair(
        stream=phase5e_hetero_bank(stream_count=stream_count).stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=build_candidate,
        build_opponent=opponent_builder,
    )
    return ordinal, record.to_data()


def run_phase5e_heterogeneous_match_comparison(
    *,
    search_profile_key: str = MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
    partner_profile_key: str = "partner_aware_v1",
    opponent_profile_key: str = "partner_aware_v1",
    pairs: int,
    safety_cap: int = PHASE5E_DEFAULT_SAFETY_CAP,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be positive")
    arrangements = []
    for arrangement in (0, 1):
        comparison = MatchComparison.build(
            name=f"phase5e_hetero_{search_profile_key}_arrangement{arrangement}",
            candidate_profile_key=f"{search_profile_key}+{partner_profile_key}",
            opponent_profile_key=f"{opponent_profile_key}+{opponent_profile_key}",
            candidate_agent_id=phase5e_agent_identity(search_profile_key),
            opponent_agent_id=phase5e_agent_identity(opponent_profile_key),
            result_class="development",
            hypothesis="Does a multi-observer search seat remain compatible with a frozen reference partner?",
        )
        units = [
            (
                search_profile_key,
                partner_profile_key,
                opponent_profile_key,
                arrangement,
                comparison.to_data(),
                pairs,
                safety_cap,
                ordinal,
            )
            for ordinal in range(pairs)
        ]
        collected: dict[int, PairRecord] = {}
        if workers is None or workers <= 1:
            iterator = map(_hetero_unit, units)
        else:
            from concurrent.futures import ProcessPoolExecutor

            pool = ProcessPoolExecutor(max_workers=workers)
            iterator = pool.map(_hetero_unit, units, chunksize=1)
        try:
            for index, (ordinal, data) in enumerate(iterator):
                collected[ordinal] = _pair_from_data(data)
                if progress is not None:
                    progress(arrangement * pairs + index + 1, 2 * pairs)
        finally:
            if workers is not None and workers > 1:
                pool.shutdown()
        records = tuple(collected[index] for index in range(pairs))
        arrangements.append(
            {
                "arrangement": arrangement,
                "arrangement_meaning": "search at lower candidate seat" if arrangement == 0 else "search at higher candidate seat",
                "comparison_id": comparison.comparison_id,
                "primary_match_inference": pair_inference(
                    records,
                    confidence_level=CONFIDENCE_LEVEL,
                    analysis_seed=PHASE5E_HETERO_ROOT_SEED,
                    bootstrap_replicates=BOOTSTRAP_REPLICATES,
                    sign_flip_replicates=SIGN_FLIP_REPLICATES,
                ),
                "secondary_metrics": secondary_metrics(records),
            }
        )
    return {
        "arrangements": arrangements,
        "design": "seat_balanced_heterogeneous_partnership",
        "opponent_profile_key": opponent_profile_key,
        "partner_profile_key": partner_profile_key,
        "search_profile_key": search_profile_key,
        "pair_count_per_arrangement": pairs,
        "safety_cap": safety_cap,
        "schema_version": "tuppi.search.phase5e_heterogeneous.v1",
        "sealed_bank_opened": False,
    }


def run_multi_observer_stability(
    corpus,
    *,
    budgets: tuple[int, ...] = (2, 8, 32),
    showing_limit: int | None = None,
    trick_play_limit: int | None = None,
) -> dict[str, object]:
    """Evaluate nested Phase 5E budgets on a fixed observation-only corpus."""

    if not budgets or tuple(sorted(budgets)) != budgets:
        raise SearchError("Phase 5E budgets must be ascending")
    profiles_by_budget = {
        configuration.simulation_budget: profile_key
        for profile_key, configuration in REGISTERED_MULTI_OBSERVER_CONFIGURATIONS.items()
    }
    missing = [budget for budget in budgets if budget not in profiles_by_budget]
    if missing:
        raise SearchError(f"no registered Phase 5E budget for {missing}")
    showing = corpus.showing[
        : len(corpus.showing) if showing_limit is None else showing_limit
    ]
    trick_play = corpus.trick_play[
        : len(corpus.trick_play) if trick_play_limit is None else trick_play_limit
    ]
    positions = showing + trick_play
    if not positions:
        raise SearchError("Phase 5E stability selected no positions")
    records = []
    for position in positions:
        evaluations = []
        for budget in budgets:
            started = time.perf_counter()
            decision = build_multi_observer_agent(
                profiles_by_budget[budget], seat=position.observation.observing_seat
            ).explain(position.observation)
            evaluations.append(
                {
                    "action_id": decision.selected_action_id,
                    "budget": budget,
                    "information_set_nodes": decision.total_information_nodes,
                    "redeterminizations": decision.observer_redeterminization_count,
                    "fallback_rollouts": decision.fallback_rollout_count,
                    "selected_action_value_gap": round(decision.selected_action_value_gap, 9),
                    "selected_action_visit_share": round(decision.selected_action_visit_share, 9),
                    "seconds": round(time.perf_counter() - started, 6),
                }
            )
        records.append(
            {
                "evaluations": evaluations,
                "phase": position.observation.phase.value,
                "position_id": position.position_id,
                "role": position.role,
                "stage": position.stage,
            }
        )
    adjacent = []
    for index, (left, right) in enumerate(zip(budgets, budgets[1:])):
        agreements = sum(
            record["evaluations"][index]["action_id"]
            == record["evaluations"][index + 1]["action_id"]
            for record in records
        )
        adjacent.append(
            {
                "from_budget": left,
                "to_budget": right,
                "agreements": agreements,
                "comparisons": len(records),
                "agreement_rate": round(agreements / len(records), 6),
            }
        )
    largest_index = len(budgets) - 1
    largest = [
        {
            "budget": budget,
            "agreements": sum(
                record["evaluations"][index]["action_id"]
                == record["evaluations"][largest_index]["action_id"]
                for record in records
            ),
            "comparisons": len(records),
        }
        for index, budget in enumerate(budgets)
    ]
    for entry in largest:
        entry["agreement_rate"] = round(entry["agreements"] / len(records), 6)
    return {
        "adjacent_action_agreement": adjacent,
        "agreement_with_largest_budget": largest,
        "budgets": list(budgets),
        "interpretation": "Development stability only; no strength claim.",
        "positions": {
            "showing": len(showing),
            "trick_play": len(trick_play),
            "total": len(records),
        },
        "records": records,
        "schema_version": "tuppi.search.phase5e_budget_stability.v1",
    }


def run_phase5e_behavior_comparison(
    corpus,
    *,
    showing_limit: int | None = None,
    trick_play_limit: int | None = None,
) -> dict[str, object]:
    """Compare reference, frozen root UCT, and Phase 5E actions."""

    # Keep the Phase 5D-B comparison as a separate frozen diagnostic and add
    # Phase 5E records beside it. The root-UCT result is not recomputed here.
    baseline = run_root_info_uct_behavior_comparison(
        corpus,
        profile_key="root_info_uct_standard_v1",
        showing_limit=showing_limit,
        trick_play_limit=trick_play_limit,
    )
    positions = corpus.showing[: len(corpus.showing) if showing_limit is None else showing_limit]
    positions += corpus.trick_play[: len(corpus.trick_play) if trick_play_limit is None else trick_play_limit]
    records = []
    for position in positions:
        observation = position.observation
        decision = build_multi_observer_agent(
            MULTI_OBSERVER_PRIMARY_PROFILE_KEY,
            seat=observation.observing_seat,
        ).explain(observation)
        records.append(
            {
                "multi_observer_action": decision.selected_action_id,
                "pimc_action": position.pimc_action_id,
                "position_id": position.position_id,
                "reference_action": position.reference_action_id,
                "root_uct_action": next(
                    item["root_uct_action"]
                    for item in baseline["records"]
                    if item["position_id"] == position.position_id
                ),
                "stage": position.stage,
            }
        )
    categories = {
        "all_agree": 0,
        "multi_observer_agrees_reference_against_root_uct": 0,
        "multi_observer_agrees_root_uct_against_reference": 0,
        "all_differ": 0,
        "other": 0,
    }
    for record in records:
        m, r, u = record["multi_observer_action"], record["reference_action"], record["root_uct_action"]
        if m == r == u:
            categories["all_agree"] += 1
        elif m == r and r != u:
            categories["multi_observer_agrees_reference_against_root_uct"] += 1
        elif m == u and u != r:
            categories["multi_observer_agrees_root_uct_against_reference"] += 1
        elif len({m, r, u}) == 3:
            categories["all_differ"] += 1
        else:
            categories["other"] += 1
    return {
        "categories": categories,
        "records": records,
        "schema_version": "tuppi.search.phase5e_behavior_comparison.v1",
    }


__all__ = (
    "PHASE5E_DEFAULT_SAFETY_CAP",
    "PHASE5E_EVALUATION_SCHEMA_VERSION",
    "PHASE5E_HETERO_ROOT_SEED",
    "PHASE5E_MATCH_ROOT_SEED",
    "phase5e_agent_builder",
    "phase5e_agent_identity",
    "phase5e_hetero_bank",
    "phase5e_match_bank",
    "run_multi_observer_stability",
    "run_phase5e_behavior_comparison",
    "run_phase5e_heterogeneous_match_comparison",
    "run_phase5e_match_comparison",
)
