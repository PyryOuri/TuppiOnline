"""Play inference in the native search (research/play-inference-20261016).

The worlds the search rolls out, resampled by the anchor policy's likelihood
of the other seats' past choices: repeatable, always consistent with the
observation and the history, and closer to the true cards than uniform
worlds when the play comes from that policy.
"""
from __future__ import annotations

import ctypes as C
import random
from pathlib import Path

import numpy as np
import pytest

from tuppi_ai import native

MODEL = Path(__file__).resolve().parents[1] / "models" / "vrpo3_final.pt"
torch = pytest.importorskip("torch")
from tuppi_ai import model as qmodel  # noqa: E402


@pytest.fixture(scope="module")
def policy():
    return native.Mlp(qmodel.load(MODEL, "cpu"))


def played_positions(policy, n, seed):
    """Policy-played v3 deals stopped in trick play (tricks 4-8), as (deal, truth)."""
    rng, out = random.Random(seed), []
    while len(out) < n:
        deck = list(range(52)); rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[s * 13:(s + 1) * 13]) for s in range(4)]
        deal = native.new_deal(hands, rng.randrange(4), 0, 0, ruleset=3)
        stop = rng.randrange(12, 33)
        while deal.phase != native.PH_DONE and not (deal.phase == native.PH_PLAY and deal.n_played >= stop):
            legal = native.legal(deal)
            if deal.phase in native.SOOLI_PHASES and deal.phase != native.PH_SOOLI_OFFER:
                break
            if deal.phase == native.PH_SOOLI_OFFER:
                a = 156  # decline
            else:
                q = policy.forward(native.encode(native.observe(deal, deal.cur), encoder=2)[None])[0]
                a = max(legal, key=lambda x: q[x])
            native.lib.tc_apply(C.byref(deal), a)
        if deal.phase == native.PH_PLAY and deal.soolaaja < 0 and deal.n_played >= stop:
            owner = {c: s for s in range(4) for c in deck[s * 13:(s + 1) * 13]}
            out.append((deal, owner))
    return out


def nll(worlds, deal, owner):
    seat = deal.cur
    played = {deal.play_card[i] for i in range(deal.n_played)}
    unseen = [c for c in range(52) if not deal.hand[seat] >> c & 1 and c not in played]
    total = 0.0
    for c in unseen:
        hits = sum(1 for w in worlds if w.hand[owner[c]] >> c & 1)
        total -= np.log((hits + 0.5) / (len(worlds) + 1.5))
    return total / len(unseen)


def test_belief_worlds_are_repeatable_consistent_and_closer_to_the_truth(policy):
    env = native.Env(8, 1)
    native.set_showing_fix(True)
    positions = played_positions(policy, 24, 20261016)
    try:
        gains = []
        for deal, owner in positions:
            obs = native.observe(deal, deal.cur)
            native.set_belief(env, None)
            uniform = native.search_worlds(env, obs, 256, C.c_uint64(7))
            native.set_belief(env, policy, mult=4, temperature=2.0, eps=0.5)
            weighted = native.search_worlds(env, obs, 256, C.c_uint64(7))
            again = native.search_worlds(env, obs, 256, C.c_uint64(7))
            assert all(bytes(a) == bytes(b) for a, b in zip(weighted, again)), "repeatable for a seed"
            seat = deal.cur
            for w in weighted:
                assert w.hand[seat] == deal.hand[seat]
                k = native.history_rows(w, 0b1111 & ~(1 << seat), 2, np.zeros((64, native.feature_dim(2)), np.uint8),
                                        np.zeros((64, native.NUM_ACTIONS), np.uint8), np.zeros(64, np.int32))
                assert k >= 0, "every resampled world replays the history"
            gains.append(nll(uniform, deal, owner) - nll(weighted, deal, owner))
        assert np.mean(gains) > 0.05, f"weighted worlds predict hidden cards better ({np.mean(gains):.3f})"
    finally:
        native.set_belief(env, None)
        native.set_showing_fix(False)


def test_off_by_default_and_not_while_bidding(policy):
    env = native.Env(8, 1)
    deck = list(range(52)); random.Random(3).shuffle(deck)
    hands = [sum(1 << c for c in deck[s * 13:(s + 1) * 13]) for s in range(4)]
    deal = native.new_deal(hands, 0, 0, 0, ruleset=3)
    obs = native.observe(deal, deal.cur)  # showing: nothing to read
    native.set_belief(env, policy, mult=4)
    try:
        a = native.search_worlds(env, obs, 16, C.c_uint64(5))
        native.set_belief(env, None)
        b = native.search_worlds(env, obs, 16, C.c_uint64(5))
        assert all(bytes(x) == bytes(y) for x, y in zip(a, b)), "the showing is sampled uniformly either way"
    finally:
        native.set_belief(env, None)


def test_controllers_are_independent(policy):
    """One team's searches can read the play while the other team's do not."""
    env_a, env_b = native.Env(8, 1), native.Env(8, 1)
    deal, _ = played_positions(policy, 1, 11)[0]
    obs = native.observe(deal, deal.cur)
    native.set_belief(env_a, policy, mult=4)
    try:
        uniform = native.search_worlds(env_b, obs, 32, C.c_uint64(9))
        native.set_belief(env_a, None)
        assert all(bytes(x) == bytes(y) for x, y in zip(uniform, native.search_worlds(env_a, obs, 32, C.c_uint64(9))))
        native.set_belief(env_a, policy, mult=4)
        assert any(bytes(x) != bytes(y) for x, y in zip(uniform, native.search_worlds(env_a, obs, 32, C.c_uint64(9))))
    finally:
        native.set_belief(env_a, None)


def test_repeated_worlds_are_played_out_once_with_the_same_values(policy):
    """Trick-play searches roll out each distinct resampled world once."""
    env = native.Env(64 * 13, 1)
    native.set_showing_fix(True)
    native.set_belief(env, policy, mult=4)
    try:
        for deal, _ in played_positions(policy, 6, 41):
            obs = native.observe(deal, deal.cur)
            acts = native.legal_obs(obs)
            worlds = [bytes(w) for w in native.search_worlds(env, obs, 64, C.c_uint64(2))]
            assert len(set(worlds)) < len(worlds), "resampling repeats worlds"
            per_world = native.search_world_values(env, policy, obs, acts, 64, 6, C.c_uint64(2))
            for i, j in ((i, j) for i in range(64) for j in range(i) if worlds[i] == worlds[j]):
                assert np.array_equal(per_world[i], per_world[j])
            values = native.search_values(env, policy, obs, acts, 64, 6, C.c_uint64(2))
            assert np.allclose(values, per_world.mean(0), rtol=0, atol=1e-12)
    finally:
        native.set_belief(env, None)
        native.set_showing_fix(False)
