"""Rank-equivalent cards in ordinary trick play (docs/EFFICIENCY_PLAN.md, E6).

Two legal cards of one suit are equivalent when no card that can still be
played lies between them in rank: every card between them has been played in
a completed trick or is in the player's own hand. Such cards take the same
tricks under every continuation, for either contract; they differ only in
what they show the other players. Cards in the current trick still count as
live (they decide who wins it).

Reads the observation only (own hand and public play), so it is private-safe.
"""

from __future__ import annotations

from . import native


def groups(obs: native.TcObs, ids: list[int]) -> list[list[int]]:
    """Legal card ids of an ordinary trick-play decision, grouped by equivalence.

    Each group lists its cards in increasing rank; groups come in increasing
    order of their lowest card. Outside ordinary trick play every id is its
    own group."""
    if obs.phase != native.PH_PLAY or any(a >= 52 for a in ids):
        return [[a] for a in ids]
    done = obs.n_played - obs.n_played % 4
    gone = 0
    for i in range(done):
        gone |= 1 << obs.play_card[i]
    legal = set(ids)
    out: list[list[int]] = []
    for suit in range(4):
        run: list[int] = []
        for c in range(13 * suit, 13 * suit + 13):
            if gone >> c & 1:
                continue  # played in a completed trick: does not separate
            if c in legal:
                run.append(c)
            elif obs.hand >> c & 1:
                continue  # own card (cannot happen for a legal suit; kept for safety)
            else:
                if run:
                    out.append(run)
                run = []
        if run:
            out.append(run)
    out.sort(key=lambda g: g[0])
    return out


def equivalent(obs: native.TcObs, ids: list[int], a: int, b: int) -> bool:
    """True if actions a and b are the same card or equivalent cards."""
    return a == b or any(a in g and b in g for g in groups(obs, ids))
