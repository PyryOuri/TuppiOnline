"""C4: G_deploy at four decision depths, using the validated feasible sampler.

The instrument for ``docs/cardplay/hypotheses_c4.md``, committed as ``0674854``
before this file existed. Nothing here may deviate from it.

    PYTHONPATH=src python work/cardplay/c4_depth.py --output <dir>

Differs from C3 in one substantive way: worlds come from
``tuppi_exact.UniformFeasibleSampler.for_observation``, which carries played
cards, void suits and show exclusions, rather than C3's hand-rolled dealing which
is only valid before a card is played. Because the sampler is new, depth 12 is a
replication target against C3 and gate I2 voids the run if it misses.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from c1_headroom import (  # noqa: E402
    DELTA, _deal_from, _resources, _show_through, _start, build_equity_table,
)

from tuppi_engine import (  # noqa: E402
    EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
    create_match, match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_exact import UniformFeasibleSampler  # noqa: E402
from tuppi_rules import MatchScore, Team  # noqa: E402

DEPTHS = (12, 9, 6, 3)
OBSERVATIONS = 256
WORLDS = 128
W = 64
ROOT_SEED = "tuppi-c4-depth-v1"
BOOTSTRAP_SEED = "tuppi-c4-bootstrap-v1"
REPLICATES = 5000
SEAT_SHARE = 0.5
C3_ANCHOR = (0.001226, 0.001717)


def _replay(initial, script, forced_index, forced, agents, table, team):
    """Replay the recorded script, substitute `forced` at one index, finish."""
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=0,
                     match_ref="c4-deal"),
        ExplicitDeal(dealer=0, hands=initial))
    step = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        if step < forced_index:
            action = script[step]
        elif step == forced_index:
            action = forced
        else:
            seat = state.current_actor
            action = agents[seat].choose_action(match_observation_for(state, seat))
        state = apply_match_action(state, action)
        step += 1
    result = state.completed_deals[-1].public_result
    return table.delta(before=result.score_before, after=result.score_after,
                       team=Team(team), we_deal=(team == 0))


def measure_observation(index: int, corpus: str) -> dict | None:
    table, agents = _resources(corpus)
    with trusted_transitions():
        rng = random.Random(f"{ROOT_SEED}|obs|{index}")
        hands = None
        for _ in range(64):
            candidate = _deal_from(rng)
            if _show_through(candidate, agents) is not None:
                hands = candidate
                break
        if hands is None:
            return None

        # record the reference's own full script, and the target seat's
        # observation and script position at each requested depth
        state = _start(hands)
        script, targets = [], {}
        leader = None
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            observation = match_observation_for(state, seat)
            if state.phase is EnginePhase.TRICK_PLAY and leader is None:
                leader = seat
            if seat == leader and state.phase is EnginePhase.TRICK_PLAY:
                left = len(observation.own_hand) - 1
                if left in DEPTHS and left not in targets:
                    targets[left] = (len(script), observation)
            action = agents[seat].choose_action(observation)
            script.append(action)
            state = apply_match_action(state, action)

        out = {"index": index, "seat": leader, "depths": {}}
        for depth in DEPTHS:
            if depth not in targets:
                out["depths"][depth] = {"skipped": "depth not reached"}
                continue
            position, observation = targets[depth]
            legal = list(observation.legal_actions)
            if len(legal) < 2:
                out["depths"][depth] = {"skipped": "fewer than two legal actions"}
                continue
            sampler = UniformFeasibleSampler.for_observation(
                observation, seed=f"{ROOT_SEED}|{index}|{depth}")
            feasible = sampler.total_assignments
            if feasible < WORLDS:
                out["depths"][depth] = {"skipped": "too few feasible worlds",
                                        "feasible": int(feasible)}
                continue
            # what each seat has played so far, from the recorded script
            played = [[] for _ in range(4)]
            for action in script[:position]:
                card = getattr(action, "card", None)
                if card is not None:
                    played[action.seat].append(card)
            team = leader % 2
            arms = [[] for _ in legal]
            for draw in range(WORLDS):
                assignment = sampler.sample_one(index=draw)
                initial = tuple(
                    tuple(played[seat]) + tuple(assignment.hands[seat])
                    for seat in range(4))
                for slot, action in enumerate(legal):
                    arms[slot].append(_replay(initial, script, position, action,
                                              agents, table, team))
            policy_index = legal.index(script[position])
            out["depths"][depth] = {
                "arms": arms, "policy_index": policy_index,
                "feasible": int(feasible), "legal": len(legal),
                "on_lead": not observation.current_trick,
                "rollouts": len(legal) * WORLDS,
            }
        return out


def deploy(block) -> float:
    arms, policy = block["arms"], block["policy_index"]
    halves = []
    for pick, score in (((0, W), (W, 2 * W)), ((W, 2 * W), (0, W))):
        chooser = [statistics.fmean(v[pick[0]:pick[1]]) for v in arms]
        best = max(range(len(chooser)), key=lambda i: chooser[i])
        halves.append(statistics.fmean(arms[best][score[0]:score[1]])
                      - statistics.fmean(arms[policy][score[0]:score[1]]))
    return statistics.fmean(halves)


def foresight(block) -> float:
    arms, policy = block["arms"], block["policy_index"]
    return statistics.fmean(max(a[c] for a in arms) - arms[policy][c]
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
            if rows and len(rows) % 32 == 0:
                print(f"  {len(rows)} observations, "
                      f"{time.perf_counter() - started:.0f}s", flush=True)
    elapsed = time.perf_counter() - started
    rows.sort(key=lambda r: r["index"])
    total = sum(b.get("rollouts", 0) for r in rows for b in r["depths"].values())

    payload = {
        "schema": "tuppi-c4-depth-v1",
        "preregistration": "docs/cardplay/hypotheses_c4.md",
        "preregistration_commit": "0674854",
        "endpoint": diagnostics, "observations": len(rows),
        "worlds": WORLDS, "W": W, "delta": DELTA, "seat_share": SEAT_SHARE,
        "rollouts": total, "seconds": round(elapsed, 1),
        "aggregate_rollouts_per_second": round(total / elapsed, 1),
        "workers": args.workers, "depths": {}, "skips": {},
    }
    usable = {}
    for depth in DEPTHS:
        blocks = [(r["index"], r["depths"][depth]) for r in rows
                  if "arms" in r["depths"].get(depth, {})]
        skipped = [b.get("skipped") for r in rows
                   for b in [r["depths"].get(depth, {})] if b.get("skipped")]
        payload["skips"][str(depth)] = {
            "count": len(skipped),
            "reasons": {s: skipped.count(s) for s in set(skipped)},
        }
        if not blocks:
            payload["depths"][str(depth)] = {"usable": 0}
            continue
        usable[depth] = {i: b for i, b in blocks}
        d = [deploy(b) for _, b in blocks]
        f = [foresight(b) for _, b in blocks]
        lo, hi = bootstrap(d, f"{BOOTSTRAP_SEED}|{depth}")
        payload["depths"][str(depth)] = {
            "usable": len(blocks),
            "mean_legal_arms": statistics.fmean(b["legal"] for _, b in blocks),
            "median_feasible_worlds": statistics.median(
                b["feasible"] for _, b in blocks),
            "share_on_lead": statistics.fmean(
                1.0 if b["on_lead"] else 0.0 for _, b in blocks),
            "G_deploy_normalised": statistics.fmean(d) * SEAT_SHARE,
            "ci95": [lo * SEAT_SHARE, hi * SEAT_SHARE],
            "G_foresight_normalised": statistics.fmean(f) * SEAT_SHARE,
            "clears_delta": lo * SEAT_SHARE > DELTA,
        }

    # ---- instrument gates
    i1 = all(v["G_deploy_normalised"] <= v["G_foresight_normalised"]
             for v in payload["depths"].values() if v.get("usable"))
    anchor = payload["depths"].get("12", {})
    i2 = bool(anchor.get("usable")) and not (
        anchor["ci95"][1] < C3_ANCHOR[0] or anchor["ci95"][0] > C3_ANCHOR[1])
    i3 = all(v.get("median_feasible_worlds", 0) >= WORLDS
             for v in payload["depths"].values() if v.get("usable"))
    payload["instrument_gates"] = {
        "I1_bounded_by_foresight": i1,
        "I2_replicates_c3_at_depth_12": i2,
        "I3_feasible_world_sufficiency": i3,
        "c3_anchor_interval": list(C3_ANCHOR),
    }
    # paired differences against depth 12
    paired = {}
    if 12 in usable:
        for depth in DEPTHS[1:]:
            if depth not in usable:
                continue
            shared = sorted(set(usable[12]) & set(usable[depth]))
            if shared:
                paired[f"{depth}-vs-12"] = statistics.fmean(
                    deploy(usable[depth][i]) - deploy(usable[12][i])
                    for i in shared) * SEAT_SHARE
    payload["paired_vs_depth_12"] = paired

    if not (i1 and i2 and i3):
        payload["science_gate"] = "VOID_INSTRUMENT_GATE_FAILED"
    else:
        clearing = [d for d in DEPTHS
                    if payload["depths"].get(str(d), {}).get("clears_delta")]
        payload["science_gate"] = (
            "INCONCLUSIVE" if 12 not in clearing
            else f"GENERALISES at depths {sorted(set(clearing) - {12})}"
            if set(clearing) - {12} else "OPENING_LEAD_SPECIFIC")
        payload["depths_clearing_delta"] = clearing

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "c4_depth.json").write_text(json.dumps(payload, indent=2))
    print(f"\nobservations {len(rows)}  rollouts {total:,}  {elapsed:.0f}s  "
          f"{total/elapsed:.0f}/s aggregate")
    print("instrument gates:", {k: v for k, v in payload["instrument_gates"].items()
                                if k != "c3_anchor_interval"})
    print(f"\n{'depth':>6}{'usable':>8}{'arms':>7}{'G_deploy':>12}{'ci low':>12}"
          f"{'ci high':>12}{'foresight':>12}{'>delta':>8}")
    for depth in DEPTHS:
        v = payload["depths"].get(str(depth), {})
        if not v.get("usable"):
            print(f"{depth:>6}{0:>8}"); continue
        print(f"{depth:>6}{v['usable']:>8}{v['mean_legal_arms']:>7.1f}"
              f"{v['G_deploy_normalised']:>12.6f}{v['ci95'][0]:>12.6f}"
              f"{v['ci95'][1]:>12.6f}{v['G_foresight_normalised']:>12.6f}"
              f"{'yes' if v['clears_delta'] else 'no':>8}")
    print("\npaired vs depth 12:", {k: round(v, 6) for k, v in paired.items()})
    print("skips:", json.dumps(payload["skips"]))
    print(f"\nSCIENCE GATE: {payload['science_gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
