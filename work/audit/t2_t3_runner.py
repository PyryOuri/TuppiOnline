"""T2 rule-ablation discovery and T3 two-trick ceiling, on one frozen manifest.

Contract in ``docs/audit/prereg_t0.md``. Both tasks are driven from the same
2 000-deal manifest and share the reference-only control execution, exactly as
the work package requires ("reuse reference-only controls where valid").

    PYTHONPATH=src python work/audit/t2_t3_runner.py --output reports/audit

**T2** deploys each frozen variant in *both* candidate seats against the
reference in the other two, then swaps the candidate team on identical hands.
That evaluates the actual two-seat variant rather than a continuation assuming a
different partner - the failure mode diagnosed in every earlier search attempt.

**T3** replays every legal action at the evaluated partnership's first turn in
trick 12 on the *actual* hidden deal, with the frozen reference in all four seats
thereafter, and takes the best realised branch. Hidden state is read only in
that offline branch-selection step; every continuation policy sees only its own
formal observation.

Determinism: aggregation is by sorted deal index, so worker completion order
cannot move a number. All bootstrap draws come from ``tuppi_corpus.seeds``.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "showing"))
from s1_headroom import build_equity_table  # noqa: E402  the one existing endpoint

from tuppi_agents import phase4_specifications_by_profile_key, registered_profiles
from tuppi_agents.factory import construct_registered_agent
from tuppi_agents.improved_registry import (
    corpus_reference_specification,
    improved_agent_from_specification,
)
from tuppi_agents.profiles import HeuristicProfile
from tuppi_agents.void_lead import VoidSeekingPartnerAwarePolicy
from tuppi_corpus.packing import canonical_hands
from tuppi_corpus.seeds import derive_seed, uniform_below
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.trusted import trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore, Team

# ---- frozen by the pre-registration; not command-line tunable ---------------
ROOT_SEED = "tuppi-t0-audit-v1"
DEALS = 2000
DELTA = 0.001
Z95 = 1.6448536269514722          # one-sided 95%
BOOTSTRAP = 5000
REFERENCE = "partner_aware_lead_v2"
BASE_PROFILE = "partner_aware_v1"

#: T2 variant list, frozen in prereg_t0.md §4. V1-V4 are single-rule ablations;
#: V5 is an explicitly compound two-layer ablation whose documented fallback is
#: the registered frozen partner_aware_v1.
SINGLE_RULE_ABLATIONS = (
    ("V1", "partner.nolo.prefer_leading_partner_void_suit.v1"),
    ("V2", "partner.rami.overtake_when_partner_beatable.v1"),
    ("V3", "partner.rami.prefer_leading_suit_partner_can_follow.v1"),
    ("V4", "reactive.rami.avoid_overtaking_partner.v1"),
)
COMPOUND_ABLATION = ("V5", "both lead_v2 lead layers -> partner_aware_v1")


#: Policies are stateless - a RuleBasedPolicy holds an identity and an immutable
#: profile and nothing else - so one table per worker process is safe and avoids
#: rebuilding the content-addressed identity catalogue for every deal. Resolving
#: per deal cost ~8 s/deal against ~1 s cached.
_AGENT_CACHE: dict[str, tuple] = {}


def reference_agents() -> dict[int, object]:
    if "reference" not in _AGENT_CACHE:
        spec = corpus_reference_specification()
        _AGENT_CACHE["reference"] = (
            {
                seat: improved_agent_from_specification(
                    spec, profile_key=REFERENCE, seat=seat
                )
                for seat in range(4)
            },
            spec.agent_id,
        )
    return _AGENT_CACHE["reference"][0]


def variant_agents(variant: str) -> tuple[dict[int, object], str]:
    """Four variant policies, and the variant's own identity."""

    if variant in _AGENT_CACHE:
        return _AGENT_CACHE[variant]
    built = _build_variant(variant)
    _AGENT_CACHE[variant] = built
    return built


def _build_variant(variant: str) -> tuple[dict[int, object], str]:
    if variant == "V5":
        spec = phase4_specifications_by_profile_key()[BASE_PROFILE]
        return (
            {seat: construct_registered_agent(spec, seat=seat) for seat in range(4)},
            spec.agent_id,
        )
    rule_id = dict(SINGLE_RULE_ABLATIONS)[variant]
    control = registered_profiles()[BASE_PROFILE]
    profile = HeuristicProfile.build(
        profile_key=BASE_PROFILE,
        family=control.family,
        showing_policy=control.showing_policy,
        parameters=dict(control.parameters),
        disabled_rule_ids=(rule_id,),
        description=f"T2 diagnostic ablation of {rule_id}",
    )
    identity = f"variant:{profile.profile_id}"
    return (
        {
            seat: VoidSeekingPartnerAwarePolicy(agent_id=identity, profile=profile)
            for seat in range(4)
        },
        identity,
    )


def deal_of(index: int):
    dealer = index % 4
    stream = MatchStream.build(
        root_seed=ROOT_SEED, stream_index=index, initial_dealer=dealer
    )
    return (canonical_hands(stream.deal(0).explicit_deal(dealer).hands), dealer)


def fresh(hands, dealer: int, ref: str):
    return begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=dealer, match_ref=ref),
        ExplicitDeal(dealer=dealer, hands=hands),
    )


def play_out(state, seats: dict[int, object]):
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        action = seats[seat].choose_action(match_observation_for(state, seat))
        state = apply_match_action(state, action)
    return state


def equity_for(state, table, team: Team, dealer: int) -> float:
    result = state.completed_deals[-1].public_result
    return table.delta(
        before=result.score_before,
        after=result.score_after,
        team=team,
        we_deal=(team.value == dealer % 2),
    )


def mixed(candidate: dict[int, object], control: dict[int, object], team: int):
    """Candidate in *team*'s two seats, reference in the other two."""

    return {seat: (candidate if seat % 2 == team else control)[seat] for seat in range(4)}


# ----------------------------------------------------------------- T3 helpers


def t3_ceiling(hands, dealer: int, table, control: dict[int, object], team: int) -> dict:
    """Oracle gain at the evaluated partnership's first turn in trick 12.

    The trigger is public: eleven completed tricks, the acting seat belongs to
    the evaluated partnership, and its partner has not yet acted in the current
    trick. Forced and outcome-identical cases return zero and are retained.
    """

    state = fresh(hands, dealer, "t3-ceiling")
    root = None
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        if (
            state.phase is EnginePhase.TRICK_PLAY
            and len(observation.completed_tricks) == 11
            and seat % 2 == team
            and not any(play.seat % 2 == team for play in observation.current_trick)
        ):
            root = (state, observation)
            break
        state = apply_match_action(state, control[seat].choose_action(observation))
    if root is None:
        return {"reached": False, "legal": 0, "gain": 0.0, "reference_equity": None}

    state, observation = root
    reference_action = control[state.current_actor].choose_action(observation)
    values = {}
    for action in observation.legal_actions:
        finished = play_out(apply_match_action(state, action), control)
        values[action] = equity_for(finished, table, Team(team), dealer)
    baseline = values[reference_action]
    best = max(values.values())
    return {
        "reached": True,
        "legal": len(observation.legal_actions),
        "forced": len(observation.legal_actions) == 1,
        "gain": best - baseline,          # >= 0 by construction
        "reference_equity": baseline,
        "distinct_outcomes": len(set(round(v, 12) for v in values.values())),
    }


# -------------------------------------------------------------------- one deal


def measure_deal(index: int, corpus: str) -> dict[str, object]:
    table, _ = _cached(corpus)
    hands, dealer = deal_of(index)
    control = reference_agents()

    with trusted_transitions():
        # One control execution, reused by every variant and by T3.
        ctrl_state = play_out(fresh(hands, dealer, "t2-control"), control)
        ctrl = {
            0: equity_for(ctrl_state, table, Team.TEAM_0, dealer),
            1: equity_for(ctrl_state, table, Team.TEAM_1, dealer),
        }
        ctrl_result = ctrl_state.completed_deals[-1].public_result

        variants: dict[str, object] = {}
        for variant, _label in list(SINGLE_RULE_ABLATIONS) + [COMPOUND_ABLATION]:
            agents, identity = variant_agents(variant)
            per_team = {}
            disagreements = 0
            for team in (0, 1):
                seats = mixed(agents, control, team)
                state = play_out(fresh(hands, dealer, "t2-variant"), seats)
                per_team[team] = equity_for(state, table, Team(team), dealer) - ctrl[team]
                result = state.completed_deals[-1].public_result
                if tuple(result.team_tricks) != tuple(ctrl_result.team_tricks):
                    disagreements += 1
            variants[variant] = {
                "identity": identity,
                "contrast": 0.5 * (per_team[0] + per_team[1]),
                "team0_change": per_team[0],
                "team1_change": per_team[1],
                "assignments_that_changed_tricks": disagreements,
            }

        t3 = {team: t3_ceiling(hands, dealer, table, control, team) for team in (0, 1)}

    return {
        "deal": index,
        "dealer": dealer,
        "control_contract": ctrl_result.contract.value,
        "control_team_tricks": list(ctrl_result.team_tricks),
        "control_points": ctrl_result.deal_score.points,
        "variants": variants,
        "t3": {
            "contrast": 0.5 * (t3[0]["gain"] + t3[1]["gain"]),
            "team0": t3[0],
            "team1": t3[1],
        },
    }


_CACHE: dict[str, object] = {}


def _cached(corpus: str):
    if corpus not in _CACHE:
        _CACHE[corpus] = build_equity_table(Path(corpus))
    return _CACHE[corpus]


# ------------------------------------------------------------------ statistics


def cluster_bootstrap(values: list[float], seed: str) -> list[float]:
    count = len(values)
    draws = []
    for replicate in range(BOOTSTRAP):
        base = derive_seed(seed, domain="bootstrap", replicate=replicate)
        total = 0.0
        for position in range(count):
            total += values[uniform_below(base, count, stride=position)]
        draws.append(total / count)
    draws.sort()
    return draws


def one_sided(values: list[float], seed: str) -> tuple[float, float, float]:
    """(mean, one-sided 95% lower, one-sided 95% upper) by cluster bootstrap."""

    draws = cluster_bootstrap(values, seed)
    return (
        statistics.fmean(values),
        draws[int(0.05 * BOOTSTRAP)],
        draws[int(0.95 * BOOTSTRAP) - 1],
    )


def clopper_pearson_upper(successes: int, trials: int, alpha: float = 0.05) -> float:
    """Exact one-sided upper bound on a rate. Used when events are rare or absent."""

    if successes >= trials:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        # P(X <= successes | p = mid) ; bisect until it equals alpha
        total = 0.0
        for k in range(successes + 1):
            total += math.comb(trials, k) * mid**k * (1 - mid) ** (trials - k)
        if total > alpha:
            lo = mid
        else:
            hi = mid
    return hi


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus", default="/Users/pyryouri/Developer/TuppiRuns/phase7/t0-pilot"
    )
    parser.add_argument("--output", type=Path, default=Path("reports/audit"))
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    table, endpoint = build_equity_table(Path(args.corpus))
    print("endpoint: per-deal frozen-continuation match equity")
    print(f"  fitted from {endpoint['deals_fitted']} reference self-play deals")
    print(f"  V(0-0) symmetric control {endpoint['symmetric_control_at_zero']}")
    print(f"  -> endpoint checks passed\n")

    variant_ids = [v for v, _ in SINGLE_RULE_ABLATIONS] + [COMPOUND_ABLATION[0]]
    executions = DEALS * (1 + 2 * len(variant_ids))
    print(f"T2+T3: {DEALS} deals x (1 control + {len(variant_ids)} variants x 2 "
          f"assignments) = {executions:,} deal executions")
    started = time.perf_counter()
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(measure_deal, index, args.corpus): index for index in range(DEALS)
        }
        for done, future in enumerate(as_completed(futures), start=1):
            rows.append(future.result())
            if done % 250 == 0:
                print(f"  {done}/{DEALS} deals", flush=True)
    elapsed = time.perf_counter() - started
    rows.sort(key=lambda row: row["deal"])          # deterministic aggregation
    print(f"  {elapsed:.1f}s ({executions / elapsed:.0f} deal executions/s)\n")

    # ------------------------------------------------------------------ T2
    print("T2 rule-ablation discovery (exploratory one-sided 95% bounds)")
    print(f"  {'':4s}{'rule / scope':56s}{'mean':>10s}{'lower':>10s}{'upper':>10s}"
          f"{'activation':>12s}{'qualifies':>11s}")
    t2_out = {}
    for variant in variant_ids:
        contrasts = [row["variants"][variant]["contrast"] for row in rows]
        changed = sum(
            row["variants"][variant]["assignments_that_changed_tricks"] for row in rows
        )
        mean, lower, upper = one_sided(contrasts, f"{ROOT_SEED}-t2-{variant}")
        qualifies = mean >= DELTA and lower > 0.0
        label = dict(SINGLE_RULE_ABLATIONS).get(variant, COMPOUND_ABLATION[1])
        print(f"  {variant:4s}{label:56s}{mean:+10.5f}{lower:+10.5f}{upper:+10.5f}"
              f"{changed / (2 * DEALS):>11.1%}{'YES' if qualifies else 'no':>11s}")
        t2_out[variant] = {
            "label": label,
            "identity": rows[0]["variants"][variant]["identity"],
            "mean_gain": mean,
            "lower_95_one_sided": lower,
            "upper_95_one_sided": upper,
            "deals": DEALS,
            "assignment_trick_change_rate": changed / (2 * DEALS),
            "qualifies": qualifies,
        }
    qualifying = [v for v, r in t2_out.items() if r["qualifies"]]
    print(f"\n  qualifying variants: {qualifying if qualifying else 'none'}")
    print("  -> " + (
        "no qualifying variant: this ablation route is CLOSED at this budget"
        if not qualifying
        else "qualifying variant(s) recorded for a later authorised task"
    ))

    # ------------------------------------------------------------------ T3
    print("\nT3 two-trick intervention ceiling (actual-layout oracle)")
    gains = [row["t3"]["contrast"] for row in rows]
    reached = sum(
        1 for row in rows for team in ("team0", "team1") if row["t3"][team]["reached"]
    )
    forced = sum(
        1
        for row in rows
        for team in ("team0", "team1")
        if row["t3"][team]["reached"] and row["t3"][team]["forced"]
    )
    opportunities = sum(
        1
        for row in rows
        for team in ("team0", "team1")
        if row["t3"][team]["reached"] and row["t3"][team]["gain"] > 0
    )
    mean, lower, upper = one_sided(gains, f"{ROOT_SEED}-t3")
    print(f"  root reached (of {2 * DEALS} assignments)   {reached}")
    print(f"  forced at the root                  {forced} = {forced / max(1, reached):.1%}")
    print(f"  assignments with any gain           {opportunities}"
          f" = {opportunities / max(1, reached):.1%}")
    print(f"  mean per-deal oracle gain           {mean:+.6f}")
    print(f"  one-sided 95% bounds                [{lower:+.6f}, {upper:+.6f}]")
    print(f"  delta                                {DELTA:+.6f}")
    if opportunities == 0:
        rate_upper = clopper_pearson_upper(0, reached)
        print(f"  no opportunities observed: exact one-sided 95% upper bound on the")
        print(f"  opportunity rate is {rate_upper:.5f}; a [0,0] bootstrap interval is NOT")
        print(f"  evidence that population headroom is zero")
    if lower > DELTA:
        t3_verdict = "PROCEED"
        t3_note = "lower bound exceeds delta; the restricted tactical route may be investigated"
    elif upper < DELTA:
        t3_verdict = "KILL"
        t3_note = "upper bound below delta; this scope has insufficient opportunity"
    else:
        t3_verdict = "INCONCLUSIVE"
        t3_note = "neither bound resolves at the fixed budget; do not enlarge the sample"
    print(f"\n  VERDICT: {t3_verdict} - {t3_note}")

    payload = {
        "schema_version": "tuppi.audit.t2_t3.v1",
        "root_seed": ROOT_SEED,
        "deals": DEALS,
        "delta": DELTA,
        "reference_agent_id": corpus_reference_specification().agent_id,
        "endpoint": endpoint,
        "deal_executions": executions,
        "seconds": elapsed,
        "t2": t2_out,
        "t2_qualifying": qualifying,
        "t2_route_closed": not qualifying,
        "t3": {
            "mean_gain": mean,
            "lower_95_one_sided": lower,
            "upper_95_one_sided": upper,
            "assignments": 2 * DEALS,
            "root_reached": reached,
            "forced_at_root": forced,
            "assignments_with_gain": opportunities,
            "verdict": t3_verdict,
            "note": t3_note,
        },
        "per_deal": rows,
    }
    (args.output / "t2_t3_results.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {args.output / 't2_t3_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
