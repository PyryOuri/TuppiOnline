"""N09: the paired forced-NOLO trial, and its fixed analysis.

A research runner mode for the frozen N08 candidate. It measures **forced-NOLO
deal play at the table** — not whole-match strength, not performance against
humans, and not equity at any other scoreboard.

## The design, and why it is shaped this way

Every base deal is played four times with identical cards and identical canonical
showing, varying only which partnership uses which policy:

    BB   Team 0 = v2         Team 1 = v2
    CB   Team 0 = candidate  Team 1 = v2
    BC   Team 0 = v2         Team 1 = candidate
    CC   Team 0 = candidate  Team 1 = candidate

Team 0 is the predeclared target throughout. The two primary contrasts are
``D_B = T_BB - T_CB`` (the candidate against baseline opponents) and
``D_C = T_BC - T_CC`` (the same replacement when the opponents also use it).

**They share deals and arms and are not independent replications**, and the
report says so wherever it quotes both. The Team-1 mirror is reported only as an
orientation diagnostic, never pooled with Team 0: trick totals are conserved
within a deal, which can make a pooled complementary contrast algebraically
identical to one already counted. Individual seats, the thirteen tricks of a
deal, and score projections are likewise not additional observations. One base
deal is one unit.

Agents are constructed fresh per arm and per deal, so no certificate, plan or
memo can cross between arms. An arm that fails is reported as an incomplete
block; it is never substituted or quietly dropped.

## Orientation of the endpoints

Both effect families are signed so that **positive favours the candidate**. In
NOLO fewer tricks is better, so the trick contrast is the baseline arm minus the
candidate arm; a deal win is better, so the win contrast is the candidate arm
minus the baseline arm. Stating this once here is what keeps the two from being
read with opposite signs later.
"""

from __future__ import annotations

import argparse
import json
import time
from multiprocessing import get_context
from pathlib import Path

from tuppi_agents.void_lead import void_seeking_agents
from tuppi_engine import EnginePhase, PlayCardAction, PlayerObservation, apply_action, observation_for
from tuppi_eval.statistics import paired_value_summary
from tuppi_rules import score_nolo

from .adapter import construct_security_certified_agent
from .runner import deal_state
from .support import SupportBudget

SCHEMA_VERSION = "tuppi.nolo.paired_trial.v1"

TRIAL_SEED = "nolo-info-strength-v1"
ANALYSIS_SEED = "nolo-info-strength-analysis-v1"
CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_REPLICATES = 5_000
PERMUTATION_REPLICATES = 5_000
DEFAULT_CAP_HOURS = 4.0

#: Predeclared acceptance thresholds. Proposed practical choices, fixed before
#: the run; neither is a historical finding nor a power calculation.
TRICK_IMPROVEMENT_THRESHOLD = 0.05
WIN_NONINFERIORITY_MARGIN = -0.02

#: Team 0 is seats 0 and 2. Both seats of a team use that team's policy.
ARMS = ("BB", "CB", "BC", "CC")


class TrialError(RuntimeError):
    """An arm could not be played; its block is incomplete, never substituted."""


def _policies(arm: str, budget: SupportBudget):
    baseline = void_seeking_agents()
    letters = {"B": 0, "C": 1}
    if arm not in ARMS:
        raise TrialError(f"unknown arm {arm!r}")
    team_choice = (letters[arm[0]], letters[arm[1]])
    candidate_seats = frozenset(seat for seat in range(4) if team_choice[seat % 2])
    agents = tuple(
        construct_security_certified_agent(seat, budget=budget)
        if seat in candidate_seats else baseline[seat]
        for seat in range(4)
    )
    return agents, candidate_seats


def play_arm(seed: str, index: int, arm: str, *, budget: SupportBudget) -> dict:
    """Play one deal to the end under one seat assignment.

    Fresh agents, so nothing carries over from another arm or another deal.
    """

    state = deal_state(seed, index)
    agents, candidate_seats = _policies(arm, budget)
    counters = {
        "decisions": 0, "corrections": 0, "plan_commitments": 0,
        "plan_executions": 0, "plan_mismatches": 0, "fallbacks": 0,
        "universal": 0, "security_only": 0, "baseline_kept": 0,
        "latency_seconds": 0.0, "max_latency_seconds": 0.0,
    }
    # Delegating because a decision is out of scope is a different thing from a
    # search that ran and could not finish, and the report must not merge them.
    fallbacks_by_reason: dict = {}

    while state.phase is EnginePhase.TRICK_PLAY:
        actor = state.current_actor
        observation = observation_for(state, actor)
        if not isinstance(observation, PlayerObservation):  # pragma: no cover
            raise TrialError("a policy was about to receive a private state")
        started = time.perf_counter()
        action = agents[actor].choose_action(observation)
        elapsed = time.perf_counter() - started
        if actor in candidate_seats:
            report = agents[actor].security_report(observation)
            outcome = report.get("outcome", "")
            counters["decisions"] += 1
            counters["latency_seconds"] += elapsed
            counters["max_latency_seconds"] = max(counters["max_latency_seconds"], elapsed)
            if outcome.startswith("nolo_fallback"):
                counters["fallbacks"] += 1
                fallbacks_by_reason[outcome] = fallbacks_by_reason.get(outcome, 0) + 1
            if outcome == "nolo_fallback_plan_history_mismatch":
                # The seat played its own certified card, so every later own key
                # must be in the plan. A mismatch here is a broken commitment.
                counters["plan_mismatches"] += 1
            if outcome == "nolo_certified_plan_continuation":
                counters["plan_executions"] += 1
            if report.get("corrected"):
                counters["corrections"] += 1
                counters["plan_commitments"] += 1
            claim = report.get("claim")
            if claim == "UNIVERSAL":
                counters["universal"] += 1
            elif claim == "SECURITY_ONLY":
                counters["security_only"] += 1
            elif claim == "TIE":
                counters["baseline_kept"] += 1
        if not isinstance(action, PlayCardAction) or action not in observation.legal_actions:
            raise TrialError(f"seat {actor} chose an action outside the legal set")
        state = apply_action(state, action)

    if not state.complete or len(state.completed_tricks) != 13:
        raise TrialError("an arm ended before all thirteen tricks were played")
    counters["fallbacks_by_reason"] = fallbacks_by_reason
    team_tricks = tuple(state.team_tricks)
    deal_score = score_nolo(*team_tricks)
    return {
        "arm": arm,
        "team_tricks": list(team_tricks),
        "winner_team": int(deal_score.winner_team),
        "points": deal_score.points,
        "counters": counters,
    }


def play_block(payload) -> dict:
    """All four arms of one base deal. Complete, or explicitly incomplete."""

    seed, index, tricks, worlds, transitions = payload
    budget = SupportBudget(tricks, worlds, transitions)
    arms: dict = {}
    for arm in ARMS:
        try:
            arms[arm] = play_arm(seed, index, arm, budget=budget)
        except Exception as exc:  # pragma: no cover - reported, never swallowed
            return {"deal_index": index, "complete": False,
                    "error": f"{arm}: {exc!r}", "arms": arms}
    return {"deal_index": index, "complete": True, "arms": arms}


# --------------------------------------------------------------- the analysis


def team_total(block: dict, arm: str, team: int) -> int:
    return block["arms"][arm]["team_tricks"][team]


def team_won(block: dict, arm: str, team: int) -> int:
    return int(block["arms"][arm]["winner_team"] == team)


def contrast(blocks, *, baseline_arm: str, candidate_arm: str, team: int) -> dict:
    """One predeclared contrast, both effect families, signed so that positive
    favours the candidate in each."""

    complete = [b for b in blocks if b["complete"]]
    incomplete = len(blocks) - len(complete)
    tricks = tuple(
        float(team_total(b, baseline_arm, team) - team_total(b, candidate_arm, team))
        for b in complete
    )
    wins = tuple(
        float(team_won(b, candidate_arm, team) - team_won(b, baseline_arm, team))
        for b in complete
    )

    def summarise(values):
        return paired_value_summary(
            values,
            incomplete_block_count=incomplete,
            transformed_game_count=0,
            confidence_level=CONFIDENCE_LEVEL,
            analysis_seed=ANALYSIS_SEED,
            bootstrap_replicates=BOOTSTRAP_REPLICATES,
            permutation_replicates=PERMUTATION_REPLICATES,
        )

    return {
        "baseline_arm": baseline_arm,
        "candidate_arm": candidate_arm,
        "team": team,
        "tricks": summarise(tricks),
        "deal_wins": summarise(wins),
    }


def _bound(summary, edge: int):
    interval = summary.get("bootstrap_confidence_interval")
    return None if interval is None else interval[edge]


def decide(primary: dict) -> tuple[str, list[str]]:
    """Apply the preregistered endpoints. No interval is chosen after the fact.

    The declared bound is always the bootstrap one, on both contrasts, for both
    effect families.
    """

    notes: list[str] = []
    passed = True
    harmed = False
    for name, result in primary.items():
        tricks, wins = result["tricks"], result["deal_wins"]
        mean = tricks.get("mean_paired_utility")
        low, high = _bound(tricks, 0), _bound(tricks, 1)
        if mean is None or low is None:
            return "INCONCLUSIVE", [f"{name}: no interval could be formed"]
        if high < 0:
            harmed = True
            notes.append(f"{name}: trick effect upper bound {high:+.4f} is below zero")
        if mean < TRICK_IMPROVEMENT_THRESHOLD:
            passed = False
            notes.append(
                f"{name}: mean {mean:+.4f} tricks is below the {TRICK_IMPROVEMENT_THRESHOLD} threshold"
            )
        if low <= 0:
            passed = False
            notes.append(f"{name}: lower trick bound {low:+.4f} does not exceed zero")
        win_mean = wins.get("mean_paired_utility")
        win_low, win_high = _bound(wins, 0), _bound(wins, 1)
        if win_high is not None and win_high < WIN_NONINFERIORITY_MARGIN:
            harmed = True
            notes.append(f"{name}: deal-win upper bound {win_high:+.4f} is below the margin")
        if win_mean is None or win_mean < 0:
            passed = False
            notes.append(f"{name}: deal-win point estimate {win_mean} is below zero")
        if win_low is None or win_low < WIN_NONINFERIORITY_MARGIN:
            passed = False
            notes.append(
                f"{name}: lower deal-win bound {win_low} breaches the "
                f"{WIN_NONINFERIORITY_MARGIN} noninferiority margin"
            )
    if harmed:
        return "HARM_DETECTED", notes
    if passed:
        return "SUPPORTED", notes
    return "INCONCLUSIVE", notes


def analyse(blocks, *, attempted: int, cap_reached: bool) -> dict:
    complete = [b for b in blocks if b["complete"]]
    incomplete = [b for b in blocks if not b["complete"]]
    primary = {
        "D_B": contrast(blocks, baseline_arm="BB", candidate_arm="CB", team=0),
        "D_C": contrast(blocks, baseline_arm="BC", candidate_arm="CC", team=0),
    }
    # Orientation diagnostics only. Never pooled with the primaries: trick totals
    # are conserved within a deal, so a pooled complementary contrast can be
    # algebraically the same observation counted twice.
    secondary = {
        "D_B_team1": contrast(blocks, baseline_arm="BB", candidate_arm="BC", team=1),
        "D_C_team1": contrast(blocks, baseline_arm="CB", candidate_arm="CC", team=1),
    }
    counters = {}
    for arm in ARMS:
        totals: dict = {}
        reasons: dict = {}
        for block in complete:
            for name, value in block["arms"][arm]["counters"].items():
                if name == "fallbacks_by_reason":
                    for reason, count in value.items():
                        reasons[reason] = reasons.get(reason, 0) + count
                elif name.startswith("max_"):
                    # A maximum does not add up. Summing it turned the worst
                    # single decision into the total, which is nonsense.
                    totals[name] = max(totals.get(name, 0), value)
                else:
                    totals[name] = totals.get(name, 0) + value
        totals["fallbacks_by_reason"] = dict(sorted(reasons.items()))
        counters[arm] = totals
    violations = {
        "plan_mismatches": sum(counters[a].get("plan_mismatches", 0) for a in ARMS),
        "incomplete_blocks": len(incomplete),
        "blocks_attempted": attempted,
        "blocks_complete": len(complete),
    }
    sound = violations["plan_mismatches"] == 0 and not incomplete and not cap_reached
    if violations["plan_mismatches"]:
        outcome, notes = "INVALID", ["a certified continuation commitment was broken"]
    elif incomplete or cap_reached or len(complete) != attempted:
        outcome, notes = "INCONCLUSIVE", [
            "the fixed bank did not complete; no selected subset is evaluated"
        ]
    else:
        outcome, notes = decide(primary)
    return {
        "schema_version": SCHEMA_VERSION,
        "outcome": outcome,
        "notes": notes,
        "sound": sound,
        "violations": violations,
        "primary": primary,
        "secondary_orientation_only": secondary,
        "counters": counters,
        "incomplete": [{"deal_index": b["deal_index"], "error": b.get("error")}
                       for b in incomplete],
        "thresholds": {
            "trick_improvement": TRICK_IMPROVEMENT_THRESHOLD,
            "deal_win_noninferiority_margin": WIN_NONINFERIORITY_MARGIN,
            "confidence_level": CONFIDENCE_LEVEL,
            "analysis_seed": ANALYSIS_SEED,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "permutation_replicates": PERMUTATION_REPLICATES,
        },
        "cap_reached": cap_reached,
    }


# ----------------------------------------------------------------- the runner


def run_paired(
    *,
    seed: str = TRIAL_SEED,
    deals: int = 512,
    workers: int = 1,
    out_dir: Path,
    cap_hours: float = DEFAULT_CAP_HOURS,
    budget: SupportBudget | None = None,
    log=print,
) -> dict:
    budget = budget or SupportBudget()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = [
        (seed, index, budget.max_remaining_tricks, budget.max_worlds,
         budget.max_engine_transitions)
        for index in range(deals)
    ]
    started = time.monotonic()
    deadline = started + cap_hours * 3600
    blocks: list[dict] = []
    cap_reached = False

    with (out_dir / "blocks.jsonl").open("w", encoding="utf-8") as handle:
        def absorb(block):
            blocks.append(block)
            handle.write(json.dumps(block, sort_keys=True) + "\n")
            handle.flush()
            totals = " ".join(
                f"{arm}:{block['arms'][arm]['team_tricks'][0]}" for arm in ARMS
            ) if block["complete"] else f"INCOMPLETE {block.get('error')}"
            log(f"[{len(blocks):>4}/{deals}] deal {block['deal_index']:>4} "
                f"team0 {totals} elapsed={(time.monotonic() - started) / 60:.1f}m")

        if workers <= 1:
            for payload in payloads:
                if time.monotonic() >= deadline:
                    cap_reached = True
                    break
                absorb(play_block(payload))
        else:
            context = get_context("spawn")
            with context.Pool(processes=workers) as pool:
                for block in pool.imap_unordered(play_block, payloads):
                    absorb(block)
                    if time.monotonic() >= deadline:
                        cap_reached = True
                        pool.terminate()
                        break

    report = analyse(blocks, attempted=deals, cap_reached=cap_reached)
    report["run"] = {
        "seed": seed, "deals": deals, "workers": workers, "cap_hours": cap_hours,
        "budget": {
            "max_remaining_tricks": budget.max_remaining_tricks,
            "max_worlds": budget.max_worlds,
            "max_engine_transitions": budget.max_engine_transitions,
        },
        "wall_seconds": time.monotonic() - started,
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True), encoding="utf-8"
    )
    log(f"outcome {report['outcome']}")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tuppi_nolo.trial")
    commands = parser.add_subparsers(dest="command", required=True)
    paired = commands.add_parser("paired", help="run the N09 paired validation")
    paired.add_argument("--seed", default=TRIAL_SEED)
    paired.add_argument("--deals", type=int, default=512)
    paired.add_argument("--workers", type=int, default=1)
    paired.add_argument("--out", required=True)
    paired.add_argument("--cap-hours", type=float, default=DEFAULT_CAP_HOURS)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "run.log").open("a", encoding="utf-8") as handle:
        def log(message):
            print(message, flush=True)
            handle.write(message + "\n")
            handle.flush()

        report = run_paired(
            seed=args.seed, deals=args.deals, workers=args.workers,
            out_dir=out_dir, cap_hours=args.cap_hours, log=log,
        )
    return 0 if report["outcome"] != "INVALID" else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
