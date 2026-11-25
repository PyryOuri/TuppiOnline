"""Lockstep self-play: the C engine steps the games, the caller picks the actions.

`native.ppo_rollouts` and `native.duplicate_eval` evaluate the network on the
CPU inside the C loop. Here the loop is in Python and each step is one batch:
`tc_ls_observe` resolves sooli phases and encodes every live game's decision,
a chooser (a network on the GPU, normally) returns one action per row, and
`tc_ls_step` applies them. The games, the rows and the rewards are the ones the
native functions produce; only where the network runs differs.

    rollouts(...)        -> the dict of native.ppo_rollouts
    duplicate_eval(...)  -> the array of native.duplicate_eval

Choosers are callables `choose(feat, mask, idx, team) -> (actions, logp)` on
packed rows (numpy views, valid during the call): `TorchSampler` and
`TorchGreedy` for networks, `NativeGreedy` for the exact CPU forward (tests).
"""

from __future__ import annotations

import ctypes as C
import time

import numpy as np

from . import tn
from tuppi_ai import native

lib = tn.lib


class Buffers:
    """Per-environment scratch arrays for the lockstep calls."""

    def __init__(self, env: "native.Env", encoder: int):
        n = env.n
        self.env, self.encoder = env, encoder
        self.dim = native.feature_dim(encoder)
        self.fb, self.mb = (self.dim + 7) // 8, tn.MASK_BYTES
        self.idx = np.zeros(n, np.int32)
        self.total = np.zeros(n, np.float64)
        self.seconds = np.zeros(2, np.float64)  # sooli, encoding (accumulated)

    def observe(self, n, feat, mask, hidden=None, team=None, offers=None) -> int:
        """Rows for the live games among 0..n-1, written to the given arrays. `offers`:
        (feat, label, counter) to record the prefiltered sooli offers answered in this call."""
        of, ol, oc = offers if offers is not None else (None, None, None)
        k = lib.tc_ls_observe(
            self.env._h, n, self.encoder, self.total.ctypes.data, self.idx.ctypes.data, feat.ctypes.data,
            mask.ctypes.data, hidden.ctypes.data if hidden is not None else None,
            team.ctypes.data if team is not None else None, of.ctypes.data if of is not None else None,
            ol.ctypes.data if ol is not None else None, len(ol) if ol is not None else 0,
            C.byref(oc) if oc is not None else None, self.seconds.ctypes.data)
        if k < 0:
            raise RuntimeError(f"lockstep observe failed ({k})")
        return k

    def step(self, actions: np.ndarray, k: int, burn_rng: bool = False) -> None:
        a = np.ascontiguousarray(actions, dtype=np.uint8)
        bad = lib.tc_ls_step(self.env._h, self.idx.ctypes.data, a.ctypes.data, k, self.total.ctypes.data, int(burn_rng))
        if bad:
            raise RuntimeError(f"{bad} illegal actions in a lockstep step")


def rollouts(env: "native.Env", choose, games: int, ruleset: int, rng_state: C.c_uint64, encoder: int = 2,
             max_rows: int | None = None, burn_rng: bool = False, offers=None, timing: dict | None = None) -> dict:
    """`games` random deals played to the end, every decision of every seat by `choose`.

    Returns what `native.ppo_rollouts` returns: packed `feat`, `hidden`, packed `mask`,
    `action`, `logp`, `team`, `deal`, `step` per decision (forced ones included) and
    `reward` per deal (team 0's match-equity change). Rows are ordered by lockstep
    step and then by deal, which is deterministic whatever the thread count."""
    if games > env.n:
        raise ValueError("environment too small")
    max_rows = max_rows or games * 64
    buf = Buffers(env, encoder)
    out = {"feat": np.zeros((max_rows, buf.fb), np.uint8), "hidden": np.zeros((max_rows, 3), np.uint64),
           "mask": np.zeros((max_rows, buf.mb), np.uint8), "action": np.zeros(max_rows, np.uint8),
           "logp": np.zeros(max_rows, np.float32), "team": np.zeros(max_rows, np.int8),
           "deal": np.zeros(max_rows, np.int32), "step": np.zeros(max_rows, np.int16)}
    if lib.tc_ls_begin(env._h, games, ruleset, C.byref(rng_state)) != 0:
        raise RuntimeError("lockstep begin failed")
    steps = np.zeros(games, np.int16)
    rows, t_choose, t0 = 0, 0.0, time.perf_counter()
    while True:
        if rows + games > max_rows:
            raise RuntimeError("trajectory buffer full; deals would be truncated")
        feat, mask = out["feat"][rows:rows + games], out["mask"][rows:rows + games]
        k = buf.observe(games, feat, mask, out["hidden"][rows:rows + games], out["team"][rows:rows + games], offers)
        if k == 0:
            break
        idx = buf.idx[:k]
        out["deal"][rows:rows + k] = idx
        out["step"][rows:rows + k] = steps[idx]
        steps[idx] += 1
        t1 = time.perf_counter()
        actions, logp = choose(feat[:k], mask[:k], idx, out["team"][rows:rows + k])
        t_choose += time.perf_counter() - t1
        out["action"][rows:rows + k] = actions
        if logp is not None:
            out["logp"][rows:rows + k] = logp
        buf.step(out["action"][rows:rows + k], k, burn_rng)
        rows += k
    if timing is not None:
        timing.update(total=time.perf_counter() - t0, choose=t_choose, sooli=float(buf.seconds[0]),
                      encode=float(buf.seconds[1]), rows=rows)
    res = {key: v[:rows] for key, v in out.items()}
    res["reward"] = buf.total[:games].astype(np.float32)
    return res


def duplicate_eval(env: "native.Env", choose_a, choose_b, base_deals: int, ruleset: int, rng_state: C.c_uint64,
                   encoder: int = 2, score=(0, 0), paired: bool = True, timing: dict | None = None) -> np.ndarray:
    """Per-base-deal mean equity change of the pair playing `choose_a` against `choose_b`
    over the 8 games of each base deal (the design of `native.duplicate_eval`).

    paired=True gives both team assignments of a rotation the same seed for the sooli
    heuristics' draws, so those draws cancel between the two and a policy against itself
    scores exactly 0. paired=False uses the native function's seeds (for comparing with it)."""
    n = 8 * base_deals
    if n > env.n:
        raise ValueError("environment too small")
    buf = Buffers(env, encoder)
    a_team = np.zeros(n, np.int8)
    if lib.tc_ls_begin_duplicate(env._h, base_deals, ruleset, score[0], score[1], int(paired), C.byref(rng_state),
                                 a_team.ctypes.data) != 0:
        raise RuntimeError("lockstep begin failed")
    feat, mask = np.zeros((n, buf.fb), np.uint8), np.zeros((n, buf.mb), np.uint8)
    team, actions = np.zeros(n, np.int8), np.zeros(n, np.uint8)
    rows, t0 = 0, time.perf_counter()
    while True:
        k = buf.observe(n, feat, mask, None, team)
        if k == 0:
            break
        idx = buf.idx[:k]
        is_a = team[:k] == a_team[idx]
        for side, choose in ((is_a, choose_a), (~is_a, choose_b)):
            if side.all():
                actions[:k] = choose(feat[:k], mask[:k], idx, team[:k])[0]
            elif side.any():
                sel = np.nonzero(side)[0]
                actions[sel] = choose(feat[sel], mask[sel], idx[sel], team[sel])[0]
        buf.step(actions, k)
        rows += k
    if timing is not None:
        timing.update(total=time.perf_counter() - t0, sooli=float(buf.seconds[0]), encode=float(buf.seconds[1]),
                      rows=rows)
    signed = np.where(a_team == 0, buf.total[:n], -buf.total[:n])
    return signed.reshape(base_deals, 8).mean(1)


def interval(values: np.ndarray) -> list[float]:
    """[mean, 95% half-width] of per-base-deal values."""
    return [float(values.mean()), float(1.96 * values.std(ddof=1) / np.sqrt(len(values)))]


# ------------------------------------------------------------------ choosers
def unpack_mask(mask: np.ndarray) -> np.ndarray:
    return np.unpackbits(mask, axis=1)[:, :native.NUM_ACTIONS].astype(bool)


class NativeGreedy:
    """Greedy play from the exact CPU forward of a `native.Mlp` (as tc_duplicate_eval)."""

    def __init__(self, mlp: "native.Mlp", encoder: int = 2):
        self.mlp, self.dim = mlp, native.feature_dim(encoder)

    def __call__(self, feat, mask, idx, team):
        x = np.unpackbits(feat, axis=1)[:, :self.dim]
        q = self.mlp.forward(x)
        return np.where(unpack_mask(mask), q, -np.inf).argmax(1).astype(np.uint8), None


class RandomLegal:
    """A uniformly random legal action (engine benchmarks; no network)."""

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)

    def __call__(self, feat, mask, idx, team):
        m = unpack_mask(mask)
        return (self.rng.random(m.shape, dtype=np.float32) * m).argmax(1).astype(np.uint8), None


class Replay:
    """The actions of a recorded rollout dict, looked up by (deal, step)."""

    def __init__(self, recorded: dict, games: int):
        self.table = np.full((games, int(recorded["step"].max()) + 1), 255, np.uint8)
        self.table[recorded["deal"], recorded["step"]] = recorded["action"]
        self.steps = np.zeros(games, np.int64)

    def __call__(self, feat, mask, idx, team):
        a = self.table[idx, self.steps[idx]]
        self.steps[idx] += 1
        return a, None


class _TorchChooser:
    def __init__(self, net, device, encoder: int = 2, chunk: int = 65536):
        import torch

        from tuppi_ai.value import _unpack
        self.torch, self.unpack = torch, _unpack
        self.net, self.device, self.chunk = net, torch.device(device), chunk
        self.dim = native.feature_dim(encoder)

    def _logits(self, feat, mask):
        """Masked logits for packed rows, in chunks, on the device."""
        torch = self.torch
        out = []
        for i in range(0, len(feat), self.chunk):
            f = torch.from_numpy(np.ascontiguousarray(feat[i:i + self.chunk])).to(self.device, non_blocking=True)
            m = torch.from_numpy(np.ascontiguousarray(mask[i:i + self.chunk])).to(self.device, non_blocking=True)
            legal = self.unpack(m, native.NUM_ACTIONS).bool()
            out.append(self.net(self.unpack(f, self.dim)).masked_fill(~legal, -1e9))
        return out[0] if len(out) == 1 else torch.cat(out)


class TorchGreedy(_TorchChooser):
    """Greedy play from a torch network on any device."""

    def __call__(self, feat, mask, idx, team):
        with self.torch.no_grad():
            return self._logits(feat, mask).argmax(1).to(self.torch.uint8).cpu().numpy(), None


class TorchSampler(_TorchChooser):
    """Samples from softmax(logits / temperature) over the legal actions and returns the
    log-probabilities, computed exactly as the learner recomputes them (vrpo `_logits`)."""

    def __init__(self, net, device, temperature: float = 1.0, generator=None, encoder: int = 2,
                 chunk: int = 65536):
        super().__init__(net, device, encoder, chunk)
        self.temperature, self.generator = temperature, generator

    def __call__(self, feat, mask, idx, team):
        torch = self.torch
        with torch.no_grad():
            logp_all = torch.log_softmax(self._logits(feat, mask) / self.temperature, 1)
            a = torch.multinomial(torch.exp(logp_all), 1, generator=self.generator)
            logp = logp_all.gather(1, a)[:, 0]
            return a[:, 0].to(torch.uint8).cpu().numpy(), logp.float().cpu().numpy()
