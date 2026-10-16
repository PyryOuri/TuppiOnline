"""History replay inside a world reproduces each seat's actual past observations."""

from __future__ import annotations

import random

import numpy as np

from tuppi_ai import native


import pytest


@pytest.mark.parametrize("ruleset", [1, 3])
def test_history_rows_reproduce_true_observations(ruleset):
    rng = random.Random(5 + ruleset)
    declined = 0
    for trial in range(200 if ruleset == 3 else 60):
        deck = list(range(52))
        rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[i * 13:(i + 1) * 13]) for i in range(4)]
        deal = native.new_deal(hands, rng.randrange(4), 0, 0, ruleset=ruleset)
        stop = rng.randrange(1, 50)
        recorded = []
        for _ in range(stop):
            if deal.phase == native.PH_DONE:
                break
            legal = native.legal(deal)
            a = rng.choice(legal)
            if len(legal) > 1 and deal.phase != native.PH_SOOLI_OFFER:
                recorded.append((deal.cur, native.encode(native.observe(deal, deal.cur), encoder=2), sorted(legal), a))
            native.lib.tc_apply(deal, a)
        if deal.phase == native.PH_DONE or deal.soolaaja >= 0:
            continue  # played soolis are not replayed (declined offers are)
        declined += bool(deal.n_decisions)
        for seat_mask in (0b1111, 0b0101, 1 << rng.randrange(4)):
            want = [r for r in recorded if seat_mask >> r[0] & 1]
            dim = native.feature_dim(2)
            feat = np.zeros((60, dim), np.uint8)
            mask = np.zeros((60, native.NUM_ACTIONS), np.uint8)
            act = np.zeros(60, np.int32)
            k = native.history_rows(deal, seat_mask, 2, feat, mask, act)
            assert k == len(want)
            for j, (seat, f, legal, a) in enumerate(want):
                assert np.array_equal(feat[j], f)
                assert sorted(np.nonzero(mask[j])[0]) == legal
                assert act[j] == a
    if ruleset == 3:
        assert declined > 0, "some replayed deals contain declined sooli offers"
