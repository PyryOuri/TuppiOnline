"""The v2 (sooli) world sampler.

Every sampled world must (1) project back to exactly the observer's
observation, (2) be reachable: some exchange and initial deal replay the whole
public history into it, and (3) for a RAMI observer, split the soolaaja's and
partner's shown cards between them with the uniform-exchange-prior odds.
"""

from __future__ import annotations

import ctypes as C
import random

from tuppi_ai import native


def _bits(m):
    return [c for c in range(52) if m >> c & 1]


def _drive(rng, stop_phase, extra_plays=0):
    """A random v2 deal with a sooli, stopped at stop_phase (+ random sooli plays)."""
    while True:
        cards = list(range(52))
        rng.shuffle(cards)
        hands = [sum(1 << c for c in cards[s * 13:(s + 1) * 13]) for s in range(4)]
        deal = native.new_deal(hands, rng.randrange(4), ruleset=2)
        history = []
        while deal.phase not in (native.PH_DONE, native.PH_PLAY) and deal.phase != stop_phase:
            legal = native.legal(deal)
            if deal.phase == native.PH_SHOW:
                # Often NOLO first, so that several seats show before a RAMI.
                rami = [a for a in legal if a >= 104]
                nolo = [a for a in legal if a < 104]
                a = rng.choice(nolo if nolo and rng.random() < 0.6 else (rami or legal))
            else:
                a = rng.choice(legal)
            history.append(a)
            assert native.lib.tc_apply(deal, a) == 0
        if deal.phase != stop_phase:
            continue
        if any(deal.show_verbal[i] for i in range(deal.n_shows)):
            continue  # the samplers ignore what a verbal show says about the hand
        for _ in range(extra_plays):
            if deal.phase != native.PH_SOOLI_PLAY:
                break
            a = rng.choice(native.legal(deal))
            history.append(a)
            native.lib.tc_apply(deal, a)
        if deal.phase == stop_phase:
            return deal, hands, history


def _replay(world, observer_deal, history):
    """Rebuilds initial hands of `world` and replays `history`; returns the end state."""
    S, P = world.soolaaja, (world.soolaaja + 2) % 4
    played = [0, 0, 0, 0]
    for i in range(world.n_played):
        played[world.play_seat[i]] |= 1 << world.play_card[i]
    now = [world.hand[s] | played[s] for s in range(4)]
    phase = observer_deal.phase
    X = next((world.show_card[i] for i in range(world.n_shows) if world.show_seat[i] == S), None)
    Y = next((world.show_card[i] for i in range(world.n_shows) if world.show_seat[i] == P), None)
    if phase == native.PH_SOOLI_RETURN:
        g = observer_deal.given
        init = list(now)
        init[S] |= 1 << g
        init[P] &= ~(1 << g)
        exchange = [native.ACT_EXCHANGE + g]
    else:
        g = X if X is not None and now[P] >> X & 1 else next(c for c in _bits(now[P]) if c != Y)
        r = Y if Y is not None and now[S] >> Y & 1 else next(c for c in _bits(now[S]) if c != X)
        init = list(now)
        init[S] = (now[S] & ~(1 << r)) | (1 << g)
        init[P] = (now[P] & ~(1 << g)) | (1 << r)
        exchange = [native.ACT_EXCHANGE + g, native.ACT_EXCHANGE + r]
    deal = native.new_deal(init, world.dealer, world.score[0], world.score[1], ruleset=2)
    n_pre = world.n_shows + world.n_decisions
    actions = history[:n_pre] + exchange + [world.play_card[i] for i in range(world.n_played)]
    for a in actions:
        if native.lib.tc_apply(deal, a) != 0:
            return None
    return deal


def _check_worlds(deal, history, rng_state, n=30):
    me = deal.cur
    obs = native.observe(deal, me)
    for _ in range(n):
        world = native.sample_world(obs, rng_state)
        assert world is not None
        assert bytes(native.observe(world, me)) == bytes(obs)
        hands = [world.hand[s] for s in range(4)]
        played = sum(1 << world.play_card[i] for i in range(world.n_played))
        assert sum(bin(h).count("1") for h in hands) + bin(played).count("1") == 52
        assert (hands[0] | hands[1] | hands[2] | hands[3] | played) == (1 << 52) - 1
        end = _replay(world, deal, history)
        assert end is not None, "sampled world is not reachable"
        assert [end.hand[s] for s in range(4)] == hands
        assert end.cur == world.cur == deal.cur and end.phase == world.phase


def test_return_phase_worlds():
    rng = random.Random("v2-sampler-return")
    state = C.c_uint64(11)
    for _ in range(60):
        deal, _, history = _drive(rng, native.PH_SOOLI_RETURN)
        _check_worlds(deal, history, state)


def test_sooli_play_worlds_for_every_actor():
    rng = random.Random("v2-sampler-play")
    state = C.c_uint64(12)
    seen = set()
    for i in range(300):
        deal, _, history = _drive(rng, native.PH_SOOLI_PLAY, extra_plays=rng.randrange(0, 20))
        role = "S" if deal.cur == deal.soolaaja else ("D" if deal.cur == deal.declarer else "Q")
        seen.add(role)
        _check_worlds(deal, history, state, n=10)
    assert seen == {"S", "D", "Q"}


def test_rami_observer_exchange_odds():
    """At the first sooli lead, with both defenders' shown cards unplayed, the
    soolaaja kept its shown card X and the partner kept Y with odds
    (12/13)^2 : 12/13^2 : 12/13^2 : 1/13^2 (uniform exchange prior)."""
    rng = random.Random("v2-sampler-odds")
    state = C.c_uint64(13)
    tried = 0
    while tried < 4:
        deal, _, _ = _drive(rng, native.PH_SOOLI_PLAY)
        S, P = deal.soolaaja, (deal.soolaaja + 2) % 4
        shows = {deal.show_seat[i]: deal.show_card[i] for i in range(deal.n_shows)}
        if S not in shows or P not in shows or deal.cur != deal.declarer:
            continue
        tried += 1
        X, Y = shows[S], shows[P]
        obs = native.observe(deal, deal.cur)
        counts = {}
        n = 20000
        for _ in range(n):
            w = native.sample_world(obs, state)
            key = (w.hand[S] >> X & 1, w.hand[P] >> Y & 1)
            counts[key] = counts.get(key, 0) + 1
        expect = {(1, 1): 144 / 169, (0, 1): 12 / 169, (1, 0): 12 / 169, (0, 0): 1 / 169}
        for key, p in expect.items():
            got = counts.get(key, 0) / n
            sd = (p * (1 - p) / n) ** 0.5
            assert abs(got - p) < 5 * sd + 1e-4, (key, got, p)
