"""C1: observation-compatible headroom at the opening card play.

The instrument for ``docs/cardplay/hypotheses_c1.md``, which fixes the design,
the estimator and the gates and was committed as ``6934da7`` before this file
existed. Read it first; nothing here may deviate from it.

    PYTHONPATH=src python work/cardplay/c1_headroom.py \
        --variant hard --output <dir>

Per pre-registration:

* draws 512 observations - a deal, played through showing by the frozen
  reference, taken at the first trick-play decision; the observation is the
  acting seat's own hand plus the public show history;
* completes each 128 times under one of two conditioning models, HARD or POLICY;
* prices all 13 legal opening leads per completion, the reference playing
  everything else, by per-deal frozen-continuation match equity;
* reports G_legal_eb (empirical-Bayes shrinkage across arms), a cross-fitted
  G_deploy, and G_foresight for comparison only.

The naive ``max(0, g + z*se)`` bound is deliberately absent: the power check put
``z*se`` at about nine times delta, so that gate could never fire. That is the
defect that cost S1 a run.
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

from tuppi_agents.improved_registry import (
    improved_agent_from_specification,
    improved_specifications_by_profile_key,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import FULL_DECK, MatchScore, Team
from tuppi_rules.showing import valid_show_cards
from tuppi_valuation.equity import DealModel, EquityTable, equity_bounds

DEALER = 0
OBSERVATIONS = 512
COMPLETIONS = 128
DELTA = 0.001
BOOTSTRAP_SEED = "tuppi-c1-bootstrap-v1"
BOOTSTRAP_REPLICATES = 5000
VARIANT_SEEDS = {"hard": "tuppi-c1-hard-v1", "policy": "tuppi-c1-policy-v1"}
MAX_DRAW_FACTOR = 200          # guard; POLICY needs about 7 draws per world


# ----------------------------------------------------------------- endpoint
def build_equity_table(corpus: Path):
    """Fit the reference deal model and run the pre-registered controls."""
    from tuppi_corpus.shards import read_catalog, read_shard

    dealer_counts: dict[int, int] = {}
    other_counts: dict[int, int] = {}
    deals = 0
    for entry in read_catalog(corpus):
        _header, matches, rows = read_shard(corpus / entry["shard"])
        for row in rows:
            if matches[row.match_row].stratum != 0:
                continue
            points = max(row.deal_points)
            winner = 0 if row.deal_points[0] else 1
            bucket = dealer_counts if winner == row.dealer % 2 else other_counts
            bucket[points] = bucket.get(points, 0) + 1
            deals += 1
    if not deals:
        raise SystemExit(f"no reference self-play deals under {corpus}")
    dealer_total = sum(dealer_counts.values())
    other_total = sum(other_counts.values())
    model = DealModel(
        dealer_win=dealer_total / (dealer_total + other_total),
        points_given_dealer={p: c / dealer_total
                             for p, c in sorted(dealer_counts.items())},
        points_given_other={p: c / other_total
                            for p, c in sorted(other_counts.items())},
    )
    table = EquityTable.build(model)
    level = MatchScore(0, 0)
    symmetric = EquityTable.build(
        DealModel.symmetric(dict(model.points_given_dealer)))
    control = symmetric.equity(level, Team.TEAM_0, we_deal=True)
    if abs(control - 0.5) > 1e-9:
        raise SystemExit(f"endpoint control failed: symmetric V(0-0) = {control}")
    low, high = equity_bounds()
    values = list(table.value.values())
    slack = abs(model.dealer_win - 0.5) * 2.0 + 1e-9
    if min(values) < low - slack or max(values) > high + slack:
        raise SystemExit("endpoint control failed: equity range out of bounds")
    return table, {
        "deals_fitted": deals, "dealer_win": model.dealer_win,
        "mean_points": model.mean_points,
        "symmetric_control_at_zero": control,
        "equity_range": [min(values), max(values)],
    }


_CACHE: dict[str, object] = {}


def _resources(corpus: str):
    if "table" not in _CACHE:
        _CACHE["table"] = build_equity_table(Path(corpus))[0]
        spec = improved_specifications_by_profile_key()["partner_aware_lead_v2"]
        _CACHE["agents"] = {
            seat: improved_agent_from_specification(
                spec, profile_key="partner_aware_lead_v2", seat=seat)
            for seat in range(4)}
    return _CACHE["table"], _CACHE["agents"]


# ------------------------------------------------------------------- engine
def _start(hands):
    return begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=DEALER,
                     match_ref="c1-deal"),
        ExplicitDeal(dealer=DEALER, hands=hands))


def _show_through(hands, agents):
    """Play showing with the reference; stop at the first trick-play decision."""
    state = _start(hands)
    shows = []
    while state.phase is EnginePhase.SHOWING:
        seat = state.current_actor
        action = agents[seat].choose_action(match_observation_for(state, seat))
        shows.append(action)
        state = apply_match_action(state, action)
    if state.phase is not EnginePhase.TRICK_PLAY:
        return None
    seat = state.current_actor
    return seat, tuple(shows), match_observation_for(state, seat)


def _price(hands, shows, forced, agents, table, team):
    """Force the recorded shows, then the arm, then let the reference finish."""
    state = _start(hands)
    queue = list(shows)
    placed = False
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        if state.phase is EnginePhase.SHOWING:
            action = queue.pop(0)
        elif not placed:
            action = forced
            placed = True
        else:
            seat = state.current_actor
            action = agents[seat].choose_action(match_observation_for(state, seat))
        state = apply_match_action(state, action)
    result = state.completed_deals[-1].public_result
    return table.delta(before=result.score_before, after=result.score_after,
                       team=Team(team), we_deal=(team == DEALER % 2))


def _deal_from(rng):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


# -------------------------------------------------------------- one worker
def measure_observation(index: int, corpus: str, root_seed: str,
                        variant: str) -> dict | None:
    table, agents = _resources(corpus)
    with trusted_transitions():
        rng = random.Random(f"{root_seed}|obs|{index}")
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
        want = tuple((a.seat, a.shown_card, a.declared_contract) for a in shows)

        arms = [[] for _ in legal]
        foresight = []
        made = draws = 0
        while made < COMPLETIONS and draws < COMPLETIONS * MAX_DRAW_FACTOR:
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
            if variant == "policy":
                replay = _show_through(world, agents)
                if replay is None:
                    continue
                got = tuple((x.seat, x.shown_card, x.declared_contract)
                            for x in replay[1])
                if got != want or replay[0] != seat:
                    continue
            made += 1
            values = [_price(world, shows, a, agents, table, team) for a in legal]
            for slot, value in enumerate(values):
                arms[slot].append(value)
            policy_index = legal.index(
                agents[seat].choose_action(observation))
            foresight.append(max(values) - values[policy_index])
        if made < COMPLETIONS:
            return None
        policy_index = legal.index(agents[seat].choose_action(observation))
        return {
            "index": index, "seat": seat, "team": team,
            "contract": observation.contract.value,
            "arms": arms, "policy_index": policy_index,
            "foresight": statistics.fmean(foresight),
            "draws": draws, "accepted": made,
        }


# ------------------------------------------------------------- estimators
def shrunk_gain(row) -> float:
    """G_legal_eb per observation: shrink arm means, then best minus policy."""
    means = [statistics.fmean(v) for v in row["arms"]]
    noise = statistics.fmean(
        (statistics.stdev(v) ** 2) / len(v) for v in row["arms"])
    observed = statistics.variance(means) if len(means) > 1 else 0.0
    signal = max(observed - noise, 0.0)
    lam = signal / (signal + noise) if (signal + noise) > 0 else 0.0
    mbar = statistics.fmean(means)
    hat = [mbar + lam * (m - mbar) for m in means]
    return max(hat) - hat[row["policy_index"]]


def cross_fitted(row) -> float:
    """Choose argmax on one half of the completions, score on the other."""
    halves = []
    m = len(row["arms"][0])
    cut = m // 2
    for pick, score in ((slice(0, cut), slice(cut, m)), (slice(cut, m), slice(0, cut))):
        chooser = [statistics.fmean(v[pick]) for v in row["arms"]]
        best = max(range(len(chooser)), key=lambda i: chooser[i])
        halves.append(statistics.fmean(row["arms"][best][score])
                      - statistics.fmean(row["arms"][row["policy_index"]][score]))
    return statistics.fmean(halves)


def bootstrap(values, seed, replicates=BOOTSTRAP_REPLICATES):
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(statistics.fmean(rng.choice(values) for _ in range(n))
                   for _ in range(replicates))
    return draws[int(0.025 * replicates)], draws[int(0.975 * replicates)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus",
                        default="/Users/pyryouri/Developer/TuppiRuns/phase7/t0-pilot")
    parser.add_argument("--variant", choices=sorted(VARIANT_SEEDS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--observations", type=int, default=OBSERVATIONS)
    args = parser.parse_args()

    table, diagnostics = build_equity_table(Path(args.corpus))
    print(f"endpoint controls passed: {json.dumps(diagnostics)}")
    root_seed = VARIANT_SEEDS[args.variant]
    started = time.perf_counter()
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(measure_observation, index, args.corpus,
                               root_seed, args.variant)
                   for index in range(args.observations)]
        for done in as_completed(futures):
            row = done.result()
            if row is not None:
                rows.append(row)
            if len(rows) % 64 == 0 and rows:
                print(f"  {len(rows)} observations, "
                      f"{time.perf_counter() - started:.0f}s", flush=True)
    elapsed = time.perf_counter() - started
    if not rows:
        raise SystemExit("no observations completed")
    rows.sort(key=lambda r: r["index"])

    eb = [shrunk_gain(r) for r in rows]
    deploy = [cross_fitted(r) for r in rows]
    fore = [r["foresight"] for r in rows]
    # deployment normalisation: the share of deals in which the evaluated
    # partnership holds the opening lead is 1.0 here by construction, because the
    # acting seat IS the opening leader and its own team is the evaluated one.
    # A deployed rule fires whenever either partner leads, so the per-deal figure
    # is the conditional figure times the probability that our side leads, which
    # for a symmetric four-seat rotation is one half.
    seat_share = 0.5
    payload = {
        "schema": "tuppi-c1-headroom-v1",
        "preregistration": "docs/cardplay/hypotheses_c1.md",
        "preregistration_commit": "6934da7",
        "variant": args.variant, "root_seed": root_seed,
        "endpoint": diagnostics,
        "observations": len(rows), "completions": COMPLETIONS,
        "arms": statistics.fmean(len(r["arms"]) for r in rows),
        "rollouts": sum(len(r["arms"]) * COMPLETIONS for r in rows),
        "mean_draws_per_world": statistics.fmean(
            r["draws"] / r["accepted"] for r in rows),
        "seconds": round(elapsed, 1),
        "seat_share": seat_share, "delta": DELTA,
    }
    for name, values in (("G_legal_eb", eb), ("G_deploy", deploy),
                         ("G_foresight", fore)):
        lo, hi = bootstrap(values, f"{BOOTSTRAP_SEED}|{name}")
        payload[name] = {
            "conditional": statistics.fmean(values),
            "normalised": statistics.fmean(values) * seat_share,
            "ci95_normalised": [lo * seat_share, hi * seat_share],
        }
    eb_hi = payload["G_legal_eb"]["ci95_normalised"][1]
    dep_lo = payload["G_deploy"]["ci95_normalised"][0]
    payload["gate"] = ("SCIENTIFIC_KILL" if eb_hi < DELTA
                       else "PASS" if dep_lo > DELTA else "INCONCLUSIVE")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / f"c1_{args.variant}.json").write_text(json.dumps(payload, indent=2))
    for key in ("observations", "rollouts", "mean_draws_per_world", "seconds"):
        print(f"  {key}: {payload[key]}")
    for name in ("G_legal_eb", "G_deploy", "G_foresight"):
        v = payload[name]
        print(f"  {name:12} normalised {v['normalised']:+.6f}  "
              f"CI {[round(x, 6) for x in v['ci95_normalised']]}")
    print(f"  delta {DELTA}  ->  GATE: {payload['gate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
