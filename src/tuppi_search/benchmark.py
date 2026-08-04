"""Phase 5C performance measurement.

Budgets in Phase 5C are chosen from measurement, not from a guess, and this module
is where the measurement happens. Four things are timed separately because they
scale differently and are fixed by different decisions:

**World construction** - constraint model, exact count, first world, later worlds,
duplicate rate. Cheap and roughly constant.

**Rollout** - the dominant cost. ``apply_action`` revalidates the whole deal state
on every transition, so a rollout is O(remaining actions x history), and it is
measured by remaining tricks rather than quoted as one number.

**PIMC decision** - latency by legal-action count, world count, rollout policy, and
exact-tail setting. A decision costs roughly
``legal_actions x world_count x rollout``, so this is the arithmetic the budget
follows.

**Match execution** - deals per second and search decisions per match, which is what
turns a per-decision latency into "can the headline comparison finish".

Timing is operational, never semantic. No agent's behaviour depends on it, and no
brittle latency threshold is asserted in the test suite: a CI machine's speed is not
a property of the ruleset.
"""

from __future__ import annotations

from collections import Counter
import statistics
import time

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_action,
    begin_explicit_deal,
    create_match,
    observation_for,
)
from tuppi_exact import HardConstraintModel, feasible_assignment_count
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore, TRICKS_PER_DEAL

from .config import PimcConfiguration
from .errors import SearchError
from .pimc import decide
from .random import SearchSeedHierarchy, information_state_digest
from .rollout import SeatPolicies, complete_deal
from .worlds import build_world_set


BENCHMARK_SCHEMA_VERSION = "tuppi.search.benchmark.v1"
BENCHMARK_ROOT_SEED = "tuppi-phase5c-benchmark-v1"


def _positions(*, streams: int, root_seed: str = BENCHMARK_ROOT_SEED):
    """Yield reproducible decision points from reference-policy play."""

    specification = phase4_specifications_by_profile_key()["partner_aware_v1"]
    for index in range(streams):
        stream = MatchStream.build(
            root_seed=root_seed, stream_index=index, initial_dealer=0
        )
        deal = stream.deal(0)
        state = create_match(
            initial_score=MatchScore(),
            initial_dealer=0,
            match_ref=f"bench-{index:04d}",
        )
        state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=deal.hands))
        active = state.active_deal
        while not active.complete:
            actor = active.current_actor
            observation = observation_for(active, actor)
            yield active, observation
            active = apply_action(
                active,
                construct_agent(specification, seat=actor).choose_action(observation),
            )


def _summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "maximum_ms": round(ordered[-1] * 1000, 3),
        "mean_ms": round(statistics.fmean(ordered) * 1000, 3),
        "median_ms": round(statistics.median(ordered) * 1000, 3),
        "minimum_ms": round(ordered[0] * 1000, 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] * 1000, 3),
    }


def benchmark_world_construction(*, streams: int = 3, world_count: int = 8) -> dict:
    """Measure constraint construction, exact counting, and world building."""

    configuration = PimcConfiguration.build(world_count=world_count)
    model_times: list[float] = []
    count_times: list[float] = []
    set_times: list[float] = []
    duplicate_fractions: list[float] = []
    unknown_counts: list[int] = []
    for _, observation in _positions(streams=streams):
        start = time.perf_counter()
        model = HardConstraintModel.build(observation)
        model_times.append(time.perf_counter() - start)
        start = time.perf_counter()
        feasible_assignment_count(model)
        count_times.append(time.perf_counter() - start)
        seeds = SearchSeedHierarchy(
            pimc_protocol=configuration.pimc_protocol_version,
            information_state=information_state_digest(observation),
            decision_seed="benchmark",
        )
        start = time.perf_counter()
        world_set = build_world_set(
            observation, configuration=configuration, seeds=seeds
        )
        set_times.append(time.perf_counter() - start)
        duplicate_fractions.append(world_set.duplicate_fraction)
        unknown_counts.append(world_set.unknown_card_count)
    return {
        "constraint_model": _summary(model_times),
        "duplicate_fraction_mean": round(
            statistics.fmean(duplicate_fractions), 6
        ),
        "exact_count": _summary(count_times),
        "mean_unknown_cards": round(statistics.fmean(unknown_counts), 3),
        "per_world_ms": round(
            statistics.fmean(set_times) * 1000 / world_count, 3
        ),
        "world_count": world_count,
        "world_set": _summary(set_times),
    }


def benchmark_rollout(*, streams: int = 2) -> dict:
    """Measure complete-deal rollout cost by remaining tricks."""

    configuration = PimcConfiguration.build(world_count=1)
    by_remaining: dict[int, list[float]] = {}
    actions: list[int] = []
    for state, observation in _positions(streams=streams):
        if state.phase is not EnginePhase.TRICK_PLAY or state.current_trick:
            continue
        remaining = TRICKS_PER_DEAL - len(state.completed_tricks)
        policies = SeatPolicies(
            configuration=configuration, root_seat=observation.observing_seat
        )
        start = time.perf_counter()
        outcome = complete_deal(
            state, policies=policies, root_seat=observation.observing_seat
        )
        by_remaining.setdefault(remaining, []).append(time.perf_counter() - start)
        actions.append(outcome.actions_simulated)
    return {
        "by_remaining_tricks": {
            str(key): _summary(value) for key, value in sorted(by_remaining.items())
        },
        "mean_actions_per_rollout": round(statistics.fmean(actions), 2),
        "simulated_actions_per_second": round(
            sum(actions)
            / sum(sum(value) for value in by_remaining.values()),
            1,
        ),
    }


def benchmark_decisions(
    *,
    streams: int = 2,
    world_counts: tuple[int, ...] = (2, 4, 8),
    include_exact_tail: bool = True,
    rollout_policies: tuple[str, ...] = ("partner_aware_v1",),
    maximum_decisions: int = 24,
) -> dict:
    """Measure PIMC decision latency across the configuration axes."""

    results: list[dict[str, object]] = []
    for policy in rollout_policies:
        for world_count in world_counts:
            for tail in (False, True) if include_exact_tail else (False,):
                configuration = PimcConfiguration.build(
                    world_count=world_count,
                    rollout_policy_key=policy,
                    exact_tail_enabled=tail,
                )
                latencies: list[float] = []
                by_actions: dict[int, list[float]] = {}
                by_phase: dict[str, list[float]] = {}
                solver_calls = 0
                simulated = 0
                for state, observation in _positions(streams=streams):
                    if len(latencies) >= maximum_decisions:
                        break
                    if len(observation.legal_actions) < 2:
                        continue
                    del state
                    start = time.perf_counter()
                    decision = decide(
                        observation,
                        configuration=configuration,
                        decision_seed="benchmark",
                    )
                    elapsed = time.perf_counter() - start
                    latencies.append(elapsed)
                    by_actions.setdefault(
                        len(observation.legal_actions), []
                    ).append(elapsed)
                    by_phase.setdefault(observation.phase.value, []).append(elapsed)
                    solver_calls += sum(
                        item.solver_calls for item in decision.candidates
                    )
                    simulated += sum(
                        item.actions_simulated for item in decision.candidates
                    )
                results.append(
                    {
                        "by_legal_action_count": {
                            str(key): _summary(value)
                            for key, value in sorted(by_actions.items())
                        },
                        "by_phase": {
                            key: _summary(value) for key, value in sorted(by_phase.items())
                        },
                        "configuration_id": configuration.configuration_id,
                        "exact_tail_enabled": tail,
                        "latency": _summary(latencies),
                        "rollout_policy_key": policy,
                        "simulated_actions": simulated,
                        "solver_calls": solver_calls,
                        "world_count": world_count,
                    }
                )
    return {"decisions": results}


def benchmark_match_throughput(
    *, profile_key: str, deals: int = 2, opponent_profile_key: str = "partner_aware_v1"
) -> dict:
    """Measure complete-deal throughput with PIMC occupying two seats."""

    from .evaluation import agent_builder

    build_candidate = agent_builder(profile_key)
    build_opponent = agent_builder(opponent_profile_key)
    deal_times: list[float] = []
    search_decisions = 0
    total_decisions = 0
    for index in range(deals):
        stream = MatchStream.build(
            root_seed=BENCHMARK_ROOT_SEED, stream_index=100 + index, initial_dealer=0
        )
        stream_deal = stream.deal(0)
        state = create_match(
            initial_score=MatchScore(),
            initial_dealer=0,
            match_ref=f"thr-{index:04d}",
        )
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=0, hands=stream_deal.hands)
        )
        active = state.active_deal
        agents = tuple(
            (build_candidate if seat in (0, 2) else build_opponent)(seat)
            for seat in range(4)
        )
        start = time.perf_counter()
        while not active.complete:
            actor = active.current_actor
            observation = observation_for(active, actor)
            if actor in (0, 2):
                search_decisions += 1
            total_decisions += 1
            active = apply_action(active, agents[actor].choose_action(observation))
        deal_times.append(time.perf_counter() - start)
    total = sum(deal_times)
    return {
        "deal_time": _summary(deal_times),
        "deals": len(deal_times),
        "deals_per_second": round(len(deal_times) / total, 4),
        "estimated_matches_per_hour_single_worker": round(
            3600.0 / (total / len(deal_times) * 30.5), 2
        ),
        "mean_search_decisions_per_deal": round(
            search_decisions / len(deal_times), 2
        ),
        "note": (
            "Match estimates assume the Phase 5A mean leg length of 30.5 deals. A "
            "decisive agent shortens legs and changes the estimate."
        ),
        "opponent_profile_key": opponent_profile_key,
        "profile_key": profile_key,
        "total_decisions": total_decisions,
    }


def action_stability(
    *,
    profile_key: str,
    prefixes: tuple[int, ...] = (2, 4, 8),
    streams: int = 3,
    maximum_decisions: int = 40,
) -> dict:
    """Measure how often the selected action changes as the budget grows.

    Nested prefixes are exact: the Phase 5B sampler is an indexed stream and
    Phase 5C consumes its contiguous prefix, so the first N worlds of an 8-world
    budget are literally the 8-world budget's first N. Stability is therefore a
    property of the budget, not of a re-roll.
    """

    from .registry import configuration_for

    base = configuration_for(profile_key)
    largest = max(prefixes)
    configuration = PimcConfiguration.build(
        world_count=largest,
        rollout_policy_key=base.rollout_policy_key,
        utility_id=base.utility_id,
        exact_tail_enabled=base.exact_tail_enabled,
        exact_tail_max_tricks_remaining=base.exact_tail_max_tricks_remaining,
    )
    agreements: Counter = Counter()
    totals: Counter = Counter()
    considered = 0
    for state, observation in _positions(streams=streams):
        if considered >= maximum_decisions:
            break
        if len(observation.legal_actions) < 2:
            continue
        del state
        considered += 1
        seeds = SearchSeedHierarchy(
            pimc_protocol=configuration.pimc_protocol_version,
            information_state=information_state_digest(observation),
            decision_seed="stability",
        )
        full = build_world_set(
            observation, configuration=configuration, seeds=seeds
        )
        selections: dict[int, object] = {}
        for prefix in sorted(prefixes):
            sub = PimcConfiguration.build(
                world_count=prefix,
                rollout_policy_key=base.rollout_policy_key,
                utility_id=base.utility_id,
                exact_tail_enabled=base.exact_tail_enabled,
                exact_tail_max_tricks_remaining=(
                    base.exact_tail_max_tricks_remaining
                ),
            )
            decision = decide(
                observation,
                configuration=sub,
                decision_seed="stability",
                reuse_world_set=full.prefix(prefix),
            )
            selections[prefix] = decision.selected_action
        ordered = sorted(prefixes)
        for smaller, larger in zip(ordered, ordered[1:]):
            totals[(smaller, larger)] += 1
            if selections[smaller] == selections[larger]:
                agreements[(smaller, larger)] += 1
    if not considered:
        raise SearchError("action stability found no multi-action decision")
    return {
        "decisions_considered": considered,
        "note": (
            "Prefix nesting is exact, so a change between budgets is a genuine "
            "change of opinion rather than a different sample."
        ),
        "prefixes": list(sorted(prefixes)),
        "profile_key": profile_key,
        "stability": [
            {
                "agreement_rate": round(agreements[key] / totals[key], 6),
                "agreements": agreements[key],
                "comparisons": totals[key],
                "from_worlds": key[0],
                "to_worlds": key[1],
            }
            for key in sorted(totals)
        ],
    }


def full_benchmark(*, streams: int = 2) -> dict:
    """Run every benchmark section and return one canonical report."""

    return {
        "decisions": benchmark_decisions(streams=streams),
        "match_throughput": benchmark_match_throughput(
            profile_key="uniform_feasible_pimc_small_v1", deals=2
        ),
        "rollout": benchmark_rollout(streams=streams),
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "timing_is_operational": (
            "Every number here is operational. No agent's behaviour depends on "
            "timing and no latency threshold is asserted by the test suite."
        ),
        "world_construction": benchmark_world_construction(streams=streams),
    }
