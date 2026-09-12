"""T5: does the improvement survive a genuinely foreign opponent, or a familiar one?

The instrument for [docs/transfer/hypotheses_t5.md], committed as `5b77e42`
before this file existed. Read it first; nothing here may deviate from it.

    PYTHONPATH=src python work/transfer/t5_range.py --output <dir>

T4 could only reach 8.7% opponent divergence, below the 10.1% of the improvement
it was testing. The Phase 3 controls reach 61.5%. They are also weak, so this
instrument measures *strength* alongside divergence and separates a saturation
ceiling from a transfer failure by the rule fixed in section 6.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import random
import statistics
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "cardplay"))
from c1_headroom import build_equity_table, _deal_from  # noqa: E402
from t4_transfer import (  # noqa: E402
    ASSIGNMENTS, DEALER, INCUMBENT, PREDECESSOR, ROTATIONS,
    CANCELLATION_TOLERANCE, T2_V5_MARGIN, _agent,
)

from tuppi_agents.controls import (  # noqa: E402
    control_agent_specifications,
    construct_control_agent,
)
from tuppi_engine import (  # noqa: E402
    EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
    create_match, match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_rules import MatchScore, Team  # noqa: E402

CONTROL_OPPONENT = PREDECESSOR
PEERS = ("reactive_contract_v1", "reactive_contract_legacy_show_v1",
         "legacy_heuristic_port_v1")
#: Phase 3 controls. `show_selection_nolo_low` is excluded: it is a showing-phase
#: control and would confound the trick-play comparison with a showing difference.
FOREIGN = ("lowest_legal_card", "first_legal", "highest_legal_card",
           "seeded_random_legal")
OPPONENTS = (CONTROL_OPPONENT,) + PEERS + FOREIGN
#: Fixed here so it cannot be chosen after seeing a result.
OPPONENT_SEED = "tuppi-t5-opponent-v1"
BASE_DEALS = 1024
ROOT_SEED = "tuppi-t5-range-v1"
BOOTSTRAP_SEED = "tuppi-t5-bootstrap-v1"
REPLICATES = 5000
SPEARMAN_TIEBREAK = 0.8
#: T4's measured peer margins, for gate I4.
T4_MARGINS = {
    "legacy_heuristic_port_v1": (0.004707, 0.007191),
    "reactive_contract_legacy_show_v1": (0.004164, 0.006637),
    "reactive_contract_v1": (0.004324, 0.007039),
}

_CACHE: dict = {}


def _opponent_agents(key: str):
    """Either registry. Controls take a seed only when they are stochastic."""

    if key in _CACHE:
        return _CACHE[key]
    controls = {s.agent_family: s for s in control_agent_specifications()}
    if key in controls:
        spec = controls[key]
        seed = OPPONENT_SEED if key == "seeded_random_legal" else None
        built = {s: construct_control_agent(spec, seat=s, seed=seed) for s in range(4)}
    else:
        built = {s: _agent(key, s) for s in range(4)}
    _CACHE[key] = built
    return built


def _candidate_agents(key: str):
    if ("cand", key) not in _CACHE:
        _CACHE[("cand", key)] = {s: _agent(key, s) for s in range(4)}
    return _CACHE[("cand", key)]


def _table(corpus: str):
    if "table" not in _CACHE:
        _CACHE["table"] = build_equity_table(Path(corpus))[0]
    return _CACHE["table"]


def _play(*, hands, candidate_key, opponent_key, candidate_team, table):
    candidate = _candidate_agents(candidate_key)
    opponent = _opponent_agents(opponent_key)
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=DEALER,
                     match_ref="t5-deal"),
        ExplicitDeal(dealer=DEALER, hands=hands))
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        ours = (seat % 2) == candidate_team
        actor = candidate[seat] if ours else opponent[seat]
        state = apply_match_action(state, actor.choose_action(observation))
    result = state.completed_deals[-1].public_result
    return table.delta(before=result.score_before, after=result.score_after,
                       team=Team(candidate_team),
                       we_deal=(DEALER % 2 == candidate_team))


def measure_base_deal(index: int, corpus: str, opponent_key: str) -> dict:
    table = _table(corpus)
    rng = random.Random(f"{ROOT_SEED}|deal|{index}")
    base = _deal_from(rng)
    with trusted_transitions():
        incumbent_values, predecessor_values = [], []
        for rotation in range(ROTATIONS):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for assignment in range(ASSIGNMENTS):
                incumbent_values.append(_play(
                    hands=hands, candidate_key=INCUMBENT, opponent_key=opponent_key,
                    candidate_team=assignment, table=table))
                predecessor_values.append(_play(
                    hands=hands, candidate_key=PREDECESSOR, opponent_key=opponent_key,
                    candidate_team=assignment, table=table))
    return {
        "index": index,
        "games": len(incumbent_values),
        "margin": statistics.fmean(incumbent_values) - statistics.fmean(predecessor_values),
        # Strength: how much the predecessor beats X by. Already computed.
        "strength": statistics.fmean(predecessor_values),
    }


def measure_control_block(index: int, corpus: str) -> float:
    table = _table(corpus)
    rng = random.Random(f"{ROOT_SEED}|control|{index}")
    base = _deal_from(rng)
    with trusted_transitions():
        values = []
        for rotation in range(ROTATIONS):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for assignment in range(ASSIGNMENTS):
                values.append(_play(
                    hands=hands, candidate_key=PREDECESSOR,
                    opponent_key=PREDECESSOR, candidate_team=assignment, table=table))
    return statistics.fmean(values)


def bootstrap(values, seed):
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(statistics.fmean(rng.choice(values) for _ in range(n))
                   for _ in range(REPLICATES))
    return draws[int(0.025 * REPLICATES)], draws[int(0.975 * REPLICATES)]


def spearman(xs, ys) -> float:
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for place, i in enumerate(order):
            r[i] = float(place)
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else 0.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",
                        default="/Users/pyryouri/Developer/TuppiRuns/phase7/t0-pilot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-deals", type=int, default=BASE_DEALS)
    parser.add_argument("--control-deals", type=int, default=32)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    build_equity_table(Path(args.corpus))
    started = time.perf_counter()
    control_blocks = [measure_control_block(i, args.corpus)
                      for i in range(args.control_deals)]
    worst = max(abs(v) for v in control_blocks) if control_blocks else 0.0
    i1 = worst <= CANCELLATION_TOLERANCE
    print(f"I1 identical teams cancel: {i1} (largest |value| {worst:.2e})", flush=True)

    results = {}
    for opponent in OPPONENTS:
        rows = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(measure_base_deal, i, args.corpus, opponent)
                       for i in range(args.base_deals)]
            for future in as_completed(futures):
                rows.append(future.result())
        margins = [r["margin"] for r in rows]
        lo, hi = bootstrap(margins, f"{BOOTSTRAP_SEED}|{opponent}")
        results[opponent] = {
            "group": ("control" if opponent == CONTROL_OPPONENT
                      else "peer" if opponent in PEERS else "foreign"),
            "mean": statistics.fmean(margins), "ci95": [lo, hi],
            "strength": statistics.fmean([r["strength"] for r in rows]),
            "base_deals": len(rows),
            "complete_blocks": all(r["games"] == ROTATIONS * ASSIGNMENTS for r in rows),
        }
        r = results[opponent]
        print(f"{opponent:<34} {r['group']:<8} margin {r['mean']:+.6f} "
              f"[{lo:+.6f}, {hi:+.6f}]  strength {r['strength']:+.4f}", flush=True)
    elapsed = time.perf_counter() - started

    ctrl = results[CONTROL_OPPONENT]
    foreign = [results[o] for o in FOREIGN]
    foreign_mean = statistics.fmean(r["mean"] for r in foreign)
    rho_strength = spearman([r["strength"] for r in foreign],
                            [r["mean"] for r in foreign])

    overlaps_control = all(
        results[o]["ci95"][1] >= ctrl["ci95"][0] and
        results[o]["ci95"][0] <= ctrl["ci95"][1] for o in OPPONENTS)
    if overlaps_control:
        verdict = "ROBUST_TRANSFER"
    elif foreign_mean >= ctrl["mean"]:
        verdict = "AMBIGUOUS"
    elif abs(rho_strength) >= SPEARMAN_TIEBREAK:
        verdict = "SATURATION"
    else:
        verdict = "TRANSFER_DEGRADES"

    i4 = {o: (results[o]["ci95"][1] >= lo and results[o]["ci95"][0] <= hi)
          for o, (lo, hi) in T4_MARGINS.items()}
    divergences = {"reactive_contract_v1": 3.7,
                   "reactive_contract_legacy_show_v1": 5.3,
                   "legacy_heuristic_port_v1": 8.7, "lowest_legal_card": 45.2,
                   "first_legal": 55.7, "highest_legal_card": 59.3,
                   "seeded_random_legal": 61.5}
    gates = {
        "I1_identical_teams_cancel": i1,
        "I2_block_completeness": all(r["complete_blocks"] for r in results.values()),
        "I3_control_replicates_t2_v5":
            ctrl["ci95"][0] <= T2_V5_MARGIN <= ctrl["ci95"][1],
        "I4_t4_replicates": all(i4.values()),
        "I5_range_is_real": min(divergences.values()) < 10 and max(divergences.values()) > 40,
    }
    payload = {
        "schema": "tuppi-t5-range-v1", "root_seed": ROOT_SEED,
        "opponent_seed": OPPONENT_SEED, "seconds": round(elapsed, 1),
        "instrument_gates": gates, "i4_by_opponent": i4,
        "control_worst_cancellation": worst,
        "divergence_percent": divergences,
        "margins": results,
        "foreign_mean_margin": foreign_mean,
        "spearman_margin_vs_strength_foreign": rho_strength,
        "verdict": verdict,
        "overall": ("VOID_INSTRUMENT_GATE_FAILED" if not all(gates.values())
                    else "MEASURED"),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "t5_range.json").write_text(json.dumps(payload, indent=2))

    print(f"\n{elapsed:.0f}s")
    print("instrument gates:", gates)
    print(f"control margin {ctrl['mean']:+.6f}   foreign mean {foreign_mean:+.6f}")
    print(f"spearman(margin, strength) over the four foreign: {rho_strength:+.3f}")
    print(f"VERDICT: {verdict}   OVERALL: {payload['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
