"""C3: G_deploy as a function of sampled world count, with cost.

The instrument for ``docs/cardplay/hypotheses_c3.md``, committed as ``8eb1d67``
before this file existed. Nothing here may deviate from it.

    PYTHONPATH=src python work/cardplay/c3_worlds.py --output <dir>

Reuses C1's observation sampling, conditioning and pricing unchanged. One set of
128 completions per observation is priced across all 13 arms, then each W reads a
disjoint choose/score pair out of it. The three instrument gates in §4 are
evaluated FIRST and a failure voids the science.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
from pathlib import Path
import random
import statistics
import time

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from c1_headroom import (  # noqa: E402
    COMPLETIONS, DELTA, _deal_from, _price, _resources, _show_through,
    build_equity_table,
)

from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_rules import FULL_DECK  # noqa: E402
from tuppi_rules.showing import valid_show_cards  # noqa: E402

OBSERVATIONS = 512
WORLD_COUNTS = (1, 2, 4, 8, 16, 32, 64)
ROOT_SEED = "tuppi-c3-worlds-v1"
BOOTSTRAP_SEED = "tuppi-c3-bootstrap-v1"
REPLICATES = 5000
SEAT_SHARE = 0.5
MAX_DRAWS = COMPLETIONS * 200


def measure_observation(index: int, corpus: str) -> dict | None:
    """One observation's 128 hard-constraint completions, all 13 arms priced."""
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


def deploy_at(row, worlds: int) -> float:
    """Choose on a disjoint block of `worlds` completions, score on the next."""
    arms, policy = row["arms"], row["policy_index"]
    halves = []
    for pick, score in (((0, worlds), (worlds, 2 * worlds)),
                        ((worlds, 2 * worlds), (0, worlds))):
        chooser = [statistics.fmean(v[pick[0]:pick[1]]) for v in arms]
        best = max(range(len(chooser)), key=lambda i: chooser[i])
        halves.append(
            statistics.fmean(arms[best][score[0]:score[1]])
            - statistics.fmean(arms[policy][score[0]:score[1]]))
    return statistics.fmean(halves)


def foresight(row) -> float:
    arms, policy = row["arms"], row["policy_index"]
    return statistics.fmean(
        max(arm[c] for arm in arms) - arms[policy][c]
        for c in range(len(arms[0])))


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
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--observations", type=int, default=OBSERVATIONS)
    args = parser.parse_args()

    _table, diagnostics = build_equity_table(Path(args.corpus))
    print(f"endpoint controls passed: {json.dumps(diagnostics)}")
    started = time.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(measure_observation, i, args.corpus)
                   for i in range(args.observations)]
        for done in as_completed(futures):
            row = done.result()
            if row is not None:
                rows.append(row)
            if rows and len(rows) % 64 == 0:
                print(f"  {len(rows)} observations, "
                      f"{time.perf_counter() - started:.0f}s", flush=True)
    elapsed = time.perf_counter() - started
    if not rows:
        raise SystemExit("no observations completed")
    rows.sort(key=lambda r: r["index"])
    total_rollouts = sum(r["rollouts"] for r in rows)
    aggregate_rate = total_rollouts / elapsed
    single_rate = aggregate_rate / args.workers

    per_w = {w: [deploy_at(r, w) for r in rows] for w in WORLD_COUNTS}
    fore = [foresight(r) for r in rows]
    arms_n = statistics.fmean(len(r["arms"]) for r in rows)

    # ---- instrument gates, evaluated before any science is read
    fore_mean = statistics.fmean(fore) * SEAT_SHARE
    i1 = all(statistics.fmean(per_w[w]) * SEAT_SHARE <= fore_mean
             for w in WORLD_COUNTS)
    pairs = list(zip(WORLD_COUNTS, WORLD_COUNTS[1:]))
    paired = {f"{a}->{b}": statistics.fmean(y - x for x, y in
                                            zip(per_w[a], per_w[b])) * SEAT_SHARE
              for a, b in pairs}
    i2 = all(v >= 0 for v in paired.values())
    i3 = paired["32->64"] < paired["4->8"]
    gates = {"I1_bounded_by_foresight": i1, "I2_monotone_in_W": i2,
             "I3_decelerating": i3, "paired_increments": paired}

    payload = {
        "schema": "tuppi-c3-worlds-v1",
        "preregistration": "docs/cardplay/hypotheses_c3.md",
        "preregistration_commit": "8eb1d67",
        "endpoint": diagnostics, "observations": len(rows),
        "completions": COMPLETIONS, "arms": arms_n,
        "rollouts": total_rollouts, "seconds": round(elapsed, 1),
        "aggregate_rollouts_per_second": round(aggregate_rate, 1),
        "single_process_rollouts_per_second": round(single_rate, 1),
        "workers": args.workers, "delta": DELTA, "seat_share": SEAT_SHARE,
        "instrument_gates": gates,
        "G_foresight_normalised": fore_mean,
        "curve": {}, "science_gate": None,
    }
    for w in WORLD_COUNTS:
        lo, hi = bootstrap(per_w[w], f"{BOOTSTRAP_SEED}|{w}")
        cost = arms_n * w
        payload["curve"][str(w)] = {
            "G_deploy_normalised": statistics.fmean(per_w[w]) * SEAT_SHARE,
            "ci95": [lo * SEAT_SHARE, hi * SEAT_SHARE],
            "rollouts_per_decision": round(cost),
            "seconds_single_process": round(cost / single_rate, 2),
            "seconds_at_workers": round(cost / aggregate_rate, 2),
            "clears_delta": lo * SEAT_SHARE > DELTA,
        }
    if not (i1 and i2 and i3):
        payload["science_gate"] = "VOID_INSTRUMENT_GATE_FAILED"
    else:
        clearing = [w for w in WORLD_COUNTS
                    if payload["curve"][str(w)]["clears_delta"]]
        affordable = [w for w in clearing
                      if payload["curve"][str(w)]["seconds_at_workers"] <= 10.0]
        payload["science_gate"] = (
            f"AFFORDABLE at W={min(affordable)}" if affordable
            else "UNAFFORDABLE" if clearing else "INCONCLUSIVE")
        if i3 and clearing:
            payload["descriptive_plateau"] = payload["curve"]["64"]["G_deploy_normalised"]

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "c3_worlds.json").write_text(json.dumps(payload, indent=2))
    print(f"\nobservations {len(rows)}  rollouts {total_rollouts:,}  "
          f"{elapsed:.0f}s  {aggregate_rate:.0f}/s aggregate, "
          f"{single_rate:.0f}/s per process")
    print(f"G_foresight normalised {fore_mean:+.6f}\n")
    print("instrument gates:", {k: v for k, v in gates.items()
                                if k != "paired_increments"})
    print("paired increments:", {k: round(v, 6) for k, v in paired.items()}, "\n")
    print(f"{'W':>4}{'G_deploy':>12}{'ci95 low':>12}{'ci95 high':>12}"
          f"{'roll/dec':>10}{'s single':>10}{'s x10':>8}{'>delta':>8}")
    for w in WORLD_COUNTS:
        c = payload["curve"][str(w)]
        print(f"{w:>4}{c['G_deploy_normalised']:>12.6f}{c['ci95'][0]:>12.6f}"
              f"{c['ci95'][1]:>12.6f}{c['rollouts_per_decision']:>10}"
              f"{c['seconds_single_process']:>10.2f}{c['seconds_at_workers']:>8.2f}"
              f"{'yes' if c['clears_delta'] else 'no':>8}")
    print(f"\nSCIENCE GATE: {payload['science_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
