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
# project_target_v2 (sooli): phases and the action ids outside the network head.
PH_SOOLI_OFFER, PH_SOOLI_GIVE, PH_SOOLI_RETURN, PH_SOOLI_PLAY = 3, 4, 5, 6
SOOLI_PHASES = (PH_SOOLI_OFFER, PH_SOOLI_GIVE, PH_SOOLI_RETURN, PH_SOOLI_PLAY)
ACT_SOOLI_DECLINE, ACT_SOOLI_ACCEPT, ACT_EXCHANGE = 156, 157, 158
NUM_ACTIONS_V2 = 210
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
        ("ruleset", C.c_uint8), ("trick_size", C.c_uint8), ("n_decisions", C.c_uint8),
        ("decision_seat", C.c_uint8 * 2), ("decision_accept", C.c_uint8 * 2),
        ("soolaaja", C.c_int8), ("given", C.c_int8), ("returned", C.c_int8),
        ("sooli_won", C.c_uint8),
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
        ("ruleset", C.c_uint8), ("trick_size", C.c_uint8), ("n_decisions", C.c_uint8),
        ("decision_seat", C.c_uint8 * 2), ("decision_accept", C.c_uint8 * 2),
        ("soolaaja", C.c_int8), ("known_given", C.c_int8), ("known_returned", C.c_int8),
    ]


_P = C.POINTER
lib.tc_deal_init.argtypes = [_P(TcDeal), _P(C.c_uint64), C.c_int, C.c_int, C.c_int]
lib.tc_deal_init_v.argtypes = [_P(TcDeal), _P(C.c_uint64), C.c_int, C.c_int, C.c_int, C.c_int]
lib.tc_struct_sizes.argtypes = [_P(C.c_int)]
lib.tc_sooli_solve.argtypes = [_P(TcDeal)]
lib.tc_sooli_solve.restype = C.c_int
lib.tc_sooli_move_values.argtypes = [_P(TcDeal), _P(C.c_int), C.c_int, _P(C.c_int)]
lib.tc_sooli_move_values.restype = C.c_int
lib.tc_sooli_finish.argtypes = [_P(TcDeal)]
lib.tc_sooli_nodes.restype = C.c_long
lib.tc_sooli_policy.argtypes = [_P(TcObs), _P(C.c_uint64)]
lib.tc_sooli_policy.restype = C.c_int
lib.tc_sooli_offer_prefilter.argtypes = [C.c_uint64]
lib.tc_sooli_offer_prefilter.restype = C.c_int
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
lib.tc_env_set_sooli.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_double]
lib.tc_sample_world_sooli.argtypes = [_P(TcObs), _P(C.c_uint64), _P(TcDeal), C.c_int, C.c_double]
lib.tc_sample_world_sooli.restype = C.c_int
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
lib.tc_env_hands.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p]
lib.tc_sample_world_weighted.argtypes = [_P(TcObs), C.c_void_p, _P(C.c_uint64), _P(TcDeal)]
lib.tc_sample_world_weighted.restype = C.c_int
lib.tc_mlp_new.argtypes = [C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_void_p]
lib.tc_mlp_new.restype = C.c_void_p
lib.tc_mlp_free.argtypes = [C.c_void_p]
lib.tc_mlp_forward.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p]
lib.tc_search_values.argtypes = [C.c_void_p, C.c_void_p, _P(TcObs), C.c_void_p, C.c_int, C.c_int, C.c_int,
                                 _P(C.c_uint64), C.c_void_p]
lib.tc_search_values.restype = C.c_int
lib.tc_sample_world.argtypes = [_P(TcObs), _P(C.c_uint64), _P(TcDeal)]
lib.tc_sample_world.restype = C.c_int

FEATURE_DIM = lib.tc_feature_dim()

_sizes = (C.c_int * 2)()
lib.tc_struct_sizes(_sizes)
if (_sizes[0], _sizes[1]) != (C.sizeof(TcDeal), C.sizeof(TcObs)):
    raise ImportError(f"libtuppi struct layout mismatch: native {tuple(_sizes)}, "
                      f"ctypes {(C.sizeof(TcDeal), C.sizeof(TcObs))}; rebuild native/")


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


def sample_world_weighted(obs: TcObs, weights: np.ndarray, rng_state: C.c_uint64) -> TcDeal | None:
    """Exact draw from prod_c weights[c, relative_seat - 1] over hard-feasible worlds."""
    w = np.ascontiguousarray(weights, dtype=np.float32).reshape(52, 3)
    world = TcDeal()
    if lib.tc_sample_world_weighted(C.byref(obs), w.ctypes.data, C.byref(rng_state), C.byref(world)) != 0:
        return None
    return world


def sample_world(obs: TcObs, rng_state: C.c_uint64) -> TcDeal | None:
    world = TcDeal()
    if lib.tc_sample_world(C.byref(obs), C.byref(rng_state), C.byref(world)) != 0:
        return None
    return world


def legal(deal: TcDeal) -> list[int]:
    buf = (C.c_int * NUM_ACTIONS_V2)()
    k = lib.tc_legal(C.byref(deal), buf)
    return list(buf[:k])


def sooli_solve(deal: TcDeal) -> int:
    """1 if the soolaaja survives under perfect-information play, 0 if not, -1 outside sooli play."""
    return lib.tc_sooli_solve(C.byref(deal))


def sooli_move_values(deal: TcDeal, actions: list[int]) -> list[int]:
    acts = (C.c_int * len(actions))(*actions)
    out = (C.c_int * len(actions))()
    if lib.tc_sooli_move_values(C.byref(deal), acts, len(actions), out) != 0:
        raise ValueError("not in sooli play, or an illegal action")
    return list(out)


def sooli_policy(obs: TcObs, rng_state: C.c_uint64) -> int:
    """The observation-only sooli heuristic's action (tuppi_sooli_policy.c)."""
    a = lib.tc_sooli_policy(C.byref(obs), C.byref(rng_state))
    if a < 0:
        raise ValueError("not a sooli decision")
    return a


def legal_obs(obs: TcObs) -> list[int]:
    buf = (C.c_int * NUM_ACTIONS_V2)()
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


def new_deal(hands_masks, dealer: int, score0: int = 0, score1: int = 0, ruleset: int = 1) -> TcDeal:
    deal = TcDeal()
    arr = (C.c_uint64 * 4)(*hands_masks)
    lib.tc_deal_init_v(C.byref(deal), arr, dealer, score0, score1, ruleset)
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

    def set_sooli(self, belief: int = 0, return_pi: bool = False, play_heur: bool = False,
                  lam: float = 0.0) -> None:
        """Search options for sooli decisions (see tc_sample_world_sooli, resolve_sooli)."""
        lib.tc_env_set_sooli(self._h, belief, int(return_pi), int(play_heur), float(lam))

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

    def hands(self) -> tuple[np.ndarray, np.ndarray]:
        """(n, 4) uint64 hands and current actors - research labelling only."""
        h = np.zeros((self.n, 4), dtype=np.uint64)
        a = np.zeros(self.n, dtype=np.int32)
        lib.tc_env_hands(self._h, h.ctypes.data, a.ctypes.data)
        return h, a

    def reset_all(self) -> None:
        lib.tc_env_reset_all(self._h)

    def __del__(self):
        h = getattr(self, "_h", None)
        if h:
            lib.tc_env_free(h)
            self._h = None


class Mlp:
    """A QNet's weights in native memory, for rollouts without Python."""

    def __init__(self, net):
        sd = {k: v.detach().cpu().float().numpy() for k, v in net.state_dict().items()}
        cfg = net.config
        parts = [sd["inp.weight"], sd["inp.bias"]]
        for b in range(cfg["blocks"]):
            for name in ("norm.weight", "norm.bias", "fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"):
                parts.append(sd[f"blocks.{b}.{name}"])
        parts += [sd["norm.weight"], sd["norm.bias"], sd["out.weight"], sd["out.bias"]]
        flat = np.ascontiguousarray(np.concatenate([p.ravel() for p in parts]), dtype=np.float32)
        self.encoder = cfg.get("encoder", 1)
        self.width = cfg["width"]
        self._h = lib.tc_mlp_new(feature_dim(self.encoder), cfg["width"], cfg["blocks"], NUM_ACTIONS,
                                 self.encoder, flat.ctypes.data)
        if not self._h:
            raise ValueError("unsupported network shape")

    def forward(self, feat: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(feat, dtype=np.uint8)
        out = np.zeros((len(x), NUM_ACTIONS), dtype=np.float32)
        lib.tc_mlp_forward(self._h, x.ctypes.data, len(x), out.ctypes.data)
        return out

    def __del__(self):
        h = getattr(self, "_h", None)
        if h:
            lib.tc_mlp_free(h)
            self._h = None


lib.tc_search_world_values.argtypes = [C.c_void_p, C.c_void_p, _P(TcObs), C.c_void_p, C.c_int, C.c_int, C.c_int,
                                       _P(C.c_uint64), C.c_void_p, C.c_void_p]
lib.tc_search_world_values.restype = C.c_int


def search_world_values(env: "Env", mlp: Mlp, obs: TcObs, actions, worlds: int, dd_left: int,
                        rng_state: C.c_uint64) -> np.ndarray:
    """(worlds, actions) values, observer's sign; the same worlds for every action."""
    a = np.ascontiguousarray(actions, dtype=np.int32)
    mean = np.zeros(len(a), dtype=np.float64)
    out = np.zeros((worlds, len(a)), dtype=np.float64)
    rc = lib.tc_search_world_values(env._h, mlp._h, C.byref(obs), a.ctypes.data, len(a), worlds, dd_left,
                                    C.byref(rng_state), mean.ctypes.data, out.ctypes.data)
    if rc != 0:
        raise RuntimeError(f"native search failed ({rc})")
    return out


def search_values(env: "Env", mlp: Mlp, obs: TcObs, actions, worlds: int, dd_left: int,
                  rng_state: C.c_uint64) -> np.ndarray:
    a = np.ascontiguousarray(actions, dtype=np.int32)
    out = np.zeros(len(a), dtype=np.float64)
    rc = lib.tc_search_values(env._h, mlp._h, C.byref(obs), a.ctypes.data, len(a), worlds, dd_left,
                              C.byref(rng_state), out.ctypes.data)
    if rc != 0:
        raise RuntimeError(f"native search failed ({rc})")
    return out
