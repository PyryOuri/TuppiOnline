"""The hidden-hand sampler: every world satisfies the public constraints, and
the draw is uniform over brute-force-enumerated feasible worlds."""

from __future__ import annotations

import collections
import ctypes as C
import itertools
import random

import numpy as np

from tuppi_ai import native

FULL = (1 << 52) - 1


def _bits(m):
    return [c for c in range(52) if m >> c & 1]


def _random_position(rng, stop):
    deck = list(range(52))
    rng.shuffle(deck)
    hands = [sum(1 << c for c in deck[i * 13:(i + 1) * 13]) for i in range(4)]
    deal = native.new_deal(hands, rng.randrange(4))
    for _ in range(stop):
        if deal.phase == native.PH_DONE:
            break
        native.lib.tc_apply(deal, rng.choice(native.legal(deal)))
    return deal


def _constraints(deal):
    played = [0, 0, 0, 0]
    voids = [set() for _ in range(4)]
    for t in range(0, deal.n_played, 4):
        led = deal.play_card[t] // 13
        for i in range(t, min(t + 4, deal.n_played)):
            s = deal.play_seat[i]
            played[s] += 1
            if deal.play_card[i] // 13 != led:
                voids[s].add(led)
    return played, voids


def test_worlds_satisfy_public_constraints():
    rng = random.Random(7)
    state = C.c_uint64(12345)
    for trial in range(400):
        deal = _random_position(rng, rng.randrange(0, 56))
        if deal.phase == native.PH_DONE:
            continue
        me = deal.cur
        obs = native.observe(deal, me)
        played, voids = _constraints(deal)
        played_mask = sum(1 << deal.play_card[i] for i in range(deal.n_played))
        ref_feat = native.encode(obs)
        for _ in range(20):
            w = native.sample_world(obs, state)
            assert w is not None
            assert w.hand[me] == deal.hand[me]
            union = 0
            for s in range(4):
                assert union & w.hand[s] == 0
                union |= w.hand[s]
                assert bin(w.hand[s]).count("1") == 13 - played[s]
                for v in voids[s]:
                    assert w.hand[s] & (0x1FFF << (13 * v)) == 0
            assert union == FULL & ~played_mask
            for i in range(deal.n_shows):
                c, s = deal.show_card[i], deal.show_seat[i]
                if not played_mask >> c & 1:
                    assert w.hand[s] >> c & 1
            assert w.cur == deal.cur and w.phase == deal.phase
            assert tuple(w.team_tricks) == tuple(deal.team_tricks)
            assert sorted(native.legal(w)) == sorted(native.legal(deal))
            assert np.array_equal(native.encode(native.observe(w, me)), ref_feat)


def test_sampling_is_uniform_over_enumerated_worlds():
    rng = random.Random(11)
    state = C.c_uint64(99)
    checked = 0
    for _ in range(300):
        deal = _random_position(rng, rng.choice([4 + 4 * 10, 4 + 4 * 10 + 1, 4 + 4 * 10 + 2]))
        if deal.phase != native.PH_PLAY:
            continue
        me = deal.cur
        obs = native.observe(deal, me)
        played, voids = _constraints(deal)
        others = [s for s in range(4) if s != me]
        played_mask = sum(1 << deal.play_card[i] for i in range(deal.n_played))
        known = {s: 0 for s in range(4)}
        for i in range(deal.n_shows):
            c, s = deal.show_card[i], deal.show_seat[i]
            if s != me and not played_mask >> c & 1:
                known[s] |= 1 << c
        free = _bits(FULL & ~played_mask & ~deal.hand[me] & ~sum(known.values()))
        caps = [13 - played[s] - bin(known[s]).count("1") for s in others]
        worlds = []
        for first in itertools.combinations(free, caps[0]):
            rest = [c for c in free if c not in first]
            for second in itertools.combinations(rest, caps[1]):
                third = tuple(c for c in rest if c not in second)
                parts = (first, second, third)
                if all(c // 13 not in voids[others[j]] for j in range(3) for c in parts[j]):
                    worlds.append(tuple(known[others[j]] | sum(1 << c for c in parts[j]) for j in range(3)))
        if not 5 <= len(worlds) <= 300:
            continue
        index = {w: i for i, w in enumerate(worlds)}
        counts = collections.Counter()
        draws = 60 * len(worlds)
        for _ in range(draws):
            w = native.sample_world(obs, state)
            key = tuple(w.hand[s] for s in others)
            assert key in index
            counts[key] += 1
        expected = draws / len(worlds)
        chi2 = sum((counts[w] - expected) ** 2 / expected for w in worlds)
        dof = len(worlds) - 1
        # Very loose bound: mean dof, sd sqrt(2 dof).
        assert chi2 < dof + 6 * (2 * dof) ** 0.5, (chi2, dof)
        checked += 1
        if checked >= 12:
            break
    assert checked >= 5
