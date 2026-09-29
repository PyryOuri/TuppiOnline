"""Value-net leaves (docs/VALUE_NET_PLAN.md): features, wiring and data rows."""

from __future__ import annotations

import ctypes as C

import numpy as np
import torch

from tuppi_ai import native
from tuppi_ai import value as vmod
from tuppi_ai.best import EQUITY, ROLLOUT
from tuppi_ai.equity import Equity


def _constant_net(c: float) -> vmod.VNet:
    net = vmod.VNet(width=16, blocks=1)
    with torch.no_grad():
        for p in net.parameters():
            p.zero_()
        net.out.bias.fill_(c * vmod.VALUE_SCALE)
    return net


def test_pi_features_are_the_hands_from_the_side_to_move():
    rng = np.random.default_rng(0)
    cards = rng.permutation(52)
    hands = [sum(1 << int(c) for c in cards[13 * s:13 * s + 13]) for s in range(4)]
    deal = native.new_deal(hands, 1)
    for _ in range(4):  # four NOLO shows
        nolo = [a for a in native.legal(deal) if 52 <= a < 104]
        native.lib.tc_apply(C.byref(deal), nolo[0])
    f = native.encode_pi(deal, bot_side=True)
    bot, pre_offer = native.PI_DIM - 2, native.PI_DIM - 1
    assert f.shape == (native.PI_DIM,) and f[bot] == 1 and f[pre_offer] == 0
    s = deal.cur
    for r in range(4):
        block = sum(1 << c for c in range(52) if f[52 * r + c])
        assert block == deal.hand[(s + r) & 3]
    assert native.encode_pi(deal)[bot] == 0
    # The end of bidding under sooli rules (before any offer) sets the last bit.
    deal = native.new_deal(hands, 1, ruleset=2)
    rami = [a for a in native.legal(deal) if a >= 104]
    native.lib.tc_apply(C.byref(deal), rami[0])
    assert deal.phase == native.PH_SOOLI_OFFER and native.encode_pi(deal)[pre_offer] == 1


def test_constant_value_leaf_prices_every_bid_world_at_plus_or_minus_c():
    from tuppi_ai import model as qmodel

    c = 0.0371
    net = qmodel.load(ROLLOUT, "cpu")
    mlp = native.Mlp(net)
    env = native.Env(64 * 26, 3, Equity.load(EQUITY).table, single_deal=True, encoder=net.encoder)
    vm = vmod.to_native(_constant_net(c))
    env.set_value(vm, 0, -1, False)
    rng = np.random.default_rng(1)
    cards = rng.permutation(52)
    hands = [sum(1 << int(x) for x in cards[13 * s:13 * s + 13]) for s in range(4)]
    deal = native.new_deal(hands, 0, ruleset=1)  # no sooli: every rollout reaches trick play
    obs = native.observe(deal, deal.cur)
    ids = native.legal(deal)
    per_world = native.search_world_values(env, mlp, obs, ids, 64, 6, C.c_uint64(5))
    assert per_world.shape == (64, len(ids))
    assert np.allclose(np.abs(per_world), c, atol=1e-6)
    # Switched off, the same search plays the deals out instead.
    env.set_value(None)
    per_world = native.search_world_values(env, mlp, obs, ids, 64, 6, C.c_uint64(5))
    assert not np.allclose(np.abs(per_world), c, atol=1e-6)


def test_value_rollout_rows_are_trick_boundaries_with_bounded_targets():
    from tuppi_ai import model as qmodel

    net = qmodel.load(ROLLOUT, "cpu")
    env = native.Env(256, 7, Equity.load(EQUITY).table, single_deal=True, encoder=net.encoder)
    feat, target = native.value_rollouts(env, native.Mlp(net), 256, 3, 6, C.c_uint64(11), 256 * 14)
    assert len(feat) > 256 and len(feat) == len(target)
    cards = feat[:, :208].sum(axis=1)
    assert np.all(cards % 4 == 0) and cards.min() >= 28  # trick boundaries with more than 6 tricks left
    assert np.all(np.abs(target) <= 1.0)


def test_suit_permutations_are_bijections_that_move_whole_suits():
    perms = vmod.suit_permutations()
    assert perms.shape == (24, native.PI_DIM)
    for p in perms:
        assert sorted(p) == list(range(native.PI_DIM))
        assert np.array_equal(p[208:], np.arange(208, native.PI_DIM))
