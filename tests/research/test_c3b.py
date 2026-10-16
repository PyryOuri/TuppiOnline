"""C3b contract tests K01-K04: conservative utility-equivalence stopping."""

from __future__ import annotations

import ctypes as C

import numpy as np
import pytest

from tuppi_ai.research import c3_utility_stop as c3
from tuppi_ai.research.ledger import count
from tuppi_ai.research.native_api import OPT_UTILITY_STOP, RS_CERTIFIED, RS_DOUBLE, RS_RECORDED, row_utility, \
    utility_certificate
from tuppi_ai.research.testing import fixture_case, tobs_of

SCORES = [(0, 0)] + [(4 * lv, 0) for lv in range(1, 13)] + [(0, 4 * lv) for lv in range(1, 13)]


@pytest.fixture(scope="module")
def equity():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity

    return Equity.load(EQUITY)


def _deal(nat, score, dealer, contract, declarer, t0=0, played=0):
    d = nat.TcDeal()
    d.phase, d.trick_size, d.soolaaja, d.ruleset = 1, 4, -1, 3
    d.score[0], d.score[1] = score
    d.dealer, d.contract, d.declarer = dealer, contract, declarer
    d.team_tricks[0], d.team_tricks[1] = t0, played // 4 - t0
    d.n_played = played
    return d


def trajectory_deals(hands, history, dealer=0, score=(0, 0)):
    """Every native state along a legal fixture trajectory (ordinary play only)."""
    from tuppi_ai.research.fixtures import native_deal_after

    for i in range(len(history) + 1):
        d = native_deal_after(hands, history[:i], dealer=dealer, score=score)
        if d.phase == 1 and d.trick_size == 4:
            yield i, d


def test_K02_native_row_utility_equals_the_authoritative_rules_for_every_state(research, nat, search_env, equity):
    n = 0
    for score in SCORES:
        for dealer in range(4):
            for contract, declarer in [(0, -1)] + [(1, s) for s in range(4)]:
                for t0 in range(14):
                    d = _deal(nat, score, dealer, contract, declarer)
                    got = row_utility(research, search_env, d, t0)
                    want = c3.deal_utility(score, dealer, contract, None if contract == 0 else declarer, t0, equity)
                    assert got == want, (score, dealer, contract, declarer, t0)
                    n += 1
    assert n == 25 * 4 * 5 * 14


def test_K01_K02_native_certificate_equals_the_oracle_over_the_whole_state_grid(research, nat, search_env, equity):
    certified = uncertain_at_48 = 0
    for score in SCORES:
        for dealer in range(4):
            for contract, declarer in [(0, -1)] + [(1, s) for s in range(4)]:
                for completed in range(0, 13):
                    for t0 in range(completed + 1):
                        for partial in (0, 2):  # trick boundary and mid-trick (the superset is unchanged)
                            d = _deal(nat, score, dealer, contract, declarer, t0, 4 * completed + partial)
                            got = utility_certificate(research, search_env, d)
                            want = c3.certificate(score, dealer, contract, None if contract == 0 else declarer,
                                                  t0, completed, equity)
                            assert (got is None) == (want is None), (score, dealer, contract, declarer, completed, t0)
                            if want is not None:
                                assert got == want.value
                                certified += 1
                            elif 48 in score:
                                uncertain_at_48 += 1
    assert certified > 0 and uncertain_at_48 > 0


def test_K01_superset_contains_every_reachable_final_total_both_contracts_and_declarer_teams(research, nat, equity):
    """Exhaustive continuation from late legal states of NOLO and of RAMI with each declarer team."""
    from tuppi_ai.research.fixtures import _card_from_code, enumerate_final_tricks, load_fixture

    _p, _c, t02 = load_fixture("F02")
    hands02 = tuple(tuple(_card_from_code(c) for c in h) for h in t02.initial_hands)
    samples = list(trajectory_deals(hands02, list(t02.action_history)))
    rami = _rami_trajectories()
    checked = {"NOLO": 0, "RAMI-declarer-team0": 0, "RAMI-declarer-team1": 0}
    for label, deals in [("NOLO", samples)] + rami:
        for i, d in deals:
            done = d.n_played // 4
            if 13 - done > 3:
                continue  # exhaustive enumeration only for small suffixes
            reach = enumerate_final_tricks(d)
            assert reach <= set(c3.feasible_totals(d.team_tricks[0], done)), (label, i)
            cert = c3.certificate_of_deal(d, equity)
            if cert is not None:  # sound against every actual continuation
                assert c3.reachable_utilities(d, equity) == {cert.value}
            checked[label] += 1
    assert all(v > 0 for v in checked.values()), checked


def _rami_trajectories():
    """F03's deck: ordinary RAMI after two declines with the declarer on team 1 (dealer 0) and team 0 (dealer 1)."""
    from tuppi_engine import action_to_data

    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent, f03_hands, rami_first, walk

    hands = f03_hands()
    decline = lambda ob: next(i for i, a in enumerate(ob.legal_actions) if not a.play_sooli)  # noqa: E731
    out = []
    for dealer, label in ((0, "RAMI-declarer-team1"), (1, "RAMI-declarer-team0")):
        declarer = (dealer + 1) % 4
        agents = {s: RuleAgent(s, CloneGreedyAgent(s), show=rami_first if s == declarer else None, offer=decline)
                  for s in range(4)}
        state, history, _ = walk(hands, agents, dealer=dealer)
        r = state.completed_deals[-1].public_result
        assert r.contract.value == "RAMI" and r.declarer % 2 == int(label[-1])
        out.append((label, list(trajectory_deals(hands, history, dealer=dealer))))
    return out


def test_K03_score48_with_an_uncertain_winner_is_not_stopped(research, nat, search_env, equity):
    from tuppi_ai.research.fixtures import _card_from_code, load_fixture, native_deal_after

    payload, _c, truth = load_fixture("F06")
    hands = tuple(tuple(_card_from_code(c) for c in h) for h in truth.initial_hands)
    positions = payload["rollout_positions"]
    unc = native_deal_after(hands, list(truth.action_history)[:positions["uncertain_winner"]["history_len"]],
                            score=(48, 0))
    assert (unc.score[0], unc.score[1]) == (48, 0)
    from tuppi_ai.research.fixtures import enumerate_final_tricks
    assert len({0 if t < 13 - t else 1 for t in enumerate_final_tricks(unc)}) == 2  # both winners reachable
    assert utility_certificate(research, search_env, unc) is None and c3.certificate_of_deal(unc, equity) is None
    same = native_deal_after(hands, list(truth.action_history)[:positions["same_winner_margins"]["history_len"]],
                             score=(48, 0))
    reach = c3.reachable_utilities(same, equity)
    assert len(reach) == 1  # several margins, one winner (a reset at 48-0): one utility
    cert = utility_certificate(research, search_env, same)
    if cert is not None:
        assert {cert} == reach
    # at 48-0 the SAME position with both winners possible must never certify, whatever the dealer
    for dealer in range(4):
        d = _deal(nat, (48, 0), dealer, 0, -1, t0=5, played=40)  # t0 in 5..8 crosses the 6/7 boundary
        assert utility_certificate(research, search_env, d) is None
    # existing sooli shortcuts are not relabelled: no certificate in any sooli phase
    for phase in (3, 4, 5, 6):
        d = _deal(nat, (48, 0), 0, 1, 1)
        d.phase, d.soolaaja = phase, 2
        assert utility_certificate(research, search_env, d) is None


def _score_variant(obs, score):
    o = type(obs)()
    C.pointer(o)[0] = obs
    o.score[0], o.score[1] = score
    return o


def test_K02_K04_evaluator_stops_rows_exactly_once_without_fabricating_and_other_rows_are_unchanged(
        research, nat, mlp, search_env):
    """At 0-48 with a 2-trick solver tail, NOLO rows certify mid-rollout while others keep using the network."""
    case, _t = fixture_case("F02", 1)
    obs = _score_variant(tobs_of(case), (0, 48))
    ids = list(case.ordered_action_ids)
    worlds = research.sample_worlds(search_env, obs, 32, C.c_uint64(4848))
    count(probe_ids=["F02b-score0-48-dd2", "F02b-score0-48-dd6"])
    off = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 2)
    on = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 2, options=OPT_UTILITY_STOP)
    cert = (on.row_status & RS_CERTIFIED) != 0
    assert cert.any() and not cert.all()
    assert on.work["certified_rows"] == int(cert.sum())
    assert on.work["mlp_rows"] < off.work["mlp_rows"] and on.work["dd_solves"] <= off.work["dd_solves"]
    assert ((on.row_status & RS_RECORDED) != 0).all() and not ((on.row_status & RS_DOUBLE) != 0).any()
    # certified values are the exact utilities, and NO other row changed (batching effect check)
    assert np.array_equal(on.per_world, off.per_world)
    # the certified slots were left unfinished: no winner, no final tricks manufactured
    k = len(ids)
    for wi, ai in zip(*np.nonzero(cert)):
        slot = nat.lib.tc_env_deal(search_env._h, int(wi) * k + int(ai)).contents
        assert slot.phase == 1 and slot.winner_team == -1
    # the as-is configuration (6-trick tail): same values, and the certification rate is recorded
    off6 = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 6)
    on6 = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 6, options=OPT_UTILITY_STOP)
    assert np.array_equal(on6.per_world, off6.per_world)
    assert on6.work["dd_solves"] + on6.work["certified_rows"] >= off6.work["dd_solves"]


def test_K04_disabled_switch_is_the_original_computation(research, mlp, search_env, f02b):
    obs = tobs_of(f02b[0])
    ids = list(f02b[0].ordered_action_ids)
    rng1, rng2 = C.c_uint64(515), C.c_uint64(515)
    a, _w = research.trace_search(search_env, mlp, obs, ids, 32, 6, rng1)
    b, _w = research.trace_search(search_env, mlp, obs, ids, 32, 6, rng2, options=0)
    assert np.array_equal(a.per_world, b.per_world) and rng1.value == rng2.value and b.work["certified_rows"] == 0
