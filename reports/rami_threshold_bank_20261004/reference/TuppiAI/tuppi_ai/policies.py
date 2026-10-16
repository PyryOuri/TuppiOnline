"""Batched policies over native features, and their engine-agent wrappers.

A policy maps (features, legal mask, phase) for a batch of decisions to action
ids. `Greedy` is argmax of one network; `Conservative` follows a blueprint
network unless a learned Q-network rates another legal action better than the
blueprint's own choice by more than `margin` (in RETURN_SCALE units), which
guards against the optimism of maximising over noisy estimates.

Spec strings (used by the evaluators):
    <ckpt>                                      greedy
    cons:<q_ckpt>:<blueprint_ckpt>[:m=0.05][:show=bp|q]
"""

from __future__ import annotations

import numpy as np
import torch

from . import model as qmodel
from . import native


def _q(net, feat: np.ndarray, device="cpu") -> np.ndarray:
    with torch.no_grad():
        return net(torch.from_numpy(feat).to(device)).cpu().numpy()


class Greedy:
    def __init__(self, net, device="cpu"):
        self.net, self.device = net, device
        self.encoder = net.encoder

    def act(self, feat, mask, phase):
        q = _q(self.net, feat, self.device)
        return np.where(mask == 1, q, -np.inf).argmax(1)


class Conservative:
    def __init__(self, qnet, blueprint, margin: float = 0.05, show: str = "bp", device="cpu"):
        if qnet.encoder != blueprint.encoder:
            raise ValueError("Q-network and blueprint must share an encoder")
        self.qnet, self.bp, self.margin, self.show, self.device = qnet, blueprint, margin, show, device
        self.encoder = qnet.encoder

    def act(self, feat, mask, phase):
        q = np.where(mask == 1, _q(self.qnet, feat, self.device), -np.inf)
        b = np.where(mask == 1, _q(self.bp, feat, self.device), -np.inf)
        bp_act = b.argmax(1)
        q_act = q.argmax(1)
        gain = q[np.arange(len(q)), q_act] - q[np.arange(len(q)), bp_act]
        use_q = gain > self.margin
        if self.show == "bp":
            use_q &= phase != native.PH_SHOW
        return np.where(use_q, q_act, bp_act)


def from_spec(spec: str, device="cpu"):
    if spec.startswith("cons:"):
        parts = spec.split(":")[1:]
        opts = dict(p.split("=") for p in parts[2:])
        return Conservative(qmodel.load(parts[0], device), qmodel.load(parts[1], device),
                            margin=float(opts.get("m", 0.05)), show=opts.get("show", "bp"), device=device)
    return Greedy(qmodel.load(spec, device), device)


class PolicyAgent:
    """Engine-interface agent for any batched policy (one decision at a time)."""

    def __init__(self, policy, seat: int):
        from .bridge import obs_from_player_observation  # noqa: F401  (import check)
        self.policy, self.seat = policy, seat
        self._feat = np.zeros((1, native.feature_dim(policy.encoder)), dtype=np.uint8)
        self._mask = np.zeros((1, native.NUM_ACTIONS), dtype=np.uint8)

    def choose_action(self, observation):
        from .bridge import action_id, obs_from_player_observation

        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        native.encode(obs, self._feat[0], self.policy.encoder)
        self._mask[:] = 0
        ids = [action_id(a) for a in legal]
        self._mask[0, ids] = 1
        a = int(self.policy.act(self._feat, self._mask, np.array([obs.phase]))[0])
        return legal[ids.index(a)]
