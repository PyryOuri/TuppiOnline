"""Decision-time search on top of the learned policy (determinized rollouts).

For the acting seat's observation: sample W hidden-hand worlds exactly
uniformly from the hard-feasible set, and for every legal action play each
world to the end with the blueprint network acting greedily for all four seats
(each from its own observation inside that world), optionally finishing the
last `dd_left` tricks with the perfect-information solver. The same worlds
price every action (common random numbers). The action with the best mean
match-equity change for the acting team is chosen.

This is policy improvement over the blueprint, not an equilibrium method: it
inherits PIMC's strategy-fusion caveat, and uniform worlds ignore what the
other players' past choices imply about their hands.
"""

from __future__ import annotations

import ctypes as C

import numpy as np
import torch

from . import model as qmodel
from . import native
from .bridge import action_id, obs_from_player_observation


class Searcher:
    def __init__(self, net: qmodel.QNet, equity_table: np.ndarray, worlds: int = 32,
                 dd_left: int = 0, seed: int = 0, max_actions: int = 26):
        self.net = net
        self.worlds = worlds
        self.dd_left = dd_left
        self.env = native.Env(worlds * max_actions, seed, equity_table, single_deal=True,
                              encoder=net.encoder)
        self.rng = C.c_uint64(seed * 2654435761 + 1)

    def action_values(self, obs: native.TcObs, actions: list[int]) -> np.ndarray:
        k, w = len(actions), self.worlds
        env = self.env
        worlds = []
        while len(worlds) < w:
            world = native.sample_world(obs, self.rng)
            if world is None:
                raise RuntimeError("no world consistent with the observation")
            worlds.append(world)
        n = w * k
        for wi, world in enumerate(worlds):
            for ai in range(k):
                env.set_state(wi * k + ai, world)
        for i in range(n, env.n):  # park unused slots as finished
            env.set_state(i, worlds[0])
            env.deal(i).phase = native.PH_DONE
        me_team = obs.seat & 1
        total = np.zeros(n)
        live = np.ones(n, dtype=bool)
        first = np.array([actions[i % k] for i in range(n)] + [0] * (env.n - n), dtype=np.int32)
        env.step(first)
        self._collect(total, live, n)
        while live.any():
            if self.dd_left:
                env.dd_finish(self.dd_left)
                self._collect(total, live, n)
                if not live.any():
                    break
            feat, mask, _, _ = env.observe()
            with torch.no_grad():
                q = self.net(torch.from_numpy(feat))
                acts = qmodel.masked_argmax(q, torch.from_numpy(mask)).numpy().astype(np.int32)
            acts[mask.sum(axis=1) == 0] = 0
            env.step(acts)
            self._collect(total, live, n)
        values = total.reshape(w, k).mean(axis=0)
        return values if me_team == 0 else -values

    def _collect(self, total, live, n):
        done = self.env.done[:n].astype(bool)
        total[done] += self.env.delta0[:n][done]
        live[done] = False


class SearchAgent:
    """Engine-interface agent: blueprint for showing, search for trick play."""

    def __init__(self, net, equity_table, seat: int, worlds: int = 32, dd_left: int = 0,
                 search_showing: bool = False, seed: int = 0):
        self.seat = seat
        self.net = net
        self.search_showing = search_showing
        self.searcher = Searcher(net, equity_table, worlds=worlds, dd_left=dd_left, seed=seed + seat)
        self._feat = np.zeros((1, native.feature_dim(net.encoder)), dtype=np.uint8)

    def choose_action(self, observation):
        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        if obs.phase == native.PH_SHOW and not self.search_showing:
            native.encode(obs, self._feat[0], self.net.encoder)
            with torch.no_grad():
                q = self.net(torch.from_numpy(self._feat))[0].numpy()
            return legal[int(np.argmax([q[i] for i in ids]))]
        values = self.searcher.action_values(obs, ids)
        return legal[int(np.argmax(values))]
