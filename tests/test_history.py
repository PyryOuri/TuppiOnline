"""History replay inside a world reproduces each seat's actual past observations."""

from __future__ import annotations

import random

import numpy as np

from tuppi_ai import native


def test_history_rows_reproduce_true_observations():
    rng = random.Random(5)
    for trial in range(60):
        deck = list(range(52))
        rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[i * 13:(i + 1) * 13]) for i in range(4)]
        deal = native.new_deal(hands, rng.randrange(4), 0, 0)
        stop = rng.randrange(1, 50)
        recorded = []
        for _ in range(stop):
            if deal.phase == native.PH_DONE:
                break
            legal = native.legal(deal)
            a = rng.choice(legal)
            if len(legal) > 1:
                recorded.append((deal.cur, native.encode(native.observe(deal, deal.cur), encoder=2), sorted(legal), a))
            native.lib.tc_apply(deal, a)
        if deal.phase == native.PH_DONE:
            continue
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
