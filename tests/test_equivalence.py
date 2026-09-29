"""Rank-equivalent cards (tuppi_ai.equivalence) against the perfect-information solver."""

from __future__ import annotations

import ctypes as C
import random

from tuppi_ai import native
from tuppi_ai.equivalence import equivalent, groups


def _positions(n, seed=11):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        cards = list(range(52))
        rng.shuffle(cards)
        hands = [sum(1 << c for c in cards[s * 13:(s + 1) * 13]) for s in range(4)]
        deal = native.new_deal(hands, rng.randrange(4))
        contract = rng.randrange(2)
        for _ in range(4):
            acts = [a for a in native.legal(deal) if (a - 52) // 52 == contract]
            if not acts:
                break
            native.lib.tc_apply(C.byref(deal), rng.choice(acts))
            if deal.phase == native.PH_PLAY:
                break
        if deal.phase != native.PH_PLAY:
            continue
        stop = rng.randrange(28, 48)  # 5-7 tricks left, any point of a trick
        while deal.n_played < stop:
            native.lib.tc_apply(C.byref(deal), rng.choice(native.legal(deal)))
        out.append(deal)
    return out


def test_groups_partition_the_legal_cards_and_equivalent_cards_solve_alike():
    checked = 0
    for deal in _positions(300):
        obs = native.observe(deal, deal.cur)
        ids = native.legal(deal)
        gs = groups(obs, ids)
        assert sorted(a for g in gs for a in g) == sorted(ids)
        for g in gs:
            assert len({a // 13 for a in g}) == 1  # one suit per group
            results = set()
            for a in g:
                child = native.TcDeal.from_buffer_copy(deal)
                assert native.lib.tc_apply(C.byref(child), a) == 0
                results.add(child.team_tricks[0] if child.phase == native.PH_DONE
                            else native.dd_team0_tricks(child))
            assert len(results) == 1, (g, results)
            checked += len(g) > 1
    assert checked > 50


def test_cards_split_by_a_live_card_are_not_equivalent():
    # Seat 0 holds H2 and H4; H3 is still out (not played): not equivalent.
    # Once H3 has been played in a completed trick, they are.
    obs = native.TcObs()
    obs.hand = (1 << 0) | (1 << 2)
    obs.phase = native.PH_PLAY
    obs.n_played = 0
    assert not equivalent(obs, [0, 2], 0, 2)
    obs.play_card[0], obs.play_card[1], obs.play_card[2], obs.play_card[3] = 1, 13, 14, 15
    obs.n_played = 4
    assert equivalent(obs, [0, 2], 0, 2)
    obs.n_played = 1  # H3 only in the current trick: still live
    assert not equivalent(obs, [0, 2], 0, 2)
