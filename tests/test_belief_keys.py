"""Distinct-key play-inference scoring (Heidi fast plan, Stage 1).

Each distinct (seat, hand) among the candidates is replayed and scored once
instead of every candidate in full. The log-weights must equal the
per-candidate method: here recomputed in Python with tc_history_rows and the
Torch anchor (T 2, eps 0.5; people at T 4, eps 0.8), and compared with the
library's plain path. Accelerate's sgemm is not row-independent, so native
comparisons use a tolerance; the WASM build is compared bit for bit elsewhere.
"""
from __future__ import annotations

import ctypes as C
import random

import numpy as np
import pytest

from tuppi_ai import native

torch = pytest.importorskip("torch")
import test_belief_search as T  # noqa: E402
from tuppi_ai import model as qmodel  # noqa: E402


@pytest.fixture(scope="module")
def nets():
    net = qmodel.load(T.MODEL, "cpu").eval()
    return net, native.Mlp(net)


def late_positions(policy, n, seed, lo=40, hi=47):
    """Policy-played v3 deals stopped late in trick play (tricks 11-12)."""
    rng, out = random.Random(seed), []
    while len(out) < n:
        deck = list(range(52)); rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[s * 13:(s + 1) * 13]) for s in range(4)]
        deal = native.new_deal(hands, rng.randrange(4), 0, 0, ruleset=3)
        stop = rng.randrange(lo, hi)
        while deal.phase != native.PH_DONE and not (deal.phase == native.PH_PLAY and deal.n_played >= stop):
            if deal.phase in native.SOOLI_PHASES and deal.phase != native.PH_SOOLI_OFFER:
                break
            legal = native.legal(deal)
            if deal.phase == native.PH_SOOLI_OFFER:
                a = 156
            else:
                q = policy.forward(native.encode(native.observe(deal, deal.cur), encoder=2)[None])[0]
                a = max(legal, key=lambda x: q[x])
            native.lib.tc_apply(C.byref(deal), a)
        if deal.phase == native.PH_PLAY and deal.soolaaja < 0 and deal.n_played >= stop and len(native.legal(deal)) > 1:
            out.append(deal)
    return out


def python_log_weights(cands, net, seat, people, t=2.0, eps=0.5, h_t=4.0, h_eps=0.8):
    """Per-candidate method: the bot seats' rows in history order, then the people's."""
    dim, others = native.feature_dim(2), 0xF & ~(1 << seat)
    out = np.zeros(len(cands))
    for i, cand in enumerate(cands):
        for mask, temp, e in ((others & ~people, t, eps), (others & people, h_t, h_eps)):
            if not mask:
                continue
            feat, legal = np.zeros((64, dim), np.uint8), np.zeros((64, native.NUM_ACTIONS), np.uint8)
            act = np.zeros(64, np.int32)
            k = native.history_rows(cand, mask, 2, feat, legal, act)
            assert k >= 0
            with torch.no_grad():
                q = net(torch.from_numpy(feat[:k].astype(np.float32))).double().numpy()
            for r in range(k):
                ok = legal[r].astype(bool)
                z = (q[r] - q[r][ok].max()) / temp
                p = np.exp(z[act[r]]) / np.exp(z[ok]).sum()
                out[i] += np.log((1 - e) * p + e / ok.sum())
    return out


@pytest.mark.parametrize("people", [0, 0b0101])
def test_key_log_weights_equal_the_per_candidate_method(nets, people):
    net, policy = nets
    env = native.Env(8, 1)
    native.set_showing_fix(True)
    native.set_belief(env, policy, mult=8, temperature=2.0, eps=0.5)
    try:
        for i, deal in enumerate(late_positions(policy, 4, 20261022)):
            seat = deal.cur
            native.set_belief_humans(env, [s for s in range(4) if people >> s & 1 and s != seat])
            obs = native.observe(deal, deal.cur)
            native.belief_counters(reset=True)
            native.set_belief_keys(True)
            cands, keys = native.belief_log_weights(env, obs, 8, C.c_uint64(100 + i))
            work = native.belief_counters(reset=True)
            native.set_belief_keys(False)
            cands2, plain = native.belief_log_weights(env, obs, 8, C.c_uint64(100 + i))
            assert len(cands) == 64 and all(bytes(a) == bytes(b) for a, b in zip(cands, cands2)), "same draws"
            assert work["key_searches"] == 1 and work["keys_scored"] < 3 * 64, "late: hands repeat, keys apply"
            assert work["rows_plain"] > work["rows_scored"]
            expected = python_log_weights(cands, net, seat, people & ~(1 << seat))
            assert np.allclose(keys, expected, rtol=0, atol=1e-5), np.abs(keys - expected).max()
            assert np.allclose(keys, plain, rtol=0, atol=1e-6), np.abs(keys - plain).max()
    finally:
        native.set_belief_keys(True)
        native.set_belief_humans(env, [])
        native.set_belief(env, None)
        native.set_showing_fix(False)


def test_keys_fall_back_where_every_hand_is_distinct(nets):
    _, policy = nets
    env = native.Env(8, 1)
    native.set_belief(env, policy, mult=8)
    try:
        deal, _ = T.played_positions(policy, 1, 5)[0]  # tricks 4-8
        obs = native.observe(deal, deal.cur)
        native.belief_counters(reset=True)
        native.belief_log_weights(env, obs, 128, C.c_uint64(3))
        work = native.belief_counters(reset=True)
        # Either path gives the same weights; early hands are almost all distinct.
        assert work["rows_scored"] == work["rows_plain"] or work["key_searches"] == 1
        assert work["uniform_fallbacks"] == 0 and work["replay_failures"] == 0
    finally:
        native.set_belief(env, None)
