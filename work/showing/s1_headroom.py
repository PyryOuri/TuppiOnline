"""S1: observation-compatible headroom at the forehand's first show.

The instrument for ``docs/showing/hypotheses_s1.md``, which fixes the design and
the gates and was committed before this file existed.  Read it first; nothing
here may deviate from it.

    PYTHONPATH=src python work/showing/s1_headroom.py --output <dir>

What it does, per pre-registration:

* draws 512 distinct forehand hands - at the first show the public history is
  empty, so a hand *is* an observation;
* completes each 128 times by dealing the other 39 cards uniformly among the
  three unseen seats, which at this decision is the exact conditional and needs
  no belief model;
* plays two executable arms per completion - the reference's own show, and the
  other declaration with a declared lowest-eligible-rank selector - with the
  frozen reference playing everything else in both arms;
* prices each completed deal by per-deal frozen-continuation match equity;
* cross-fits the selector so it cannot be scored on the noise it chose from.

The three reported quantities are different things and the pre-registration
tests different ones:

``G_deploy``       what a deployed cross-fitted selector actually gains, per deal
``G_legal_upper``  an optimistic bound on observation-compatible headroom
``G_foresight``    the oracle, for comparison with the charter's 3.3x framing only
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import json
import math
from pathlib import Path
import statistics
import sys
import time

from tuppi_agents.improved_registry import (
    corpus_reference_specification,
    improved_agent_from_specification,
)
from tuppi_corpus.packing import canonical_hands
from tuppi_corpus.seeds import derive_seed, uniform_below
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import FULL_DECK, Contract, MatchScore, Team
from tuppi_valuation.equity import DealModel, EquityTable, equity_bounds

REFERENCE = "partner_aware_lead_v2"
ROOT_SEED = "tuppi-s1-headroom-v1"

#: Fixed by the pre-registration. Not tunable from the command line.
OBSERVATIONS = 512
COMPLETIONS = 128
DELTA = 0.001
#: The forehand's partnership holds the forehand in half of complementary legs.
SEAT_SHARE = 0.5
#: One-sided 97.5%.
Z = 1.959963984540054

DEALER = 0
FOREHAND = (DEALER + 1) % 4
FOREHAND_TEAM = Team.TEAM_1 if FOREHAND % 2 else Team.TEAM_0


# ----------------------------------------------------------------- the endpoint


def build_equity_table(corpus: Path) -> tuple[EquityTable, dict[str, object]]:
    """Fit the reference's deal model, solve the chain, and check it.

    The reference is score-independent (``match_state_enabled = false``), so one
    outcome distribution serves every score and the chain is exact given it.
    """

    from tuppi_corpus.shards import read_catalog, read_shard

    dealer_counts: dict[int, int] = {}
    other_counts: dict[int, int] = {}
    deals = 0
    for entry in read_catalog(corpus):
        _header, matches, rows = read_shard(corpus / entry["shard"])
        for row in rows:
            if matches[row.match_row].stratum != 0:  # reference self-play only
                continue
            points = max(row.deal_points)
            winner = 0 if row.deal_points[0] else 1
            bucket = dealer_counts if winner == row.dealer % 2 else other_counts
            bucket[points] = bucket.get(points, 0) + 1
            deals += 1
    if not deals:
        raise SystemExit(f"no reference self-play deals found under {corpus}")
    dealer_total = sum(dealer_counts.values())
    other_total = sum(other_counts.values())
    model = DealModel(
        dealer_win=dealer_total / (dealer_total + other_total),
        points_given_dealer={
            points: count / dealer_total for points, count in sorted(dealer_counts.items())
        },
        points_given_other={
            points: count / other_total for points, count in sorted(other_counts.items())
        },
    )
    table = EquityTable.build(model)

    # Pre-registration §8: the endpoint must pass its own model-free checks
    # before it is allowed to price anything.
    level = MatchScore(0, 0)
    symmetric = EquityTable.build(DealModel.symmetric(dict(model.points_given_dealer)))
    symmetric_zero = symmetric.equity(level, Team.TEAM_0, we_deal=True)
    if abs(symmetric_zero - 0.5) > 1e-9:
        raise SystemExit(f"endpoint check failed: symmetric V(0-0) = {symmetric_zero}")
    low, high = equity_bounds()
    values = list(table.value.values())
    # The empirical model is not exactly symmetric, so a small excursion past the
    # equal-strength bounds is correct. Allow only as much as the measured dealer
    # asymmetry can explain.
    slack = abs(model.dealer_win - 0.5) * 2.0 + 1e-9
    if min(values) < low - slack or max(values) > high + slack:
        raise SystemExit(
            f"endpoint check failed: equity range [{min(values)}, {max(values)}] "
            f"exceeds [{low}, {high}] by more than the dealer asymmetry explains"
        )
    diagnostics = {
        "deals_fitted": deals,
        "dealer_win": model.dealer_win,
        "mean_points": model.mean_points,
        "equity_at_zero_dealing": table.equity(level, Team.TEAM_0, we_deal=True),
        "equity_range": [min(values), max(values)],
        "symmetric_control_at_zero": symmetric_zero,
    }
    return (table, diagnostics)


# ---------------------------------------------------------------- the two arms


def _alternative_show(observation, wanted: Contract):
    """Lowest eligible rank of *wanted*, ties by engine legal-action order.

    Declared in the pre-registration and deliberately not the reference's own
    ranking: the alternative arm has to be a policy we could ship, not a
    borrowing of whatever card preference the reference happens to hold.
    """

    best = None
    for index, action in enumerate(observation.legal_actions):
        if not isinstance(action, ShowAction) or action.declared_contract is not wanted:
            continue
        key = (action.shown_card.rank, index)
        if best is None or key < best[0]:
            best = (key, action)
    return None if best is None else best[1]


def _complete(hand: tuple, seed: int) -> tuple:
    """Deal the 39 cards the forehand does not hold among the other three seats.

    At the first show there is no public history, so this uniform assignment *is*
    the exact conditional distribution. Fisher-Yates over a derived seed; nothing
    touches a module-global RNG.
    """

    held = frozenset(hand)
    rest = [card for card in FULL_DECK if card not in held]
    for position in range(len(rest) - 1, 0, -1):
        swap = uniform_below(seed, position + 1, stride=position)
        rest[position], rest[swap] = rest[swap], rest[position]
    hands = [None] * 4
    hands[FOREHAND] = tuple(hand)
    others = [seat for seat in range(4) if seat != FOREHAND]
    for offset, seat in enumerate(others):
        hands[seat] = tuple(rest[offset * 13 : (offset + 1) * 13])
    return canonical_hands(tuple(hands))


def _play(hands: tuple, forced, table: EquityTable, agents) -> float:
    """Play one deal from 0-0 and return the forehand team's equity delta.

    ``forced`` replaces only the forehand's first show. Every other decision in
    both arms is the frozen reference acting on its own formal observation.

    ``agents`` is resolved once per observation rather than per deal. The
    policies are stateless - a ``RuleBasedPolicy`` holds an identity and an
    immutable profile and nothing else - so reuse cannot carry information
    between deals. Resolving them per deal instead rebuilt the whole
    content-addressed identity catalogue three times per completion and cost
    about two thirds of the runtime.
    """

    state = begin_explicit_deal(
        create_match(
            initial_score=MatchScore(0, 0), initial_dealer=DEALER, match_ref="s1-deal"
        ),
        ExplicitDeal(dealer=DEALER, hands=hands),
    )
    first = True
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        if first:
            if seat != FOREHAND:  # pragma: no cover - forehand shows first
                raise SystemExit("the first actor was not the forehand")
            action = forced if forced is not None else agents[seat].choose_action(observation)
            if action not in observation.legal_actions:
                raise SystemExit("an arm's forced action was not legal")
            first = False
        else:
            action = agents[seat].choose_action(observation)
        state = apply_match_action(state, action)
    result = state.completed_deals[-1].public_result
    # The forehand is dealer+1, so the forehand's team does not deal this deal.
    return table.delta(
        before=result.score_before,
        after=result.score_after,
        team=FOREHAND_TEAM,
        we_deal=False,
    )


# ------------------------------------------------------------------ one worker


@dataclass(frozen=True, slots=True)
class Observation:
    index: int
    baseline_contract: str
    alternative_contract: str
    deltas: tuple[float, ...]


def measure_observation(index: int, corpus: str) -> dict[str, object]:
    table, _ = _cached_table(corpus)
    stream = MatchStream.build(
        root_seed=ROOT_SEED, stream_index=index, initial_dealer=DEALER
    )
    hand = canonical_hands(stream.deal(0).explicit_deal(DEALER).hands)[FOREHAND]

    specification = corpus_reference_specification()
    agents = {
        seat: improved_agent_from_specification(
            specification, profile_key=REFERENCE, seat=seat
        )
        for seat in range(4)
    }

    deltas: list[float] = []
    baseline_contract = None
    alternative_contract = None
    with trusted_transitions():
        for completion in range(COMPLETIONS):
            hands = _complete(
                hand,
                derive_seed(
                    ROOT_SEED, domain="completion", observation=index, draw=completion
                ),
            )
            state = begin_explicit_deal(
                create_match(
                    initial_score=MatchScore(0, 0),
                    initial_dealer=DEALER,
                    match_ref="s1-probe",
                ),
                ExplicitDeal(dealer=DEALER, hands=hands),
            )
            observation = match_observation_for(state, FOREHAND)
            reference_action = agents[FOREHAND].choose_action(observation)
            wanted = (
                Contract.NOLO
                if reference_action.declared_contract is Contract.RAMI
                else Contract.RAMI
            )
            alternative = _alternative_show(observation, wanted)
            if alternative is None:
                raise SystemExit(
                    "no legal show action for the alternative declaration; the "
                    "ruleset guarantees both contracts are expressible"
                )
            if baseline_contract is None:
                baseline_contract = reference_action.declared_contract.value
                alternative_contract = wanted.value
            elif baseline_contract != reference_action.declared_contract.value:
                # The reference is score-independent and sees only its own hand
                # at this decision, so its choice must be constant across the
                # completions of one observation.
                raise SystemExit(
                    "the reference changed its declaration across completions of "
                    "one observation; the baseline arm is not well defined"
                )
            baseline = _play(hands, None, table, agents)
            alternate = _play(hands, alternative, table, agents)
            deltas.append(alternate - baseline)
    return {
        "index": index,
        "baseline_contract": baseline_contract,
        "alternative_contract": alternative_contract,
        "deltas": deltas,
    }


_TABLE_CACHE: dict[str, tuple] = {}


def _cached_table(corpus: str):
    if corpus not in _TABLE_CACHE:
        _TABLE_CACHE[corpus] = build_equity_table(Path(corpus))
    return _TABLE_CACHE[corpus]


# ------------------------------------------------------------------ estimation


def cross_fitted(deltas: list[float]) -> float:
    """The value a selector that chose on one half earns on the other.

    Choosing and scoring on the same completions would manufacture headroom out
    of Monte Carlo error: the max of two noisy means is biased upward. Splitting,
    swapping and averaging removes that.
    """

    half = len(deltas) // 2
    first, second = deltas[:half], deltas[half:]
    total = 0.0
    for choose, value in ((first, second), (second, first)):
        if statistics.fmean(choose) > 0.0:
            total += statistics.fmean(value)
    return total / 2.0


def optimistic(deltas: list[float]) -> float:
    """max(0, mean + z*se): credits every observation that could be positive."""

    mean = statistics.fmean(deltas)
    if len(deltas) < 2:
        return max(0.0, mean)
    standard_error = statistics.stdev(deltas) / math.sqrt(len(deltas))
    return max(0.0, mean + Z * standard_error)


def bootstrap(values: list[float], seed: str, replicates: int = 5000) -> tuple[float, float]:
    """Cluster bootstrap over observations, which are the unit of resampling."""

    count = len(values)
    draws = []
    for replicate in range(replicates):
        base = derive_seed(seed, domain="bootstrap", replicate=replicate)
        total = 0.0
        for position in range(count):
            total += values[uniform_below(base, count, stride=position)]
        draws.append(total / count)
    draws.sort()
    return (draws[int(0.025 * replicates)], draws[int(0.975 * replicates)])


def check_baseline_arm_is_the_reference(table: EquityTable, corpus: str) -> int:
    """Pre-registration §8: the baseline arm must *be* the reference.

    ``_play(hands, None, ...)`` takes the same code path as the forced arm and
    differs only in whether it substitutes the first action. If that path were
    subtly not the reference - a stale observation, a re-resolved agent, an
    off-by-one on which decision is "first" - every delta would be measured
    against the wrong baseline and the experiment would answer nothing. So it is
    compared against a plain reference loop that shares none of that machinery.
    """

    specification = corpus_reference_specification()
    agents = {
        seat: improved_agent_from_specification(
            specification, profile_key=REFERENCE, seat=seat
        )
        for seat in range(4)
    }
    checked = 0
    with trusted_transitions():
        for index in range(4):
            stream = MatchStream.build(
                root_seed=ROOT_SEED, stream_index=index, initial_dealer=DEALER
            )
            hand = canonical_hands(stream.deal(0).explicit_deal(DEALER).hands)[FOREHAND]
            for draw in range(8):
                hands = _complete(
                    hand,
                    derive_seed(
                        ROOT_SEED, domain="completion", observation=index, draw=draw
                    ),
                )
                through_arm = _play(hands, None, table, agents)

                # A plain loop, written independently of _play.
                state = begin_explicit_deal(
                    create_match(
                        initial_score=MatchScore(0, 0),
                        initial_dealer=DEALER,
                        match_ref="s1-control",
                    ),
                    ExplicitDeal(dealer=DEALER, hands=hands),
                )
                while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                    seat = state.current_actor
                    state = apply_match_action(
                        state,
                        agents[seat].choose_action(match_observation_for(state, seat)),
                    )
                result = state.completed_deals[-1].public_result
                plain = table.delta(
                    before=result.score_before,
                    after=result.score_after,
                    team=FOREHAND_TEAM,
                    we_deal=False,
                )
                if through_arm != plain:
                    raise SystemExit(
                        "endpoint check failed: the baseline arm does not reproduce "
                        f"the reference ({through_arm} != {plain})"
                    )
                checked += 1
    return checked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        default="/Users/pyryouri/Developer/TuppiRuns/phase7/t0-pilot",
        help="corpus the reference deal model is fitted from",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()

    table, endpoint = build_equity_table(Path(args.corpus))
    print("endpoint (per-deal frozen-continuation match equity)")
    for key, value in endpoint.items():
        print(f"  {key:28s} {value}")
    print("  -> §8 endpoint checks passed")
    checked = check_baseline_arm_is_the_reference(table, args.corpus)
    print(f"  -> baseline arm reproduces the reference on {checked}/{checked} deals")
    print()

    workers = args.workers or 12
    print(
        f"S1: {OBSERVATIONS} observations x {COMPLETIONS} completions x 2 arms "
        f"= {OBSERVATIONS * COMPLETIONS * 2} rollouts on {workers} workers"
    )
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(measure_observation, index, args.corpus): index
            for index in range(OBSERVATIONS)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if done % 64 == 0:
                print(f"  {done}/{OBSERVATIONS} observations", flush=True)
    elapsed = time.perf_counter() - started
    results.sort(key=lambda row: row["index"])
    print(f"  {elapsed:.1f}s ({OBSERVATIONS * COMPLETIONS * 2 / elapsed:.0f} rollouts/s)")
    print()

    deploy_terms, upper_terms, foresight_terms = [], [], []
    override_flags = []
    for row in results:
        deltas = list(row["deltas"])
        deploy_terms.append(SEAT_SHARE * cross_fitted(deltas))
        upper_terms.append(SEAT_SHARE * optimistic(deltas))
        foresight_terms.append(SEAT_SHARE * statistics.fmean([max(0.0, d) for d in deltas]))
        override_flags.append(1.0 if statistics.fmean(deltas) > 0.0 else 0.0)

    g_deploy = statistics.fmean(deploy_terms)
    g_upper = statistics.fmean(upper_terms)
    g_foresight = statistics.fmean(foresight_terms)
    deploy_ci = bootstrap(deploy_terms, ROOT_SEED + "-deploy")
    upper_ci = bootstrap(upper_terms, ROOT_SEED + "-upper")

    all_deltas = [d for row in results for d in row["deltas"]]
    print("results (equity per evaluated deal, deployment-normalised)")
    print(f"  G_deploy       {g_deploy:+.6f}   95% CI [{deploy_ci[0]:+.6f}, {deploy_ci[1]:+.6f}]")
    print(f"  G_legal_upper  {g_upper:+.6f}   95% CI [{upper_ci[0]:+.6f}, {upper_ci[1]:+.6f}]")
    print(f"  G_foresight    {g_foresight:+.6f}")
    print(f"  delta          {DELTA:+.6f}")
    print()
    print("descriptive")
    print(f"  observations where the alternative's mean beat the baseline: "
          f"{sum(override_flags):.0f}/{OBSERVATIONS} = {100*statistics.fmean(override_flags):.1f}%")
    print(f"  mean per-completion delta   {statistics.fmean(all_deltas):+.5f}")
    print(f"  sd per-completion delta     {statistics.pstdev(all_deltas):.5f}")
    print(f"  completions with any effect {100*sum(1 for d in all_deltas if d != 0)/len(all_deltas):.1f}%")
    contracts = {}
    for row in results:
        contracts[row["baseline_contract"]] = contracts.get(row["baseline_contract"], 0) + 1
    print(f"  reference baseline declaration: {contracts}")
    print()

    if deploy_ci[0] > DELTA:
        verdict = "PASS"
        note = "the cross-fitted selector's lower bound exceeds delta"
    elif upper_ci[1] < DELTA:
        verdict = "SCIENTIFIC KILL"
        note = "the optimistic upper bound on legal headroom falls below delta"
    else:
        verdict = "INCONCLUSIVE"
        note = "neither gate met at the pre-registered budget; the programme stops here"
    print("=" * 68)
    print(f"VERDICT: {verdict}")
    print(f"  {note}")
    print("=" * 68)

    args.output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "tuppi.showing.s1_headroom.v1",
        "root_seed": ROOT_SEED,
        "reference_agent_id": corpus_reference_specification().agent_id,
        "observations": OBSERVATIONS,
        "completions": COMPLETIONS,
        "rollouts": OBSERVATIONS * COMPLETIONS * 2,
        "delta": DELTA,
        "seat_share": SEAT_SHARE,
        "endpoint": endpoint,
        "g_deploy": g_deploy,
        "g_deploy_ci": list(deploy_ci),
        "g_legal_upper": g_upper,
        "g_legal_upper_ci": list(upper_ci),
        "g_foresight": g_foresight,
        "override_rate": statistics.fmean(override_flags),
        "mean_delta": statistics.fmean(all_deltas),
        "sd_delta": statistics.pstdev(all_deltas),
        "effect_rate": sum(1 for d in all_deltas if d != 0) / len(all_deltas),
        "baseline_declarations": contracts,
        "seconds": elapsed,
        "verdict": verdict,
        "per_observation": results,
    }
    (args.output / "s1_headroom.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {args.output / 's1_headroom.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
