"""T4: does the incumbent's improvement survive an opponent it was not fitted to?

The instrument for [docs/transfer/hypotheses_t4.md], committed as `b80128e`
before this file existed. Read it first; nothing here may deviate from it.

    PYTHONPATH=src python work/transfer/t4_transfer.py --output <dir>

Everything measured in this programme so far has the incumbent or its
predecessor on both sides of the table. This puts a third party there.

The estimand is a difference in differences — the incumbent's margin over its
predecessor, both against the same opponent on the same deals — because a harder
opponent lowers both terms and cancels, so a change in the margin is about the
improvement rather than about the opponent. The remaining confound is
composition, and it is separated by measuring exposure: how often the two
policies disagree at all.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cardplay"))
from c1_headroom import build_equity_table, _deal_from  # noqa: E402

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key  # noqa: E402
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
from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_rules import MatchScore, Team  # noqa: E402

INCUMBENT = "partner_aware_lead_v2"
PREDECESSOR = "partner_aware_v1"
CONTROL_OPPONENT = PREDECESSOR
#: Chosen on measured divergence from the predecessor at 0-0, not on what the
#: profile names imply; see section 9 of the hypotheses. `match_aware_v1` agrees
#: with `partner_aware_v1` on 100.0% of decisions here because its match-state
#: features are inert at a level score, and the "different convention" profile
#: differs on 0.9%. Both were removed.
OPPONENTS = (
    PREDECESSOR,                          # control
    "legacy_heuristic_port_v1",           # 8.7% divergence
    "reactive_contract_legacy_show_v1",   # 5.3%
    "reactive_contract_v1",               # 3.7%
)
BASE_DEALS = 1024
ROTATIONS = 4
ASSIGNMENTS = 2
DEALER = 0
ROOT_SEED = "tuppi-t4-transfer-v1"
BOOTSTRAP_SEED = "tuppi-t4-bootstrap-v1"
REPLICATES = 5000
CANCELLATION_TOLERANCE = 1e-12
#: T2's V5 positive control for removing both lead layers.
T2_V5_MARGIN = 0.00574
#: Section 5's bands for separating transfer failure from composition.
EXPOSURE_BAND = 0.20

_CACHE: dict = {}


def _agent(key: str, seat: int):
    """One seat's policy, whichever registry declares it."""

    if key == INCUMBENT:
        spec = improved_specifications_by_profile_key()[INCUMBENT]
        return improved_agent_from_specification(spec, profile_key=INCUMBENT, seat=seat)
    return construct_agent(phase4_specifications_by_profile_key()[key], seat=seat)


def _agents(key: str):
    if key not in _CACHE:
        _CACHE[key] = {seat: _agent(key, seat) for seat in range(4)}
    return _CACHE[key]


def _table(corpus: str):
    if "table" not in _CACHE:
        _CACHE["table"] = build_equity_table(Path(corpus))[0]
    return _CACHE["table"]


def _play(*, hands, candidate_key, opponent_key, candidate_team, table, shadow_key=None):
    """Play one deal; return the candidate team's equity and the exposure counts.

    ``shadow_key`` names a policy asked, at every candidate-team decision, what
    it would have played from the *same* observation. Nothing it returns is
    applied — it measures how often the two policies disagree at all, which is
    the exposure the composition test needs. Measuring it on the candidate's own
    trajectory is what keeps it well defined: the two arms diverge after the
    first disagreement, so there is no shared trajectory to compare on.
    """

    candidate = _agents(candidate_key)
    opponent = _agents(opponent_key)
    shadow = _agents(shadow_key) if shadow_key else None
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=DEALER,
                     match_ref="t4-deal"),
        ExplicitDeal(dealer=DEALER, hands=hands))
    decisions = disagreements = 0
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        ours = (seat % 2) == candidate_team
        actor = candidate[seat] if ours else opponent[seat]
        action = actor.choose_action(observation)
        if ours and shadow is not None:
            decisions += 1
            if shadow[seat].choose_action(observation) != action:
                disagreements += 1
        state = apply_match_action(state, action)
    result = state.completed_deals[-1].public_result
    equity = table.delta(
        before=result.score_before, after=result.score_after,
        team=Team(candidate_team), we_deal=(DEALER % 2 == candidate_team))
    return equity, decisions, disagreements


def measure_base_deal(index: int, corpus: str, opponent_key: str) -> dict:
    """One base deal's 8 transformations, played by both arms on identical cards."""

    table = _table(corpus)
    rng = random.Random(f"{ROOT_SEED}|deal|{index}")
    base = _deal_from(rng)
    with trusted_transitions():
        incumbent_values, predecessor_values = [], []
        decisions = disagreements = 0
        for rotation in range(ROTATIONS):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for assignment in range(ASSIGNMENTS):
                a, seen, differ = _play(
                    hands=hands, candidate_key=INCUMBENT, opponent_key=opponent_key,
                    candidate_team=assignment, table=table, shadow_key=PREDECESSOR)
                b, _, _ = _play(
                    hands=hands, candidate_key=PREDECESSOR, opponent_key=opponent_key,
                    candidate_team=assignment, table=table)
                incumbent_values.append(a)
                predecessor_values.append(b)
                decisions += seen
                disagreements += differ
    return {
        "index": index,
        "games": len(incumbent_values),
        "margin": statistics.fmean(incumbent_values) - statistics.fmean(predecessor_values),
        "decisions": decisions,
        "disagreements": disagreements,
    }


def measure_control(index: int, corpus: str) -> float:
    """Identical teams, for gate I1. Must cancel."""

    table = _table(corpus)
    rng = random.Random(f"{ROOT_SEED}|control|{index}")
    base = _deal_from(rng)
    with trusted_transitions():
        values = []
        for rotation in range(ROTATIONS):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for assignment in range(ASSIGNMENTS):
                value, _, _ = _play(
                    hands=hands, candidate_key=PREDECESSOR,
                    opponent_key=PREDECESSOR, candidate_team=assignment, table=table)
                values.append(value)
    return statistics.fmean(values)


def bootstrap(values, seed):
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(statistics.fmean(rng.choice(values) for _ in range(n))
                   for _ in range(REPLICATES))
    return draws[int(0.025 * REPLICATES)], draws[int(0.975 * REPLICATES)]


def _verdict(margin, control_margin, exposure, control_exposure) -> str:
    """Section 5, applied. Fixed before the run; not decided by the numbers."""

    if margin["ci95"][1] >= control_margin["ci95"][0]:
        return "transfers"
    flat = abs(exposure - control_exposure) <= EXPOSURE_BAND * control_exposure
    if flat:
        return "transfer_failure"
    if exposure <= 0:
        return "ambiguous"
    per_unit = margin["mean"] / exposure
    control_per_unit = control_margin["mean"] / control_exposure
    if abs(per_unit - control_per_unit) <= EXPOSURE_BAND * abs(control_per_unit):
        return "composition"
    return "ambiguous"


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

    control = [measure_control(i, args.corpus) for i in range(args.control_deals)]
    worst = max(abs(v) for v in control) if control else 0.0
    i1 = worst <= CANCELLATION_TOLERANCE
    print(f"I1 identical teams cancel: {i1} (largest |value| {worst:.2e})", flush=True)

    results = {}
    for opponent in OPPONENTS:
        rows = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(measure_base_deal, i, args.corpus, opponent)
                       for i in range(args.base_deals)]
            for done, future in enumerate(as_completed(futures), start=1):
                rows.append(future.result())
                if done % 256 == 0:
                    print(f"  {opponent}: {done}/{args.base_deals}", flush=True)
        margins = [r["margin"] for r in rows]
        lo, hi = bootstrap(margins, f"{BOOTSTRAP_SEED}|{opponent}")
        decisions = sum(r["decisions"] for r in rows)
        disagreements = sum(r["disagreements"] for r in rows)
        results[opponent] = {
            "mean": statistics.fmean(margins), "ci95": [lo, hi],
            "base_deals": len(rows),
            "complete_blocks": all(r["games"] == ROTATIONS * ASSIGNMENTS for r in rows),
            "decisions": decisions, "disagreements": disagreements,
            "exposure": disagreements / decisions if decisions else 0.0,
        }
        r = results[opponent]
        print(f"{opponent:<36} margin {r['mean']:+.6f} "
              f"[{lo:+.6f}, {hi:+.6f}]  exposure {r['exposure']:.3%}", flush=True)
    elapsed = time.perf_counter() - started

    ctrl = results[CONTROL_OPPONENT]
    i3 = ctrl["ci95"][0] <= T2_V5_MARGIN <= ctrl["ci95"][1]
    i5 = all(
        abs(results[o]["exposure"] - ctrl["exposure"]) > 1e-9
        for o in OPPONENTS if o != CONTROL_OPPONENT
    )
    gates = {
        "I1_identical_teams_cancel": i1,
        "I2_block_completeness": all(r["complete_blocks"] for r in results.values()),
        "I3_control_replicates_t2_v5": i3,
        "I5_opponents_actually_differ": i5,
    }
    verdicts = {
        o: _verdict(results[o], ctrl, results[o]["exposure"], ctrl["exposure"])
        for o in OPPONENTS if o != CONTROL_OPPONENT
    }

    payload = {
        "schema": "tuppi-t4-transfer-v1", "root_seed": ROOT_SEED,
        "incumbent": INCUMBENT, "predecessor": PREDECESSOR,
        "control_opponent": CONTROL_OPPONENT, "t2_v5_margin": T2_V5_MARGIN,
        "seconds": round(elapsed, 1), "instrument_gates": gates,
        "control_worst_cancellation": worst,
        "margins": results, "verdicts": verdicts,
        "overall": ("VOID_INSTRUMENT_GATE_FAILED" if not all(gates.values())
                    else "MEASURED"),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "t4_transfer.json").write_text(json.dumps(payload, indent=2))

    print(f"\n{elapsed:.0f}s")
    print("instrument gates:", gates)
    print("verdicts:", verdicts)
    print(f"OVERALL: {payload['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
