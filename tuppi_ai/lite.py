"""The hosted lite bot ("L0"): the VRPO3 actor playing greedily, without search.

Qualified in audit_deliverables/tuppi_lite_bot_20261014: about 1/11,000 of
the W1024 search bot's CPU; level with it at W128 and -0.0031 equity per deal
against it at W1024. Owner's decision 2026-10-14: the hosted bot level.

No PyTorch at run time. The weights come from `models/vrpo3_final.lite.npz`,
written by tools/export_lite_model.py in tc_mlp_new's layout. Sooli phases use
the native observation-only heuristics (tuppi_sooli_policy.c), whose only
randomness is the agent's 64-bit cursor `rng`; everything else is deterministic.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path

import numpy as np

from . import native
from .bridge import action_id, obs_from_player_observation

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "vrpo3_final.lite.npz"
_shared: native.Mlp | None = None


def load_mlp(path: Path = MODEL) -> native.Mlp:
    with np.load(path, allow_pickle=False) as blob:
        width, blocks, encoder = (int(x) for x in blob["shape"])
        return native.Mlp.from_flat(blob["weights"], width, blocks, encoder)


def shared_mlp() -> native.Mlp:
    """One immutable network for every lite agent in the process."""
    global _shared
    if _shared is None:
        _shared = load_mlp()
    return _shared


def initial_cursor(seat: int) -> int:
    return (0x9E3779B97F4A7C15 * (seat + 1)) & 0xFFFFFFFFFFFFFFFF


class LiteAgent:
    handles_sooli = True

    def __init__(self, seat: int, mlp: native.Mlp | None = None, rng: int | None = None):
        self.seat = seat
        self.mlp = mlp or shared_mlp()
        self.rng = C.c_uint64(initial_cursor(seat) if rng is None else rng)
        self._feat = np.zeros((1, native.feature_dim(self.mlp.encoder)), dtype=np.uint8)

    def choose_action(self, observation):
        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        if obs.phase in native.SOOLI_PHASES:
            return legal[ids.index(native.sooli_policy(obs, self.rng))]
        native.encode(obs, self._feat[0], self.mlp.encoder)
        q = self.mlp.forward(self._feat)[0]
        return legal[ids.index(max(ids, key=lambda a: (q[a], -a)))]  # first maximum, as an argmax over the mask


def lite_agents(seats=range(4)) -> dict:
    return {s: LiteAgent(s) for s in seats}
