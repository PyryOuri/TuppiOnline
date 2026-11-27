"""Complete matches and match-weighted scores (tuppi_train/matches.py)."""

from __future__ import annotations

import ctypes as C

import numpy as np
import pytest

from tuppi_train import lockstep, matches, tn
from tuppi_ai import native

lib = tn.lib


def test_next_scores_is_the_engines():
    rng, after = np.random.default_rng(0), (C.c_uint8 * 2)()
    for _ in range(3000):
        lead = int(rng.integers(0, 13)) * 4
        s = (lead, 0) if rng.random() < 0.5 else (0, lead)
        w, pts = int(rng.integers(0, 2)), int(rng.integers(1, 14)) * 4
        lib.tc_next_score((C.c_uint8 * 2)(*s), w, pts, after)
        mine = matches.next_scores(np.uint8([s]), np.array([w]), np.array([pts]))[0]
        assert (int(mine[0]), int(mine[1])) == (after[0], after[1])


def test_games_from_seeds(make_env):
    """tc_ls_begin_games: the deal depends on the game's seed alone; score and dealer are as given."""
    env, n = make_env(6), 6
    scores = np.uint8([[0, 0], [8, 0], [0, 44], [8, 0], [0, 0], [12, 0]])
    dealers = np.uint8([0, 1, 2, 3, 1, 1])
    seeds = np.uint64([5, 7, 9, 7, 5, 11])
    assert lib.tc_ls_begin_games(env._h, n, 3, scores.ctypes.data, dealers.ctypes.data, seeds.ctypes.data) == 0
    state = np.zeros(n, np.dtype(native.TcDeal))
    games = np.arange(n, dtype=np.int32)
    lib.tc_ls_copy_states(env._h, games.ctypes.data, n, state.ctypes.data)
    assert np.array_equal(state["score"], scores) and np.array_equal(state["dealer"], dealers)
    assert np.array_equal(state["hand"][1], state["hand"][3]) and np.array_equal(state["hand"][0], state["hand"][4])
    assert not np.array_equal(state["hand"][0], state["hand"][1])
    for hands in state["hand"]:
        assert sum(bin(int(h)).count("1") for h in hands) == 52 and int(np.bitwise_or.reduce(hands)) == 2**52 - 1


def test_matches(table, net1, make_env):
    """A network against itself splits every mirrored pair 1-1; against random play it wins them
    all; the equity changes of a match's deals sum to its result minus the starting equity."""
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    eq = Equity.load(EQUITY)
    env = make_env(64)
    env.set_sooli(0, False, True, 0.0)
    native.set_offer_model(None)
    a = lockstep.TorchGreedy(net1, "cpu", 2)
    r = matches.play_matches(env, a, a, 12, 6)
    assert (r["a_wins"] == 1).all() and matches.win_rate(r["a_wins"]) == [0.5, 0.0]
    assert r["deals"].min() >= 2 and 15 < r["deals"].mean() < 80 and r["visits"].sum() == pytest.approx(r["deals"].mean())
    assert r["visits"][0] > r["visits"][1:].max()
    start = np.array([eq.team0(0, 0, int(d)) for d in r["first_dealer"]])
    assert np.abs(r["team0_total"] - ((r["winner"] == 0) - start)).max() < 1e-5
    again = matches.play_matches(env, a, a, 12, 6)
    assert np.array_equal(r["deals"], again["deals"]) and np.array_equal(r["winner"], again["winner"])
    assert not np.array_equal(r["deals"], matches.play_matches(env, a, a, 12, 7)["deals"])
    weak = matches.play_matches(env, a, lockstep.RandomLegal(3), 12, 5)
    assert (weak["a_wins"] == 2).all() and weak["deals"].mean() < r["deals"].mean()
    with pytest.raises(ValueError):
        matches.play_matches(env, a, a, 33, 1)


def test_match_scores_and_model_visits():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    visits, length = matches.model_visits(Equity.load(EQUITY).model, matches=20000, seed=2)
    assert len(visits) == 13 and length == pytest.approx(visits.sum()) and 25 < length < 50
    assert visits[0] / length > 0.25                      # a third of a match is played from 0-0
    scores = matches.match_scores(40000, 3, visits)
    lead = scores.max(1)
    assert (scores.min(1) == 0).all() and np.array_equal(scores, matches.match_scores(40000, 3, visits))
    share = np.bincount(lead // 4, minlength=13) / len(lead)
    assert np.abs(share - visits / length).max() < 0.01
    assert abs((scores[lead > 0, 0] > 0).mean() - 0.5) < 0.02
