"""ctypes bindings for native/libtuppi.dylib."""

from __future__ import annotations

import ctypes as C
from pathlib import Path

import numpy as np

_LIB_PATH = Path(__file__).resolve().parents[1] / "native" / "libtuppi.dylib"
lib = C.CDLL(str(_LIB_PATH))

NUM_ACTIONS = 156
NOLO, RAMI = 0, 1
PH_SHOW, PH_PLAY, PH_DONE = 0, 1, 2
U8x4 = C.c_uint8 * 4
U8x52 = C.c_uint8 * 52


class TcDeal(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64 * 4),
        ("dealer", C.c_uint8), ("phase", C.c_uint8), ("cur", C.c_uint8),
        ("n_shows", C.c_uint8),
        ("show_seat", U8x4), ("show_card", U8x4), ("show_contract", U8x4), ("show_verbal", U8x4),
        ("contract", C.c_int8), ("declarer", C.c_int8),
        ("first_leader", C.c_uint8),
        ("n_played", C.c_uint8),
        ("play_card", U8x52), ("play_seat", U8x52),
        ("team_tricks", C.c_uint8 * 2),
        ("score", C.c_uint8 * 2),
        ("winner_team", C.c_int8), ("points", C.c_uint8), ("stolen", C.c_uint8),
    ]


class TcObs(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64),
        ("seat", C.c_uint8), ("dealer", C.c_uint8), ("phase", C.c_uint8),
        ("n_shows", C.c_uint8),
        ("show_seat", U8x4), ("show_card", U8x4), ("show_contract", U8x4), ("show_verbal", U8x4),
        ("contract", C.c_int8), ("declarer", C.c_int8),
        ("first_leader", C.c_uint8),
        ("n_played", C.c_uint8),
        ("play_card", U8x52), ("play_seat", U8x52),
        ("score", C.c_uint8 * 2),
    ]


_P = C.POINTER
lib.tc_deal_init.argtypes = [_P(TcDeal), _P(C.c_uint64), C.c_int, C.c_int, C.c_int]
lib.tc_legal.argtypes = [_P(TcDeal), _P(C.c_int)]
lib.tc_legal.restype = C.c_int
lib.tc_apply.argtypes = [_P(TcDeal), C.c_int]
lib.tc_apply.restype = C.c_int
lib.tc_next_score.argtypes = [_P(C.c_uint8), C.c_int, C.c_int, _P(C.c_uint8)]
lib.tc_next_score.restype = C.c_int
lib.tc_observe.argtypes = [_P(TcDeal), C.c_int, _P(TcObs)]
lib.tc_legal_obs.argtypes = [_P(TcObs), _P(C.c_int)]
lib.tc_legal_obs.restype = C.c_int
lib.tc_feature_dim.restype = C.c_int
lib.tc_encode.argtypes = [_P(TcObs), _P(C.c_uint8)]
lib.tc_encode_v.argtypes = [_P(TcObs), _P(C.c_uint8), C.c_int]
lib.tc_feature_dim_v.argtypes = [C.c_int]
lib.tc_feature_dim_v.restype = C.c_int
lib.tc_env_set_encoder.argtypes = [C.c_void_p, C.c_int]
lib.tc_valid_show_cards.argtypes = [C.c_uint64, C.c_int]
lib.tc_valid_show_cards.restype = C.c_uint64
lib.tc_verbal_required.argtypes = [C.c_int, C.c_int]
lib.tc_verbal_required.restype = C.c_int

lib.tc_env_new.argtypes = [C.c_int, C.c_uint64]
lib.tc_env_new.restype = C.c_void_p
lib.tc_env_free.argtypes = [C.c_void_p]
lib.tc_env_set_equity.argtypes = [C.c_void_p, _P(C.c_double)]
lib.tc_env_set_options.argtypes = [C.c_void_p, C.c_double, C.c_int]
lib.tc_env_reset_all.argtypes = [C.c_void_p]
lib.tc_env_set_deal.argtypes = [C.c_void_p, C.c_int, _P(C.c_uint64), C.c_int, C.c_int, C.c_int]
lib.tc_env_deal.argtypes = [C.c_void_p, C.c_int]
lib.tc_env_deal.restype = _P(TcDeal)
lib.tc_env_observe.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
lib.tc_env_step.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
lib.tc_env_step.restype = C.c_int

lib.tc_env_set_state.argtypes = [C.c_void_p, C.c_int, _P(TcDeal)]
lib.tc_dd_team0_tricks.argtypes = [_P(TcDeal)]
lib.tc_dd_team0_tricks.restype = C.c_int
lib.tc_env_dd_finish.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_void_p]
lib.tc_env_dd_finish.restype = C.c_int
lib.tc_env_observe_live.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
lib.tc_env_observe_live.restype = C.c_int
lib.tc_env_step_live.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_void_p]
lib.tc_env_set_state_repeat.argtypes = [C.c_void_p, C.c_int, _P(TcDeal), C.c_int]
lib.tc_env_park_all.argtypes = [C.c_void_p]
lib.tc_history_rows.argtypes = [_P(TcDeal), C.c_int, C.c_int, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p]
lib.tc_history_rows.restype = C.c_int
lib.tc_sample_world.argtypes = [_P(TcObs), _P(C.c_uint64), _P(TcDeal)]
lib.tc_sample_world.restype = C.c_int

FEATURE_DIM = lib.tc_feature_dim()


def feature_dim(encoder: int = 1) -> int:
    return lib.tc_feature_dim_v(encoder)


def dd_team0_tricks(deal: TcDeal) -> int:
    """Final team-0 tricks under perfect-information optimal play (late positions)."""
    return lib.tc_dd_team0_tricks(C.byref(deal))


def history_rows(world: TcDeal, seat_mask: int, encoder: int, feat: np.ndarray,
                 mask: np.ndarray, action: np.ndarray) -> int:
    """Past unforced decisions of seats in seat_mask, replayed inside `world`."""
    return lib.tc_history_rows(C.byref(world), seat_mask, encoder, len(action), feat.ctypes.data,
                               mask.ctypes.data, action.ctypes.data)


def sample_world(obs: TcObs, rng_state: C.c_uint64) -> TcDeal | None:
    world = TcDeal()
    if lib.tc_sample_world(C.byref(obs), C.byref(rng_state), C.byref(world)) != 0:
        return None
    return world


def legal(deal: TcDeal) -> list[int]:
    buf = (C.c_int * NUM_ACTIONS)()
    k = lib.tc_legal(C.byref(deal), buf)
    return list(buf[:k])


def legal_obs(obs: TcObs) -> list[int]:
    buf = (C.c_int * NUM_ACTIONS)()
    k = lib.tc_legal_obs(C.byref(obs), buf)
    return list(buf[:k])


def encode(obs: TcObs, out: np.ndarray | None = None, encoder: int = 1) -> np.ndarray:
    if out is None:
        out = np.zeros(feature_dim(encoder), dtype=np.uint8)
    lib.tc_encode_v(C.byref(obs), out.ctypes.data_as(_P(C.c_uint8)), encoder)
    return out


def observe(deal: TcDeal, seat: int) -> TcObs:
    obs = TcObs()
    lib.tc_observe(C.byref(deal), seat, C.byref(obs))
    return obs


def new_deal(hands_masks, dealer: int, score0: int = 0, score1: int = 0) -> TcDeal:
    deal = TcDeal()
    arr = (C.c_uint64 * 4)(*hands_masks)
    lib.tc_deal_init(C.byref(deal), arr, dealer, score0, score1)
    return deal


class Env:
    """N parallel matches in native code, observed and stepped as numpy arrays."""

    def __init__(self, n: int, seed: int, equity: np.ndarray | None = None,
                 p_random_start: float = 0.0, single_deal: bool = False, encoder: int = 1):
        self.n = n
        self.encoder = encoder
        self._h = lib.tc_env_new(n, seed)
        lib.tc_env_set_encoder(self._h, encoder)
        if equity is not None:
            self.set_equity(equity)
        lib.tc_env_set_options(self._h, float(p_random_start), int(single_deal))
        self.feat = np.zeros((n, feature_dim(encoder)), dtype=np.uint8)
        self.mask = np.zeros((n, NUM_ACTIONS), dtype=np.uint8)
        self.seat = np.zeros(n, dtype=np.int32)
        self.phase = np.zeros(n, dtype=np.int32)
        self.done = np.zeros(n, dtype=np.int32)
        self.delta0 = np.zeros(n, dtype=np.float32)
        self.info = np.zeros((n, 8), dtype=np.int32)

    def set_equity(self, equity: np.ndarray) -> None:
        eq = np.ascontiguousarray(equity, dtype=np.float64).reshape(25, 2)
        lib.tc_env_set_equity(self._h, eq.ctypes.data_as(_P(C.c_double)))

    def observe(self):
        lib.tc_env_observe(self._h, self.feat.ctypes.data, self.mask.ctypes.data,
                           self.seat.ctypes.data, self.phase.ctypes.data)
        return self.feat, self.mask, self.seat, self.phase

    def step(self, actions: np.ndarray) -> int:
        a = np.ascontiguousarray(actions, dtype=np.int32)
        return lib.tc_env_step(self._h, a.ctypes.data, self.done.ctypes.data,
                               self.delta0.ctypes.data, self.info.ctypes.data)

    def set_deal(self, i: int, hands_masks, dealer: int, score0: int, score1: int) -> None:
        arr = (C.c_uint64 * 4)(*hands_masks)
        lib.tc_env_set_deal(self._h, i, arr, dealer, score0, score1)

    def dd_finish(self, dd_left: int) -> int:
        return lib.tc_env_dd_finish(self._h, dd_left, self.done.ctypes.data, self.delta0.ctypes.data)

    def observe_live(self):
        """(features, masks, game indices) for live games only, compact."""
        if not hasattr(self, "_idx"):
            self._idx = np.zeros(self.n, dtype=np.int32)
        k = lib.tc_env_observe_live(self._h, self.feat.ctypes.data, self.mask.ctypes.data, self._idx.ctypes.data)
        return self.feat[:k], self.mask[:k], self._idx[:k]

    def step_live(self, idx: np.ndarray, actions: np.ndarray) -> None:
        idx = np.ascontiguousarray(idx, dtype=np.int32)
        a = np.ascontiguousarray(actions, dtype=np.int32)
        self.done[:] = 0
        lib.tc_env_step_live(self._h, idx.ctypes.data, a.ctypes.data, len(idx),
                             self.done.ctypes.data, self.delta0.ctypes.data)

    def set_state_repeat(self, j: int, deal: TcDeal, count: int) -> None:
        lib.tc_env_set_state_repeat(self._h, j, C.byref(deal), count)

    def park_all(self) -> None:
        lib.tc_env_park_all(self._h)

    def set_state(self, i: int, deal: TcDeal) -> None:
        lib.tc_env_set_state(self._h, i, C.byref(deal))

    def deal(self, i: int) -> TcDeal:
        return lib.tc_env_deal(self._h, i).contents

    def reset_all(self) -> None:
        lib.tc_env_reset_all(self._h)

    def __del__(self):
        h = getattr(self, "_h", None)
        if h:
            lib.tc_env_free(h)
            self._h = None
