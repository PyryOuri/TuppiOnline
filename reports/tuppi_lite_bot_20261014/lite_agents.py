"""Agent factories for the Lite programme (PLAN.md). Imports TuppiAI read-only."""
from __future__ import annotations

import ctypes as C
import sys
from pathlib import Path

TUPPIAI = Path('/Users/pyryouri/Developer/TuppiAI')
if str(TUPPIAI) not in sys.path:
    sys.path.insert(0, str(TUPPIAI))

import numpy as np  # noqa: E402

ENDGAME_TRICKS = 6  # L2: tricks left (including the current one) at or below which the controller searches
ENDGAME_WORLDS = 128


class LiteAgent:
    """VRPO3 actor, greedy over legal actions, via the native MLP. Sooli phases use
    the native observation-only heuristics. With `endgame`, trick-play decisions
    with at most ENDGAME_TRICKS tricks left go to that (live-controller) agent."""

    handles_sooli = True

    def __init__(self, seat: int, mlp, encoder: int, endgame=None, seed: int = 0):
        from tuppi_ai import native
        self.native, self.seat, self.mlp, self.encoder, self.endgame = native, seat, mlp, encoder, endgame
        self.feat = np.zeros((1, native.feature_dim(encoder)), dtype=np.uint8)
        self.rng = C.c_uint64((0x9E3779B97F4A7C15 * (seed * 4 + seat + 1)) & 0xFFFFFFFFFFFFFFFF)
        self.counts = {'policy': 0, 'sooli': 0, 'endgame': 0, 'forced': 0}

    def choose_action(self, observation):
        from tuppi_ai.bridge import action_id, obs_from_player_observation
        native = self.native
        legal = observation.legal_actions
        if len(legal) == 1:
            self.counts['forced'] += 1
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        if obs.phase in native.SOOLI_PHASES:
            self.counts['sooli'] += 1
            return legal[ids.index(native.sooli_policy(obs, self.rng))]
        if self.endgame is not None and obs.phase == native.PH_PLAY and 13 - obs.n_played // 4 <= ENDGAME_TRICKS:
            self.counts['endgame'] += 1
            return self.endgame.choose_action(observation)
        self.counts['policy'] += 1
        native.encode(obs, self.feat[0], self.encoder)
        q = self.mlp.forward(self.feat)[0]
        return legal[ids.index(max(ids, key=lambda a: (q[a], -a)))]  # first maximum, as Greedy's argmax


def make(spec: str, seed: int = 0) -> dict:
    """live1024 | live128 | L0 | L2 | profile:<heuristic key>"""
    from tuppi_ai import best
    if spec == 'live1024':
        return best.best_agents(worlds=1024, seed=seed)
    if spec == 'live128':
        return best.best_agents(worlds=128, seed=seed)
    if spec.startswith('profile:'):
        from tuppi_ai.incumbent import incumbent_agents
        return incumbent_agents(spec.split(':', 1)[1])
    if spec in ('L0', 'L2'):
        from tuppi_ai import model as qmodel, native
        net = qmodel.load(best.ANCHOR, 'cpu')
        mlp = native.Mlp(net)  # immutable, shared by the four seats
        end = best.best_agents(worlds=ENDGAME_WORLDS, seed=seed) if spec == 'L2' else {s: None for s in range(4)}
        return {s: LiteAgent(s, mlp, net.encoder, end[s], seed) for s in range(4)}
    raise ValueError(f'unknown spec {spec}')
