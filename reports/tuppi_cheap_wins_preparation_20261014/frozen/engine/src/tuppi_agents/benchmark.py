"""Deterministic performance measurements for the Phase 4 baselines.

Phase 4 agents are meant to stay cheap enough to serve later as rollout
policies, opponent models, fixed historical baselines, and readable reference
agents. This module measures that, on fixed deals, with no CI threshold: the
numbers are recorded, not asserted.

Wall-clock figures are hardware-dependent by nature. What is reproducible is
the *relative* cost against the Phase 3 protocol controls on the same deals in
the same process, so that is reported alongside the absolute values.
"""

from __future__ import annotations

from statistics import fmean
import time
import tracemalloc

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.deals import DealBank, DealerPolicy, generate_deal_bank
from tuppi_rules import MatchScore

from .controls import construct_control_agent, control_specification
from .factory import construct_agent
from .features import build_features
from .profiles import registered_profiles
from .protocol import DiagnosticsRecordingAgent
from .registry import LADDER_PROFILE_KEYS, phase4_specifications_by_profile_key


BENCHMARK_SCHEMA_VERSION = "tuppi.agents.performance_report.v1"
BENCHMARK_SEED = "phase4-benchmark-v1"


def benchmark_bank(count: int) -> DealBank:
    return generate_deal_bank(
        count=count,
        root_seed=BENCHMARK_SEED,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "phase4_benchmark"},
    )


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _run_bank(bank: DealBank, make_agent, *, collect_latency: bool):
    latencies: list[float] = []
    started = time.perf_counter()
    for base in bank.base_deals:
        agents = tuple(make_agent(seat) for seat in range(4))
        state = create_match(
            initial_score=base.starting_score,
            initial_dealer=base.dealer,
            match_ref="benchmark",
        )
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=base.dealer, hands=base.hands)
        )
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            actor = state.current_actor
            assert actor is not None
            observation = match_observation_for(state, actor)
            if collect_latency:
                action_start = time.perf_counter()
                action = agents[actor].choose_action(observation)
                latencies.append(time.perf_counter() - action_start)
            else:
                action = agents[actor].choose_action(observation)
            state = apply_match_action(state, action)
    return time.perf_counter() - started, latencies


def _latency_summary(latencies: list[float]) -> dict[str, object]:
    return {
        "actions": len(latencies),
        "mean_seconds": fmean(latencies) if latencies else None,
        "p50_seconds": _percentile(latencies, 0.50),
        "p95_seconds": _percentile(latencies, 0.95),
        "p99_seconds": _percentile(latencies, 0.99),
        "max_seconds": max(latencies) if latencies else None,
    }


def measure_feature_extraction(bank: DealBank, profile_key: str) -> dict[str, object]:
    """Time the pure feature layer separately from action selection."""

    profile = registered_profiles()[profile_key]
    specification = phase4_specifications_by_profile_key()[profile_key]
    durations: list[float] = []
    base = bank.base_deals[0]
    agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    state = create_match(
        initial_score=base.starting_score,
        initial_dealer=base.dealer,
        match_ref="benchmark-features",
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=base.dealer, hands=base.hands))
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        started = time.perf_counter()
        build_features(observation, include_inference=profile.uses_public_inference)
        durations.append(time.perf_counter() - started)
        state = apply_match_action(state, agents[actor].choose_action(observation))
    return {
        "includes_public_inference": profile.uses_public_inference,
        "profile_key": profile_key,
        **_latency_summary(durations),
    }


def measure_diagnostics_overhead(bank: DealBank, profile_key: str) -> dict[str, object]:
    """Compare plain play with diagnostics-recording play on the same deals."""

    specification = phase4_specifications_by_profile_key()[profile_key]
    plain_seconds, plain_latency = _run_bank(
        bank,
        lambda seat: construct_agent(specification, seat=seat),
        collect_latency=True,
    )
    verbose_seconds, verbose_latency = _run_bank(
        bank,
        lambda seat: DiagnosticsRecordingAgent(
            construct_agent(specification, seat=seat)
        ),
        collect_latency=True,
    )
    return {
        "diagnostics_disabled": _latency_summary(plain_latency),
        "diagnostics_enabled": _latency_summary(verbose_latency),
        "overhead_ratio": (
            verbose_seconds / plain_seconds if plain_seconds > 0 else None
        ),
        "profile_key": profile_key,
    }


def measure_memory(bank: DealBank, profile_key: str) -> dict[str, object]:
    specification = phase4_specifications_by_profile_key()[profile_key]
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    _run_bank(
        bank,
        lambda seat: construct_agent(specification, seat=seat),
        collect_latency=False,
    )
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "peak_bytes": peak,
        "profile_key": profile_key,
        "retained_bytes": current - before,
    }


def run_benchmark(*, deal_count: int = 12) -> dict[str, object]:
    """Measure every ladder rung plus the protocol-control reference."""

    bank = benchmark_bank(deal_count)
    control = control_specification("first_legal")
    control_seconds, control_latency = _run_bank(
        bank,
        lambda seat: construct_control_agent(control, seat=seat, seed=None),
        collect_latency=True,
    )
    control_rate = deal_count / control_seconds if control_seconds > 0 else None

    rows: list[dict[str, object]] = [
        {
            "agent": "control:first_legal",
            "deals_per_second": control_rate,
            "latency": _latency_summary(control_latency),
            "relative_wall_clock": 1.0,
            "seconds": control_seconds,
        }
    ]
    for key in LADDER_PROFILE_KEYS:
        specification = phase4_specifications_by_profile_key()[key]
        seconds, latency = _run_bank(
            bank,
            lambda seat, spec=specification: construct_agent(spec, seat=seat),
            collect_latency=True,
        )
        rows.append(
            {
                "agent": key,
                "deals_per_second": deal_count / seconds if seconds > 0 else None,
                "latency": _latency_summary(latency),
                "relative_wall_clock": (
                    seconds / control_seconds if control_seconds > 0 else None
                ),
                "seconds": seconds,
            }
        )
    return {
        "deal_bank_id": bank.deal_bank_id,
        "deal_count": deal_count,
        "diagnostics_overhead": measure_diagnostics_overhead(bank, "match_aware_v1"),
        "feature_extraction": [
            measure_feature_extraction(bank, key)
            for key in ("reactive_contract_v1", "match_aware_v1")
        ],
        "memory": [
            measure_memory(bank, key)
            for key in ("reactive_contract_v1", "match_aware_v1")
        ],
        "note": (
            "Wall-clock values are hardware dependent. The engine revalidates the "
            "whole deal state on every accepted action, so it dominates the "
            "measurement; the relative column is the meaningful comparison."
        ),
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "throughput": rows,
    }
