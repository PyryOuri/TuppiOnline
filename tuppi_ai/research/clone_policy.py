"""Masked encoder-2 deterministic clone policy (cheap fixture policy; C1 reference; C2/C5 model).

The rollout network's greedy choice over the legal actions, from the actor's
own observation only. Two declared tie orders exist and are never mixed:

- "native_id": ascending action id, first maximum (what native rollouts do);
- "engine": the engine's legal-action order, first maximum (what the search
  root and `PolicyAgent` use).

Sooli phases use the observation-only native heuristic `tc_sooli_policy`
with the agent's own seeded scalar stream (the offer heuristic samples).
"""

from __future__ import annotations

import ctypes as C
from functools import lru_cache

import numpy as np

TIE_ORDERS = ("native_id", "engine")


@lru_cache(maxsize=2)
def rollout_network(path: str | None = None):
    """The immutable rollout clone (shared read-only; weights never mutate)."""
    from .. import model as qmodel
    from ..best import ROLLOUT

    return qmodel.load(path or ROLLOUT, "cpu")


def clone_scores(obs, mlp, encoder: int) -> np.ndarray:
    """The network's 156 action scores for one native observation (native forward)."""
    from .. import native

    feat = native.encode(obs, encoder=encoder)[None]
    return mlp.forward(feat)[0]


def preferred(ids: list[int], scores: np.ndarray, tie_order: str) -> int:
    """Index into `ids` of the first maximum under the declared tie order."""
    if tie_order not in TIE_ORDERS:
        raise ValueError(tie_order)
    order = sorted(range(len(ids)), key=lambda i: ids[i]) if tie_order == "native_id" else range(len(ids))
    best = None
    for i in order:
        if best is None or scores[ids[i]] > scores[ids[best]]:
            best = i
    return best


class CloneGreedyAgent:
    """Engine-interface deterministic clone for one seat."""

    handles_sooli = True

    def __init__(self, seat: int, tie_order: str = "native_id", sooli_seed: int = 0):
        from .. import native

        self.seat = seat
        self.tie_order = tie_order
        self.net = rollout_network()
        self.encoder = self.net.encoder
        self.mlp = native.Mlp(self.net)
        self.sooli_rng = C.c_uint64(sooli_seed * 0x9E3779B97F4A7C15 % (1 << 64) + seat + 1)

    def choose_action(self, observation):
        from .. import native
        from ..bridge import action_id, obs_from_player_observation

        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        if obs.phase in native.SOOLI_PHASES:
            return legal[ids.index(native.sooli_policy(obs, self.sooli_rng))]
        return legal[preferred(ids, clone_scores(obs, self.mlp, self.encoder), self.tie_order)]
