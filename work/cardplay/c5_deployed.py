"""C5: does the measured headroom survive deployment and a real score?

The instrument for [docs/cardplay/hypotheses_c5.md], committed as `d515f3b`
before this file existed. Read it first; nothing here may deviate from it.

    PYTHONPATH=src python work/cardplay/c5_deployed.py --output <dir>

C2 measured headroom inside an instrument, every deal starting at 0-0, with the
arms enumerated rather than chosen in play. This deploys the scoped selector:
it plays, against the incumbent, under the canonical duplicate design, from
score states drawn from the distribution a real match visits.

Two things it deliberately does *not* do. It does not parallelise base deals:
each searched decision already uses eight processes, and nesting the two
oversubscribes the machine. And it is a screening campaign — Phase 5A fixed
promotion on orientation-averaged match win probability over complementary
pairs, which this is not.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c1_headroom import build_equity_table, _deal_from  # noqa: E402

from tuppi_agents import construct_agent  # noqa: E402
from tuppi_agents.improved_registry import (  # noqa: E402
    improved_agent_from_specification,
    improved_specifications_by_profile_key,
)
from tuppi_engine import (  # noqa: E402
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_rules import MatchScore, Team  # noqa: E402

from tuppi_search.config import PimcConfiguration  # noqa: E402
from tuppi_search.hybrid import (  # noqa: E402
    construct_gated_agent_from_specification,
    is_opening_lead,
)
from tuppi_search.registry import opening_lead_specification  # noqa: E402

INCUMBENT = "partner_aware_lead_v2"
WORLD_COUNT = 128
WORKERS = 8
BASE_DEALS = 256
ROTATIONS = 4
ASSIGNMENTS = 2
ROOT_SEED = "tuppi-c5-deployed-v1"
BOOTSTRAP_SEED = "tuppi-c5-bootstrap-v1"
REPLICATES = 5000
DELTA = 0.001
#: I1 tolerance. The equity endpoint is a float lookup, so the two orientations
#: cancel to about 1e-17 rather than to 0.0; see section 8 of the hypotheses.
CANCELLATION_TOLERANCE = 1e-12
#: I5: the draw may not sit more than this far above the visit distribution's own
#: 0-0 share. An absolute bar would void a faithful draw by chance.
MAX_ZERO_ZERO_EXCESS = 0.10
#: Matches simulated, reference against reference, to build the visit distribution.
VISIT_MATCHES = 64

_CACHE: dict = {}


def _reference_agents():
    if "reference" not in _CACHE:
        spec = improved_specifications_by_profile_key()[INCUMBENT]
        _CACHE["reference"] = {
            seat: improved_agent_from_specification(
                spec, profile_key=INCUMBENT, seat=seat)
            for seat in range(4)}
    return _CACHE["reference"]


def _candidate_specification():
    if "candidate" not in _CACHE:
        pimc = PimcConfiguration.build(
            world_count=WORLD_COUNT,
            showing_search_enabled=False,
            rollout_policy_key=INCUMBENT,
        )
        _CACHE["candidate"] = opening_lead_specification(
            pimc=pimc, delegate_policy_key=INCUMBENT)
    return _CACHE["candidate"]


def _table(corpus: str):
    if "table" not in _CACHE:
        _CACHE["table"] = build_equity_table(Path(corpus))[0]
    return _CACHE["table"]


def visit_distribution(seed: str) -> list[tuple[MatchScore, int]]:
    """Every (score, dealer) a reference-vs-reference match actually visits.

    Sampled rather than assumed: the distribution of score states a match
    reaches is a property of the rules and the incumbent's play, and simulating
    it costs seconds because no search is involved.
    """

    agents = _reference_agents()
    rng = random.Random(seed)
    visited: list[tuple[MatchScore, int]] = []
    for index in range(VISIT_MATCHES):
        state = create_match(
            initial_score=MatchScore(0, 0), initial_dealer=0,
            match_ref=f"c5-visit-{index}")
        guard = 0
        while not state.terminal and guard < 4000:
            guard += 1
            if state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                seat = state.current_actor
                state = apply_match_action(
                    state,
                    agents[seat].choose_action(match_observation_for(state, seat)))
                continue
            # Between deals: this is the state a real match arrives at, which is
            # exactly what the draw is meant to represent.
            visited.append((state.score, state.dealer))
            state = begin_explicit_deal(
                state, ExplicitDeal(dealer=state.dealer, hands=_deal_from(rng)))
    return visited


def _play_deal(*, hands, dealer, score, seat_agents, table, candidate_team):
    """Play one deal to completion and return the candidate team's equity delta."""

    state = begin_explicit_deal(
        create_match(initial_score=score, initial_dealer=dealer,
                     match_ref="c5-deal"),
        ExplicitDeal(dealer=dealer, hands=hands))
    searched = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        agent = seat_agents[seat]
        if getattr(agent, "searches", None) is not None and agent.searches(observation):
            searched += 1
        state = apply_match_action(state, agent.choose_action(observation))
    result = state.completed_deals[-1].public_result
    value = table.delta(
        before=result.score_before,
        after=result.score_after,
        team=Team(candidate_team),
        we_deal=(dealer % 2 == candidate_team),
    )
    return value, searched


def measure_base_deal(index: int, corpus: str, visits, *, control: bool) -> dict:
    """One base deal's 8 transformations: 4 rotations x 2 team assignments.

    Exactly 4 of the 8 are searched, which is what makes gate I3's expected count
    exact rather than approximate. Showing is delegated to the incumbent by the
    gate, so the contract, the declarer and therefore `first_leader` are settled
    identically in both assignments of a rotation; the candidate's only deviation
    is the opening lead itself, which comes after. So the leading seat is the same
    in both assignments, and it belongs to the candidate team in exactly one.
    """

    table = _table(corpus)
    reference = _reference_agents()
    specification = _candidate_specification()
    rng = random.Random(f"{ROOT_SEED}|deal|{index}")
    base = _deal_from(rng)
    score, dealer = visits[rng.randrange(len(visits))]

    values, searched_total = [], 0
    for rotation in range(ROTATIONS):
        hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
        for assignment in range(ASSIGNMENTS):
            candidate_team = assignment          # 0 -> seats 0,2 ; 1 -> seats 1,3
            seat_agents = {}
            for seat in range(4):
                on_candidate = (seat % 2) == candidate_team
                if on_candidate and not control:
                    seat_agents[seat] = construct_gated_agent_from_specification(
                        specification, seat=seat, workers=WORKERS)
                else:
                    seat_agents[seat] = reference[seat]
            value, searched = _play_deal(
                hands=hands, dealer=dealer, score=score,
                seat_agents=seat_agents, table=table,
                candidate_team=candidate_team)
            # Orientation-averaged: assignment 1 measures the same cards with the
            # teams swapped, so its sign is taken from the candidate's side too.
            values.append(value)
            searched_total += searched
    return {
        "index": index,
        "games": len(values),
        # Orientation-averaged. Assignment 0 records team 0's equity and
        # assignment 1 records team 1's, and those are exact negatives when the
        # two teams play alike — so the MEAN over the eight transformations is
        # the statistic that cancels to 0.0, which gate I1 checks directly.
        # Their difference would not cancel; it would double the signal and the
        # noise together and make the control meaningless.
        "paired_utility": statistics.fmean(values),
        "searched": searched_total,
        "zero_zero": score == MatchScore(0, 0),
        "score": [score.team0, score.team1],
    }


def bootstrap(values, seed):
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(statistics.fmean(rng.choice(values) for _ in range(n))
                   for _ in range(REPLICATES))
    return draws[int(0.025 * REPLICATES)], draws[int(0.975 * REPLICATES)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",
                        default="/Users/pyryouri/Developer/TuppiRuns/phase7/t0-pilot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-deals", type=int, default=BASE_DEALS)
    parser.add_argument("--control-deals", type=int, default=16,
                        help="reference-vs-reference blocks for gate I1")
    args = parser.parse_args()

    build_equity_table(Path(args.corpus))
    print("sampling the match-visit distribution...", flush=True)
    visits = visit_distribution(f"{ROOT_SEED}|visits")
    zero = sum(1 for score, _ in visits if score == MatchScore(0, 0))
    print(f"  {len(visits)} visited states, {zero} of them 0-0", flush=True)

    started = time.perf_counter()
    print(f"\nI1 control: {args.control_deals} reference-vs-reference blocks",
          flush=True)
    control = [measure_base_deal(-1 - i, args.corpus, visits, control=True)
               for i in range(args.control_deals)]
    i1_values = [row["paired_utility"] for row in control]
    worst = max(abs(value) for value in i1_values) if i1_values else 0.0
    i1 = worst <= CANCELLATION_TOLERANCE
    print(f"  identical teams cancel: {i1} (largest |paired_utility| {worst:.2e})",
          flush=True)

    rows = []
    for index in range(args.base_deals):
        rows.append(measure_base_deal(index, args.corpus, visits, control=False))
        if (index + 1) % 16 == 0:
            print(f"  {index+1}/{args.base_deals} base deals, "
                  f"{time.perf_counter()-started:.0f}s", flush=True)
    elapsed = time.perf_counter() - started

    searched = sum(row["searched"] for row in rows)
    expected = args.base_deals * ROTATIONS
    zero_share = sum(1 for row in rows if row["zero_zero"]) / len(rows)
    visit_zero_share = zero / len(visits)
    values = [row["paired_utility"] for row in rows]
    lo, hi = bootstrap(values, BOOTSTRAP_SEED)
    mean = statistics.fmean(values)

    gates = {
        "I1_identical_teams_cancel": i1,
        # Counted, not assumed. `tuppi_eval.qualification` is the repository's
        # enforcement of this and the pre-registration named it, but it operates
        # on `DuplicateBlockRecord`s produced by the arena; this harness drives
        # the engine directly as C1, C2 and C3 do and produces none, so there is
        # nothing for it to check. The deviation is declared in the results. The
        # substantive property is enforced here instead: every block contributes
        # all eight transformations, and a failure raises rather than being
        # averaged away.
        "I2_block_completeness": all(
            row["games"] == ROTATIONS * ASSIGNMENTS for row in rows
        ) and len(rows) == args.base_deals,
        "I3_searched_exactly_the_opening_leads": searched == expected,
        "I5_score_draw_is_faithful":
            zero_share - visit_zero_share <= MAX_ZERO_ZERO_EXCESS,
    }
    verdict = ("VOID_INSTRUMENT_GATE_FAILED" if not all(gates.values())
               else "SCREENED_IN" if lo > DELTA
               else "SCREENED_OUT" if hi < DELTA
               else "EQUIVALENT" if -DELTA <= lo and hi <= DELTA
               else "INCONCLUSIVE")

    payload = {
        "schema": "tuppi-c5-deployed-v1",
        "root_seed": ROOT_SEED, "bootstrap_seed": BOOTSTRAP_SEED,
        "world_count": WORLD_COUNT, "continuation": INCUMBENT,
        "base_deals": len(rows), "games": len(rows) * ROTATIONS * ASSIGNMENTS,
        "searched_decisions": searched, "expected_searched": expected,
        "games_per_block": sorted({row["games"] for row in rows}),
        "qualification_module_used": False,
        "zero_zero_share": zero_share, "visit_zero_zero_share": visit_zero_share,
        "control_worst_cancellation": worst, "seconds": round(elapsed, 1),
        "instrument_gates": gates,
        "mean_equity_difference": mean, "ci95": [lo, hi],
        "delta": DELTA, "verdict": verdict,
        "candidate_agent_id": _candidate_specification().agent_id,
        # Persisted because the first run of this instrument could not evaluate
        # its own prediction P3: the per-block scores were computed and thrown
        # away. A prediction the instrument cannot test is not a prediction.
        "rows": rows,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "c5_deployed.json").write_text(json.dumps(payload, indent=2))

    print(f"\nbase deals {len(rows)}  games {payload['games']}  "
          f"searched {searched}/{expected}  {elapsed:.0f}s")
    print(f"0-0 share {zero_share:.1%} (visit distribution {visit_zero_share:.1%})")
    print("instrument gates:", gates)
    print(f"\nmean equity difference {mean:+.6f}  ci95 [{lo:+.6f}, {hi:+.6f}]"
          f"  delta {DELTA}")
    print(f"VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
