"""ctypes bindings for the platform's qualified native library."""

from __future__ import annotations

import ctypes as C
import os
import sys
from pathlib import Path

import numpy as np

_LIB_PATH = Path(os.environ.get("TUPPI_NATIVE_LIBRARY", str(
    Path(__file__).resolve().parents[1] / "native" /
    ("libtuppi.dylib" if sys.platform == "darwin" else "libtuppi.so")
)))
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
class _Absent:
    """Stands in for a symbol that an older library build lacks (the research
    comparator builds of native/research); declaring its types is a no-op and
    calling it raises."""

    def __init__(self, name: str):
        object.__setattr__(self, "name", name)

    def __setattr__(self, key, value):
        pass

    def __call__(self, *args):
        raise AttributeError(f"{self.name} is not in {lib._name}")


def _sym(name: str):
    """A library function whose types are declared only if this build has it (later additions)."""
    return getattr(lib, name) if hasattr(lib, name) else _Absent(name)


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
lib.tc_env_set_exact_speed.argtypes = [C.c_void_p, C.c_int]
lib.tc_env_set_sooli.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_double]
lib.tc_set_rollout_chunk.argtypes = [C.c_int]
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

    _BUFFER_DTYPES = {
        "feat": np.uint8, "mask": np.uint8, "seat": np.int32,
        "phase": np.int32, "done": np.int32, "delta0": np.float32,
        "info": np.int32,
    }

    def __init__(self, n: int, seed: int, equity: np.ndarray | None = None,
                 p_random_start: float = 0.0, single_deal: bool = False, encoder: int = 1):
        self.n = n
        self.encoder = encoder
        self._h = lib.tc_env_new(n, seed)
        lib.tc_env_set_encoder(self._h, encoder)
        if equity is not None:
            self.set_equity(equity)
        lib.tc_env_set_options(self._h, float(p_random_start), int(single_deal))

    def __getattr__(self, name):
        # Native root search never uses the Python stepping buffers. Preserve
        # their public array API, allocating each buffer only when requested.
        dtype = self._BUFFER_DTYPES.get(name)
        if dtype is None:
            raise AttributeError(name)
        width = {"feat": feature_dim(self.encoder), "mask": NUM_ACTIONS, "info": 8}.get(name)
        shape = (self.n,) if width is None else (self.n, width)
        value = np.zeros(shape, dtype=dtype)
        setattr(self, name, value)
        return value

    def set_sooli(self, belief: int = 0, return_pi: bool = False, play_heur: bool = False,
                  lam: float = 0.0) -> None:
        """Search options for sooli decisions (see tc_sample_world_sooli, resolve_sooli)."""
        lib.tc_env_set_sooli(self._h, belief, int(return_pi), int(play_heur), float(lam))

    def set_value(self, vnet: "Mlp | None", leaf_bid: int = -1, leaf_play: int = -1, bot_bit: bool = False) -> None:
        """Value leaf for searches in this environment (docs/VALUE_NET_PLAN.md); None switches it off."""
        self._vnet = vnet  # keep the native weights alive
        lib.tc_env_set_value(self._h, vnet._h if vnet is not None else None, leaf_bid, leaf_play, int(bot_bit))

    def set_team_rollout(self, mlp: "Mlp | None") -> None:
        """Search rollouts: the searching team's own seats play `mlp`, the others the search's net."""
        self._team_mlp = mlp
        lib.tc_env_set_team_rollout(self._h, mlp._h if mlp is not None else None)

    def set_exact_speed(self, enabled: bool) -> None:
        """Per-controller reward buckets, chunk 128 and forced-row compaction."""
        lib.tc_env_set_exact_speed(self._h, int(enabled))

    def set_incremental(self, on: bool, width: int = 256) -> None:
        """Self-play only: incremental first layer for networks of this width (not bitwise exact)."""
        lib.tc_env_set_incremental(self._h, int(on), width)

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


def flat_weights(net, out_scale: float = 1.0) -> np.ndarray:
    """A QNet's parameters in tc_mlp_new's order, as one float32 array."""
    sd = {k: v.detach().cpu().float().numpy() for k, v in net.state_dict().items()}
    sd["out.weight"], sd["out.bias"] = sd["out.weight"] * out_scale, sd["out.bias"] * out_scale
    parts = [sd["inp.weight"], sd["inp.bias"]]
    for b in range(net.config["blocks"]):
        for name in ("norm.weight", "norm.bias", "fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"):
            parts.append(sd[f"blocks.{b}.{name}"])
    parts += [sd["norm.weight"], sd["norm.bias"], sd["out.weight"], sd["out.bias"]]
    return np.ascontiguousarray(np.concatenate([p.ravel() for p in parts]), dtype=np.float32)


class Mlp:
    """A QNet's weights in native memory, for rollouts without Python."""

    def __init__(self, net, in_dim: int | None = None, out_dim: int | None = None, out_scale: float = 1.0):
        """`in_dim`/`out_dim` default to the Q-network's; `out_scale` multiplies the outputs."""
        cfg = net.config
        self._create(flat_weights(net, out_scale), cfg["width"], cfg["blocks"], cfg.get("encoder", 1), in_dim, out_dim)

    @classmethod
    def from_flat(cls, flat: np.ndarray, width: int, blocks: int, encoder: int) -> "Mlp":
        """From `flat_weights` output, without PyTorch (the hosted lite bot)."""
        self = cls.__new__(cls)
        self._create(flat, width, blocks, encoder, None, None)
        return self

    def _create(self, flat, width, blocks, encoder, in_dim, out_dim):
        flat = np.ascontiguousarray(flat, dtype=np.float32)
        self.encoder, self.width = encoder, width
        self._h = lib.tc_mlp_new(in_dim or feature_dim(encoder), width, blocks,
                                 out_dim or NUM_ACTIONS, encoder, flat.ctypes.data)
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


_sym("tc_pi_feature_dim").restype = C.c_int
_sym("tc_encode_pi").argtypes = [_P(TcDeal), C.c_int, C.c_void_p]
_sym("tc_env_set_value").argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int]
_sym("tc_value_rollouts").argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int, _P(C.c_uint64), C.c_int,
                                  C.c_void_p, C.c_void_p]
_sym("tc_value_rollouts").restype = C.c_int
PI_DIM = lib.tc_pi_feature_dim() if hasattr(lib, "tc_pi_feature_dim") else 0


def encode_pi(deal: TcDeal, bot_side: bool = False) -> np.ndarray:
    """Full-information value-net features of a trick-boundary position (side to move)."""
    out = np.zeros(PI_DIM, dtype=np.uint8)
    lib.tc_encode_pi(C.byref(deal), int(bot_side), out.ctypes.data)
    return out


def value_rollouts(env: "Env", mlp: "Mlp", games: int, ruleset: int, dd_left: int, rng_state: C.c_uint64,
                   max_rows: int) -> tuple[np.ndarray, np.ndarray]:
    """VN1 training rows: (features [rows, PI_DIM], target equity change for the side to move)."""
    feat = np.zeros((max_rows, PI_DIM), dtype=np.uint8)
    target = np.zeros(max_rows, dtype=np.float32)
    rows = lib.tc_value_rollouts(env._h, mlp._h, games, ruleset, dd_left, C.byref(rng_state), max_rows,
                                 feat.ctypes.data, target.ctypes.data)
    if rows < 0:
        raise RuntimeError(f"value rollouts failed ({rows})")
    return feat[:rows], target[:rows]


_sym("tc_set_parallel").argtypes = [C.c_int]
_sym("tc_env_set_incremental").argtypes = [C.c_void_p, C.c_int, C.c_int]
_sym("tc_set_branch_share").argtypes = [C.c_int]
_sym("tc_env_set_team_rollout").argtypes = [C.c_void_p, C.c_void_p]


def set_branch_share(on: bool) -> None:
    """Branch labels: play out one card per run of rank-equivalent cards and copy its value."""
    lib.tc_set_branch_share(int(on))
_sym("tc_set_offer_model").argtypes = [C.c_void_p]
_offer_model = None


def set_offer_model(mlp: "Mlp | None") -> None:
    """Sooli offers by a fast acceptance model (tuppi_ai/offer_screen.py) instead of
    the exact heuristic, process-wide; None restores the exact heuristic."""
    global _offer_model
    _offer_model = mlp  # keep the native weights alive
    lib.tc_set_offer_model(mlp._h if mlp is not None else None)


def set_parallel(on: bool) -> None:
    """Spread each search over all cores (default) or run it on the calling thread
    (same results; for batch jobs that already run one process per core)."""
    lib.tc_set_parallel(int(on))


if __import__("os").environ.get("TUPPI_AI_SERIAL") == "1":  # batch jobs: one process per core
    set_parallel(False)


_sym("tc_selfplay_states").argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int, _P(C.c_uint64), C.c_double,
                                   C.c_double, C.c_int, C.c_void_p]
_sym("tc_selfplay_states").restype = C.c_int
_sym("tc_branch_values").argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int, _P(C.c_uint64),
                                 C.c_void_p, C.c_void_p, C.c_void_p]
_sym("tc_branch_values").restype = C.c_int
_sym("tc_encode_states").argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.c_void_p]
MAX_K = 26  # at most 26 legal network actions (13 cards x 2 contracts in showing)


_sym("tc_selfplay_states_w").argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int, _P(C.c_uint64), C.c_double,
                                     C.c_double, C.c_void_p, C.c_int, C.c_void_p]
_sym("tc_selfplay_states_w").restype = C.c_int
_sym("tc_record_class").argtypes = [_P(TcDeal)]
_sym("tc_record_class").restype = C.c_int
N_RECORD_CLASSES = 27  # 0 showing, 1 + trick NOLO play, 14 + trick RAMI play


def record_classes(states, n: int) -> np.ndarray:
    """Position class of each state (as tc_record_class), vectorised over the raw state buffer."""
    raw = np.frombuffer(states, dtype=np.uint8).reshape(-1, C.sizeof(TcDeal))[:n]
    phase = raw[:, TcDeal.phase.offset]
    rami = raw[:, TcDeal.contract.offset].view(np.int8) == RAMI
    trick = np.minimum(raw[:, TcDeal.n_played.offset] // 4, 12).astype(np.int8)
    return np.where(phase == PH_SHOW, 0, np.where(rami, 14, 1) + trick).astype(np.int8)


def selfplay_states(env: "Env", mlp: "Mlp", games: int, ruleset: int, rng_state: C.c_uint64, p_record: float,
                    p_random: float, max_states: int, class_mult: np.ndarray | None = None):
    """Full states recorded at random unforced decisions of policy self-play (docs/SELFPLAY_PLAN.md);
    `class_mult` scales the recording probability per position class (importance sampling)."""
    buf = (TcDeal * max_states)()
    cm = None if class_mult is None else np.ascontiguousarray(class_mult, dtype=np.float64)
    n = lib.tc_selfplay_states_w(env._h, mlp._h, games, ruleset, C.byref(rng_state), p_record, p_random,
                                 None if cm is None else cm.ctypes.data, max_states, buf)
    if n < 0:
        raise RuntimeError(f"self-play failed ({n})")
    return buf, n


def branch_values(env: "Env", mlp: "Mlp", states, n: int, dd_left: int, rng_state: C.c_uint64,
                  offset: int = 0):
    """(actions [n, MAX_K], k [n], q [n, MAX_K]): every legal action of states[offset:offset+n] played
    out by the policy; q is the acting team's equity change."""
    actions = np.zeros((n, MAX_K), dtype=np.int32)
    k = np.zeros(n, dtype=np.int32)
    q = np.zeros((n, MAX_K), dtype=np.float32)
    ptr = C.byref(states, offset * C.sizeof(TcDeal))
    rc = lib.tc_branch_values(env._h, mlp._h, ptr, n, MAX_K, dd_left, C.byref(rng_state), actions.ctypes.data,
                              k.ctypes.data, q.ctypes.data)
    if rc != 0:
        raise RuntimeError(f"branch values failed ({rc}); environment too small")
    return actions, k, q


_sym("tc_world_values").argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int,
                                _P(C.c_uint64), C.c_void_p, C.c_void_p, C.c_void_p, C.c_void_p]
_sym("tc_world_values").restype = C.c_int


def world_values(env: "Env", mlp: "Mlp", states, n: int, worlds: int, include_true: bool, dd_left: int,
                 rng_state: C.c_uint64, offset: int = 0):
    """(actions [n, MAX_K], k [n], q [n, MAX_K] mean over worlds, q_true [n, MAX_K]) for
    states[offset:offset+n]: every legal action played out by the policy in `worlds` worlds
    (the true state first if include_true, the rest sampled from the acting seat's observation)."""
    actions = np.zeros((n, MAX_K), dtype=np.int32)
    k = np.zeros(n, dtype=np.int32)
    q = np.zeros((n, MAX_K), dtype=np.float32)
    qt = np.zeros((n, MAX_K), dtype=np.float32)
    rc = lib.tc_world_values(env._h, mlp._h, C.byref(states, offset * C.sizeof(TcDeal)), n, MAX_K, worlds,
                             int(include_true), dd_left, C.byref(rng_state), actions.ctypes.data, k.ctypes.data,
                             q.ctypes.data, qt.ctypes.data)
    if rc != 0:
        raise RuntimeError(f"world values failed ({rc})")
    return actions, k, q, qt


_sym("tc_ppo_rollouts").argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int, _P(C.c_uint64), C.c_double, C.c_int] + \
    [C.c_void_p] * 9
_sym("tc_ppo_rollouts").restype = C.c_int


def ppo_rollouts(env: "Env", mlp: "Mlp", games: int, ruleset: int, rng_state: C.c_uint64, temperature: float = 1.0,
                 max_rows: int | None = None) -> dict:
    """On-policy sampled self-play trajectories for tuppi_ai/vrpo.py (see tc_ppo_rollouts)."""
    max_rows = max_rows or games * 64
    fb = (feature_dim(mlp.encoder) + 7) // 8
    out = {"feat": np.zeros((max_rows, fb), np.uint8), "hidden": np.zeros((max_rows, 3), np.uint64),
           "mask": np.zeros((max_rows, (NUM_ACTIONS + 7) // 8), np.uint8), "action": np.zeros(max_rows, np.uint8),
           "logp": np.zeros(max_rows, np.float32), "team": np.zeros(max_rows, np.int8),
           "deal": np.zeros(max_rows, np.int32), "step": np.zeros(max_rows, np.int16),
           "reward": np.zeros(games, np.float32)}
    n = lib.tc_ppo_rollouts(env._h, mlp._h, games, ruleset, C.byref(rng_state), temperature, max_rows,
                            *(out[k].ctypes.data for k in ("feat", "hidden", "mask", "action", "logp", "team",
                                                          "deal", "step", "reward")))
    if n < 0:
        raise RuntimeError(f"ppo rollouts failed ({n})")
    return {k: (v if k == "reward" else v[:n]) for k, v in out.items()}


def encode_states(states, n: int, encoder: int, offset: int = 0) -> tuple[np.ndarray, np.ndarray]:
    feat = np.zeros((n, feature_dim(encoder)), dtype=np.uint8)
    mask = np.zeros((n, NUM_ACTIONS), dtype=np.uint8)
    lib.tc_encode_states(C.byref(states, offset * C.sizeof(TcDeal)), n, encoder, feat.ctypes.data, mask.ctypes.data)
    return feat, mask


_sym("tc_duplicate_eval").argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int,
                                  _P(C.c_uint64), C.c_void_p]
_sym("tc_duplicate_eval").restype = C.c_int


_sym("tc_set_eval_temperature").argtypes = [C.c_double]


def duplicate_eval(env: "Env", mlp_a: "Mlp", mlp_b: "Mlp", base_deals: int, ruleset: int, rng_state: C.c_uint64,
                   score=(0, 0), dd_left: int = 0, temperature: float = 0.0) -> np.ndarray:
    """Per-base-deal mean equity change of the pair playing mlp_a (8 games per base deal); both sides
    greedy, or sampling from softmax(logits / temperature) if temperature > 0."""
    lib.tc_set_eval_temperature(temperature)
    out = np.zeros(base_deals, dtype=np.float64)
    rc = lib.tc_duplicate_eval(env._h, mlp_a._h, mlp_b._h, base_deals, ruleset, score[0], score[1], dd_left,
                               C.byref(rng_state), out.ctypes.data)
    lib.tc_set_eval_temperature(0.0)
    if rc != 0:
        raise RuntimeError(f"duplicate evaluation failed ({rc})")
    return out


_sym("tc_set_showing_fix").argtypes = [C.c_int]


lib.tc_set_belief.argtypes = [C.c_void_p, C.c_int, C.c_double, C.c_double, C.c_int]
lib.tc_set_belief.restype = None
_belief_model = None  # keeps the action model alive while the search uses it


def set_belief(model: "Mlp | None", mult: int = 4, temperature: float = 2.0, eps: float = 0.5,
               all_seats: bool = True) -> None:
    """Play inference in the native search (research/play-inference-20261016):
    draw mult * w worlds and resample w by `model`'s likelihood of the other
    seats' past choices. None (or mult <= 1) switches it off."""
    global _belief_model
    _belief_model = model if model is not None and mult > 1 else None
    lib.tc_set_belief(_belief_model._h if _belief_model else None, mult, temperature, eps, int(all_seats))


lib.tc_search_worlds.argtypes = [C.c_void_p, _P(TcObs), C.c_int, _P(C.c_uint64), C.c_void_p]
lib.tc_search_worlds.restype = C.c_int


def search_worlds(env: "Env", obs: TcObs, w: int, rng_state: C.c_uint64) -> list:
    """The worlds the native search would roll out at `obs` (belief applied when set)."""
    out = (TcDeal * w)()
    if lib.tc_search_worlds(env._h, C.byref(obs), w, C.byref(rng_state), out) != 0:
        raise RuntimeError("no world consistent with the observation")
    return list(out)


def set_showing_fix(on: bool) -> None:
    """Honour showing-fallback restrictions when sampling worlds (B0-S1; off by default)."""
    lib.tc_set_showing_fix(int(bool(on)))


_sym("tc_set_dd_extra_nolo").argtypes = [C.c_int]


def set_dd_extra_nolo(extra: int) -> None:
    """Extra solver-tail tricks for NOLO contracts in search rollouts (0 = off, the default)."""
    lib.tc_set_dd_extra_nolo(int(extra))


def set_rollout_chunk(chunk: int) -> None:
    """Rollouts per network batch in the search (same moves; 32 = lowest latency,
    128 = least total work, for batch jobs running several processes)."""
    lib.tc_set_rollout_chunk(chunk)
