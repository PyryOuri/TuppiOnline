"""Authoritative v3 duplicate-deal and complete-match runner (C0.06; R01-R06, A09, A11).

This is a new measurement instrument (`E-v3-runner`), not a playing change.
It plays deals only through the ENGINE's legal transitions
(`begin_explicit_deal` / `apply_match_action` / `match_observation_for`),
handling showing, both sooli offers, give, return, three-player play and
ordinary play, and accepts any named policy factory on either team -
including the current W128 search on both opposing seats.

Instruments (lifecycle labels in `lifecycle.LIFECYCLES`):

- `duplicate_bundle`: one base deck, 4 rotations x 2 team assignments; every
  game constructs fresh agents with the seat seeds of its bundle
  ("independent_cold_bundle"), so results do not depend on task order or
  worker count.
- `match_leg` / `match_pair`: agents built once at leg start and kept for the
  whole leg ("retained_match_leg"; or "cold_reset_per_deal" when asked); the
  complementary legs share the indexed decks and the seat-seed map but use
  fresh environments.

A failed action, an exception or a deal-count cap is a recorded outcome: a
capped leg is "unresolved", never a 0.5 draw (statistics.py reports bounds).

Seat seeds: `bundle_seed(namespace, index)` is SHA-256 of the namespace and
the bundle/pair index - the same index that selects the deck, through a
separately labelled SHA-256 stream. The seed therefore contains no card or
layout information; it only makes every arm of one bundle start from the same
seat seeds (spec 1.3), and the factories add their own seat offsets.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .lifecycle import AgentSpec, RecordingAgent
from .records import DealTransition, parent_deal_id
from .streams import shuffled_deck, stream_seed

V3 = "project_target_v3"
DEFAULT_CAP = 400

#: Starting-score laws. The old evaluator's "uniform" is NOT uniform over the
#: 25 nonterminal states: it draws a level 0..12 uniformly, then a side.
SCORE_LAWS = {
    "zero": {"label": "0-0 only"},
    "legacy_uniform": {"label": "legacy evaluate --scores uniform: P(0-0)=1/13, each other state 1/26"},
    "uniform25": {"label": "uniform over the 25 nonterminal states: each 1/25"},
}


def score_weights(law: str) -> dict[tuple[int, int], float]:
    states = [(0, 0)] + [(4 * lv, 0) for lv in range(1, 13)] + [(0, 4 * lv) for lv in range(1, 13)]
    if law == "zero":
        return {(0, 0): 1.0}
    if law == "legacy_uniform":
        return {s: (1 / 13 if s == (0, 0) else 1 / 26) for s in states}
    if law == "uniform25":
        return {s: 1 / 25 for s in states}
    raise KeyError(law)


def draw_score(law: str, namespace: str, index: int) -> tuple[int, int]:
    if law == "zero":
        return (0, 0)
    if law == "legacy_uniform":
        import random

        rng = random.Random(f"{namespace}|score|{index}")  # evaluate._score_for, verbatim
        level = rng.randrange(13)
        if level == 0:
            return (0, 0)
        return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)
    if law == "uniform25":
        states = sorted(score_weights("uniform25"))
        return states[stream_seed("score", namespace, index) % 25]
    raise KeyError(law)


@dataclass(frozen=True)
class PolicyFamily:
    """A named policy for a team: factory, fixed parameters and whether it takes a seed."""

    label: str
    factory: str
    params: tuple = ()
    seeded: bool = False

    @classmethod
    def of(cls, label: str, factory: str, seeded: bool = False, **params) -> "PolicyFamily":
        return cls(label, factory, tuple(sorted(params.items())), seeded)

    def spec(self, seat: int, seed: int | None) -> AgentSpec:
        params = dict(self.params)
        if self.seeded:
            params["seed"] = seed
        return AgentSpec.of(self.factory, seat, **params)


@dataclass
class DealOutcome:
    state: object
    decisions: list = field(default_factory=list)
    failed: bool = False
    failure: str | None = None
    over_deadline: int = 0
    cpu_s: float = 0.0
    wall_s: float = 0.0


def new_match(score=(0, 0), dealer: int = 0, match_ref: str = "research-v3", ruleset: str = V3):
    from tuppi_engine import create_match
    from tuppi_rules import MatchScore, RulesetId

    return create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref=match_ref,
                        ruleset_id=RulesetId(ruleset))


def play_deal(state, agents: dict, hands, deadline_ms: float | None = None,
              max_actions: int | None = None) -> DealOutcome:
    """Plays one explicit deal with legal engine transitions; never raises for a policy failure.

    `max_actions` stops a (smoke-test) deal early; the row is then recorded as
    incomplete, never as a result.
    """
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES

    c0, t0 = time.process_time(), time.perf_counter()
    out = DealOutcome(begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=hands)))
    steps = 0
    while out.state.phase in ACTIVE_PHASES:
        if max_actions is not None and steps >= max_actions:
            out.failed, out.failure = True, f"stopped after max_actions={max_actions} (incomplete by design)"
            break
        seat = out.state.current_actor
        obs = match_observation_for(out.state, seat)
        d0 = time.perf_counter()
        try:
            action = agents[seat].choose_action(obs)
        except Exception as exc:  # a policy failure is data, not a crash of the instrument
            out.failed, out.failure = True, f"seat {seat}: {type(exc).__name__}: {exc}"
            break
        ms = 1000 * (time.perf_counter() - d0)
        out.decisions.append((seat, obs.phase.value, ms))
        if deadline_ms is not None and ms > deadline_ms:
            out.over_deadline += 1
        if action not in obs.legal_actions:
            out.failed, out.failure = True, f"seat {seat}: illegal action {action!r}"
            break
        out.state = apply_match_action(out.state, action)
        steps += 1
        if steps > 60:
            out.failed, out.failure = True, "deal exceeded 60 actions"
            break
    out.cpu_s, out.wall_s = time.process_time() - c0, time.perf_counter() - t0
    return out


def _equity():
    from ..best import EQUITY
    from ..equity import Equity

    return Equity.load(EQUITY)


def transition_row(out: DealOutcome, *, cluster_id, arm, rotation, assignment, source_score, dealer,
                   policy_ids, snapshot_ids, lifecycle, candidate_team, equity) -> DealTransition:
    common = dict(cluster_id=cluster_id, arm=arm, rotation=rotation, assignment=assignment, dealer=dealer,
                  source_score=tuple(source_score), ruleset=V3, policy_ids=tuple(policy_ids),
                  snapshot_ids=tuple(snapshot_ids), lifecycle=lifecycle, candidate_team=candidate_team,
                  cpu_s=out.cpu_s, wall_s=out.wall_s, decision_ms=tuple(d[2] for d in out.decisions),
                  fallbacks=out.over_deadline, rng_scheme="per-seat factory seeds; see policy_ids")
    if out.failed or not out.state.completed_deals or out.state.phase.value not in ("DEAL_COMPLETE",
                                                                                     "MATCH_COMPLETE"):
        return DealTransition(**common, terminal_type=None, contract=None, declarer=None, soolaaja=None,
                              winner_team=None, points=None, team_tricks=None, next_score=None, next_dealer=None,
                              match_terminal=None, candidate_value=None, failed=True,
                              failure=out.failure or "deal did not complete")
    r = out.state.completed_deals[-1].public_result
    before, after = r.score_before.as_tuple(), r.score_after.as_tuple()
    d0 = equity.delta0(before, after, dealer)
    soolaaja = getattr(r, "soolaaja", None)
    return DealTransition(
        **common, terminal_type="sooli" if soolaaja is not None else "ordinary", contract=r.contract.value,
        declarer=r.declarer, soolaaja=soolaaja, winner_team=r.deal_score.winner_team.value,
        points=r.deal_score.points, team_tricks=tuple(r.team_tricks), next_score=after,
        next_dealer=out.state.dealer, match_terminal=out.state.terminal,
        candidate_value=None if candidate_team is None else (d0 if candidate_team == 0 else -d0))


def bundle_seed(namespace: str, index: int) -> int:
    """Seat-seed base of one bundle/pair (the factories add their own seat offsets)."""
    return stream_seed("agent", namespace, "bundle", index) % (1 << 31)


def duplicate_bundle(index: int, candidate: PolicyFamily, baseline: PolicyFamily, *, namespace: str,
                     score_law: str = "zero", dealer: int = 0, deadline_ms: float | None = None,
                     record_calls: bool = False) -> dict:
    """One base deck, 4 rotations x 2 assignments, fresh agents per game."""
    from .lifecycle import snapshot, snapshot_id

    equity = _equity()
    base = shuffled_deck("deal", namespace, index)
    score = draw_score(score_law, namespace, index)
    seed = bundle_seed(namespace, index)
    cluster = parent_deal_id(namespace, index)
    rows, calls = [], []
    for rotation in range(4):
        hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
        for assignment in (0, 1):
            fams = {s: candidate if s % 2 == assignment else baseline for s in range(4)}
            specs = {s: fams[s].spec(s, seed) for s in range(4)}
            agents = {s: RecordingAgent(specs[s]) for s in range(4)}
            snaps = tuple(snapshot_id(snapshot(agents[s])) for s in range(4))
            out = play_deal(new_match(score, dealer, match_ref="research-dup"), agents, hands, deadline_ms)
            rows.append(transition_row(out, cluster_id=cluster, arm=f"cand_team{assignment}", rotation=rotation,
                                       assignment=assignment, source_score=score, dealer=dealer,
                                       policy_ids=[specs[s].spec_id for s in range(4)], snapshot_ids=snaps,
                                       lifecycle="independent_cold_bundle", candidate_team=assignment,
                                       equity=equity))
            if record_calls:
                calls.append({s: agents[s].history for s in range(4)})
    values = [r.candidate_value for r in rows]
    resolved = not any(r.failed for r in rows)
    return {"index": index, "cluster_id": cluster, "score": score, "score_law": score_law,
            "value": sum(values) / len(values) if resolved else None, "resolved": resolved,
            "rows": [r.to_data() for r in rows], "calls": calls if record_calls else None,
            "candidate": candidate.label, "baseline": baseline.label, "lifecycle": "independent_cold_bundle"}


def match_leg(pair: int, candidate: PolicyFamily, baseline: PolicyFamily, candidate_team: int, *,
              namespace: str, cap: int = DEFAULT_CAP, lifecycle: str = "retained_match_leg",
              deadline_ms: float | None = None) -> dict:
    """One complete match from 0-0, dealer 0; the candidate partnership is `candidate_team`."""
    from .lifecycle import snapshot, snapshot_id

    if lifecycle not in ("retained_match_leg", "cold_reset_per_deal"):
        raise ValueError(lifecycle)
    equity = _equity()
    seed = bundle_seed(namespace, pair)
    fams = {s: candidate if s % 2 == candidate_team else baseline for s in range(4)}
    specs = {s: fams[s].spec(s, seed) for s in range(4)}
    agents = {s: RecordingAgent(specs[s]) for s in range(4)}
    agent_ids = [id(agents[s].agent) for s in range(4)]
    state = new_match((0, 0), 0, match_ref="research-match")
    rows, deals, outcome = [], 0, None
    while not state.terminal and deals < cap:
        if lifecycle == "cold_reset_per_deal" and deals:
            agents = {s: RecordingAgent(specs[s]) for s in range(4)}
        hands = shuffled_deck("deal", namespace, "pair", pair, "deal", deals)
        source, dealer = state.score.as_tuple(), state.dealer
        snaps = tuple(snapshot_id(snapshot(agents[s])) for s in range(4))
        out = play_deal(state, agents, hands, deadline_ms)
        row = transition_row(out, cluster_id=parent_deal_id(namespace, pair), arm=f"leg_cand_team{candidate_team}",
                             rotation=0, assignment=candidate_team, source_score=source, dealer=dealer,
                             policy_ids=[specs[s].spec_id for s in range(4)], snapshot_ids=snaps,
                             lifecycle=lifecycle, candidate_team=candidate_team, equity=equity)
        rows.append(row)
        deals += 1
        if row.failed:
            outcome = "failed"
            break
        state = out.state
    if outcome is None:
        if state.terminal:
            from tuppi_rules import Team

            outcome = "win" if state.score.for_team(Team(candidate_team)) >= 52 else "loss"
        else:
            outcome = "unresolved"
    retained = [id(agents[s].agent) for s in range(4)] == agent_ids
    return {"pair": pair, "candidate_team": candidate_team, "outcome": outcome, "deals": deals, "cap": cap,
            "lifecycle": lifecycle, "agents_retained_whole_leg": retained,
            "calls_per_seat": [len(agents[s].history) for s in range(4)],
            "rows": [r.to_data() for r in rows]}


def match_pair(pair: int, candidate: PolicyFamily, baseline: PolicyFamily, *, namespace: str,
               cap: int = DEFAULT_CAP, lifecycle: str = "retained_match_leg") -> dict:
    """Complementary legs on the same indexed decks and seat seeds, fresh environments."""
    legs = [match_leg(pair, candidate, baseline, t, namespace=namespace, cap=cap, lifecycle=lifecycle)
            for t in (0, 1)]
    return {"pair": pair, "cluster_id": parent_deal_id(namespace, pair), "legs": legs,
            "deck_stream": f"deal|{namespace}|pair|{pair}|deal|<i>", "seat_seed_base": bundle_seed(namespace, pair)}


def historical_order(indices, candidate: PolicyFamily, baseline: PolicyFamily, *, namespace: str,
                     score_law: str = "zero", dealer: int = 0) -> list[dict]:
    """The old evaluator's lifecycle (agents built once, reused for every game): continuity only."""
    equity = _equity()
    seed = bundle_seed(namespace, 0)
    cand = {s: RecordingAgent(candidate.spec(s, seed)) for s in range(4)}
    base = {s: RecordingAgent(baseline.spec(s, seed)) for s in range(4)}
    results = []
    for index in indices:
        deck = shuffled_deck("deal", namespace, index)
        score = draw_score(score_law, namespace, index)
        values = []
        for rotation in range(4):
            hands = tuple(deck[(seat + rotation) % 4] for seat in range(4))
            for assignment in (0, 1):
                agents = {s: cand[s] if s % 2 == assignment else base[s] for s in range(4)}
                out = play_deal(new_match(score, dealer, match_ref="research-hist"), agents, hands)
                row = transition_row(out, cluster_id=parent_deal_id(namespace, index), arm=f"cand_team{assignment}",
                                     rotation=rotation, assignment=assignment, source_score=score, dealer=dealer,
                                     policy_ids=[], snapshot_ids=[], lifecycle="historical_worker_reuse",
                                     candidate_team=assignment, equity=equity)
                values.append(row.candidate_value)
        results.append({"index": index, "values": values, "lifecycle": "historical_worker_reuse"})
    return results
