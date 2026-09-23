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
    """`belief` > 1 enables policy-based inference: that many times `worlds`
    candidate worlds are drawn, each weighted by the blueprint's likelihood of
    the other three seats' past unforced choices (softmax at `belief_t`, mixed
    with uniform at `belief_eps`), and `worlds` of them are resampled by weight.
    """

    def __init__(self, net: qmodel.QNet, equity_table: np.ndarray, worlds: int = 32,
                 dd_left: int = 0, seed: int = 0, max_actions: int = 26, belief: int = 0,
                 belief_t: float = 1.0, belief_eps: float = 0.1, belief_seats: str = "all",
                 belief_net=None, belief_n: int = 1024, belief_alpha: float = 0.5, team_net=None,
                 opp_temp: float = 0.0):
        self.net = net
        self.worlds = worlds
        self.dd_left = dd_left
        self.belief, self.belief_t, self.belief_eps = belief, belief_t, belief_eps
        self.belief_seats = belief_seats
        # Learned card-location belief: uniform candidates reweighted by the
        # product of the network's per-card probabilities, tempered by alpha.
        self.belief_net, self.belief_n, self.belief_alpha = belief_net, belief_n, belief_alpha
        self.last_ess = None
        # Optional different rollout policy for the searching seat's own team.
        self.team_net = team_net
        # If > 0, opponents' rollout moves are sampled from softmax(logits / opp_temp)
        # instead of taken greedily: less reliance on predicting them exactly.
        self.opp_temp = opp_temp
        self.np_rng = np.random.default_rng(seed)
        self._hf = np.zeros((64, native.feature_dim(net.encoder)), dtype=np.uint8)
        self._hm = np.zeros((64, native.NUM_ACTIONS), dtype=np.uint8)
        self._ha = np.zeros(64, dtype=np.int32)
        self.env = native.Env(worlds * max_actions, seed, equity_table, single_deal=True,
                              encoder=net.encoder)
        self.rng = C.c_uint64(seed * 2654435761 + 1)

    def action_values(self, obs: native.TcObs, actions: list[int]) -> np.ndarray:
        k, w = len(actions), self.worlds
        env = self.env
        worlds = self.sample_worlds(obs, w)
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
            feat, mask, seat, _ = env.observe()
            with torch.no_grad():
                x = torch.from_numpy(feat)
                q = self.net(x).numpy()
                if self.team_net is not None:
                    mine = (seat & 1) == me_team
                    if mine.any():
                        q[mine] = self.team_net(torch.from_numpy(feat[mine])).numpy()
                qm = np.where(mask == 1, q, -np.inf)
                acts = qm.argmax(1).astype(np.int32)
                if self.opp_temp > 0:
                    opp = (seat & 1) != me_team
                    if opp.any():
                        z = qm[opp] / self.opp_temp
                        z -= z.max(1, keepdims=True)
                        pr = np.exp(z)
                        pr /= pr.sum(1, keepdims=True)
                        u = self.np_rng.random((len(pr), 1))
                        acts[opp] = (pr.cumsum(1) < u).sum(1).astype(np.int32)
            acts[mask.sum(axis=1) == 0] = 0
            env.step(acts)
            self._collect(total, live, n)
        values = total.reshape(w, k).mean(axis=0)
        return values if me_team == 0 else -values

    def _direct_belief_worlds(self, obs: native.TcObs, w: int) -> list:
        """Exact draws from the tempered product of the network's card marginals."""
        feat = native.encode(obs, encoder=self.belief_net.encoder)[None]
        with torch.no_grad():
            p = torch.softmax(self.belief_net(torch.from_numpy(feat)), dim=2)[0].numpy()
        wt = p ** self.belief_alpha
        worlds = []
        for _ in range(w):
            world = native.sample_world_weighted(obs, wt, self.rng)
            if world is None:  # belief and constraints disagree completely: fall back
                world = native.sample_world(obs, self.rng)
            worlds.append(world)
        return worlds

    def _learned_belief_worlds(self, obs: native.TcObs, w: int) -> list:
        if self.belief_n <= 0:
            return self._direct_belief_worlds(obs, w)
        n = self.belief_n
        cands = []
        while len(cands) < n:
            world = native.sample_world(obs, self.rng)
            if world is None:
                raise RuntimeError("no world consistent with the observation")
            cands.append(world)
        feat = native.encode(obs, encoder=self.belief_net.encoder)[None]
        with torch.no_grad():
            logp = torch.log_softmax(self.belief_net(torch.from_numpy(feat)), dim=2)[0].numpy()  # (52, 3)
        hands = np.array([[c.hand[(obs.seat + r) & 3] for r in (1, 2, 3)] for c in cands], dtype=np.uint64)
        bits = np.unpackbits(hands.view(np.uint8).reshape(n, 3, 8), axis=2, bitorder="little")[:, :, :52]
        # log p of each candidate's placement: sum over cards held by others
        lw = self.belief_alpha * np.einsum("nrc,cr->n", bits.astype(np.float32), logp)
        wts = np.exp(lw - lw.max())
        wts /= wts.sum()
        self.last_ess = 1.0 / float(np.sum(wts ** 2))
        # Systematic resampling keeps duplicates to the minimum the weights force.
        u = (self.np_rng.random() + np.arange(w)) / w
        pick = np.minimum(np.searchsorted(np.cumsum(wts), u), n - 1)
        return [cands[i] for i in pick]

    def sample_worlds(self, obs: native.TcObs, w: int) -> list:
        if self.belief_net is not None:
            return self._learned_belief_worlds(obs, w)
        n = w * self.belief if self.belief > 1 else w
        cands = []
        while len(cands) < n:
            world = native.sample_world(obs, self.rng)
            if world is None:
                raise RuntimeError("no world consistent with the observation")
            cands.append(world)
        if self.belief <= 1:
            return cands
        others = 0b1111 & ~(1 << obs.seat)
        if self.belief_seats == "opp":
            others &= ~(1 << ((obs.seat + 2) & 3))
        feats, masks, acts, owner = [], [], [], []
        for i, world in enumerate(cands):
            r = native.history_rows(world, others, self.net.encoder, self._hf, self._hm, self._ha)
            if r > 0:
                feats.append(self._hf[:r].copy()); masks.append(self._hm[:r].copy())
                acts.append(self._ha[:r].copy()); owner.append(np.full(r, i))
        if not feats:
            return cands[:w]
        f, m, a, o = (np.concatenate(x) for x in (feats, masks, acts, owner))
        with torch.no_grad():
            logits = self.net(torch.from_numpy(f)).numpy() / self.belief_t
        logits = np.where(m == 1, logits, -np.inf)
        logits -= logits.max(1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(1, keepdims=True)
        k = m.sum(1)
        taken = (1 - self.belief_eps) * p[np.arange(len(a)), a] + self.belief_eps / k
        logw = np.zeros(n)
        np.add.at(logw, o, np.log(taken))
        wts = np.exp(logw - logw.max())
        wts /= wts.sum()
        pick = self.np_rng.choice(n, size=w, replace=True, p=wts)
        return [cands[i] for i in pick]

    def _collect(self, total, live, n):
        done = self.env.done[:n].astype(bool)
        total[done] += self.env.delta0[:n][done]
        live[done] = False


class SearchAgent:
    """Engine-interface agent: blueprint for showing, search for trick play."""

    def __init__(self, net, equity_table, seat: int, worlds: int = 32, dd_left: int = 0,
                 search_showing=False, seed: int = 0, keep: float | None = None,
                 show_worlds: int | None = None, rami_bonus: float = 0.0, **belief):
        """search_showing: False (blueprint shows), True/1 (search every legal show), or 2
        (search only the blueprint's preferred card for each contract, then keep
        the blueprint's card within the chosen contract)."""
        self.seat = seat
        self.net = net
        self.search_showing = search_showing
        self.keep = keep  # None: plain argmax; >= 0: keep the blueprint's action unless beaten by more
        # Added to the value of declaring RAMI (RETURN_SCALE units): the rollouts
        # play the rest of the deal with the clone, which undervalues contracts
        # this agent's own (better) play would make.
        self.rami_bonus = rami_bonus
        self.searcher = Searcher(net, equity_table, worlds=worlds, dd_left=dd_left, seed=seed + seat, **belief)
        self.show_searcher = None
        if show_worlds and show_worlds != worlds:
            self.show_searcher = Searcher(net, equity_table, worlds=show_worlds, dd_left=dd_left,
                                          seed=seed + seat + 17, **belief)
        self._feat = np.zeros((1, native.feature_dim(net.encoder)), dtype=np.uint8)

    def choose_action(self, observation):
        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        searcher = self.show_searcher if (obs.phase == native.PH_SHOW and self.show_searcher) else self.searcher
        if obs.phase == native.PH_SHOW and self.search_showing != 1 and self.search_showing is not True:
            native.encode(obs, self._feat[0], self.net.encoder)
            with torch.no_grad():
                q = self.net(torch.from_numpy(self._feat))[0].numpy()
            if not self.search_showing:
                return legal[int(np.argmax([q[i] for i in ids]))]
            # Two-stage: one representative card per contract, chosen by the blueprint.
            reps = []
            for contract in (0, 1):
                cands = [i for i in ids if (i - 52) // 52 == contract]
                if cands:
                    reps.append(max(cands, key=lambda i: q[i]))
            if len(reps) == 1:
                return legal[ids.index(reps[0])]
            values = searcher.action_values(obs, reps)
            return legal[ids.index(reps[int(np.argmax(values))])]
        values = searcher.action_values(obs, ids)
        if self.rami_bonus and obs.phase == native.PH_SHOW:
            values = values + self.rami_bonus * np.array([1.0 if i >= 104 else 0.0 for i in ids])
        best = int(np.argmax(values))
        if self.keep is not None:
            native.encode(obs, self._feat[0], self.net.encoder)
            with torch.no_grad():
                q = self.net(torch.from_numpy(self._feat))[0].numpy()
            bp = int(np.argmax([q[i] for i in ids]))
            if values[bp] >= values[best] - self.keep:
                best = bp
        return legal[best]
