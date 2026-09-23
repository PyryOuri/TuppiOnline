"""The native sooli solver against brute force, on positions from random play."""

from __future__ import annotations

import random

from tuppi_ai import native


def _to_sooli_play(rng, accept_seat_first=True):
    """A random v2 deal driven to the start of sooli play (None if no sooli)."""
    cards = list(range(52))
    rng.shuffle(cards)
    hands = [sum(1 << c for c in cards[s * 13:(s + 1) * 13]) for s in range(4)]
    deal = native.new_deal(hands, rng.randrange(4), ruleset=2)
    while deal.phase not in (native.PH_SOOLI_PLAY, native.PH_DONE, native.PH_PLAY):
        legal = native.legal(deal)
        if deal.phase == native.PH_SHOW:
            rami = [a for a in legal if a >= 52 + 52]
            action = rng.choice(rami or legal)
        elif deal.phase == native.PH_SOOLI_OFFER:
            action = native.ACT_SOOLI_ACCEPT
        else:
            action = rng.choice(legal)
        assert native.lib.tc_apply(deal, action) == 0
    return deal if deal.phase == native.PH_SOOLI_PLAY else None


def _brute(deal, memo):
    """1 if the soolaaja survives: they choose, the RAMI pair chooses against."""
    if deal.phase == native.PH_DONE:
        return deal.sooli_won
    key = (bytes(deal.hand), deal.cur, deal.n_played % 3,
           tuple(deal.play_card[deal.n_played - deal.n_played % 3:deal.n_played]))
    if key in memo:
        return memo[key]
    values = []
    for a in native.legal(deal):
        child = native.TcDeal.from_buffer_copy(deal)
        assert native.lib.tc_apply(child, a) == 0
        values.append(_brute(child, memo))
    v = max(values) if deal.cur == deal.soolaaja else min(values)
    memo[key] = v
    return v


def _advance_randomly(deal, rng, plays):
    """Plays random cards but keeps the soolaaja alive when possible."""
    for _ in range(plays):
        if deal.phase != native.PH_SOOLI_PLAY:
            return
        legal = native.legal(deal)
        if deal.cur == deal.soolaaja:
            safe = []
            for a in legal:
                child = native.TcDeal.from_buffer_copy(deal)
                native.lib.tc_apply(child, a)
                if child.phase != native.PH_DONE or child.sooli_won:
                    safe.append(a)
            legal = safe or legal
        native.lib.tc_apply(deal, rng.choice(legal))


def test_solver_matches_brute_force_late():
    rng = random.Random("sooli-solver")
    checked = {0: 0, 1: 0}
    while min(checked.values()) < 40:
        deal = _to_sooli_play(rng)
        if deal is None:
            continue
        _advance_randomly(deal, rng, rng.randrange(24, 34))
        if deal.phase != native.PH_SOOLI_PLAY:
            continue
        expect = _brute(deal, {})
        assert native.sooli_solve(deal) == expect
        legal = native.legal(deal)
        values = native.sooli_move_values(deal, legal)
        for a, v in zip(legal, values):
            child = native.TcDeal.from_buffer_copy(deal)
            native.lib.tc_apply(child, a)
            assert v == _brute(child, {})
        checked[expect] += 1


def test_solver_is_consistent_at_every_step():
    """Along random play, a position's value is the max/min of its children's values."""
    rng = random.Random("sooli-consistency")
    for _ in range(40):
        deal = _to_sooli_play(rng)
        if deal is None:
            continue
        while deal.phase == native.PH_SOOLI_PLAY:
            legal = native.legal(deal)
            v = native.sooli_solve(deal)
            kids = native.sooli_move_values(deal, legal)
            assert v == (max(kids) if deal.cur == deal.soolaaja else min(kids))
            native.lib.tc_apply(deal, rng.choice(legal))
