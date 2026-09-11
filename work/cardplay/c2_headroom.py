"""C2: how much of the opening lead's headroom is reachable at all?

The instrument for [docs/cardplay/hypotheses_c2.md], committed as `e37d54e`
before this file existed. Read it first; nothing here may deviate from it.

    PYTHONPATH=src python work/cardplay/c2_headroom.py --output <dir>

C1 tried to estimate `G_legal` with empirical-Bayes shrinkage and produced an
impossibility. This abandons that approach rather than repairing it:
`G_deploy(W)` is *itself* a valid lower bound on `G_legal` at every W, because a
W-world selector is observation-compatible. So the primary estimator is a
one-sided bootstrap lower bound on `G_deploy(256)`, which needs no functional
form and no model of the noise.

Reaching W=256 is why M is 512 completions rather than C3's 128: the choosing and
scoring blocks must stay disjoint, which caps W at M/2.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c1_headroom import (  # noqa: E402
    DELTA, _deal_from, _price, _resources, _show_through, build_equity_table,
)
from c3_worlds import deploy_at, foresight  # noqa: E402

from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_rules import FULL_DECK  # noqa: E402
from tuppi_rules.showing import valid_show_cards  # noqa: E402

OBSERVATIONS = 512
#: M. Caps the largest budget at M/2 because choose and score blocks are disjoint.
COMPLETIONS = 512
WORLD_COUNTS = (1, 2, 4, 8, 16, 32, 64, 128, 256)
ROOT_SEED = "tuppi-c2-headroom-v1"
BOOTSTRAP_SEED = "tuppi-c2-bootstrap-v1"
REPLICATES = 5000
SEAT_SHARE = 0.5
MAX_DRAWS = COMPLETIONS * 200

#: C3's published curve, for the I4 replication gate. Normalised, with 95% CIs.
C3_CURVE = {
    1: (-0.000794, -0.001975, 0.000393),
    2: (-0.000246, -0.001151, 0.000652),
    4: (-0.000148, -0.000820, 0.000530),
    8: (0.000382, -0.000136, 0.000906),
    16: (0.000891, 0.000500, 0.001284),
    32: (0.001255, 0.000954, 0.001574),
    64: (0.001470, 0.001226, 0.001717),
}

#: The increments the secondary extrapolation is fitted over, per section 5.
FIT_WINDOW = (8, 16, 32, 64, 128)


def measure_observation(index: int, corpus: str) -> dict | None:
    """One observation's 512 hard-constraint completions, all 13 arms priced.

    Identical to C3's worker except for the completion count and the seed. Kept
    as a copy rather than imported because C3's binds its own COMPLETIONS and
    ROOT_SEED at module level, and rebinding another module's constants to reuse
    a function is precisely how two runs come to disagree about what they ran.
    """

    table, agents = _resources(corpus)
    with trusted_transitions():
        rng = random.Random(f"{ROOT_SEED}|obs|{index}")
        found = None
        for _ in range(64):
            hands = _deal_from(rng)
            got = _show_through(hands, agents)
            if got is not None:
                found = (hands, *got)
                break
        if found is None:
            return None
        hands, seat, shows, observation = found
        team = seat % 2
        own = hands[seat]
        legal = list(observation.legal_actions)
        others = [s for s in range(4) if s != seat]
        pinned = {a.seat: a.shown_card for a in shows if a.seat != seat}
        fixed = set(own) | set(pinned.values())
        pool = [c for c in FULL_DECK if c not in fixed]
        arms = [[] for _ in legal]
        made = draws = 0
        while made < COMPLETIONS and draws < MAX_DRAWS:
            draws += 1
            rng.shuffle(pool)
            built = [None] * 4
            built[seat] = own
            need = {s: ([pinned[s]] if s in pinned else []) for s in others}
            cursor = 0
            for s in others:
                take = 13 - len(need[s])
                need[s].extend(pool[cursor:cursor + take])
                cursor += take
                built[s] = tuple(need[s])
            world = tuple(built)
            if not all(a.shown_card in valid_show_cards(world[a.seat],
                                                        a.declared_contract)
                       for a in shows):
                continue
            made += 1
            for slot, action in enumerate(legal):
                arms[slot].append(_price(world, shows, action, agents, table, team))
        if made < COMPLETIONS:
            return None
        return {"index": index, "arms": arms,
                "policy_index": legal.index(agents[seat].choose_action(observation)),
                "rollouts": len(legal) * made}


def bootstrap(values, seed, *, one_sided: bool = False):
    """Percentile bootstrap over observations. One-sided returns only the 5% tail."""

    rng = random.Random(seed)
    n = len(values)
    draws = sorted(statistics.fmean(rng.choice(values) for _ in range(n))
                   for _ in range(REPLICATES))
    if one_sided:
        return draws[int(0.05 * REPLICATES)]
    return draws[int(0.025 * REPLICATES)], draws[int(0.975 * REPLICATES)]


def _increment_fit(curve: dict[int, float]) -> tuple[float, float] | None:
    """OLS of log(increment) on log(W) over FIT_WINDOW. None if any is <= 0."""

    xs, ys = [], []
    for w in FIT_WINDOW:
        step = curve[2 * w] - curve[w]
        if step <= 0:
            return None
        xs.append(math.log(w))
        ys.append(math.log(step))
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    if denominator == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator
    return my - b * mx, b


def _plateau(curve: dict[int, float]) -> float | None:
    """G_deploy(256) plus the fitted tail beyond it. None when b >= 0."""

    fit = _increment_fit(curve)
    if fit is None:
        return None
    a, b = fit
    if b >= 0:
        return None
    top = max(WORLD_COUNTS)
    return curve[top] + math.exp(a) * top ** b / (1 - 2 ** b)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",
                        default="/Users/pyryouri/Developer/TuppiRuns/phase7/t0-pilot")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--observations", type=int, default=OBSERVATIONS)
    args = parser.parse_args()

    build_equity_table(Path(args.corpus))
    rows = []
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(measure_observation, index, args.corpus)
                   for index in range(args.observations)]
        for done, future in enumerate(as_completed(futures), start=1):
            row = future.result()
            if row is not None:
                rows.append(row)
            if done % 64 == 0:
                print(f"  {done} observations, {time.perf_counter()-started:.0f}s",
                      flush=True)
    elapsed = time.perf_counter() - started
    if not rows:
        print("no observation produced a full completion set")
        return 1

    per_w = {w: [deploy_at(row, w) for row in rows] for w in WORLD_COUNTS}
    fore = [foresight(row) for row in rows]
    fore_mean = statistics.fmean(fore) * SEAT_SHARE
    point = {w: statistics.fmean(per_w[w]) * SEAT_SHARE for w in WORLD_COUNTS}

    # Paired increments: per observation, then averaged. Correlated subsets make
    # this a far tighter test than differencing the two marginal means.
    paired = {}
    for low, high in zip(WORLD_COUNTS, WORLD_COUNTS[1:]):
        paired[f"{low}->{high}"] = statistics.fmean(
            b - a for a, b in zip(per_w[low], per_w[high])) * SEAT_SHARE

    i1 = all(point[w] <= fore_mean for w in WORLD_COUNTS)
    i2 = all(value >= 0 for value in paired.values())
    i3 = paired["128->256"] < paired["32->64"]
    ci = {w: bootstrap(per_w[w], f"{BOOTSTRAP_SEED}|{w}") for w in WORLD_COUNTS}
    i4 = {}
    for w, (_, c3_lo, c3_hi) in C3_CURVE.items():
        lo, hi = ci[w][0] * SEAT_SHARE, ci[w][1] * SEAT_SHARE
        i4[str(w)] = bool(lo <= c3_hi and hi >= c3_lo)
    gates = {"I1_bounded_by_foresight": i1, "I2_monotone_in_W": i2,
             "I3_decelerating_into_new_range": i3,
             "I4_replicates_c3": all(i4.values()), "I4_by_budget": i4}

    top = max(WORLD_COUNTS)
    lower_bound = bootstrap(
        per_w[top], f"{BOOTSTRAP_SEED}|lower", one_sided=True) * SEAT_SHARE
    plateau = _plateau(point)
    fit = _increment_fit(point)

    payload = {
        "schema": "tuppi-c2-headroom-v1",
        "root_seed": ROOT_SEED, "bootstrap_seed": BOOTSTRAP_SEED,
        "observations": len(rows), "completions": COMPLETIONS,
        "rollouts": sum(r["rollouts"] for r in rows),
        "seconds": round(elapsed, 1), "workers": args.workers, "delta": DELTA,
        "instrument_gates": gates,
        "paired_increments": {k: round(v, 7) for k, v in paired.items()},
        "G_foresight_normalised": fore_mean,
        "curve": {str(w): {"G_deploy_normalised": point[w],
                           "ci95": [ci[w][0] * SEAT_SHARE, ci[w][1] * SEAT_SHARE]}
                  for w in WORLD_COUNTS},
        "G_legal_lower_bound_95": lower_bound,
        "increment_fit": None if fit is None else {"log_a": fit[0], "b": fit[1]},
        "plateau_extrapolated": plateau,
        "reachable_fraction_lower": lower_bound / fore_mean if fore_mean else None,
        "reachable_fraction_plateau": (
            plateau / fore_mean if plateau and fore_mean else None),
    }
    if not all([i1, i2, i3, gates["I4_replicates_c3"]]):
        payload["verdict"] = "VOID_INSTRUMENT_GATE_FAILED"
    else:
        payload["verdict"] = "MEASURED"

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "c2_headroom.json").write_text(json.dumps(payload, indent=2))

    print(f"\nobservations {len(rows)}  rollouts {payload['rollouts']:,}  "
          f"{elapsed:.0f}s")
    print(f"G_foresight normalised {fore_mean:+.6f}\n")
    print("instrument gates:", {k: v for k, v in gates.items()
                                if k != "I4_by_budget"})
    print("paired increments:", {k: round(v, 6) for k, v in paired.items()}, "\n")
    print(f"{'W':>5}{'G_deploy':>12}{'ci95 low':>12}{'ci95 high':>12}")
    for w in WORLD_COUNTS:
        print(f"{w:>5}{point[w]:>12.6f}{ci[w][0]*SEAT_SHARE:>12.6f}"
              f"{ci[w][1]*SEAT_SHARE:>12.6f}")
    print(f"\nPRIMARY   G_legal >= {lower_bound:.6f} "
          f"(one-sided 95% lower bound on G_deploy({top}))")
    if plateau is None:
        print("SECONDARY plateau not reported: the increment fit is not decaying")
    else:
        print(f"SECONDARY plateau {plateau:.6f} (b={fit[1]:.3f}, model-dependent)")
    print(f"\nreachable fraction of foresight: "
          f">= {lower_bound / fore_mean:.1%}"
          + (f", plateau {plateau / fore_mean:.1%}" if plateau else ""))
    print(f"VERDICT: {payload['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
