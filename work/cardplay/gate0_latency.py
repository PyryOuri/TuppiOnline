"""Gate zero: the latency of one opening-lead decision, measured cold.

The admission margin the architecture review asked for is "a measured cold
maximum under 8 s against a 10 s failure bound". Everything quoted so far has
been a single warm decision on one fixed deal, which is not that.

    PYTHONPATH=src python work/cardplay/gate0_latency.py --output <dir>

What it measures, and why this shape:

* **One decision, not a throughput rate.** A deployed selector faces the bound
  on a single opening lead while a human waits. C3's 10x figure was aggregate
  throughput across *independent* observations, and `pimc.decide` is serial over
  candidates and worlds, so cross-decision parallelism does not shorten one
  decision. The honest number for this gate is single-process.
* **Cold.** A fresh gate, specification and agent per deal, and a fresh deal, so
  nothing is amortised across measurements the way a repeated call on one fixed
  observation amortises.
* **A maximum, not a mean.** The bound is a failure bound; it is the worst
  decision that breaks a match, not the average one.

It is an instrument gate, not science: it has no hypothesis and no preregistered
estimator, and it may not be read as evidence about strength.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_rules import FULL_DECK, MatchScore

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_search.config import PimcConfiguration
from tuppi_search.hybrid import construct_gated_agent, is_opening_lead
from tuppi_search.registry import opening_lead_gate, opening_lead_specification

DEALER = 0
ROOT_SEED = "tuppi-gate0-latency-v1"

#: The review's admission margin and the failure bound it sits under.
ADMISSION_MARGIN_SECONDS = 8.0
FAILURE_BOUND_SECONDS = 10.0

REFERENCE = "partner_aware_v1"
INCUMBENT = "partner_aware_lead_v2"


def _reference_agents():
    specification = phase4_specifications_by_profile_key()[REFERENCE]
    return [construct_agent(specification, seat=seat) for seat in range(4)]


def _deal_from(rng):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[seat * 13:(seat + 1) * 13]) for seat in range(4))


def _opening_lead_observation(hands, agents):
    """Play showing with the reference; stop at the opening lead."""

    state = begin_explicit_deal(
        create_match(
            initial_score=MatchScore(0, 0),
            initial_dealer=DEALER,
            match_ref="gate0-deal",
        ),
        ExplicitDeal(dealer=DEALER, hands=hands),
    )
    while state.phase is EnginePhase.SHOWING:
        seat = state.current_actor
        state = apply_match_action(
            state, agents[seat].choose_action(match_observation_for(state, seat))
        )
    if state.phase is not EnginePhase.TRICK_PLAY:
        return None
    observation = match_observation_for(state, state.current_actor)
    if not is_opening_lead(observation):
        return None
    return observation


def measure(*, worlds: int, continuation: str, deals: int) -> dict:
    agents = _reference_agents()
    rng = random.Random(f"{ROOT_SEED}:{worlds}:{continuation}")
    pimc = PimcConfiguration.build(
        world_count=worlds,
        showing_search_enabled=False,
        rollout_policy_key=continuation,
    )
    specification = opening_lead_specification(pimc=pimc)
    seconds: list[float] = []
    arms: list[int] = []
    collected = 0
    while collected < deals:
        observation = _opening_lead_observation(_deal_from(rng), agents)
        if observation is None:
            continue
        # Cold: a fresh gate and a fresh agent for every measured decision.
        gate = opening_lead_gate(pimc=pimc)
        agent = construct_gated_agent(
            specification, seat=observation.observing_seat, gate=gate
        )
        started = time.perf_counter()
        action = agent.choose_action(observation)
        seconds.append(time.perf_counter() - started)
        arms.append(len(observation.legal_actions))
        assert action in observation.legal_actions
        collected += 1
        print(f"  {collected:>3}/{deals}  {seconds[-1]:6.2f}s", flush=True)
    ordered = sorted(seconds)
    worst = ordered[-1]
    return {
        "agent_id": specification.agent_id,
        "arms_max": max(arms),
        "arms_min": min(arms),
        "continuation": continuation,
        "deals": deals,
        "gate_id": gate.gate_id,
        "max_seconds": round(worst, 3),
        "mean_seconds": round(statistics.fmean(seconds), 3),
        "median_seconds": round(statistics.median(seconds), 3),
        "min_seconds": round(ordered[0], 3),
        "p90_seconds": round(ordered[math.ceil(0.9 * len(ordered)) - 1], 3),
        "passes_admission_margin": bool(worst < ADMISSION_MARGIN_SECONDS),
        "under_failure_bound": bool(worst < FAILURE_BOUND_SECONDS),
        "world_count": worlds,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worlds", type=int, nargs="+", default=[16, 32, 64])
    parser.add_argument(
        "--continuations", nargs="+", default=[REFERENCE, INCUMBENT]
    )
    parser.add_argument("--deals", type=int, default=12)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    rows = []
    started = time.perf_counter()
    for continuation in args.continuations:
        for worlds in args.worlds:
            print(f"\nW={worlds} continuation={continuation}", flush=True)
            rows.append(measure(
                worlds=worlds, continuation=continuation, deals=args.deals
            ))
    elapsed = time.perf_counter() - started

    payload = {
        "admission_margin_seconds": ADMISSION_MARGIN_SECONDS,
        "failure_bound_seconds": FAILURE_BOUND_SECONDS,
        "note": (
            "Single-process, one decision. pimc.decide is serial over candidates "
            "and worlds, so cross-decision parallelism does not shorten one "
            "decision; C3's 10x was aggregate throughput, not latency."
        ),
        "root_seed": ROOT_SEED,
        "rows": rows,
        "schema": "tuppi-gate0-latency-v1",
        "total_seconds": round(elapsed, 1),
    }
    (args.output / "gate0_latency.json").write_text(json.dumps(payload, indent=2))

    print(f"\n{'W':>4} {'continuation':<22}{'min':>7}{'med':>7}{'p90':>7}"
          f"{'max':>7}  {'<8s':>5} {'<10s':>5}")
    for row in rows:
        print(f"{row['world_count']:>4} {row['continuation']:<22}"
              f"{row['min_seconds']:>7.2f}{row['median_seconds']:>7.2f}"
              f"{row['p90_seconds']:>7.2f}{row['max_seconds']:>7.2f}"
              f"{'yes' if row['passes_admission_margin'] else 'NO':>6}"
              f"{'yes' if row['under_failure_bound'] else 'NO':>6}")
    # Reported per continuation. A single "largest admissible" line would pick
    # arbitrarily between two continuations that both clear at the same budget,
    # and the choice between them is not a latency question.
    print()
    for continuation in args.continuations:
        admissible = [
            r for r in rows
            if r["continuation"] == continuation and r["passes_admission_margin"]
        ]
        if admissible:
            best = max(admissible, key=lambda r: r["world_count"])
            print(f"GATE ZERO  {continuation:<22} largest admissible W="
                  f"{best['world_count']} (cold max {best['max_seconds']}s)")
        else:
            print(f"GATE ZERO  {continuation:<22} no measured budget clears "
                  f"the {ADMISSION_MARGIN_SECONDS:g} s margin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
