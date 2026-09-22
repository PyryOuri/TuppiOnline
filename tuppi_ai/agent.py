"""A learned policy that plays through the authoritative engine's agent interface.

`choose_action` receives only the engine's PlayerObservation, converts it with
`bridge.obs_from_player_observation`, and returns one of the observation's own
legal actions.
"""

from __future__ import annotations

import numpy as np
import torch

from . import model as qmodel
from . import native
from .bridge import action_id, obs_from_player_observation


class LearnedAgent:
    def __init__(self, net: qmodel.QNet, seat: int):
        self.net = net
        self.seat = seat
        self._feat = np.zeros((1, native.feature_dim(net.encoder)), dtype=np.uint8)

    @classmethod
    def from_checkpoint(cls, path, seat: int):
        return cls(qmodel.load(path, "cpu"), seat)

    def q_values(self, observation) -> dict:
        native.encode(obs_from_player_observation(observation), self._feat[0], self.net.encoder)
        with torch.no_grad():
            q = self.net(torch.from_numpy(self._feat))[0].numpy()
        return {a: float(q[action_id(a)]) for a in observation.legal_actions}

    def choose_action(self, observation):
        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        values = self.q_values(observation)
        return max(legal, key=lambda a: values[a])
