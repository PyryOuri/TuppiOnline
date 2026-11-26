"""Focused counterfactual labels: the candidates only, in the deal as it really is.

The look-ahead (lookahead.py) averages a move's result over sampled deals because
at the table the true deal is hidden. For training data it is not: the full state
of a self-play decision is known, and the true deal is an exact draw from what
the acting seat should believe. So one play-out per candidate from the true state
is an unbiased sample of that candidate's value, at 1/W of the look-ahead's cost,
and a network trained on many such samples averages the noise itself.

`labels.branch_labels` does this for every legal action of a sample of states.
Here only the decisions that matter are labelled, and only their plausible moves:
decisions where the network gives at least two moves `min_prob` of its
probability, and at most `top` of those. With a strong network that is about a
quarter of the unforced decisions and two or three moves each, which is why the
same play-out budget buys an order of magnitude more labelled decisions.

    collect(...) -> rows in the compact format of labels.py / improve.py:
        feat   packed observation
        ids    uint8 [n, top], the candidates, the network's own move first (padding 156)
        q      float32 [n, top], the acting team's equity change after each candidate,
               continued by the network on all seats
        cls, explored, w   as in labels.py (w = 1)

`improve.fit_policy` trains on these rows directly: its softmax then runs over
the candidates only.
"""

from __future__ import annotations

import ctypes as C
import time

import numpy as np

from . import labels, lockstep, lookahead, tn
from tuppi_ai import native

lib = tn.lib
PAD = native.NUM_ACTIONS


class Focused:
    """A chooser for `lockstep.rollouts`: plays the network's move (with at most one exploration
    move per deal) and labels every decision that has more than one candidate."""

    def __init__(self, env: "native.Env", anchor, searcher: "lookahead.Searcher", games: int, top: int = 4,
                 min_prob: float = 0.01, p_explore: float = 0.01, seed: int = 0, capacity: int | None = None):
        self.env, self.anchor, self.searcher = env, anchor, searcher
        self.top, self.min_prob, self.p_explore = top, min_prob, p_explore
        self.rng = np.random.default_rng(seed)
        self.deviated = np.zeros(games, bool)
        capacity = capacity or games * 24
        fb = (native.feature_dim(env.encoder) + 7) // 8
        self.feat = np.zeros((capacity, fb), np.uint8)
        self.ids = np.full((capacity, top), PAD, np.uint8)
        self.q = np.zeros((capacity, top), np.float32)
        self.cls = np.zeros(capacity, np.int8)
        self.explored = np.zeros(capacity, np.uint8)
        self.n = self.dropped = self.decisions = self.unforced = 0

    def __call__(self, feat, mask, idx, team):
        actions, cand, k, legal = lookahead.candidates(self.anchor, feat, mask, self.top, self.min_prob)
        idx32 = np.ascontiguousarray(idx, np.int32)
        rows = np.flatnonzero(k > 1)
        self.decisions += len(idx)
        self.unforced += int((legal > 1).sum())
        room = len(self.feat) - self.n
        if len(rows) > room:
            self.dropped += len(rows) - room
            rows = rows[:room]
        if len(rows):
            m = len(rows)
            games = np.ascontiguousarray(idx32[rows])
            states = np.zeros(m, lookahead.STATE)
            lib.tc_ls_copy_states(self.env._h, games.ctypes.data, m, states.ctypes.data)
            cls = np.zeros(m, np.int8)
            lib.tc_ls_classes(self.env._h, games.ctypes.data, m, cls.ctypes.data, None)
            seeds = self.rng.integers(1, 2**63, m, dtype=np.uint64)
            q = self.searcher.play(states, 1, cand[rows], k[rows], seeds)[:, 0, :self.top]
            sl = slice(self.n, self.n + m)
            valid = np.arange(self.top)[None, :] < k[rows, None]
            self.feat[sl] = feat[rows]
            self.ids[sl] = np.where(valid, cand[rows, :self.top], PAD)
            self.q[sl] = q
            self.cls[sl], self.explored[sl] = cls, self.deviated[games]
            self.n += m
        if self.p_explore > 0:
            dev = np.flatnonzero((legal > 1) & ~self.deviated[idx32] & (self.rng.random(len(idx)) < self.p_explore))
            if len(dev):
                noise = self.rng.random((len(dev), native.NUM_ACTIONS), dtype=np.float32) * lockstep.unpack_mask(mask[dev])
                actions[dev] = noise.argmax(1)
                self.deviated[idx32[dev]] = True
        return actions, None


def collect(env: "native.Env", anchor, searcher: "lookahead.Searcher", games: int, rng_state: C.c_uint64, top: int = 4,
            min_prob: float = 0.01, p_explore: float = 0.01, seed: int = 0, ruleset: int = 3, encoder: int = 2,
            timing: dict | None = None) -> dict:
    """One batch of `games` self-play deals by the network of `anchor`; its focused label rows.
    `searcher`: play-outs by the same network (`lookahead.Searcher`)."""
    t0 = time.perf_counter()
    rec = Focused(env, anchor, searcher, games, top, min_prob, p_explore, seed)
    lockstep.rollouts(env, rec, games, ruleset, rng_state, encoder)
    n = rec.n
    if timing is not None:
        timing.update(seconds=time.perf_counter() - t0, decisions=rec.decisions, unforced=rec.unforced, labelled=n,
                      dropped=rec.dropped, **searcher.counts())
    return {"feat": rec.feat[:n].copy(), "ids": rec.ids[:n].copy(), "q": rec.q[:n].copy(), "cls": rec.cls[:n].copy(),
            "explored": rec.explored[:n].copy(), "w": np.ones(n, np.float16)}
