"""T6: is it rigidity, and not foreignness, that collapses the margin?

The instrument for [docs/transfer/hypotheses_t6.md], committed as `68e7812`
before this file existed. Read it first; nothing here may deviate from it.

    PYTHONPATH=src python work/transfer/t6_rigidity.py --output <dir>

An opponent family interpolates between `first_legal` and uniform random by a
mixing probability. Along the sweep the opponent becomes both less rigid and
weaker, so the two live hypotheses predict opposite signs and one monotone sweep
separates them.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
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

from tuppi_engine import (  # noqa: E402
    EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal,
    create_match, match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions  # noqa: E402
from tuppi_rules import MatchScore, Team  # noqa: E402

EPSILONS = (0.00, 0.25, 0.50, 0.75, 1.00)
CONTROL_OPPONENT = PREDECESSOR
BASE_DEALS = 1024
ROOT_SEED = "tuppi-t6-rigidity-v1"
OPPONENT_SEED = "tuppi-t6-opponent-v1"
BOOTSTRAP_SEED = "tuppi-t6-bootstrap-v1"
REPLICATES = 5000
MONOTONE_THRESHOLD = 0.9
#: T5's interval for `first_legal`, which epsilon=0.00 reproduces. Gate I4.
T5_FIRST_LEGAL = (0.001083, 0.003056)

_CACHE: dict = {}


class MixtureOpponent:
    """`first_legal` with probability 1-epsilon, uniform random otherwise.

    The random choice is a deterministic function of the *position*, not a draw
    from a running stream. The incumbent and predecessor arms diverge during a
    deal, so a stream would desynchronise and give the two arms different
    opponent behaviour in the same position — adding variance to the very
    difference being measured. Keying on the position is common random numbers,
    and stays reproducible from the seed.
    """

    __slots__ = ("_epsilon", "_seat", "_seed")

    def __init__(self, *, epsilon: float, seat: int, seed: str) -> None:
        self._epsilon = epsilon
        self._seat = seat
        self._seed = seed

    def choose_action(self, observation):
        legal = observation.legal_actions
        if not legal:
            raise ValueError("no legal action offered")
        if self._epsilon <= 0.0:
            return legal[0]
        # `match_ref` carries the deal identity. Without it the key repeats
        # across deals and the "random" opponent becomes a fixed table of
        # positional decisions — uniform in its action distribution but
        # perfectly determined by position. The first run of this instrument had
        # exactly that defect: 2,704 keys replayed over 1,024 deals, so the
        # epsilon=1.00 arm was rigid and its margin collapsed accordingly.
        key = "|".join((
            self._seed, f"{self._epsilon:.2f}", observation.match_ref,
            str(self._seat),
            str(len(observation.completed_tricks)),
            str(len(observation.current_trick)),
            observation.phase.value,
            str(len(observation.own_hand)),
        ))
        digest = hashlib.sha256(key.encode()).digest()
        draw = int.from_bytes(digest[:8], "big") / float(1 << 64)
        if draw >= self._epsilon:
            return legal[0]
        pick = int.from_bytes(digest[8:16], "big") % len(legal)
        return legal[pick]


def _opponent_agents(key):
    if key in _CACHE:
        return _CACHE[key]
    if isinstance(key, float):
        built = {s: MixtureOpponent(epsilon=key, seat=s, seed=OPPONENT_SEED)
                 for s in range(4)}
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


def _play(*, hands, candidate_key, opponent_key, candidate_team, table, deal_key):
    """`deal_key` is identical across the two arms, so the stochastic opponent
    behaves identically in identical positions — common random numbers — while
    differing across deals, which the first version of this instrument did not."""

    candidate = _candidate_agents(candidate_key)
    opponent = _opponent_agents(opponent_key)
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=DEALER,
                     match_ref=f"t6-{deal_key}"),
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


def measure_base_deal(index: int, corpus: str, opponent_key) -> dict:
    table = _table(corpus)
    rng = random.Random(f"{ROOT_SEED}|deal|{index}")
    base = _deal_from(rng)
    with trusted_transitions():
        incumbent_values, predecessor_values = [], []
        for rotation in range(ROTATIONS):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for assignment in range(ASSIGNMENTS):
                deal_key = f"{index}-{rotation}-{assignment}"
                incumbent_values.append(_play(
                    hands=hands, candidate_key=INCUMBENT, opponent_key=opponent_key,
                    candidate_team=assignment, table=table, deal_key=deal_key))
                predecessor_values.append(_play(
                    hands=hands, candidate_key=PREDECESSOR, opponent_key=opponent_key,
                    candidate_team=assignment, table=table, deal_key=deal_key))
    return {
        "games": len(incumbent_values),
        "margin": statistics.fmean(incumbent_values) - statistics.fmean(predecessor_values),
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
                    opponent_key=PREDECESSOR, candidate_team=assignment, table=table,
                    deal_key=f"ctl-{index}-{rotation}-{assignment}"))
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


def _run(opponent_key, corpus, base_deals, workers):
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(measure_base_deal, i, corpus, opponent_key)
                   for i in range(base_deals)]
        for future in as_completed(futures):
            rows.append(future.result())
    margins = [r["margin"] for r in rows]
    lo, hi = bootstrap(margins, f"{BOOTSTRAP_SEED}|{opponent_key}")
    return {
        "mean": statistics.fmean(margins), "ci95": [lo, hi],
        "strength": statistics.fmean(r["strength"] for r in rows),
        "base_deals": len(rows),
        "complete_blocks": all(r["games"] == ROTATIONS * ASSIGNMENTS for r in rows),
    }


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
    blocks = [measure_control_block(i, args.corpus) for i in range(args.control_deals)]
    worst = max(abs(v) for v in blocks) if blocks else 0.0
    i1 = worst <= CANCELLATION_TOLERANCE
    print(f"I1 identical teams cancel: {i1} (largest |value| {worst:.2e})", flush=True)

    control = _run(CONTROL_OPPONENT, args.corpus, args.base_deals, args.workers)
    print(f"control {CONTROL_OPPONENT:<22} margin {control['mean']:+.6f} "
          f"[{control['ci95'][0]:+.6f}, {control['ci95'][1]:+.6f}]", flush=True)

    sweep = {}
    for epsilon in EPSILONS:
        sweep[epsilon] = _run(epsilon, args.corpus, args.base_deals, args.workers)
        r = sweep[epsilon]
        print(f"epsilon {epsilon:.2f}            margin {r['mean']:+.6f} "
              f"[{r['ci95'][0]:+.6f}, {r['ci95'][1]:+.6f}]  "
              f"strength {r['strength']:+.4f}  "
              f"{100*r['mean']/control['mean']:5.1f}% of control", flush=True)
    elapsed = time.perf_counter() - started

    margins = [sweep[e]["mean"] for e in EPSILONS]
    strengths = [sweep[e]["strength"] for e in EPSILONS]
    rho = spearman(list(EPSILONS), margins)
    lo0, hi0 = sweep[0.00]["ci95"]
    lo1, hi1 = sweep[1.00]["ci95"]
    endpoints_overlap = hi1 >= lo0 and lo1 <= hi0
    if endpoints_overlap:
        verdict = "NEITHER"
    elif rho >= MONOTONE_THRESHOLD and lo1 > hi0:
        verdict = "RIGIDITY_SUPPORTED"
    elif rho <= -MONOTONE_THRESHOLD and hi1 < lo0:
        verdict = "SATURATION_SUPPORTED"
    else:
        verdict = "AMBIGUOUS"

    gates = {
        "I1_identical_teams_cancel": i1,
        "I2_block_completeness": (control["complete_blocks"]
                                  and all(r["complete_blocks"] for r in sweep.values())),
        "I3_control_replicates_t2_v5":
            control["ci95"][0] <= T2_V5_MARGIN <= control["ci95"][1],
        "I4_rigid_endpoint_replicates_t5":
            hi0 >= T5_FIRST_LEGAL[0] and lo0 <= T5_FIRST_LEGAL[1],
        "I5_strength_monotone_in_epsilon":
            all(a < b for a, b in zip(strengths, strengths[1:])),
    }
    payload = {
        "schema": "tuppi-t6-rigidity-v1", "root_seed": ROOT_SEED,
        "opponent_seed": OPPONENT_SEED, "seconds": round(elapsed, 1),
        "instrument_gates": gates, "control": control,
        "sweep": {f"{e:.2f}": sweep[e] for e in EPSILONS},
        "spearman_margin_vs_epsilon": rho,
        "endpoints_overlap": endpoints_overlap,
        "verdict": verdict,
        "overall": ("VOID_INSTRUMENT_GATE_FAILED" if not all(gates.values())
                    else "MEASURED"),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "t6_rigidity.json").write_text(json.dumps(payload, indent=2))

    print(f"\n{elapsed:.0f}s")
    print("instrument gates:", gates)
    print(f"spearman(epsilon, margin) = {rho:+.3f}   endpoints overlap: {endpoints_overlap}")
    print(f"VERDICT: {verdict}   OVERALL: {payload['overall']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
