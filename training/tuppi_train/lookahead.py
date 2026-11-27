"""Look-ahead with the network on the GPU: is a search above a strong network worth anything?

At a decision the look-ahead draws W deals ("worlds") that agree with everything
the acting seat has seen, plays every candidate action to the end of the deal in
each of them with a network on all four seats (each seat from its own
observation), and keeps the network's own move unless another one is better by a
margin. This is what the engine's search does (`search_core` in tuppi_env.c, the
bot "Heidi"), with the play-outs in lockstep on the GPU: thousands of decisions
at once, any network as the play-out policy, as many worlds as one likes.

    python -m tuppi_train.lookahead --net <best_student.pt> --out <dir> --base 1024 --worlds 64

plays the look-ahead pair against the plain network by paired duplicate and
prints the gain per deal with its 95% interval after every chunk; a run that is
stopped continues from its last chunk. Either side can be plain or look ahead,
with its own anchor and play-out network (--plain, --opponent,
--opponent-rollout), e.g. a Heidi-style search around a new network against
one around the old.

Pieces:

- `Searcher`: worlds (`sample`, or `belief` = resampled by the likelihood of the
  other seats' past play, the engine's play inference) and play-outs (`play`).
  Play-outs run in `lanes` separate environments: while the engine steps one
  lane, the GPU evaluates another. Rows with one legal action never reach the
  network.
- `LookAhead`: a lockstep chooser. The network's own move is the anchor; the
  candidates are its most probable moves; a candidate replaces the anchor only
  if its mean gain over the worlds exceeds `keep` and `z` paired standard errors.

What it is not: a solver. The worlds are drawn uniformly from the consistent
ones unless `belief` is set; `dd_left` > 0 finishes the last tricks with open
cards (as Heidi does), which is faster and biased.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import device, lockstep, tn
from tuppi_ai import native

lib = tn.lib
STATE = np.dtype(native.TcDeal)
MAX_K = native.MAX_K
HISTORY_STRIDE = 42      # at most 14 unforced decisions for each of three seats
FIRST_SHOW_ACTION = 52   # actions 0..51 play a card, the rest show one


@dataclass
class Settings:
    worlds: int = 64
    top: int = 4              # at most this many candidates per decision, the network's own move included
    min_prob: float = 0.01    # a candidate needs this much of the network's probability
    keep: float = 0.003       # card play: another move must beat the network's by more than this (equity) ...
    keep_show: float = 0.003  # ... showing
    z: float = 2.0            # ... and by more than z paired standard errors
    show: bool = True         # look ahead at showing decisions too
    dd_left: int = 0          # > 0: finish the last tricks of every play-out with the open-card solver
    belief: int = 0           # > 1: draw belief x worlds candidates in card play and resample them by likelihood
    belief_t: float = 2.0     # temperature and uniform share of the likelihood (the engine's play inference)
    belief_eps: float = 0.5


class Lane:
    """One play-out environment and its scratch arrays."""

    def __init__(self, env: "native.Env", encoder: int):
        self.env, self.buf = env, lockstep.Buffers(env, encoder)
        self.feat = np.zeros((env.n, self.buf.fb), np.uint8)
        self.mask = np.zeros((env.n, self.buf.mb), np.uint8)
        self.forced = np.zeros(env.n, np.uint8)
        self.solver = np.zeros(2, np.float64)
        self.games = self.rows = self.net_rows = 0

    def begin(self, worlds: np.ndarray, n: int, w: int, cand: np.ndarray, k: np.ndarray, seeds: np.ndarray) -> None:
        g = lib.tc_ls_search_begin(self.env._h, worlds.ctypes.data, n, w, cand.shape[1], cand.ctypes.data, k.ctypes.data,
                                   seeds.ctypes.data, self.buf.total.ctypes.data)
        if g < 0:
            raise RuntimeError(f"look-ahead: loading the play-outs failed ({g})")
        self.games = g

    def advance(self, chooser, dd_left: int) -> bool:
        """Engine work up to the next decisions that need the network, which are submitted to it.
        False when every game of the lane is finished."""
        while True:
            if dd_left > 0:
                lib.tc_ls_resolve(self.env._h, self.games, dd_left, self.buf.total.ctypes.data, self.buf.idx.ctypes.data,
                                  self.solver.ctypes.data)
            live = self.buf.observe(self.games, self.feat, self.mask, forced=self.forced)
            if live == 0:
                return False
            self.rows += live
            self.live = live
            self.actions = self.forced[:live].copy()
            self.sel = np.flatnonzero(self.actions == 255)
            if len(self.sel) == 0:      # nothing but forced moves
                self.buf.step(self.actions, live)
                continue
            self.net_rows += len(self.sel)
            if len(self.sel) == live:
                self.pending = _submit(chooser, self.feat[:live], self.mask[:live])
            else:
                self.pending = _submit(chooser, self.feat[self.sel], self.mask[self.sel])
            return True

    def apply(self, chooser) -> None:
        self.actions[self.sel] = _collect(chooser, self.pending)
        self.buf.step(self.actions, self.live)


def _submit(chooser, feat, mask):
    if hasattr(chooser, "submit"):
        return chooser.submit(feat, mask)
    return chooser(feat, mask, None, None)[0]


def _collect(chooser, handle):
    return chooser.collect(handle) if hasattr(chooser, "collect") else handle


class Searcher:
    """Worlds and play-outs for many decisions at once. `rollout` is a greedy lockstep chooser
    (`lockstep.TorchGreedy`, or `NativeGreedy` in tests) that plays every seat of the play-outs."""

    def __init__(self, table: np.ndarray, rollout, encoder: int = 2, lanes: int = 2, lane_games: int = 65536,
                 heuristic_sooli: bool = True, dd_left: int = 0, offer_model=None):
        self.rollout, self.encoder, self.dd_left, self.offer_model = rollout, encoder, dd_left, offer_model
        self.lanes = []
        for _ in range(lanes):
            env = native.Env(lane_games, 1, table, single_deal=True, encoder=encoder)
            env.set_sooli(0, False, heuristic_sooli, 0.0)
            self.lanes.append(Lane(env, encoder))
        self.seconds = {"worlds": 0.0, "play": 0.0, "belief": 0.0}
        self.games = 0

    # ------------------------------------------------------------------ worlds
    def sample(self, states: np.ndarray, w: int, seeds: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(worlds [n * w], bad [n], u [n]): w uniform consistent worlds for the acting seat of each
        state, state s from the stream seeds[s], as the engine's search draws them. A state without
        a consistent world (bad) gets copies of itself. u: the stream's next uniform number."""
        t0 = time.perf_counter()
        n = len(states)
        states = np.ascontiguousarray(states)
        seeds = np.ascontiguousarray(seeds, np.uint64)
        out, bad, u = np.zeros(n * w, STATE), np.zeros(n, np.uint8), np.zeros(n, np.float64)
        lib.tc_ls_sample_worlds(states.ctypes.data, n, w, seeds.ctypes.data, 0, 0.0, out.ctypes.data, bad.ctypes.data,
                                u.ctypes.data)
        self.seconds["worlds"] += time.perf_counter() - t0
        return out, bad, u

    def log_weights(self, worlds: np.ndarray, logits, temperature: float, eps: float, block: int = 4096) -> np.ndarray:
        """Per world: the log-likelihood of the other three seats' past unforced choices, replayed
        in that world: sum of log((1 - eps) softmax(logits / T)[action] + eps / legal). -inf where
        the history cannot be replayed. `logits(feat, mask)`: masked logits on a device."""
        import torch
        n = len(worlds)
        fb, mb = self.lanes[0].buf.fb, self.lanes[0].buf.mb
        out = np.zeros(n, np.float64)
        worlds = np.ascontiguousarray(worlds)
        for a in range(0, n, block):
            m = min(block, n - a)
            feat = np.zeros((m * HISTORY_STRIDE, fb), np.uint8)
            mask = np.zeros((m * HISTORY_STRIDE, mb), np.uint8)
            action = np.zeros(m * HISTORY_STRIDE, np.uint8)
            count = np.zeros(m, np.int32)
            lib.tc_ls_history(worlds[a:a + m].ctypes.data, m, self.encoder, HISTORY_STRIDE, feat.ctypes.data,
                              mask.ctypes.data, action.ctypes.data, count.ctypes.data)
            rows = np.flatnonzero((np.arange(HISTORY_STRIDE)[None, :] < count[:, None]).ravel())
            lw = np.zeros(m, np.float64)
            if len(rows):
                with torch.no_grad():
                    q = logits(feat[rows], mask[rows]).float()
                    legal = q > -1e8
                    taken = torch.from_numpy(action[rows].astype(np.int64)).to(q.device)[:, None]
                    p = torch.softmax(q.double() / temperature, 1).gather(1, taken)[:, 0]
                    factor = torch.log((1.0 - eps) * p + eps / legal.sum(1).double())
                    owner = torch.from_numpy(rows // HISTORY_STRIDE).to(q.device)
                    lw = torch.zeros(m, dtype=torch.float64, device=q.device).index_add_(0, owner, factor).cpu().numpy()
            lw[count < 0] = -np.inf
            out[a:a + m] = lw
        return out

    def belief(self, states: np.ndarray, w: int, mult: int, seeds: np.ndarray, logits, temperature: float = 2.0,
               eps: float = 0.5) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """As `sample`, with the engine's play inference (belief_worlds in tuppi_env.c): mult * w
        candidates per state, w of them resampled by their likelihood, systematically, from the
        stream's next draw. A state whose candidates all fail the replay keeps uniform weights."""
        n, m = len(states), w * mult
        cand, bad, u = self.sample(states, m, seeds)
        t0 = time.perf_counter()
        logw = self.log_weights(cand, logits, temperature, eps).reshape(n, m)
        top = logw.max(1, keepdims=True)
        weight = np.where(np.isfinite(logw), np.exp(logw - np.where(np.isfinite(top), top, 0.0)), 0.0)
        weight[weight.sum(1) <= 0] = 1.0
        cum = np.cumsum(weight, 1)
        target = (u[:, None] / w + np.arange(w)[None, :] / w) * cum[:, -1:]
        pick = np.minimum((cum[:, None, :] < target[:, :, None]).sum(2), m - 1)
        # whole records as bytes: a field-wise copy would leave the struct's padding undefined
        rows = (np.arange(n)[:, None] * m + pick).reshape(-1)
        out = np.ascontiguousarray(cand.view(np.uint8).reshape(n * m, STATE.itemsize)[rows]).view(STATE).reshape(-1)
        self.seconds["belief"] += time.perf_counter() - t0
        return out, bad, pick

    # --------------------------------------------------------------- play-outs
    def play(self, worlds: np.ndarray, w: int, cand: np.ndarray, k: np.ndarray, seeds: np.ndarray) -> np.ndarray:
        """q float64 [n, w, max_k]: the acting team's match-equity change of the deal when candidate
        cand[s, j] (j < k[s]) is played in world worlds[s * w + i] and the rollout policy plays the
        rest; 0 beyond k[s]. seeds [n * w]: one stream per world for the heuristics' draws."""
        t0 = time.perf_counter()
        n, max_k = len(k), cand.shape[1]
        worlds = np.ascontiguousarray(worlds)
        cand = np.ascontiguousarray(cand, np.int32)
        k = np.ascontiguousarray(k, np.int32)
        seeds = np.ascontiguousarray(seeds, np.uint64)
        need = np.cumsum(w * k.astype(np.int64))
        q = np.zeros((n, w, max_k), np.float64)
        sign = np.where((worlds["cur"][::w] & 1) == 0, 1.0, -1.0)
        previous = native._offer_model
        native.set_offer_model(self.offer_model)
        try:
            pos = 0
            while pos < n:
                parts = []
                for lane in self.lanes:
                    base = need[pos - 1] if pos else 0
                    end = int(np.searchsorted(need, base + lane.env.n, side="right"))
                    if end > pos:
                        lane.begin(worlds[pos * w:end * w], end - pos, w, cand[pos:end], k[pos:end], seeds[pos * w:end * w])
                        parts.append((lane, pos, end))
                        pos = end
                    if pos >= n:
                        break
                if not parts:
                    raise ValueError("one decision's play-outs do not fit a lane: raise lane_games")
                active = [lane for lane, _, _ in parts if lane.advance(self.rollout, self.dd_left)]
                while active:
                    for lane in list(active):
                        lane.apply(self.rollout)
                        if not lane.advance(self.rollout, self.dd_left):
                            active.remove(lane)
                for lane, a, b in parts:
                    self.games += lane.games
                    start = 0
                    for s in range(a, b):
                        ks = int(k[s])
                        q[s, :, :ks] = sign[s] * lane.buf.total[start:start + w * ks].reshape(w, ks)
                        start += w * ks
        finally:
            native.set_offer_model(previous)
        self.seconds["play"] += time.perf_counter() - t0
        return q

    def counts(self) -> dict:
        return {"games": self.games, "rows": sum(lane.rows for lane in self.lanes),
                "net_rows": sum(lane.net_rows for lane in self.lanes)}

    def reset_counts(self) -> None:
        self.games = 0
        self.seconds = dict.fromkeys(self.seconds, 0.0)
        for lane in self.lanes:
            lane.rows = lane.net_rows = 0


def candidates(anchor, feat, mask, top: int, min_prob: float):
    """(anchor action [r], candidates int32 [r, MAX_K] with the anchor first, count [r], legal count [r]):
    the network's greedy move, then its most probable other moves, at most `top` in all, each with
    at least `min_prob` of its probability. `anchor`: a `lockstep.TorchGreedy`."""
    torch = anchor.torch
    with torch.no_grad():
        logits = anchor._logits(feat, mask)
        a0 = lockstep.greedy(logits)
        p = torch.softmax(logits, 1).scatter(1, a0[:, None], 2.0)
        top = min(top if top > 0 else MAX_K, MAX_K)
        value, ids = p.topk(top, 1)
        k = ((value >= min_prob) & (value > 0)).sum(1)
        legal = (logits > -1e8).sum(1)
    cand = np.zeros((len(feat), MAX_K), np.int32)
    cand[:, :top] = ids.cpu().numpy()
    return a0.cpu().numpy().astype(np.uint8), cand, k.cpu().numpy().astype(np.int32), legal.cpu().numpy()


def decide(q: np.ndarray, k: np.ndarray, keep: np.ndarray, z: float, effective: np.ndarray | None = None
           ) -> tuple[np.ndarray, np.ndarray]:
    """(choice [n], gain [n]): candidate 0 is the anchor. Another candidate is chosen if its mean
    gain over the worlds is above keep[s] and above z paired standard errors; of those, the one
    with the largest mean gain. gain is that mean (0 where the anchor stays). effective [n]: the
    number of independent worlds behind each state's w (fewer after resampling, which repeats
    worlds); default w."""
    n, w, max_k = q.shape
    d = q[:, :, 1:] - q[:, :, :1]
    mean = d.mean(1)
    size = np.full(n, float(w)) if effective is None else np.asarray(effective, np.float64)
    se = d.std(1, ddof=1) / np.sqrt(size)[:, None] if w > 1 else np.zeros_like(mean)
    ok = (np.arange(1, max_k)[None, :] < k[:, None]) & (mean > keep[:, None]) & (mean > z * se)
    score = np.where(ok, mean, -np.inf)
    best = score.argmax(1)
    found = ok.any(1)
    return np.where(found, best + 1, 0), np.where(found, score[np.arange(n), best], 0.0)


def effective_worlds(pick: np.ndarray) -> np.ndarray:
    """For resampled worlds pick [n, w] (the candidate each came from): w^2 / sum of squared
    multiplicities, the number of independent worlds a mean over them is worth."""
    same = (pick[:, :, None] == pick[:, None, :]).sum((1, 2))
    return pick.shape[1] ** 2 / same


class LookAhead:
    """A lockstep chooser: the network's move, unless the look-ahead finds a better one.

    env: the environment of the match it plays in (the states are copied from it). anchor: a
    `lockstep.TorchGreedy` of the network whose move is kept by default (float32, as deployed)."""

    def __init__(self, env: "native.Env", anchor, searcher: Searcher, settings: Settings, seed: int = 0,
                 likelihood=None):
        self.env, self.anchor, self.searcher, self.s = env, anchor, searcher, settings
        self.likelihood = likelihood or anchor    # the chooser whose logits score the worlds (belief)
        self.reset(seed)

    def reset(self, seed: int) -> None:
        """A fresh stream of draws and zeroed counters (one match of a resumable run)."""
        self.rng = np.random.default_rng(seed)
        self.stats = {"decisions": 0, "forced": 0, "searched": 0, "switched": 0, "claimed_gain": 0.0,
                      "no_world": 0, "candidates": 0, "seconds": 0.0}
        self.searcher.reset_counts()

    def candidates(self, feat, mask):
        return candidates(self.anchor, feat, mask, self.s.top, self.s.min_prob)

    def _belief(self, states, w, seeds):
        s = self.s
        return self.searcher.belief(states, w, s.belief, seeds, self.likelihood._logits, s.belief_t, s.belief_eps)

    def __call__(self, feat, mask, idx, team):
        t0 = time.perf_counter()
        s, st = self.s, self.stats
        actions, cand, k, legal = self.candidates(feat, mask)
        showing = actions >= FIRST_SHOW_ACTION
        rows = np.flatnonzero((k > 1) & (s.show | ~showing))
        st["decisions"] += len(idx)
        st["forced"] += int((legal == 1).sum())
        if len(rows):
            games = np.ascontiguousarray(np.asarray(idx)[rows], np.int32)
            states = np.zeros(len(rows), STATE)
            lib.tc_ls_copy_states(self.env._h, games.ctypes.data, len(rows), states.ctypes.data)
            # all draws up front, in row order: the result does not depend on lanes or chunks
            state_seeds = self.rng.integers(1, 2**63, len(rows), dtype=np.uint64)
            world_seeds = self.rng.integers(1, 2**63, len(rows) * s.worlds, dtype=np.uint64)
            inferred = ~showing[rows] & (states["soolaaja"] < 0) if s.belief > 1 else np.zeros(len(rows), bool)
            worlds, bad = np.zeros(len(rows) * s.worlds, STATE), np.zeros(len(rows), np.uint8)
            effective = np.full(len(rows), float(s.worlds))
            for part, draw in ((np.flatnonzero(~inferred), self.searcher.sample), (np.flatnonzero(inferred), self._belief)):
                if len(part):
                    wp, bad[part], extra = draw(states[part], s.worlds, state_seeds[part])
                    worlds.reshape(len(rows), s.worlds)[part] = wp.reshape(len(part), s.worlds)
                    if draw == self._belief:   # resampling repeats worlds: fewer independent ones
                        effective[part] = effective_worlds(extra)
            kc = np.where(bad > 0, 1, k[rows]).astype(np.int32)   # no consistent world: the anchor stays
            q = self.searcher.play(worlds, s.worlds, cand[rows], kc, world_seeds)
            keep = np.where(showing[rows], s.keep_show, s.keep)
            choice, gain = decide(q, kc, keep, s.z, effective)
            actions[rows] = cand[rows, choice]
            st["searched"] += len(rows)
            st["candidates"] += int(kc.sum())
            st["switched"] += int((choice > 0).sum())
            st["claimed_gain"] += float(gain.sum())
            st["no_world"] += int(bad.sum())
        st["seconds"] += time.perf_counter() - t0
        return actions, None


# ------------------------------------------------------------------ the match
def build(net, dev, settings: Settings, env: "native.Env", table: np.ndarray, rollout_net=None, amp=None,
          lanes: int = 2, lane_games: int = 65536, heuristic_sooli: bool = True, offer_model=None,
          seed: int = 0, likelihood_net=None) -> LookAhead:
    """The look-ahead chooser for matches in `env`: `net` is the anchor (float32); the play-outs
    are played by `rollout_net` (default: the same network) under autocast `amp`. With play
    inference the worlds are scored by `likelihood_net` in float32, or, if none is given, by the
    play-out network as the play-outs run it."""
    rollout = lockstep.TorchGreedy(rollout_net if rollout_net is not None else net, dev, net.encoder, amp=amp)
    searcher = Searcher(table, rollout, net.encoder, lanes, lane_games, heuristic_sooli, settings.dd_left, offer_model)
    likelihood = lockstep.TorchGreedy(likelihood_net, dev, net.encoder) if likelihood_net is not None else rollout
    return LookAhead(env, lockstep.TorchGreedy(net, dev, net.encoder), searcher, settings, seed, likelihood=likelihood)


def measure(out: Path, net_name: str, settings: Settings, base: int = 1024, chunk: int = 64, seed: int = 20261126,
            rollout_name: str = "", opponent_name: str = "", dev=None, amp_name: str = "", lanes: int = 2,
            lane_games: int = 65536, sooli_play: str = "heuristic", offer_model_path: str = "", hours: float = 0.0,
            log=print, plain: bool = False, opponent_rollout_name: str = "", likelihood_name: str = "",
            opponent_likelihood_name: str = "") -> dict:
    """Side A (anchor `net_name`, with the look-ahead unless `plain`) against side B (the network
    `opponent_name`, default the anchor itself; with the same look-ahead settings and the play-out
    network `opponent_rollout_name` if that is given, else plain). `likelihood_name` /
    `opponent_likelihood_name`: the network that scores worlds for play inference on that side
    (default: its play-out network). `base` base deals in chunks of `chunk`, resumable in `out`.
    Returns the summary that is also written to out/summary.json."""
    from . import offer, symmetry
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity

    if plain and not opponent_rollout_name:
        raise SystemExit("two plain networks: use tuppi_train.evaluate")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dev = dev or device.pick()
    device.setup(dev)
    amp_name = amp_name or ("fp16" if dev.type == "cuda" else "off")
    config = {"net": net_name, "rollout": "" if plain else rollout_name or net_name, "opponent": opponent_name or net_name,
              "opponent_rollout": opponent_rollout_name, "settings": asdict(settings), "chunk": chunk, "seed": seed,
              "amp": amp_name, "sooli_play": sooli_play, "offer_model": bool(offer_model_path),
              "likelihood": "" if plain else likelihood_name,
              "opponent_likelihood": opponent_likelihood_name if opponent_rollout_name else ""}
    cfg_path, log_path = out / "config.json", out / "chunks.jsonl"
    if cfg_path.exists():
        # a run started before an option existed had that option's default
        old = {"opponent_rollout": "", "likelihood": "", "opponent_likelihood": "", **json.loads(cfg_path.read_text())}
        if old != config:
            raise SystemExit(f"{out} holds a run with other settings; use another --out\n  there: {old}\n  now:   {config}")
    cfg_path.write_text(json.dumps(config, indent=1))
    done = [json.loads(line) for line in log_path.read_text().splitlines()] if log_path.exists() else []

    native.set_showing_fix(True)   # worlds honour what a fallback show implies (best.py, B0-S1)
    native.set_offer_model(None)   # the match itself is played with the exact sooli-offer heuristic
    heur = sooli_play == "heuristic"
    table = Equity.load(EQUITY).table
    nets: dict = {}

    def load(name):
        if name not in nets:
            nets[name] = symmetry.load_net(name, dev)
        return nets[name]

    net, opponent = load(net_name), load(opponent_name or net_name)
    env = native.Env(8 * chunk, 1, table, single_deal=True, encoder=net.encoder)
    env.set_sooli(0, False, heur, 0.0)
    offer_model = offer.load_native(offer_model_path) if offer_model_path else None

    def side(anchor, rollout_name_, searching, likelihood_name_):
        if not searching:
            return lockstep.TorchGreedy(anchor, dev, anchor.encoder)
        return build(anchor, dev, settings, env, table, load(rollout_name_) if rollout_name_ else None,
                     device.AMP[amp_name], lanes, lane_games, heur, offer_model,
                     likelihood_net=load(likelihood_name_) if likelihood_name_ else None)

    a = side(net, rollout_name, not plain, likelihood_name)
    b = side(opponent, opponent_rollout_name, bool(opponent_rollout_name), opponent_likelihood_name)
    looks = [x for x in (a, b) if isinstance(x, LookAhead)]
    describe = lambda name, roll, searching: (f"{name} with look-ahead (play-outs by {roll or name})" if searching  # noqa: E731
                                              else f"plain {name}")
    log(f"A: {describe(net_name, rollout_name, not plain)}")
    log(f"B: {describe(config['opponent'], opponent_rollout_name, bool(opponent_rollout_name))}")
    log(f"settings {json.dumps(asdict(settings))}")
    log(f"device {device.describe(dev)}, engine threads {tn.threads()}, play-outs in {amp_name}, {lanes} lanes of "
        f"{lane_games:,} games")
    t_start = time.perf_counter()
    for c in range(len(done), (base + chunk - 1) // chunk):
        if hours > 0 and time.perf_counter() - t_start > hours * 3600:
            log("time is up; run the same command again to continue")
            break
        for j, look in enumerate(looks):
            look.reset(seed + 7919 * c + 104729 * j)
        t0 = time.perf_counter()
        values = lockstep.duplicate_eval(env, a, b, chunk, 3, C.c_uint64(seed + c), net.encoder)
        counts = [look.searcher.counts() for look in looks]
        wall = time.perf_counter() - t0
        # seconds: the whole match. search_seconds: inside the look-ahead of every searching side.
        row = {**looks[0].stats, **{key: sum(x[key] for x in counts) for key in counts[0]},
               "chunk": c, "values": [float(v) for v in values], "seconds": wall,
               "search_seconds": sum(look.stats["seconds"] for look in looks),
               "parts": {key: sum(look.searcher.seconds[key] for look in looks) for key in looks[0].searcher.seconds},
               "threads": tn.threads()}
        with open(log_path, "a") as f:
            f.write(json.dumps(row) + "\n")
        done.append(row)
        log(brief(summary(done)))
    result = summary(done)
    result["config"] = config
    (out / "summary.json").write_text(json.dumps(result, indent=1))
    return result


def summary(chunks: list) -> dict:
    values = np.array([v for c in chunks for v in c["values"]])
    total = {key: sum(c[key] for c in chunks) for key in
             ("seconds", "decisions", "forced", "searched", "switched", "claimed_gain", "no_world", "candidates",
              "games", "rows", "net_rows")}
    mean, half = lockstep.interval(values) if len(values) > 1 else (float("nan"), float("nan"))
    games = 8 * len(values)
    return {"base_deals": int(len(values)), "mean": mean, "ci95": half, **total,
            "changed_base_deals": float((values != 0).mean()) if len(values) else 0.0,
            "claimed_per_deal": total["claimed_gain"] / games if games else 0.0,
            "rows_per_s": total["rows"] / total["seconds"] if total["seconds"] else 0.0}


def brief(r: dict) -> str:
    choices = max(1, r["decisions"] - r["forced"])
    return (f"{r['base_deals']:6d} base deals | A minus B {r['mean']:+.5f} +/- {r['ci95']:.5f} per deal | "
            f"searched {r['searched'] / choices:.0%} of free decisions, changed {r['switched'] / max(1, r['searched']):.1%} "
            f"of those | its own estimate {r['claimed_per_deal']:+.5f} | {r['seconds'] / 60:.1f} min, "
            f"{r['rows_per_s'] / 1e3:.0f}k play-out rows/s")


def verdict(r: dict) -> str:
    lo, hi = r["mean"] - r["ci95"], r["mean"] + r["ci95"]
    if lo > 0:
        return f"VERDICT: A beats B by {r['mean']:+.5f} per deal (95% interval {lo:+.5f} to {hi:+.5f})."
    if hi < 0:
        return f"VERDICT: B beats A by {-r['mean']:+.5f} per deal (95% interval {-hi:+.5f} to {-lo:+.5f})."
    if hi < 0.001 and lo > -0.001:
        return f"VERDICT: no difference worth having: {r['mean']:+.5f} per deal, interval {lo:+.5f} to {hi:+.5f}."
    return f"VERDICT: undecided: {r['mean']:+.5f} per deal, interval {lo:+.5f} to {hi:+.5f}. More base deals would settle it."


def main(argv=None) -> None:
    d = Settings()
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--net", required=True, help="the network: the anchor, and the opponents")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--rollout", default="", help="play-out network (default: --net)")
    p.add_argument("--opponent", default="", help="the network on the other side (default: --net)")
    p.add_argument("--opponent-rollout", default="", help="the other side looks ahead too, with this play-out network")
    p.add_argument("--plain", action="store_true", help="side A plays --net without the look-ahead")
    p.add_argument("--likelihood", default="", help="with --belief: the network that scores side A's worlds "
                   "(float32; default: its play-out network)")
    p.add_argument("--opponent-likelihood", default="", help="the same for the other side's look-ahead")
    p.add_argument("--base", type=int, default=1024)
    p.add_argument("--chunk", type=int, default=64, help="base deals per match (8 games each)")
    p.add_argument("--seed", type=int, default=20261126)
    p.add_argument("--hours", type=float, default=0.0, help="stop after this long (0 = until --base is reached)")
    p.add_argument("--worlds", type=int, default=d.worlds)
    p.add_argument("--top", type=int, default=d.top)
    p.add_argument("--min-prob", type=float, default=d.min_prob)
    p.add_argument("--keep", type=float, default=d.keep)
    p.add_argument("--keep-show", type=float, default=d.keep_show)
    p.add_argument("--z", type=float, default=d.z)
    p.add_argument("--no-show", action="store_true", help="no look-ahead at showing decisions")
    p.add_argument("--dd", type=int, default=d.dd_left)
    p.add_argument("--belief", type=int, default=d.belief)
    p.add_argument("--lanes", type=int, default=2)
    p.add_argument("--lane-games", type=int, default=65536)
    p.add_argument("--amp", default="", choices=["", "off", "bf16", "fp16"])
    p.add_argument("--sooli-play", default="heuristic", choices=["heuristic", "solver"])
    p.add_argument("--offer-model", default="", help="fast sooli-offer model for the play-outs")
    p.add_argument("--threads", type=int, default=0, help="engine threads (0 = every CPU the process may use)")
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    tn.use_cpus(a.threads)
    settings = Settings(worlds=a.worlds, top=a.top, min_prob=a.min_prob, keep=a.keep, keep_show=a.keep_show, z=a.z,
                        show=not a.no_show, dd_left=a.dd, belief=a.belief)
    r = measure(a.out, a.net, settings, a.base, a.chunk, a.seed, a.rollout, a.opponent, device.pick(a.device), a.amp,
                a.lanes, a.lane_games, a.sooli_play, a.offer_model, a.hours, plain=a.plain,
                opponent_rollout_name=a.opponent_rollout, likelihood_name=a.likelihood,
                opponent_likelihood_name=a.opponent_likelihood)
    print(verdict(r) if r["base_deals"] > 1 else "nothing played")


if __name__ == "__main__":
    main()
