"""Four isolated arms of the current bot. No production imports or training.

Imported after bootstrap selects the frozen engine and private runtime.
All values/margins below are equity units. Sooli paths retain the baseline.
"""
from __future__ import annotations

import ctypes as C
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

from tuppi_ai import best, model, native
from tuppi_ai.search import SearchAgent

ARMS = ("baseline", "hard_anchor", "suit_ensemble", "reward_bucket", "same_net")
PERMS = ((0, 1, 2, 3), (1, 0, 2, 3), (0, 1, 3, 2), (1, 0, 3, 2))


def map_card(card, permutation):
    return 13 * permutation[card // 13] + card % 13


def map_action(action, permutation):
    if action < 52:
        return map_card(action, permutation)
    if action < 156:
        contract, card = divmod(action - 52, 52)
        return 52 + 52 * contract + map_card(card, permutation)
    raise ValueError("Ordinary actor ensemble supports only play/show actions")


def permute_observation(obs, permutation):
    if tuple(sorted(permutation)) != (0, 1, 2, 3) or any((s < 2) != (permutation[s] < 2) for s in range(4)):
        raise ValueError("Full-game actor swaps must preserve suit colour")
    out = native.TcObs.from_buffer_copy(bytes(obs))
    out.hand = sum(1 << map_card(c, permutation) for c in range(52) if obs.hand >> c & 1)
    # Only visible prefixes are transformed; no hidden world is supplied.
    for i in range(obs.n_shows):
        out.show_card[i] = map_card(obs.show_card[i], permutation)
    for i in range(obs.n_played):
        out.play_card[i] = map_card(obs.play_card[i], permutation)
    for name in ("known_given", "known_returned"):
        card = getattr(obs, name)
        if card >= 0:
            setattr(out, name, map_card(card, permutation))
    return out


def adaptive(searcher, obs, actions, batch, z, delta, *, offsets=None, preferred=None):
    """Current E7 arithmetic, with opt-in offsets and sample-count recording.

    Null offsets follow the original leader and elimination arithmetic. World
    caps are validated before native work; this programme uses divisible caps.
    """
    k = len(actions)
    if k < 1 or batch < 2 or searcher.worlds < batch or searcher.worlds % batch:
        raise ValueError("Adaptive worlds must be positive multiples of batch >= 2")
    if offsets is not None and (len(offsets) != k or not np.isfinite(offsets).all()):
        raise ValueError("Finite offsets must match the action count")
    if preferred is not None and not 0 <= preferred < k:
        raise ValueError("Invalid preferred index")
    active, cols, drawn = list(range(k)), [[] for _ in actions], 0
    while True:
        per_world = native.search_world_values(searcher.env, searcher.mlp, obs, [actions[i] for i in active],
                                               batch, searcher.dd_left, searcher.rng)
        for j, i in enumerate(active):
            cols[i].append(per_world[:, j])
        drawn += batch
        x = {i: np.concatenate(cols[i]) for i in active}
        means = {i: float(x[i].mean()) for i in active}
        if offsets is None:
            lead = max(active, key=lambda i: (means[i], -i))
        else:
            lead = max(active, key=lambda i: (means[i] + offsets[i], i == preferred, -i))
        if len(active) == 1 or drawn >= searcher.worlds:
            break
        keep, settled = [], True
        for i in active:
            if i == lead:
                keep.append(i)
                continue
            d = x[lead] - x[i]
            gap, se = float(d.mean()), float(d.std(ddof=1) / np.sqrt(len(d)))
            if offsets is not None:
                gap += offsets[lead] - offsets[i]
            if gap - z * se > 0:
                continue
            keep.append(i)
            if -gap + z * se >= delta:
                settled = False
        active = keep
        if settled:
            break
    searcher.last_action_worlds = [sum(len(v) for v in xs) for xs in cols]
    return np.array([float(np.concatenate(xs).mean()) for xs in cols]), lead, drawn


class AnalysisAgent(SearchAgent):
    def choose_action(self, observation):
        self.last_world_counts = None
        self.last_anchor = None
        self._integrated_bid = False
        # The ordinary baseline uses E7 only for bids. Record that path without
        # changing its arithmetic; fixed and sooli prices have the full count.
        for searcher in (self.searcher, self.show_searcher):
            if searcher is not None:
                searcher.last_action_worlds = None
        result = super().choose_action(observation)
        if self.last_values is not None:
            searcher = self.show_searcher if self.show_searcher and observation.phase.value == "SHOWING" else self.searcher
            counts = getattr(searcher, "last_action_worlds", None)
            self.last_world_counts = dict(zip(self.last_values, counts)) if counts else {a: searcher.worlds for a in self.last_values}
        return result

    def _search(self, searcher, obs, ids):
        if self.adaptive and searcher.mlp is not None and (obs.phase == native.PH_SHOW or self.adaptive.get("play", False)):
            cfg = self.adaptive
            offsets, preferred = None, None
            if self.arm == "hard_anchor" and obs.phase == native.PH_SHOW:
                margin = self.keep_show if self.keep_show is not None else self.keep
                native.encode(obs, self._feat[0], self.blueprint_net.encoder)
                with torch.no_grad():
                    q = self.blueprint_net(torch.from_numpy(self._feat))[0].numpy()
                preferred = int(np.argmax([q[i] for i in ids]))
                offsets = np.zeros(len(ids), dtype=np.float64)
                offsets[preferred] = margin
                self.last_anchor = ids[preferred]
                self._integrated_bid = True
            values, chosen, _ = adaptive(searcher, obs, ids, int(cfg["batch"]), float(cfg["z"]), float(cfg["delta"]),
                                         offsets=offsets, preferred=preferred)
            return values, chosen
        return super()._search(searcher, obs, ids)

    def _keep_blueprint(self, obs, ids, values, best_index):
        if self._integrated_bid:
            return best_index  # selected surviving leader; never reselect stale Q
        if self.arm != "suit_ensemble":
            return super()._keep_blueprint(obs, ids, values, best_index)
        margin = self.keep_show if obs.phase == native.PH_SHOW and self.keep_show is not None else self.keep
        if margin is None:
            return best_index
        features = np.stack([native.encode(permute_observation(obs, p), encoder=self.blueprint_net.encoder) for p in PERMS])
        logits = self.anchor_mlp.forward(features)
        legal = np.array([[map_action(a, p) for a in ids] for p in PERMS])
        scores = logits[np.arange(4)[:, None], legal].astype(np.float64)
        scores -= scores.max(axis=1, keepdims=True)
        probs = np.exp(scores)
        probs /= probs.sum(axis=1, keepdims=True)
        anchor = int(np.argmax(probs.mean(axis=0)))
        self.last_anchor = ids[anchor]
        return anchor if values[anchor] >= values[best_index] - margin else best_index


@lru_cache(maxsize=4)
def loaded(path):
    return model.load(Path(path), "cpu")


@lru_cache(maxsize=1)
def equity():
    from tuppi_ai.equity import Equity
    return Equity.load(best.EQUITY)


def agents(arm, worlds=1024, seed=0, seats=range(4)):
    if arm not in ARMS or worlds < 1 or worlds > 4096:
        raise ValueError("Unknown arm or unsupported world cap")
    if worlds > 128 and worlds % 128:
        raise ValueError("Above W128, use multiples of 128")
    native.set_showing_fix(True)
    net = loaded(str(best.OPPONENT_ROLLOUT))
    team = loaded(str(best.TEAM_ROLLOUT))
    anchor = loaded(str(best.ANCHOR))
    if arm == "same_net" and net is not team:
        raise ValueError("Identical-model arm requires exactly the same frozen model")
    shared = native.Mlp(net) if arm == "same_net" else None
    anchor_mlp = native.Mlp(anchor) if arm == "suit_ensemble" else None
    result = {}
    for seat in seats:
        agent = AnalysisAgent(net, equity().table, seat, worlds=worlds, dd_left=best.SOLVER_TAIL,
                              search_showing=1, seed=seed + seat,
                              adaptive=best.ADAPTIVE_BIDS if worlds > 128 else None,
                              team_net=None if arm == "same_net" else team,
                              shared_mlp=shared, keep=best.KEEP, blueprint_net=anchor,
                              rami_bonus=-best.RAMI_MARGIN, keep_show=best.KEEP_SHOW)
        agent.arm, agent.anchor_mlp = arm, anchor_mlp
        result[seat] = agent
    return result


def configure_native(arm, serial=True):
    native.set_parallel(not serial)
    native.set_rollout_chunk(32)  # product chunk; changed batching is its own arm
    native.set_dd_extra_nolo(0)
    native.set_showing_fix(True)
    if arm == "reward_bucket":
        setter = getattr(native.lib, "tc_set_reward_buckets", None)
        if setter is None:
            raise RuntimeError("Reward-bucket arm requires the isolated candidate library")
        setter.argtypes = [C.c_int]
        setter(1)
    elif hasattr(native.lib, "tc_set_reward_buckets"):
        native.lib.tc_set_reward_buckets(0)
