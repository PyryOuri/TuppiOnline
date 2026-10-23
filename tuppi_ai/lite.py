"""The hosted lite bot ("L0"): the VRPO3 actor playing greedily, without search.

Qualified in audit_deliverables/tuppi_lite_bot_20261014: about 1/11,000 of
the W1024 search bot's CPU; level with it at W128 and -0.0031 equity per deal
against it at W1024. Owner's decision 2026-10-14: the hosted bot level.

No PyTorch at run time. The weights come from `models/vrpo3_final.lite.npz`,
written by tools/export_lite_model.py in tc_mlp_new's layout. Sooli phases use
the native observation-only heuristics (tuppi_sooli_policy.c), whose only
randomness is the agent's 64-bit cursor `rng`; everything else is deterministic.

Options (off by default; `LiteOptions`, audit_deliverables/tuppi_faceup_improvements_20261020):

- ``net``: the face-up safety net with play-inference layouts (C1,
  native/tuppi_lite_net.c). In card play with at most ``tricks`` tricks left
  it may replace the network's card; it draws from two more cursors,
  ``gate_rng`` and ``belief_rng``.
- ``sooli_need``: accept a sooli offer when this many of the heuristic's 8
  sampled layouts survive (the heuristic: 4); ``sooli_need_ahead`` and
  ``sooli_need_behind`` override it while the bot's team leads or trails.

C1H reads the moves of seats the host marks as people more loosely
(LiteAgent.set_human_seats); with no person marked it plays exactly as C1.
C1 (the net alone) is the candidate: it gains against the plain lite bot,
older networks and the W128 search bot. D1 (C1 plus ``sooli_need=2``) gains
against the lite bot's own family but loses its sooli part against the search
bot. The options reproduce the research harness's decisions.

``LiteAgent(model=MODEL_V4)`` plays the same bot on the Heidi 1.2 network
(Nelli 1.1 is C1H on it); with ``model=None`` the agent uses ``MODEL`` exactly
as before. Each network file is loaded once per process (``shared_mlp``).
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from . import native
from .bridge import action_id, obs_from_player_observation

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "vrpo3_final.lite.npz"
#: The Heidi 1.2 network (768x4, encoder 2), exported by tools/export_lite_model.py.
MODEL_V4 = ROOT / "models" / "vrpo4_final.lite.npz"
EQUITY = ROOT / "models" / "equity_incumbent.json"
_shared: dict[Path, native.Mlp] = {}
_equity: np.ndarray | None = None


@dataclass(frozen=True)
class LiteOptions:
    net: bool = False
    worlds: int = 16
    tricks: int = 9
    rami_tricks: int = 0
    belief_mult: int = 4
    sooli_need: int = 0
    sooli_need_ahead: int = 0
    sooli_need_behind: int = 0
    #: Read the moves of seats known to be people more loosely in the net's
    #: play inference (people's games: T 4, eps 0.8 predicted the cards best;
    #: audit_deliverables/tuppi_human_games). The host names those seats with
    #: LiteAgent.set_human_seats before each decision.
    human_aware: bool = False
    human_t: float = 4.0
    human_eps: float = 0.8


#: The research candidate C1: the safety net with play inference (robust against the
#: lite bot, two older networks and the W128 search bot).
C1 = LiteOptions(net=True)
#: C1 reading people's moves loosely (human_aware).
C1H = LiteOptions(net=True, human_aware=True)
#: D1: C1 plus sooli at 2 of 8. The sooli part lost against the search bot; kept for reference.
D1 = LiteOptions(net=True, sooli_need=2)

_P = C.POINTER
native.lib.tc_lite_net_applies.argtypes = [_P(native.TcObs), C.c_int, C.c_int]
native.lib.tc_lite_net.argtypes = [C.c_void_p, C.c_void_p, _P(native.TcObs), C.c_int, C.c_int, C.c_int,
                                   _P(C.c_uint64), _P(C.c_uint64)]
native.lib.tc_lite_net_h.argtypes = [C.c_void_p, C.c_void_p, _P(native.TcObs), C.c_int, C.c_int, C.c_int,
                                     C.c_int, C.c_double, C.c_double, _P(C.c_uint64), _P(C.c_uint64)]
native.lib.tc_sooli_offer_need.argtypes = [_P(native.TcObs), _P(C.c_uint64), C.c_int]


def shared_equity() -> np.ndarray:
    """The bot's team-0 match-equity table (25 x 2), as the native code reads it."""
    global _equity
    if _equity is None:
        table = np.ascontiguousarray(json.loads(EQUITY.read_text())["table"], dtype=np.float64)
        if table.shape != (25, 2):
            raise ValueError("unexpected equity table shape")
        _equity = table
    return _equity


def load_mlp(path: Path = MODEL) -> native.Mlp:
    with np.load(path, allow_pickle=False) as blob:
        width, blocks, encoder = (int(x) for x in blob["shape"])
        return native.Mlp.from_flat(blob["weights"], width, blocks, encoder)


def shared_mlp(path: Path = MODEL) -> native.Mlp:
    """One immutable network per file for every lite agent in the process."""
    key = Path(path).resolve()
    mlp = _shared.get(key)
    if mlp is None:
        mlp = _shared[key] = load_mlp(key)
    return mlp


def initial_cursor(seat: int) -> int:
    return (0x9E3779B97F4A7C15 * (seat + 1)) & 0xFFFFFFFFFFFFFFFF


def initial_net_cursors(seat: int) -> tuple[int, int]:
    """The safety net's gate and belief cursors at the start."""
    return 0x5AFE0000 + seat, 0xBE11EF00 + seat


class LiteAgent:
    handles_sooli = True

    def __init__(self, seat: int, mlp: native.Mlp | None = None, rng: int | None = None,
                 options: LiteOptions | None = None, net_rng: tuple[int, int] | None = None,
                 model: Path | str | None = None):
        """`model`: a network file (e.g. MODEL_V4), loaded once through shared_mlp; None keeps MODEL."""
        if mlp is not None and model is not None:
            raise ValueError("pass either mlp or model, not both")
        self.seat = seat
        self.mlp = mlp or (shared_mlp() if model is None else shared_mlp(model))
        self.rng = C.c_uint64(initial_cursor(seat) if rng is None else rng)
        self._feat = np.zeros((1, native.feature_dim(self.mlp.encoder)), dtype=np.uint8)
        self.options = options or LiteOptions()
        gate, belief = initial_net_cursors(seat) if net_rng is None else net_rng
        self.gate_rng, self.belief_rng = C.c_uint64(gate), C.c_uint64(belief)
        if self.options.net:
            self._equity = shared_equity()
        self.human_mask = 0  # seats played by people (bit s = seat s); set by the host

    def set_human_seats(self, seats) -> None:
        """The seats currently played by people (only human_aware options use it)."""
        self.human_mask = sum(1 << s for s in seats if s != self.seat)

    def _sooli_need(self, obs: native.TcObs) -> int:
        o = self.options
        ours, theirs = obs.score[obs.seat & 1], obs.score[(obs.seat & 1) ^ 1]
        if ours > theirs and o.sooli_need_ahead:
            return o.sooli_need_ahead
        if theirs > ours and o.sooli_need_behind:
            return o.sooli_need_behind
        return o.sooli_need

    def greedy_action(self, obs: native.TcObs, ids) -> int:
        """The network's action: the first maximum of its Q over the legal network ids."""
        native.encode(obs, self._feat[0], self.mlp.encoder)
        q = self.mlp.forward(self._feat)[0]
        return max(ids, key=lambda a: (q[a], -a))  # first maximum, as an argmax over the mask

    def choose_action(self, observation):
        legal = observation.legal_actions
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        if obs.phase in native.SOOLI_PHASES:
            need = self._sooli_need(obs) if obs.phase == native.PH_SOOLI_OFFER else 0
            if need:
                return legal[ids.index(native.lib.tc_sooli_offer_need(C.byref(obs), C.byref(self.rng), need))]
            return legal[ids.index(native.sooli_policy(obs, self.rng))]
        action = self.greedy_action(obs, ids)
        o = self.options
        if o.net and native.lib.tc_lite_net_applies(C.byref(obs), o.tricks, o.rami_tricks):
            if o.human_aware and self.human_mask:
                action = native.lib.tc_lite_net_h(self.mlp._h, self._equity.ctypes.data, C.byref(obs), action,
                                                  o.worlds, o.belief_mult, self.human_mask, o.human_t, o.human_eps,
                                                  C.byref(self.gate_rng), C.byref(self.belief_rng))
            else:
                action = native.lib.tc_lite_net(self.mlp._h, self._equity.ctypes.data, C.byref(obs), action,
                                                o.worlds, o.belief_mult, C.byref(self.gate_rng),
                                                C.byref(self.belief_rng))
        return legal[ids.index(action)]


def lite_agents(seats=range(4)) -> dict:
    return {s: LiteAgent(s) for s in seats}
