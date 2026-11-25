"""Counterfactual labels on the GPU (the data of ai/tuppi_ai/selfplay.py).

At a recorded decision every legal action is played out to the end of the deal
from the same full state, by the policy on all four seats. The result of each
action in that deal is exact: there is nothing to estimate. Two kinds of label:

  dd_left = 0   own play: the policy plays every remaining card;
  dd_left = 6   solver tail: as soon as 6 tricks remain, the deal is finished
                with its perfect-information result (what Heidi's search uses).

`collect` records states during lockstep self-play (a chooser wrapper, so the
self-play loop is `lockstep.rollouts` itself); `branch_labels` labels them.
The rows have the compact format of selfplay.py: `ids` uint8 [n, 26] (legal
actions, padded with 156) and `q` float16 [n, 26] (the acting team's
match-equity change after each action).

Differences from the native functions, on purpose:
- every play-out of one state shares one random stream, set explicitly
  (tc_ls_branch_begin), so labels are reproducible and paired;
- exploration is at most one random move per deal, and every recorded state
  says whether one preceded it (`explored`), so that gates can use clean states;
- label sharing between rank-equivalent cards is off unless asked for: with
  VRPO4 those labels agree only about three times in four.
"""

from __future__ import annotations

import ctypes as C
import time

import numpy as np

from . import lockstep, tn
from tuppi_ai import native

lib = tn.lib
STATE = np.dtype(native.TcDeal)
PAD = native.NUM_ACTIONS
MAX_K = native.MAX_K
N_CLASSES = native.N_RECORD_CLASSES


class Recorder:
    """Wraps a chooser: records full states at random unforced decisions and makes at most one
    exploration move per deal. Use one Recorder per `lockstep.rollouts` call."""

    def __init__(self, env: "native.Env", choose, games: int, p_record: float, p_explore: float,
                 class_mult: np.ndarray | None, seed: int, capacity: int):
        self.env, self.choose = env, choose
        self.p_record, self.p_explore = p_record, p_explore
        self.mult = np.ones(N_CLASSES) if class_mult is None else np.asarray(class_mult, np.float64)
        self.rng = np.random.default_rng(seed)
        self.deviated = np.zeros(games, bool)
        self.states = np.zeros(capacity, STATE)
        fb = (native.feature_dim(env.encoder) + 7) // 8
        self.feat = np.zeros((capacity, fb), np.uint8)
        self.mask = np.zeros((capacity, tn.MASK_BYTES), np.uint8)
        self.cls = np.zeros(capacity, np.int8)
        self.game = np.zeros(capacity, np.int32)
        self.explored = np.zeros(capacity, np.uint8)
        self.n = 0
        self.dropped = 0

    def __call__(self, feat, mask, idx, team):
        actions, _ = self.choose(feat, mask, idx, team)
        actions = np.array(actions, np.uint8)
        legal = lockstep.unpack_mask(mask)
        unforced = legal.sum(1) > 1
        k = len(idx)
        cls = np.zeros(k, np.int8)
        idx32 = np.ascontiguousarray(idx, np.int32)
        lib.tc_ls_classes(self.env._h, idx32.ctypes.data, k, cls.ctypes.data, None)
        rec = np.nonzero(unforced & (self.rng.random(k) < self.p_record * self.mult[cls]))[0]
        room = len(self.states) - self.n
        if len(rec) > room:
            self.dropped += len(rec) - room
            rec = rec[:room]
        if len(rec):
            games = np.ascontiguousarray(idx32[rec])
            sl = slice(self.n, self.n + len(rec))
            lib.tc_ls_copy_states(self.env._h, games.ctypes.data, len(rec), self.states[sl].ctypes.data)
            self.feat[sl], self.mask[sl], self.cls[sl] = feat[rec], mask[rec], cls[rec]
            self.game[sl], self.explored[sl] = games, self.deviated[games]
            self.n += len(rec)
        if self.p_explore > 0:
            dev = np.nonzero(unforced & ~self.deviated[idx32] & (self.rng.random(k) < self.p_explore))[0]
            if len(dev):
                noise = self.rng.random((len(dev), native.NUM_ACTIONS), dtype=np.float32) * legal[dev]
                actions[dev] = noise.argmax(1)
                self.deviated[idx32[dev]] = True
        return actions, None


def collect(env: "native.Env", choose, games: int, rng_state: C.c_uint64, p_record: float = 0.08,
            p_explore: float = 0.01, class_mult: np.ndarray | None = None, seed: int = 0, ruleset: int = 3,
            encoder: int = 2) -> dict:
    """One batch of `games` self-play deals by `choose`; the recorded states with their packed
    features and masks, position class, game index and whether an exploration move preceded."""
    rec = Recorder(env, choose, games, p_record, p_explore, class_mult, seed, capacity=games * 12)
    lockstep.rollouts(env, rec, games, ruleset, rng_state, encoder)
    n = rec.n
    return {"states": rec.states[:n], "feat": rec.feat[:n], "mask": rec.mask[:n], "cls": rec.cls[:n],
            "game": rec.game[:n], "explored": rec.explored[:n], "dropped": rec.dropped}


def record_classes(states: np.ndarray) -> np.ndarray:
    """tc_record_class from the state fields: 0 showing, 1 + trick NOLO play, 14 + trick RAMI play."""
    trick = np.minimum(states["n_played"] // 4, 12)
    return np.where(states["phase"] == native.PH_SHOW, 0,
                    np.where(states["contract"] == 1, 14, 1) + trick).astype(np.int8)


def branch_labels(env: "native.Env", states: np.ndarray, choose, seeds: np.ndarray, dd_left: int = 0,
                  encoder: int = 2, timing: dict | None = None, counts: np.ndarray | None = None
                  ) -> tuple[np.ndarray, np.ndarray]:
    """(ids uint8 [n, MAX_K], q float16 [n, MAX_K]) for `states`: every legal action played out by
    `choose` (greedy) on all seats, with a solver tail of `dd_left` tricks if > 0. seeds: one
    uint64 per state. States are labelled in chunks that fit `env`; counts (the number of legal
    actions of each state, e.g. from its mask) lets the chunks fill it, else 26 per state is assumed."""
    n = len(states)
    states = np.ascontiguousarray(states)
    seeds = np.ascontiguousarray(seeds, np.uint64)
    ids = np.full((n, MAX_K), PAD, np.uint8)
    q = np.zeros((n, MAX_K), np.float16)
    buf = lockstep.Buffers(env, encoder)
    feat = np.zeros((env.n, buf.fb), np.uint8)
    mask = np.zeros((env.n, buf.mb), np.uint8)
    seconds = np.zeros(2, np.float64)
    t0, t_choose, rows, games_total, start = time.perf_counter(), 0.0, 0, 0, 0
    per_state = max(1, env.n // MAX_K)   # states that always fit, whatever their action counts
    ends = None if counts is None else np.cumsum(np.minimum(counts, MAX_K).astype(np.int64))
    while start < n:
        if ends is None:
            m = min(per_state, n - start)
        else:
            base = ends[start - 1] if start else 0
            m = max(1, int(np.searchsorted(ends, base + env.n, side="right")) - start)
        acts = np.zeros((m, MAX_K), np.int32)
        k = np.zeros(m, np.int32)
        slot = np.zeros((m, MAX_K), np.int32)
        buf.total[:] = 0.0
        games = lib.tc_ls_branch_begin(env._h, states[start:start + m].ctypes.data, m, MAX_K,
                                       seeds[start:start + m].ctypes.data, acts.ctypes.data, k.ctypes.data,
                                       slot.ctypes.data, buf.total.ctypes.data)
        if games < 0:
            raise RuntimeError(f"branch begin failed ({games})")
        while True:
            lib.tc_ls_resolve(env._h, games, dd_left, buf.total.ctypes.data, buf.idx.ctypes.data, seconds.ctypes.data)
            live = buf.observe(games, feat, mask)
            if live == 0:
                break
            t1 = time.perf_counter()
            actions = choose(feat[:live], mask[:live], buf.idx[:live], None)[0]
            t_choose += time.perf_counter() - t1
            buf.step(actions, live)
            rows += live
        valid = np.arange(MAX_K)[None, :] < k[:, None]
        sign = np.where((states["cur"][start:start + m] & 1) == 0, 1.0, -1.0)[:, None]
        value = sign * buf.total[np.where(valid, slot, 0)]
        ids[start:start + m] = np.where(valid, acts, PAD)
        q[start:start + m] = np.where(valid, value, 0.0)
        games_total += games
        start += m
    if timing is not None:
        timing.update(total=time.perf_counter() - t0, choose=t_choose, sooli=float(seconds[0] + buf.seconds[0]),
                      solver=float(seconds[1]), encode=float(buf.seconds[1]), rows=rows, games=games_total)
    return ids, q


def state_seeds(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(1, 2**63, n, dtype=np.uint64)
