"""Development-bank evaluation instruments for Phase 5D-B.

The complete-match protocol is reused unchanged, but the Phase 5D-B agent builder
is local to this search package because the earlier ``tuppi_match`` package must
not depend on later search implementations.  All banks here are fresh, unsealed,
and separate from Phase 5C and Phase 5D-A.
"""

from __future__ import annotations

import math
import time

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.banks import BankRole, StreamBank
from tuppi_match.manifest import MatchComparison
from tuppi_match.protocol import run_pair
from tuppi_match.records import PairRecord
from tuppi_match.statistics import pair_inference, secondary_metrics
from tuppi_search.registry import build_agent as build_pimc_agent
from tuppi_search.registry import configuration_for as pimc_configuration_for
from tuppi_search.registry import specification_for as pimc_specification_for

from .errors import SearchError
from .root_info_uct_registry import (
    ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
    REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS,
    build_agent as build_root_info_uct_agent,
    specification_for as root_info_uct_specification_for,
)


PHASE5D_B_MATCH_ROOT_SEED = "tuppi-phase5d-b-match-v1"
PHASE5D_B_HETERO_ROOT_SEED = "tuppi-phase5d-b-heterogeneous-v1"
PHASE5D_B_EVALUATION_SCHEMA_VERSION = "tuppi.search.phase5d_b_evaluation.v1"
PHASE5D_B_DEFAULT_SAFETY_CAP = 704
CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_REPLICATES = 2000
SIGN_FLIP_REPLICATES = 10000


def phase5d_b_match_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5d_b_match_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5D_B_MATCH_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5D-B root-information UCT complete-match development bank; "
            "unsealed and distinct from every earlier search bank."
        ),
    )


def phase5d_b_hetero_bank(*, stream_count: int) -> StreamBank:
    return StreamBank.build(
        name="phase5d_b_heterogeneous_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=PHASE5D_B_HETERO_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Phase 5D-B seat-balanced heterogeneous root-information UCT bank; "
            "unsealed and separate from the homogeneous comparison bank."
        ),
    )


def phase5d_b_agent_builder(profile_key: str):
    phase4 = phase4_specifications_by_profile_key()
    if profile_key in phase4:
        return lambda seat: construct_agent(phase4[profile_key], seat=seat)
    if profile_key in ("uniform_feasible_pimc_small_v1", "uniform_feasible_pimc_standard_v1"):
        # Explicitly retain the frozen Phase 5C builder rather than aliasing its
        # identity to a Phase 5D-B profile.
        return lambda seat: build_pimc_agent(profile_key, seat=seat)
    try:
        root_info_uct_specification_for(profile_key)
    except SearchError:
        raise SearchError(f"unknown Phase 5D-B evaluation profile {profile_key!r}")
    return lambda seat: build_root_info_uct_agent(profile_key, seat=seat)


def phase5d_b_agent_identity(profile_key: str) -> str:
    phase4 = phase4_specifications_by_profile_key()
    if profile_key in phase4:
        return phase4[profile_key].agent_id
    if profile_key.startswith("uniform_feasible_pimc_"):
        return pimc_specification_for(profile_key).agent_id
    return root_info_uct_specification_for(profile_key).agent_id


def _comparison(
    *, candidate_profile_key: str, opponent_profile_key: str, name: str, hypothesis: str
) -> MatchComparison:
    return MatchComparison.build(
        name=name,
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        candidate_agent_id=phase5d_b_agent_identity(candidate_profile_key),
        opponent_agent_id=phase5d_b_agent_identity(opponent_profile_key),
        result_class="development",
        hypothesis=hypothesis,
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
    bank = phase5d_b_match_bank(stream_count=stream_count)
    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=phase5d_b_agent_builder(candidate_key),
        build_opponent=phase5d_b_agent_builder(opponent_key),
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
        for index, unit in enumerate(units):
            ordinal, data = _unit(unit)
            collected[ordinal] = _pair_from_data(data)
            if progress is not None:
                progress(index + 1, len(units))
    else:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            for index, (ordinal, data) in enumerate(pool.map(_unit, units, chunksize=1)):
                collected[ordinal] = _pair_from_data(data)
                if progress is not None:
                    progress(index + 1, len(units))
    return tuple(collected[index] for index in range(pairs))


def run_phase5d_b_match_comparison(
    *, candidate_profile_key: str = ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
    opponent_profile_key: str = "development_reference_v1",
    pairs: int,
    safety_cap: int = PHASE5D_B_DEFAULT_SAFETY_CAP,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Run a homogeneous Phase 5D-B candidate comparison."""

    if opponent_profile_key == "development_reference_v1":
        opponent_profile_key = "partner_aware_v1"
    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be positive")
    comparison = _comparison(
        candidate_profile_key=candidate_profile_key,
        opponent_profile_key=opponent_profile_key,
        name=f"phase5d_b_{candidate_profile_key}_vs_{opponent_profile_key}",
        hypothesis=(
            f"Does {candidate_profile_key} beat {opponent_profile_key} over "
            "complete matches from 0-0?"
        ),
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
        "bank": phase5d_b_match_bank(stream_count=pairs).to_data(),
        "candidate_agent_id": phase5d_b_agent_identity(candidate_profile_key),
        "candidate_profile_key": candidate_profile_key,
        "comparison_id": comparison.comparison_id,
        "design": "homogeneous_partnership",
        "hypothesis": comparison.hypothesis,
        "name": comparison.name,
        "opponent_agent_id": phase5d_b_agent_identity(opponent_profile_key),
        "opponent_profile_key": opponent_profile_key,
        "pair_count": pairs,
        "primary_match_inference": pair_inference(
            records,
            confidence_level=CONFIDENCE_LEVEL,
            analysis_seed=PHASE5D_B_MATCH_ROOT_SEED,
            bootstrap_replicates=BOOTSTRAP_REPLICATES,
            sign_flip_replicates=SIGN_FLIP_REPLICATES,
        ),
        "safety_cap": safety_cap,
        "schema_version": PHASE5D_B_EVALUATION_SCHEMA_VERSION,
        "secondary_metrics": secondary_metrics(records),
        "sealed_bank_opened": False,
        "sign_convention": "The candidate is the Phase 5D-B variant; p_win above 0.5 favors it.",
        "worker_independence": "Each pair is a pure function of the fresh bank, comparison, cap, and ordinal.",
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
    search_builder = phase5d_b_agent_builder(search_key)
    partner_builder = phase5d_b_agent_builder(partner_key)
    opponent_builder = phase5d_b_agent_builder(opponent_key)

    def build_candidate(seat: int):
        lower = seat in (0, 1)
        search_seat = lower if arrangement == 0 else not lower
        return search_builder(seat) if search_seat else partner_builder(seat)

    bank = phase5d_b_hetero_bank(stream_count=stream_count)
    record = run_pair(
        stream=bank.stream(ordinal),
        comparison=comparison,
        safety_cap=safety_cap,
        ordinal=ordinal,
        build_candidate=build_candidate,
        build_opponent=opponent_builder,
    )
    return ordinal, record.to_data()


def run_phase5d_b_heterogeneous_match_comparison(
    *, search_profile_key: str = ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
    partner_profile_key: str = "partner_aware_v1",
    opponent_profile_key: str = "partner_aware_v1",
    pairs: int,
    safety_cap: int = PHASE5D_B_DEFAULT_SAFETY_CAP,
    workers: int | None = None,
    progress=None,
) -> dict[str, object]:
    """Evaluate UCT+reference versus reference+reference seat-balanced."""

    if type(pairs) is not int or pairs <= 0:
        raise SearchError("pair count must be positive")
    arrangements = []
    for arrangement in (0, 1):
        comparison = MatchComparison.build(
            name=f"phase5d_b_hetero_{search_profile_key}_arrangement{arrangement}",
            candidate_profile_key=f"{search_profile_key}+{partner_profile_key}",
            opponent_profile_key=f"{opponent_profile_key}+{opponent_profile_key}",
            candidate_agent_id=phase5d_b_agent_identity(search_profile_key),
            opponent_agent_id=phase5d_b_agent_identity(opponent_profile_key),
            result_class="development",
            hypothesis="Does a root-information UCT seat remain competitive with a frozen reference partner?",
        )
        units = [
            (search_profile_key, partner_profile_key, opponent_profile_key, arrangement,
             comparison.to_data(), pairs, safety_cap, ordinal)
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
                "arrangement_meaning": "UCT at lower candidate seat" if arrangement == 0 else "UCT at higher candidate seat",
                "comparison_id": comparison.comparison_id,
                "primary_match_inference": pair_inference(
                    records,
                    confidence_level=CONFIDENCE_LEVEL,
                    analysis_seed=PHASE5D_B_HETERO_ROOT_SEED,
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
        "schema_version": "tuppi.search.phase5d_b_heterogeneous.v1",
        "sealed_bank_opened": False,
    }


def run_root_info_uct_stability(
    corpus,
    *,
    budgets: tuple[int, ...] = (2, 4, 8),
    showing_limit: int | None = None,
    trick_play_limit: int | None = None,
) -> dict[str, object]:
    """Measure fixed-budget action stability on a privacy-safe corpus."""

    if not budgets or tuple(sorted(budgets)) != budgets:
        raise SearchError("root-information budgets must be ascending")
    profiles_by_budget = {
        configuration.simulation_budget: profile_key
        for profile_key, configuration in REGISTERED_ROOT_INFO_UCT_CONFIGURATIONS.items()
    }
    missing = [budget for budget in budgets if budget not in profiles_by_budget]
    if missing:
        raise SearchError(f"no registered root-information budget for {missing}")
    showing = corpus.showing[
        : len(corpus.showing) if showing_limit is None else showing_limit
    ]
    trick_play = corpus.trick_play[
        : len(corpus.trick_play) if trick_play_limit is None else trick_play_limit
    ]
    positions = showing + trick_play
    if not positions:
        raise SearchError("root-information stability selected no positions")
    records: list[dict[str, object]] = []
    for position in positions:
        evaluations = []
        for budget in budgets:
            started = time.perf_counter()
            decision = build_root_info_uct_agent(
                profiles_by_budget[budget],
                seat=position.observation.observing_seat,
            ).explain(position.observation)
            evaluations.append(
                {
                    "action_id": decision.selected_action_id,
                    "budget": budget,
                    "information_set_nodes": decision.root_information_set_nodes,
                    "maximum_tree_depth": decision.maximum_tree_depth,
                    "selected_action_value_gap": round(
                        decision.selected_action_value_gap, 9
                    ),
                    "selected_action_visit_share": round(
                        decision.selected_action_visit_share, 9
                    ),
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
    largest_agreements = []
    for index, budget in enumerate(budgets):
        agreements = sum(
            record["evaluations"][index]["action_id"]
            == record["evaluations"][largest_index]["action_id"]
            for record in records
        )
        largest_agreements.append(
            {
                "budget": budget,
                "agreements": agreements,
                "comparisons": len(records),
                "agreement_rate": round(agreements / len(records), 6),
            }
        )
    return {
        "adjacent_action_agreement": adjacent,
        "agreement_with_largest_budget": largest_agreements,
        "budgets": list(budgets),
        "interpretation": (
            "Development stability only. The indexed hidden-world stream is prefix "
            "stable; stability does not establish playing strength."
        ),
        "positions": {
            "showing": len(showing),
            "trick_play": len(trick_play),
            "total": len(records),
        },
        "records": records,
        "schema_version": "tuppi.search.phase5d_b_budget_stability.v1",
    }


def run_root_info_uct_behavior_comparison(
    corpus,
    *,
    profile_key: str = ROOT_INFO_UCT_PRIMARY_PROFILE_KEY,
    showing_limit: int | None = None,
    trick_play_limit: int | None = None,
) -> dict[str, object]:
    """Compare reference, archived PIMC, and root-UCT actions on one corpus."""

    showing = corpus.showing[
        : len(corpus.showing) if showing_limit is None else showing_limit
    ]
    trick_play = corpus.trick_play[
        : len(corpus.trick_play) if trick_play_limit is None else trick_play_limit
    ]
    records = []
    for position in showing + trick_play:
        decision = build_root_info_uct_agent(
            profile_key, seat=position.observation.observing_seat
        ).explain(position.observation)
        uct_action = decision.selected_action_id
        pimc_action = position.pimc_action_id
        reference_action = position.reference_action_id
        if uct_action == reference_action == pimc_action:
            category = "all_agree"
        elif uct_action == reference_action:
            category = "uct_agrees_with_reference_against_pimc"
        elif uct_action == pimc_action:
            category = "uct_agrees_with_pimc_against_reference"
        else:
            category = "all_differ"
        records.append(
            {
                "category": category,
                "phase": position.observation.phase.value,
                "position_id": position.position_id,
                "pimc_action": pimc_action,
                "reference_action": reference_action,
                "root_uct_action": uct_action,
            }
        )
    counts: dict[str, int] = {}
    for record in records:
        counts[record["category"]] = counts.get(record["category"], 0) + 1
    return {
        "agent_profile_key": profile_key,
        "categories": counts,
        "interpretation": (
            "Behavioural comparison only. PIMC actions are the archived Phase 5C "
            "negative-baseline decisions stored with the privacy-safe corpus; "
            "agreement does not establish which policy is correct."
        ),
        "positions": len(records),
        "records": records,
        "schema_version": "tuppi.search.phase5d_b_behavior_comparison.v1",
    }


__all__ = (
    "PHASE5D_B_DEFAULT_SAFETY_CAP",
    "PHASE5D_B_HETERO_ROOT_SEED",
    "PHASE5D_B_MATCH_ROOT_SEED",
    "phase5d_b_agent_builder",
    "phase5d_b_agent_identity",
    "phase5d_b_hetero_bank",
    "phase5d_b_match_bank",
    "run_phase5d_b_heterogeneous_match_comparison",
    "run_phase5d_b_match_comparison",
    "run_root_info_uct_stability",
    "run_root_info_uct_behavior_comparison",
)
