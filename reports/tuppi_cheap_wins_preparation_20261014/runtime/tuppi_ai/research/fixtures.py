"""Bounded legal fixture builder: F01-F06 (C0.05; FIXTURE_RECIPES.json).

Every fixture state is reached by legal engine transitions from an explicit
deal. Each fixture is written as:

- `fixtures/<id>.json`: policy-facing DecisionCase records (legal observation,
  ordered legal action ids) plus validation results, and
- `fixtures/truth/<id>.truth.json`: evaluator-only OfflineTruth (all original
  hands and the full action history) and evaluator-only extras.

`validate_replay` replays the truth through the engine and requires the
stored observation to be reproduced exactly, so a fixture cannot drift from
the rules. Deal budgets are hard caps (the contract stage allows at most 32
development deals in total); a fixture that cannot be found within its cap is
recorded UNAVAILABLE, never invented.

Contract selection in F02/F05/F06 is scripted (all four seats show their first
legal NOLO card): these are synthetic development states for contract tests,
not a natural population. F03's acceptance is the frozen *heuristic* offer
policy's natural choice (tc_sooli_policy), not the W128 searched offer.
"""

from __future__ import annotations

import ctypes as C
import hashlib
import json
from itertools import combinations
from pathlib import Path

import numpy as np

from .identity import OUTPUT_DIR
from .records import DecisionCase, OfflineTruth, TruthStore, parent_deal_id

FIXTURE_DIR = OUTPUT_DIR / "research" / "fixtures"
TRUTH_DIR = FIXTURE_DIR / "truth"
V3 = "project_target_v3"
BUDGET = {"F01": 3, "F01_alt": 6, "F02": 4, "F03": 1, "F06": 1}  # F04/F05 reuse F03/F02 deals


# ---------------------------------------------------------------- helpers


def card(index: int):
    from tuppi_rules.cards import card_from_index

    return card_from_index(index)


def codes(cards) -> list[str]:
    from tuppi_rules.cards import card_to_code

    return [card_to_code(c) for c in cards]


def deck_digest(hands) -> str:
    return "deck:" + hashlib.sha256(json.dumps([codes(h) for h in hands]).encode()).hexdigest()[:24]


def hands_of(index_lists):
    return tuple(tuple(card(i) for i in sorted(ix)) for ix in index_lists)


def first_where(obs, pred) -> int:
    return next(i for i, a in enumerate(obs.legal_actions) if pred(a))


def is_show(a, contract: str) -> bool:
    return hasattr(a, "declared_contract") and a.declared_contract.value == contract


class RuleAgent:
    """Scripted showing/sooli rules with a fallback agent for everything else."""

    handles_sooli = True

    def __init__(self, seat, fallback, show=None, offer=None, give=None, ret=None, play=None):
        self.seat, self.fallback = seat, fallback
        self.rules = {"SHOWING": show, "SOOLI_OFFER": offer, "SOOLI_GIVE": give, "SOOLI_RETURN": ret,
                      "SOOLI_PLAY": play}

    def choose_action(self, obs):
        rule = self.rules.get(obs.phase.value)
        if rule is not None and len(obs.legal_actions) > 1:
            return obs.legal_actions[rule(obs)]
        return self.fallback.choose_action(obs)


def nolo_first(obs) -> int:
    return first_where(obs, lambda a: is_show(a, "NOLO"))


def rami_first(obs) -> int:
    return first_where(obs, lambda a: is_show(a, "RAMI"))


def walk(hands, agents, *, dealer=0, score=(0, 0), match_ref="research-fixture", stop=None):
    """Plays through legal transitions; returns (state, action history, obs where stop() fired)."""
    from tuppi_engine import (ExplicitDeal, action_to_data, apply_match_action, begin_explicit_deal,
                              match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES

    from .runner_v3 import new_match

    state = begin_explicit_deal(new_match(score, dealer, match_ref), ExplicitDeal(dealer=dealer, hands=hands))
    history = []
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        obs = match_observation_for(state, seat)
        if stop is not None and stop(state, obs):
            return state, history, obs
        action = agents[seat].choose_action(obs)
        history.append(action_to_data(action))
        state = apply_match_action(state, action)
    return state, history, None


def replay(truth: OfflineTruth, upto: int | None = None, match_ref: str = "research-fixture"):
    """Replays truth.action_history[:upto] from the original hands (legal transitions only)."""
    from tuppi_engine import ExplicitDeal, action_from_data, apply_match_action, begin_explicit_deal

    from .runner_v3 import new_match

    hands = tuple(tuple(_card_from_code(c) for c in h) for h in truth.initial_hands)
    state = begin_explicit_deal(new_match(tuple(truth.starting_score), truth.dealer, match_ref),
                                ExplicitDeal(dealer=truth.dealer, hands=hands))
    for a in truth.action_history[:upto]:
        state = apply_match_action(state, action_from_data(a))
    return state


def _card_from_code(code):
    from tuppi_rules.cards import card_from_code

    return card_from_code(code)


def validate_replay(case: DecisionCase, truth: OfflineTruth, upto: int) -> dict:
    """The stored observation equals the engine's own projection after replaying the truth."""
    from tuppi_engine import match_observation_for, observation_to_data

    from .observation import observation_from_data

    state = replay(truth, upto)
    seat = case.observation["observing_seat"]
    fresh = observation_to_data(match_observation_for(state, seat))
    back = observation_from_data(case.observation)
    return {"replay_reproduces_observation": fresh == case.observation,
            "wire_roundtrip": observation_to_data(back) == case.observation,
            "actor_to_move": state.current_actor == seat,
            "ruleset": state.ruleset_id.value}


def make_case(fixture: str, cluster: str, obs, *, population: dict, split: str = "DEV", suffix: str = ""):
    from tuppi_engine import observation_to_data

    from ..bridge import action_id

    return DecisionCase(case_id=f"{fixture}{suffix}", cluster_id=cluster, split=split,
                        observation=observation_to_data(obs),
                        ordered_action_ids=tuple(action_id(a) for a in obs.legal_actions),
                        population=population)


def make_truth(cluster, hands, history, *, dealer=0, score=(0, 0), notes=None) -> OfflineTruth:
    return OfflineTruth(cluster_id=cluster, ruleset=V3, dealer=dealer, starting_score=tuple(score),
                        initial_hands=tuple(tuple(codes(h)) for h in hands), action_history=tuple(history),
                        notes=notes or {})


def write_fixture(fid: str, payload: dict, truth: OfflineTruth | None, extras: dict | None = None) -> Path:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    if truth is not None:
        TruthStore(TRUTH_DIR).put(truth)
        payload["truth_ref"] = str(TruthStore(TRUTH_DIR).path(truth.cluster_id).relative_to(FIXTURE_DIR))
    if extras is not None:
        TRUTH_DIR.mkdir(parents=True, exist_ok=True)
        (TRUTH_DIR / f"{fid}.extras.json").write_text(json.dumps(extras, indent=1, sort_keys=True))
        payload["truth_extras_ref"] = f"truth/{fid}.extras.json"
    path = FIXTURE_DIR / f"{fid}.json"
    path.write_text(json.dumps(payload, indent=1, sort_keys=True))
    return path


def load_fixture(fid: str) -> tuple[dict, list[DecisionCase], OfflineTruth | None]:
    payload = json.loads((FIXTURE_DIR / f"{fid}.json").read_text())
    cases = [DecisionCase.from_data(c) for c in payload.get("cases", [])]
    truth = None
    if payload.get("truth_ref"):
        truth = OfflineTruth.from_data(json.loads((FIXTURE_DIR / payload["truth_ref"]).read_text()))
    return payload, cases, truth


def load_extras(fid: str) -> dict:
    return json.loads((TRUTH_DIR / f"{fid}.extras.json").read_text())


# ---------------------------------------------------------------- F02 / F05


def _nolo_discard_eligible(obs) -> bool:
    if obs.phase.value != "TRICK_PLAY" or obs.contract is None or obs.contract.value != "NOLO":
        return False
    if not obs.current_trick or len(obs.legal_actions) < 2:
        return False
    led = obs.current_trick[0].card.suit
    suits = {a.card.suit for a in obs.legal_actions}
    return led not in suits and len(suits) >= 2


def _unplayed_shown_same_suit(obs) -> bool:
    played = {p.card for t in obs.completed_tricks for p in t.plays} | {p.card for p in obs.current_trick}
    suits = [s.shown_card.suit for s in obs.show_actions if s.shown_card not in played]
    return len(suits) != len(set(suits))


def proxy_variation(obs, worlds: int = 32) -> dict:
    """Samples root worlds with the bound native sampler and checks G varies (V02 precondition)."""
    from .. import native
    from ..bridge import action_id, obs_from_player_observation
    from .c1_control_variate import proxy_matrix
    from .streams import scalar_stream

    tobs = obs_from_player_observation(obs)
    ids = [action_id(a) for a in obs.legal_actions]
    rng = scalar_stream("fixture", "F02", "proxy-check", tobs.n_played)
    layouts = []
    for _ in range(worlds):
        w = native.sample_world(tobs, rng)
        layouts.append([w.hand[s] for s in range(4)])
    g = proxy_matrix(layouts, tobs.seat, ids, 0)
    varying = [j for j in range(len(ids)) if len(set(g[:, j].tolist())) > 1]
    return {"worlds": worlds, "actions": ids, "varying_columns": varying,
            "distinct_rows": len({tuple(r) for r in g.tolist()}), "nonconstant": bool(varying)}


def build_f02_f05() -> dict:
    from tuppi_engine import match_observation_for

    from .clone_policy import CloneGreedyAgent
    from .streams import shuffled_deck

    report = {"deals": []}
    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    agents = {s: RuleAgent(s, clones[s], show=nolo_first) for s in range(4)}
    for attempt in range(BUDGET["F02"]):
        hands = shuffled_deck("fixture", "F02", attempt)
        report["deals"].append(deck_digest(hands))
        final, history, _ = walk(hands, agents)
        # Re-walk, collecting every decision's observation (deterministic agents).
        eligible, f05 = [], None
        state = replay(make_truth("x", hands, history), 0)
        from tuppi_engine import action_from_data, apply_match_action
        for i, a in enumerate(history):
            obs = match_observation_for(state, state.current_actor)
            if _nolo_discard_eligible(obs) and len(obs.completed_tricks) >= 2:
                eligible.append((i, obs))
            if (f05 is None and obs.phase.value == "TRICK_PLAY" and len(obs.completed_tricks) == 10
                    and not obs.current_trick):
                f05 = (i, obs)
            state = apply_match_action(state, action_from_data(a))
        # F02: prefer trick position 1 or 2, where the OTHER seats' capacities differ too.
        ranked = sorted(eligible, key=lambda e: (len(e[1].current_trick) not in (1, 2), e[0]))
        f02 = next(((i, o) for i, o in ranked if proxy_variation(o)["nonconstant"]), None)
        # F02b: a distinct decision with two unplayed shown cards of one suit.
        f02b = next(((i, o) for i, o in eligible if f02 and i != f02[0] and _unplayed_shown_same_suit(o)), None)
        # F02t0: a team-0 actor's discard (sign checks), preferring a solver-only position (<= 6 tricks left).
        team0 = sorted((e for e in eligible if e[1].observing_seat % 2 == 0),
                       key=lambda e: (13 - len(e[1].completed_tricks) > 6, e[0]))
        f02t0 = team0[0] if team0 else None
        if f02 is not None and f02b is not None and f05 is not None:
            cluster = parent_deal_id("fixture-F02", attempt)
            return {"cluster": cluster, "hands": hands, "history": history, "f02": f02, "f02b": f02b,
                    "f02t0": f02t0, "f05": f05, "deals": report["deals"]}
    return {"cluster": None, "deals": report["deals"]}


def capacities(obs) -> list[int]:
    played = [0, 0, 0, 0]
    for t in obs.completed_tricks:
        for p in t.plays:
            played[p.seat] += 1
    for p in obs.current_trick:
        played[p.seat] += 1
    return [13 - x for x in played]


# ---------------------------------------------------------------- C5 support (F05)


def support_worlds(tobs) -> list[list[int]]:
    """Every hard-feasible assignment of the unseen cards at an ordinary trick boundary.

    Independent enumeration (itertools), used to validate F05: capacities from
    play counts, proven voids, unplayed shown cards with their shower.
    """
    me = tobs.seat
    played_by = [0, 0, 0, 0]
    voids = [set(), set(), set(), set()]
    played = 0
    n = tobs.n_played
    for t in range(0, n, 4):
        led = tobs.play_card[t] // 13
        for i in range(t, min(n, t + 4)):
            c, s = tobs.play_card[i], tobs.play_seat[i]
            played_by[s] += 1
            played |= 1 << c
            if c // 13 != led:
                voids[s].add(led)
    known = {s: 0 for s in range(4)}
    for i in range(tobs.n_shows):
        c, s = tobs.show_card[i], tobs.show_seat[i]
        if s != me and not played >> c & 1:
            known[s] |= 1 << c
    full = (1 << 52) - 1
    free = full & ~tobs.hand & ~played & ~(known[0] | known[1] | known[2] | known[3])
    free_cards = [c for c in range(52) if free >> c & 1]
    others = [s for s in range(4) if s != me]
    cap = {s: 13 - played_by[s] - bin(known[s]).count("1") for s in others}
    out = []
    a, b, c3 = others
    for first in combinations(free_cards, cap[a]):
        rest = [x for x in free_cards if x not in first]
        for second in combinations(rest, cap[b]):
            third = [x for x in rest if x not in second]
            hand = {a: first, b: second, c3: tuple(third)}
            if any(x // 13 in voids[s] for s in others for x in hand[s]):
                continue
            masks = [0, 0, 0, 0]
            masks[me] = tobs.hand
            for s in others:
                masks[s] = known[s] | sum(1 << x for x in hand[s])
            out.append(masks)
    return out


# ---------------------------------------------------------------- F06


def f06_rules_checks() -> dict:
    """Pure rules-object score fixture (derived arithmetic expectations)."""
    from tuppi_rules import Contract, DealScore, MatchScore, Team, transition_rising_score

    from ..best import EQUITY
    from ..equity import Equity

    eq = Equity.load(EQUITY)
    rows = []

    def nolo(t0):
        w = Team.TEAM_0 if t0 < 13 - t0 else Team.TEAM_1
        return DealScore(Contract.NOLO, w, 4 * (7 - (t0 if w is Team.TEAM_0 else 13 - t0)), (t0, 13 - t0), None, False)

    def rami(t0, declarer_team):
        dt = declarer_team
        dtr = t0 if dt is Team.TEAM_0 else 13 - t0
        if dtr >= 7:
            return DealScore(Contract.RAMI, dt, 4 * (dtr - 6), (t0, 13 - t0), dt, False)
        other = Team(1 - dt.value)
        return DealScore(Contract.RAMI, other, 8 * ((13 - dtr) - 6), (t0, 13 - t0), dt, True)

    cases = []
    for up_team in (Team.TEAM_0, Team.TEAM_1):
        start = MatchScore(48, 0) if up_team is Team.TEAM_0 else MatchScore(0, 48)
        for label, ds in [(f"NOLO t0={t}", nolo(t)) for t in (0, 3, 5, 6, 7, 10)] + \
                         [(f"RAMI dt={d} t0={t}", rami(t, Team(d))) for d in (0, 1) for t in (2, 5, 7, 8, 13)]:
            cases.append((start, label, ds))
    for start in (MatchScore(0, 0),):  # awards from 0-0 ("zero-score" starts)
        for label, ds in [("NOLO t0=5", nolo(5)), ("NOLO t0=8", nolo(8)), ("RAMI dt=0 t0=9", rami(9, Team.TEAM_0)),
                          ("RAMI stolen dt=0 t0=3", rami(3, Team.TEAM_0))]:
            cases.append((start, label, ds))
    ok = True
    for start, label, ds in cases:
        after = transition_rising_score(start, ds)
        up = start.up_team
        if up is None:
            expect = (ds.points, 0) if ds.winner_team is Team.TEAM_0 else (0, ds.points)
        elif ds.winner_team is up:
            expect = (start.team0 + ds.points, 0) if up is Team.TEAM_0 else (0, start.team1 + ds.points)
        else:
            expect = (0, 0)
        terminal = max(after.as_tuple()) >= 52
        v0 = eq.team0(*after.as_tuple(), dealer=1)
        derived_ok = after.as_tuple() == expect
        if up is not None and ds.winner_team is up:
            derived_ok &= terminal and v0 == (1.0 if up is Team.TEAM_0 else 0.0)
        if up is not None and ds.winner_team is not up:
            derived_ok &= after.as_tuple() == (0, 0)
        ok &= derived_ok
        rows.append({"start": start.as_tuple(), "deal": label, "winner": ds.winner_team.value, "points": ds.points,
                     "after": after.as_tuple(), "terminal": terminal, "overshoot": max(after.as_tuple()) > 52,
                     "team0_equity_after": v0, "matches_derived_expectation": derived_ok})
    return {"all_match": ok, "rows": rows,
            "interpretation": "DealScore points are always positive, so 'zero-score award' is read as an award "
                              "from 0-0; overshoot = a terminal score above 52"}


def enumerate_final_tricks(deal) -> set[int]:
    """All reachable final team-0 trick totals from a native ordinary deal (exhaustive)."""
    from .. import native

    out = set()

    def rec(d):
        if d.phase == native.PH_DONE:
            out.add(int(d.team_tricks[0]))
            return
        for a in native.legal(d):
            c = native.TcDeal()
            C.pointer(c)[0] = d
            if native.lib.tc_apply(C.byref(c), a) != 0:
                raise RuntimeError("illegal enumerated action")
            rec(c)

    rec(deal)
    return out


def native_deal_after(hands, history, *, dealer=0, score=(0, 0), ruleset=3):
    from .. import native
    from ..bridge import action_id, mask_of
    from tuppi_engine import action_from_data

    d = native.new_deal([mask_of(h) for h in hands], dealer, score[0], score[1], ruleset=ruleset)
    for a in history:
        if native.lib.tc_apply(C.byref(d), action_id(action_from_data(a))) != 0:
            raise RuntimeError("history is illegal in the native core")
    return d


def build_f06_rollout(hands) -> dict:
    """Late positions at 48-0 whose reachable final results show (a) several margins with one
    winner and (b) an uncertain winner, both by exhaustive enumeration."""
    from .clone_policy import CloneGreedyAgent

    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    agents = {s: RuleAgent(s, clones[s], show=nolo_first) for s in range(4)}
    final, history, _ = walk(hands, agents, score=(48, 0), match_ref="research-fixture-f06")
    found = {}
    shows = 4
    for i in range(shows + 36, len(history)):  # positions with at most 3 tricks left (>= 36 plays)
        d = native_deal_after(hands, history[:i], score=(48, 0))
        totals = enumerate_final_tricks(d)
        winners = {0 if t < 13 - t else 1 for t in totals}
        if len(winners) == 1 and len(totals) >= 2 and "same_winner_margins" not in found:
            found["same_winner_margins"] = {"history_len": i, "final_team0_tricks": sorted(totals),
                                            "winner": winners.pop()}
        elif len(winners) == 2 and "uncertain_winner" not in found:
            found["uncertain_winner"] = {"history_len": i, "final_team0_tricks": sorted(totals)}
    return {"history": history, "positions": found, "complete": len(found) == 2}


# ---------------------------------------------------------------- F03 / F04


def f03_hands():
    """A constructed v3 deal: seat 1 declares RAMI, seat 2 has a very low sooli hand with K of hearts."""
    H, D, Cl, S = 0, 13, 26, 39
    seat2 = [H + 12, H + 0, H + 1, H + 11, D + 12, D + 0, D + 1, Cl + 12, Cl + 0, Cl + 1, S + 12, S + 0, S + 1]
    seat1 = [H + 10, H + 9, H + 8, H + 7, H + 6, D + 11, D + 10, D + 9, D + 8, D + 7, S + 11, S + 10, S + 9]
    seat0 = [Cl + r for r in range(2, 12)] + [H + 2, H + 3, H + 4]
    seat3 = [H + 5] + [D + r for r in range(2, 7)] + [S + r for r in range(2, 9)]
    hands = hands_of([seat0, seat1, seat2, seat3])
    assert sorted(i for ix in (seat0, seat1, seat2, seat3) for i in ix) == list(range(52))
    return hands


def sooli_give_values(hands, history_to_give, gives) -> dict:
    """Evaluator-only: perfect-information survival after each give (heuristic return)."""
    from .. import native

    out = {}
    base = native_deal_after(hands, history_to_give)
    for g in gives:
        d = native.TcDeal()
        C.pointer(d)[0] = base
        if native.lib.tc_apply(C.byref(d), native.ACT_EXCHANGE + g) != 0:
            raise RuntimeError("illegal give")
        obs = native.observe(d, d.cur)
        r = native.sooli_policy(obs, C.c_uint64(1))
        if native.lib.tc_apply(C.byref(d), r) != 0:
            raise RuntimeError("illegal return")
        out[g] = {"returned": r - native.ACT_EXCHANGE, "pi_survives": native.sooli_solve(d)}
    return out


# ---------------------------------------------------------------- build all


def build_all() -> dict:
    from tuppi_engine import match_observation_for, observation_to_data

    from ..bridge import action_id, obs_from_player_observation
    from .clone_policy import CloneGreedyAgent
    from .ledger import count
    from .streams import shuffled_deck

    summary = {}
    all_deals = []

    # ---- F02 (+ F02b companion) and F05 from one scripted-NOLO clone deal
    built = build_f02_f05()
    all_deals += built["deals"]
    if built["cluster"] is None:
        summary["F02"] = write_fixture("F02", {"fixture_id": "F02", "status": "UNAVAILABLE",
                                               "deals_tried": built["deals"]}, None)
    else:
        hands, history, cluster = built["hands"], built["history"], built["cluster"]
        truth = make_truth(cluster, hands, history, notes={"contract_selection": "scripted: first legal NOLO show",
                                                           "play_policy": "clone greedy, native_id tie order"})
        pop = {"population": "synthetic development state (scripted NOLO contract, clone play)",
               "natural": False}
        cases, checks = [], {}
        for key, suffix in (("f02", ""), ("f02b", "b"), ("f02t0", "t0")):
            if built[key] is None:
                continue
            i, obs = built[key]
            case = make_case("F02", cluster, obs, population=pop, suffix=suffix)
            cases.append(case)
            chk = validate_replay(case, truth, i)
            chk.update({"history_index": i, "capacities": capacities(obs), "seat": obs.observing_seat,
                        "tricks_left": 13 - len(obs.completed_tricks),
                        "unequal_capacities": len(set(capacities(obs))) > 1,
                        "legal_discard_suits": sorted({a.card.suit.value for a in obs.legal_actions}),
                        "actor_void_in_led_suit": _nolo_discard_eligible(obs),
                        "unplayed_shown_same_suit": _unplayed_shown_same_suit(obs),
                        "proxy": proxy_variation(obs)})
            checks[case.case_id] = chk
        ok = all(c["replay_reproduces_observation"] and c["wire_roundtrip"] and c["unequal_capacities"]
                 and c["actor_void_in_led_suit"] for c in checks.values())
        ok &= checks["F02"]["proxy"]["nonconstant"] and checks["F02b"]["unplayed_shown_same_suit"]
        summary["F02"] = write_fixture("F02", {"fixture_id": "F02", "status": "VALIDATED" if ok else "FAILED",
                                               "cases": [c.to_data() for c in cases], "checks": checks,
                                               "deals_generated": built["deals"]}, truth)
        # ---- F05 from the same deal
        i, obs = built["f05"]
        tobs = obs_from_player_observation(obs)
        worlds = support_worlds(tobs)
        later = _later_choice(tobs, worlds, [action_id(a) for a in obs.legal_actions])
        case = make_case("F05", cluster, obs, population=pop)
        chk = validate_replay(case, truth, i)
        chk.update({"history_index": i, "cards_each": [len(obs.own_hand)] + [3] * 3,
                    "complete_support": len(worlds), "support_upper_bound_unconstrained": 1680,
                    "root_legal": len(obs.legal_actions), "later_non_forced_choice": later})
        ok = (chk["replay_reproduces_observation"] and chk["wire_roundtrip"] and len(worlds) >= 2
              and len(obs.legal_actions) >= 2 and later["exists"] and len(obs.own_hand) == 3
              and chk["ruleset"] == V3)
        summary["F05"] = write_fixture("F05", {"fixture_id": "F05", "status": "VALIDATED" if ok else "FAILED",
                                               "cases": [case.to_data()], "checks": {"F05": chk},
                                               "deals_generated": []}, truth,
                                       extras={"support_worlds": worlds})

    # ---- F01 blind bid
    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    focal_pos, dealer = 2, 0
    focal = (dealer + 1 + focal_pos) % 4
    f01 = None
    for attempt in range(BUDGET["F01"]):
        hands = shuffled_deck("fixture", "F01", attempt)
        all_deals.append(deck_digest(hands))
        _state, history, obs = walk(hands, clones, stop=lambda st, o: st.current_actor == focal)
        if obs is not None and obs.phase.value == "SHOWING":
            f01 = (attempt, hands, history, obs)
            break
    if f01 is None:
        summary["F01"] = write_fixture("F01", {"fixture_id": "F01", "status": "UNAVAILABLE"}, None)
    else:
        attempt, hands, history, obs = f01
        cluster = parent_deal_id("fixture-F01", attempt)
        truth = make_truth(cluster, hands, history, notes={"bids": "clone greedy (native_id); actual commits "
                                                                   "are the recorded history"})
        case = make_case("F01", cluster, obs, population={"population": "clone predecessors, reached focal call"})
        fore_state = replay(truth, 0)
        fore = make_case("F01", cluster, match_observation_for(fore_state, (dealer + 1) % 4),
                         population={"population": "forehand control (E = 1)"}, suffix="-forehand")
        chk = validate_replay(case, truth, len(history))
        chk.update({"visible_shows": len(obs.show_actions), "bids_locked": obs.bids_locked,
                    "own_cards": len(obs.own_hand), "legal_declarations": len(obs.legal_actions),
                    "forehand_bids_locked": fore.observation.get("bids_locked")})
        alt = _f01_alternative(hands, focal, observation_to_data(obs), all_deals)
        chk["alternative"] = {k: v for k, v in alt.items() if k != "hands"}
        ok = (chk["replay_reproduces_observation"] and chk["wire_roundtrip"] and chk["visible_shows"] == 0
              and chk["bids_locked"] == focal_pos and chk["own_cards"] == 13 and chk["legal_declarations"] >= 2
              and alt.get("found", False) and alt.get("focal_observation_identical", False)
              and chk["forehand_bids_locked"] == 0)
        summary["F01"] = write_fixture("F01", {"fixture_id": "F01", "status": "VALIDATED" if ok else "FAILED",
                                               "cases": [case.to_data(), fore.to_data()], "checks": {"F01": chk},
                                               "deals_generated": [deck_digest(hands)]}, truth,
                                       extras={"alternative_layout": alt})

    # ---- F03 / F04 constructed sooli deal
    hands = f03_hands()
    all_deals.append(deck_digest(hands))
    sooli = {s: RuleAgent(s, clones[s], show=rami_first if s == 1 else None) for s in range(4)}
    _st, history, obs3 = walk(hands, sooli, stop=lambda st, o: o.phase.value == "SOOLI_GIVE")
    cluster = parent_deal_id("fixture-F03", 0)
    truth = make_truth(cluster, hands, history, notes={"offer_policy": "tc_sooli_policy heuristic (natural choice)",
                                                       "bids": "seat 1 first legal RAMI show"})
    if obs3 is None:
        summary["F03"] = write_fixture("F03", {"fixture_id": "F03", "status": "UNAVAILABLE",
                                               "reason": "the heuristic offer policy declined both offers"}, truth)
    else:
        case3 = make_case("F03", cluster, obs3, population={"population": "accepted by the frozen heuristic offer "
                                                                          "policy on a constructed deal",
                                                            "accepted_offers": 1, "rejected_offers":
                                                                sum(1 for a in history if a.get("type") ==
                                                                    "sooli_decision" and not a["play_sooli"])})
        gives = [a.card for a in obs3.legal_actions]
        from tuppi_rules.cards import card_to_index
        gv = sooli_give_values(hands, history, [card_to_index(c) for c in gives])
        survive = sorted({v["pi_survives"] for v in gv.values()})
        chk3 = validate_replay(case3, truth, len(history))
        chk3.update({"own_cards": len(obs3.own_hand), "legal_gives": len(obs3.legal_actions),
                     "give_survival_values_differ": len(survive) > 1, "survival_values": survive})
        # F04: branch on the give that keeps the soolaaja alive, stop before the return.
        g = next(k for k, v in gv.items() if v["pi_survives"] == 1) if 1 in survive else card_to_index(gives[0])
        from tuppi_engine import action_to_data
        from tuppi_engine import SooliExchangeAction
        give_action = action_to_data(SooliExchangeAction(seat=obs3.observing_seat, card=card(g)))
        state4 = replay(truth, len(history))
        from tuppi_engine import action_from_data, apply_match_action
        state4 = apply_match_action(state4, action_from_data(give_action))
        partner = (obs3.observing_seat + 2) % 4
        obs4 = match_observation_for(state4, partner)
        truth4 = make_truth(cluster, hands, history + [give_action], notes=truth.notes)
        case4 = make_case("F04", cluster, obs4, population={"population": "F03 branched on a specified give"})
        chk4 = validate_replay(case4, truth4, len(history) + 1)
        defenders = [s for s in range(4) if s not in (obs3.observing_seat, partner)]
        d_obs = [match_observation_for(state4, s) for s in defenders]
        chk4.update({"partner_cards": len(obs4.own_hand), "legal_returns": len(obs4.legal_actions),
                     "given_card_visible": obs4.sooli_given_card == card(g),
                     "returns_exclude_given": all(a.card != card(g) for a in obs4.legal_actions),
                     "returned_card_unavailable": obs4.sooli_returned_card is None,
                     "defenders_see_no_exchange": all(o.sooli_given_card is None and o.sooli_returned_card is None
                                                      for o in d_obs)})
        # after a (heuristic) return: 13/13, 39 active, 13 dead
        state5 = apply_match_action(state4, clones[partner].choose_action(obs4))
        o5 = [match_observation_for(state5, s) for s in range(4)]
        chk4["after_return"] = {"hand_sizes": [len(o.own_hand) for o in o5],
                                "phase": state5.phase.value,
                                "defenders_see_no_exchange": all(o5[s].sooli_given_card is None
                                                                 and o5[s].sooli_returned_card is None
                                                                 for s in defenders),
                                "partner_is_dead": state5.current_actor != partner}
        ok3 = (chk3["replay_reproduces_observation"] and chk3["wire_roundtrip"] and chk3["own_cards"] == 13
               and chk3["legal_gives"] == 13 and chk3["give_survival_values_differ"])
        ok4 = (chk4["replay_reproduces_observation"] and chk4["wire_roundtrip"] and chk4["partner_cards"] == 14
               and chk4["legal_returns"] == 13 and chk4["given_card_visible"] and chk4["returns_exclude_given"]
               and chk4["returned_card_unavailable"] and chk4["defenders_see_no_exchange"]
               and chk4["after_return"]["hand_sizes"] == [13, 13, 13, 13]
               and chk4["after_return"]["defenders_see_no_exchange"] and chk4["after_return"]["partner_is_dead"])
        summary["F03"] = write_fixture("F03", {"fixture_id": "F03", "status": "VALIDATED" if ok3 else "FAILED",
                                               "cases": [case3.to_data()], "checks": {"F03": chk3},
                                               "deals_generated": [deck_digest(hands)]}, truth,
                                       extras={"give_values": {str(k): v for k, v in gv.items()}})
        summary["F04"] = write_fixture("F04", {"fixture_id": "F04", "status": "VALIDATED" if ok4 else "FAILED",
                                               "cases": [case4.to_data()], "checks": {"F04": chk4},
                                               "given_card_index": g, "deals_generated": []}, None)
        (TRUTH_DIR / "F04.truth.json").write_text(json.dumps(truth4.to_data(), indent=1, sort_keys=True))

    # ---- F06 rules + rollout companion (one new deal: F02's hands started at 48-0)
    rules = f06_rules_checks()
    rollout = {"complete": False, "reason": "F02 deal unavailable"}
    if built["cluster"] is not None:
        rollout = build_f06_rollout(built["hands"])
        all_deals.append(deck_digest(built["hands"]) + "@48-0")
    ok6 = rules["all_match"] and rollout.get("complete", False)
    truth6 = make_truth(parent_deal_id("fixture-F06", 0), built["hands"], rollout.get("history", []),
                        score=(48, 0)) if built["cluster"] is not None else None
    summary["F06"] = write_fixture("F06", {"fixture_id": "F06", "status": "VALIDATED" if ok6 else "FAILED",
                                           "rules": rules, "rollout_positions": rollout.get("positions"),
                                           "rollout_complete": rollout.get("complete", False)}, truth6)

    count(fixture_deal_ids=sorted(set(all_deals)))
    manifest = {"schema": "tuppi.research.fixtures.v1", "fixtures": {}, "deal_ids": sorted(set(all_deals)),
                "deal_count": len(set(all_deals))}
    for fid in ("F01", "F02", "F03", "F04", "F05", "F06"):
        payload = json.loads((FIXTURE_DIR / f"{fid}.json").read_text())
        manifest["fixtures"][fid] = {"status": payload["status"],
                                     "sha256": hashlib.sha256((FIXTURE_DIR / f"{fid}.json").read_bytes()).hexdigest()}
    (FIXTURE_DIR / "fixtures_manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def _f01_alternative(hands, focal: int, focal_obs_data: dict, all_deals: list) -> dict:
    """A hypothetical layout keeping the focal hand where a clone predecessor bids RAMI (E = 0)."""
    from tuppi_engine import match_observation_for, observation_to_data

    from .clone_policy import CloneGreedyAgent
    from .streams import python_stream

    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    others = [c for s in range(4) if s != focal for c in hands[s]]
    for j in range(BUDGET["F01_alt"]):
        cards = list(others)
        python_stream("fixture", "F01", "alternative", j).shuffle(cards)
        seats = [s for s in range(4) if s != focal]
        alt = [None] * 4
        alt[focal] = hands[focal]
        for k, s in enumerate(seats):
            alt[s] = tuple(sorted(cards[13 * k:13 * (k + 1)], key=lambda c: (c.suit.value, c.rank.value)))
        alt = tuple(alt)
        all_deals.append(deck_digest(alt))
        # predecessors' own masked precommit decisions, in reveal order
        truth = make_truth("alt", alt, [])
        state = replay(truth, 0)
        predecessor_bids = []
        event = True
        from tuppi_engine import action_to_data, apply_match_action
        while state.current_actor != focal:
            seat = state.current_actor
            o = match_observation_for(state, seat)
            a = clones[seat].choose_action(o)
            predecessor_bids.append({"seat": seat, "bid": action_to_data(a)})
            if a.declared_contract.value == "RAMI":
                event = False
                break
            state = apply_match_action(state, a)
        if event:
            continue
        # the focal observation in this layout, reached by placeholder NOLO commitments
        state = replay(truth, 0)
        while state.current_actor != focal:
            o = match_observation_for(state, state.current_actor)
            state = apply_match_action(state, o.legal_actions[nolo_first(o)])
        alt_obs = observation_to_data(match_observation_for(state, focal))
        return {"found": True, "attempt": j, "hands": [codes(h) for h in alt], "predecessor_bids": predecessor_bids,
                "event_all_earlier_nolo": False, "focal_observation_identical": alt_obs == focal_obs_data}
    return {"found": False, "attempts": BUDGET["F01_alt"]}


def _later_choice(tobs, worlds, root_actions) -> dict:
    """Does some support world and root action give the root a non-forced later choice?

    Other seats play the clone (native_id ties) from their own observations.
    """
    from .. import native
    from .clone_policy import clone_scores, preferred, rollout_network

    net = rollout_network()
    mlp = native.Mlp(net)
    for wi, masks in enumerate(worlds):
        base = native.TcDeal()
        from .native_api import native_module  # noqa: F401
        d0 = _deal_from_obs(tobs, masks)
        for a in root_actions:
            d = native.TcDeal()
            C.pointer(d)[0] = d0
            native.lib.tc_apply(C.byref(d), a)
            while d.phase != native.PH_DONE and d.cur != tobs.seat:
                o = native.observe(d, d.cur)
                ids = native.legal(d)
                native.lib.tc_apply(C.byref(d), ids[preferred(ids, clone_scores(o, mlp, net.encoder), "native_id")])
            if d.phase != native.PH_DONE and len(native.legal(d)) >= 2:
                return {"exists": True, "world_index": wi, "first_action": a, "legal_later": len(native.legal(d))}
    return {"exists": False}


def _deal_from_obs(tobs, masks):
    """A full native deal from a root observation and one support layout."""
    from .. import native

    d = native.TcDeal()
    sample = native.sample_world(tobs, C.c_uint64(12345))  # public fields filled by the sampler
    C.pointer(d)[0] = sample
    for s in range(4):
        d.hand[s] = masks[s]
    return d


if __name__ == "__main__":
    print(json.dumps(build_all(), indent=1))
