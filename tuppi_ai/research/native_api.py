"""Library-specific native ownership and the explicit-world evaluator (C0.04).

Three comparator libraries exist (IMPLEMENTATION_SPEC.md section 1.2):

- B0-installed: `native/libtuppi.dylib`, what the live factory loads;
- B0-source: `native/research/build/source/libtuppi.dylib`, the unmodified
  sources rebuilt with `native/build.sh`'s command;
- R0-parity: `native/research/build/research/libtuppi_research.dylib`, the
  overlay build (every original entrypoint unchanged) plus `research_*` exports.

`bind_native(path)` makes `tuppi_ai.native` - and therefore the unmodified
`Searcher`/`SearchAgent`/`best_agents` code - run on a chosen library in this
process. It must run before anything imports `tuppi_ai.native`; comparisons
between libraries run in separate processes (`probe.py`).

Handles are library-specific: a `ResearchLibrary` accepts only environments and
networks created through the library it wraps (A02). Crossing them raises
`NativeOwnershipError` before any native call.
"""

from __future__ import annotations

import ctypes as C
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .identity import AI_ROOT, INSTALLED_DYLIB, loaded_tuppi_libraries, sha256_file

BUILD_DIR = AI_ROOT / "native" / "research" / "build"
SOURCE_LIB = BUILD_DIR / "source" / "libtuppi.dylib"
RESEARCH_LIB = BUILD_DIR / "research" / "libtuppi_research.dylib"
LIBRARIES = {"B0-installed": INSTALLED_DYLIB, "B0-source": SOURCE_LIB, "R0-parity": RESEARCH_LIB}

API_VERSION = 3
CFG_LEN = 62
MAX_WORLDS = 4096
RS_RECORDED, RS_SOOLI_ILLEGAL, RS_DOUBLE, RS_CERTIFIED = 1, 2, 4, 8
OPT_UTILITY_STOP = 1  # C3b research switch; 0 = the original computation
WORK_NAMES = ("first_actions", "sooli_resolutions", "dd_solves", "mlp_rows", "mlp_batches", "plies", "rounds",
              "certified_rows")
RC_NAMES = {0: "OK", -1: "NO_WORLD", -2: "ENV_TOO_SMALL", -3: "BAD_ACTION", -4: "BAD_DIMS",
            -5: "WORLD_MISMATCH", -6: "NONFINITE", -7: "NULL", -8: "BAD_OBS"}
WORLD_REASONS = {0: "ok", 1: "actor", 2: "projection", 3: "partition", 4: "counts", 5: "void",
                 6: "shown_owner", 7: "range", 8: "trick_totals", 9: "bids", 10: "bad_observation"}

DEAL_FIELDS = ("hand", "dealer", "phase", "cur", "n_shows", "show_seat", "show_card", "show_contract",
               "show_verbal", "contract", "declarer", "first_leader", "n_played", "play_card", "play_seat",
               "team_tricks", "score", "winner_team", "points", "stolen", "ruleset", "trick_size",
               "n_decisions", "decision_seat", "decision_accept", "soolaaja", "given", "returned", "sooli_won")
OBS_FIELDS = ("hand", "seat", "dealer", "phase", "n_shows", "show_seat", "show_card", "show_contract",
              "show_verbal", "contract", "declarer", "first_leader", "n_played", "play_card", "play_seat",
              "score", "ruleset", "trick_size", "n_decisions", "decision_seat", "decision_accept", "soolaaja",
              "known_given", "known_returned")


class NativeOwnershipError(RuntimeError):
    """A handle from one native library was offered to another."""


class NativeCallError(RuntimeError):
    def __init__(self, what: str, code: int, detail: str = ""):
        super().__init__(f"{what} failed: {RC_NAMES.get(code, code)} ({code}){' ' + detail if detail else ''}")
        self.code = code


def bind_native(path: Path | str):
    """Import `tuppi_ai.native` bound to `path` instead of the installed library.

    `tuppi_ai/native.py` is not modified: its one `ctypes.CDLL(<installed>)`
    call is redirected while it is imported. Refuses if the module is already
    bound to a different library, and verifies the mapped images afterwards.
    """
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError(target)
    mod = sys.modules.get("tuppi_ai.native")
    if mod is not None:
        bound = Path(mod.lib._name).resolve()
        if bound != target:
            raise NativeOwnershipError(f"tuppi_ai.native is already bound to {bound}, not {target}")
        return mod
    installed = INSTALLED_DYLIB.resolve()
    original = C.CDLL

    class _Redirect(original):
        def __init__(self, name, *args, **kwargs):
            if name is not None and Path(name).resolve() == installed:
                name = str(target)
            super().__init__(name, *args, **kwargs)

    C.CDLL = _Redirect
    try:
        import tuppi_ai.native as mod  # noqa: PLC0415
    finally:
        C.CDLL = original
    images = loaded_tuppi_libraries()
    if str(target) not in images:
        raise NativeOwnershipError(f"{target} is not mapped after binding: {images}")
    if target != installed and str(installed) in images:
        raise NativeOwnershipError("the installed library was mapped as well")
    return mod


def native_module():
    import tuppi_ai.native as mod  # noqa: PLC0415

    return mod


@dataclass
class OwnedEnv:
    """A native environment created through one specific `ResearchLibrary`."""

    lib_id: str
    _h: int
    n: int
    encoder: int
    _free: object = field(repr=False, default=None)

    def __del__(self):
        if self._h and self._free is not None:
            self._free(self._h)
            self._h = 0


@dataclass
class OwnedMlp:
    lib_id: str
    _h: int
    encoder: int
    _free: object = field(repr=False, default=None)

    def __del__(self):
        if self._h and self._free is not None:
            self._free(self._h)
            self._h = 0


@dataclass(frozen=True)
class WorldEvaluation:
    """values[K] and per_world[W, K] in the observer's sign, plus status and work."""

    actions: tuple[int, ...]
    values: np.ndarray
    per_world: np.ndarray
    row_status: np.ndarray
    work: dict
    cpu_s: float
    wall_s: float

    @property
    def valid(self) -> np.ndarray:
        """Cells whose utility was recorded exactly once and never marked illegal."""
        s = self.row_status
        return ((s & RS_RECORDED) != 0) & ((s & (RS_SOOLI_ILLEGAL | RS_DOUBLE)) == 0)


def flat_mlp_params(net) -> np.ndarray:
    """A QNet's parameters in tc_mlp_new's order (as tuppi_ai.native.Mlp)."""
    sd = {k: v.detach().cpu().float().numpy() for k, v in net.state_dict().items()}
    parts = [sd["inp.weight"], sd["inp.bias"]]
    for b in range(net.config["blocks"]):
        for name in ("norm.weight", "norm.bias", "fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"):
            parts.append(sd[f"blocks.{b}.{name}"])
    parts += [sd["norm.weight"], sd["norm.bias"], sd["out.weight"], sd["out.bias"]]
    return np.ascontiguousarray(np.concatenate([p.ravel() for p in parts]), dtype=np.float32)


class ResearchLibrary:
    """One loaded research build and the handles it owns."""

    def __init__(self, path: Path | str | None = None):
        nat = native_module()
        self.native = nat
        self.path = Path(path).resolve() if path else Path(nat.lib._name).resolve()
        self.sha256 = sha256_file(self.path)
        self.lib_id = f"{self.path.name}:{self.sha256[:16]}"
        self.lib = C.CDLL(str(self.path))
        if not hasattr(self.lib, "research_api_version"):
            raise NativeOwnershipError(f"{self.path} is not a research build (no research_api_version)")
        self._bind()
        if self.lib.research_api_version() != API_VERSION:
            raise NativeOwnershipError("research API version mismatch")
        self.owns_native_module = Path(nat.lib._name).resolve() == self.path
        self.abi = self.check_abi()

    # ------------------------------------------------------------ binding
    def _bind(self) -> None:
        L, P, nat = self.lib, C.POINTER, self.native
        L.research_api_version.restype = C.c_int
        L.research_abi_layout.argtypes = [P(C.c_int64), C.c_int]
        L.research_abi_layout.restype = C.c_int
        L.research_world_consistent.argtypes = [P(nat.TcObs), P(nat.TcDeal)]
        L.research_world_consistent.restype = C.c_int
        L.research_obs_valid.argtypes = [P(nat.TcObs)]
        L.research_obs_valid.restype = C.c_int
        L.research_env_config.argtypes = [C.c_void_p, P(C.c_double), C.c_int]
        L.research_env_config.restype = C.c_int
        L.research_env_import_config.argtypes = [C.c_void_p, P(C.c_double), C.c_int]
        L.research_env_import_config.restype = C.c_int
        L.research_get_rollout_chunk.restype = C.c_int
        L.research_sample_worlds.argtypes = [C.c_void_p, P(nat.TcObs), C.c_int, P(C.c_uint64), P(nat.TcDeal),
                                             C.c_int, P(C.c_int)]
        L.research_sample_worlds.restype = C.c_int
        L.research_trace_search.argtypes = [C.c_void_p, C.c_void_p, P(nat.TcObs), C.c_void_p, C.c_int, C.c_int,
                                            C.c_int, C.c_int, P(C.c_uint64), C.c_void_p, C.c_void_p, C.c_void_p,
                                            C.c_int, P(nat.TcDeal), C.c_int, C.c_void_p]
        L.research_trace_search.restype = C.c_int
        L.research_evaluate_worlds.argtypes = [C.c_void_p, C.c_void_p, P(nat.TcObs), P(nat.TcDeal), C.c_int,
                                               C.c_void_p, C.c_int, C.c_int, C.c_int, P(C.c_uint64), C.c_void_p,
                                               C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, P(C.c_int)]
        L.research_evaluate_worlds.restype = C.c_int
        L.research_row_utility.argtypes = [C.c_void_p, P(nat.TcDeal), C.c_int, P(C.c_float)]
        L.research_row_utility.restype = C.c_int
        L.research_utility_certificate.argtypes = [C.c_void_p, P(nat.TcDeal), P(C.c_float)]
        L.research_utility_certificate.restype = C.c_int
        # Owned-handle constructors (same signatures as tuppi_ai.native).
        L.tc_env_new.argtypes = [C.c_int, C.c_uint64]
        L.tc_env_new.restype = C.c_void_p
        L.tc_env_free.argtypes = [C.c_void_p]
        L.tc_env_set_encoder.argtypes = [C.c_void_p, C.c_int]
        L.tc_env_set_equity.argtypes = [C.c_void_p, P(C.c_double)]
        L.tc_env_set_options.argtypes = [C.c_void_p, C.c_double, C.c_int]
        L.tc_env_set_sooli.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_double]
        L.tc_mlp_new.argtypes = [C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, C.c_void_p]
        L.tc_mlp_new.restype = C.c_void_p
        L.tc_mlp_free.argtypes = [C.c_void_p]
        L.tc_feature_dim_v.argtypes = [C.c_int]
        L.tc_feature_dim_v.restype = C.c_int
        L.tc_struct_sizes.argtypes = [P(C.c_int)]

    def check_abi(self) -> dict:
        """A04: native sizes/offsets/endianness agree with the ctypes structures."""
        buf = (C.c_int64 * 128)()
        n = self.lib.research_abi_layout(buf, 128)
        if n <= 0:
            raise NativeCallError("research_abi_layout", n)
        vals = list(buf[:n])
        nat = self.native
        expect = [API_VERSION, 4 if sys.byteorder == "little" else 1, C.sizeof(nat.TcDeal), len(DEAL_FIELDS)]
        expect += [getattr(nat.TcDeal, f).offset for f in DEAL_FIELDS]
        expect += [C.sizeof(nat.TcObs), len(OBS_FIELDS)]
        expect += [getattr(nat.TcObs, f).offset for f in OBS_FIELDS]
        ctypes_fields = ([name for name, _t in nat.TcDeal._fields_] == list(DEAL_FIELDS)
                         and [name for name, _t in nat.TcObs._fields_] == list(OBS_FIELDS))
        ok = vals == expect and ctypes_fields
        report = {"native": vals, "ctypes": expect, "field_order_matches": ctypes_fields, "agrees": ok,
                  "byteorder": sys.byteorder}
        if not ok:
            raise NativeOwnershipError(f"ABI layout disagrees: {report}")
        return report

    # ------------------------------------------------------------ ownership
    def new_env(self, n: int, seed: int, equity: np.ndarray | None = None, single_deal: bool = True,
                encoder: int = 2) -> OwnedEnv:
        if not 1 <= n <= 1 << 20:
            raise ValueError("environment size out of range")
        h = self.lib.tc_env_new(n, seed)
        self.lib.tc_env_set_encoder(h, encoder)
        if equity is not None:
            eq = np.ascontiguousarray(equity, dtype=np.float64).reshape(25, 2)
            self.lib.tc_env_set_equity(h, eq.ctypes.data_as(C.POINTER(C.c_double)))
        self.lib.tc_env_set_options(h, 0.0, int(single_deal))
        return OwnedEnv(self.lib_id, h, n, encoder, self.lib.tc_env_free)

    def new_mlp(self, net) -> OwnedMlp:
        flat = flat_mlp_params(net)
        enc = net.config.get("encoder", 1)
        h = self.lib.tc_mlp_new(self.lib.tc_feature_dim_v(enc), net.config["width"], net.config["blocks"],
                                self.native.NUM_ACTIONS, enc, flat.ctypes.data)
        if not h:
            raise ValueError("unsupported network shape")
        return OwnedMlp(self.lib_id, h, enc, self.lib.tc_mlp_free)

    def _env(self, env) -> tuple[int, int]:
        if isinstance(env, OwnedEnv):
            if env.lib_id != self.lib_id:
                raise NativeOwnershipError(f"environment belongs to {env.lib_id}, not {self.lib_id}")
            return env._h, env.n
        if isinstance(env, self.native.Env):
            if not self.owns_native_module:
                raise NativeOwnershipError("tuppi_ai.native environments belong to "
                                           f"{Path(self.native.lib._name).name}, not {self.path.name}")
            return env._h, env.n
        raise NativeOwnershipError(f"not a native environment: {type(env).__name__}")

    def _mlp(self, mlp) -> int:
        if isinstance(mlp, OwnedMlp):
            if mlp.lib_id != self.lib_id:
                raise NativeOwnershipError(f"network belongs to {mlp.lib_id}, not {self.lib_id}")
            return mlp._h
        if isinstance(mlp, self.native.Mlp):
            if not self.owns_native_module:
                raise NativeOwnershipError("tuppi_ai.native networks belong to another library")
            return mlp._h
        raise NativeOwnershipError(f"not a native network: {type(mlp).__name__}")

    # ------------------------------------------------------------ calls
    def rollout_chunk(self) -> int:
        return self.lib.research_get_rollout_chunk()

    def env_config(self, env) -> dict:
        h, _n = self._env(env)
        out = (C.c_double * CFG_LEN)()
        rc = self.lib.research_env_config(h, out, CFG_LEN)
        if rc != CFG_LEN:
            raise NativeCallError("research_env_config", rc)
        v = list(out)
        return {"version": int(v[0]), "n": int(v[1]), "encoder": int(v[2]), "single_deal": int(v[3]),
                "p_random_start": v[4], "sooli_belief": int(v[5]), "sooli_return_pi": int(v[6]),
                "sooli_play_heur": int(v[7]), "sooli_lambda": v[8], "rollout_chunk": int(v[9]),
                "slot_digest": (int(v[10]) << 32) | int(v[11]), "equity": v[12:]}

    def import_config(self, env, cfg: dict) -> None:
        h, _n = self._env(env)
        v = [cfg["version"], cfg["n"], cfg["encoder"], cfg["single_deal"], cfg["p_random_start"],
             cfg["sooli_belief"], cfg["sooli_return_pi"], cfg["sooli_play_heur"], cfg["sooli_lambda"],
             cfg["rollout_chunk"], float(cfg["slot_digest"] >> 32), float(cfg["slot_digest"] & 0xFFFFFFFF),
             *cfg["equity"]]
        arr = (C.c_double * CFG_LEN)(*v)
        rc = self.lib.research_env_import_config(h, arr, CFG_LEN)
        if rc != 0:
            raise NativeCallError("research_env_import_config", rc)

    def obs_valid(self, obs) -> bool:
        return bool(self.lib.research_obs_valid(C.byref(obs)))

    def world_consistent(self, obs, world) -> str:
        return WORLD_REASONS.get(self.lib.research_world_consistent(C.byref(obs), C.byref(world)), "unknown")

    def sample_worlds(self, env, obs, w: int, rng: C.c_uint64) -> list:
        """The first `w` root worlds tc_search_values would draw; advances `rng` identically."""
        h, _n = self._env(env)
        if not 1 <= w <= MAX_WORLDS:
            raise ValueError("w out of range")
        out = (self.native.TcDeal * w)()
        drawn = C.c_int(0)
        rc = self.lib.research_sample_worlds(h, C.byref(obs), w, C.byref(rng), out, w, C.byref(drawn))
        if rc != 0:
            raise NativeCallError("research_sample_worlds", rc, f"after {drawn.value} worlds")
        return list(out)

    def trace_search(self, env, mlp, obs, actions, w: int, dd_left: int, rng: C.c_uint64, options: int = 0):
        """tc_search_world_values plus the worlds it drew; advances `rng` identically."""
        h, n = self._env(env)
        mh = self._mlp(mlp)
        a = np.ascontiguousarray(actions, dtype=np.int32)
        k = len(a)
        _check_dims(w, k, n)
        values = np.zeros(k, dtype=np.float64)
        per_world = np.zeros((w, k), dtype=np.float64)
        status = np.zeros((w, k), dtype=np.uint8)
        worlds = (self.native.TcDeal * w)()
        work = np.zeros(8, dtype=np.int64)
        t0, c0 = time.perf_counter(), time.process_time()
        rc = self.lib.research_trace_search(h, mh, C.byref(obs), a.ctypes.data, k, w, dd_left, options, C.byref(rng),
                                            values.ctypes.data, per_world.ctypes.data, status.ctypes.data, w * k,
                                            worlds, w, work.ctypes.data)
        wall, cpu = time.perf_counter() - t0, time.process_time() - c0
        if rc != 0:
            raise NativeCallError("research_trace_search", rc)
        ev = WorldEvaluation(tuple(int(x) for x in a), values, per_world, status,
                             dict(zip(WORK_NAMES, work.tolist())), cpu, wall)
        return ev, list(worlds)

    def evaluate_worlds(self, env, mlp, obs, worlds, actions, dd_left: int,
                        cont_rng: C.c_uint64 | None = None, options: int = 0) -> WorldEvaluation:
        """The original continuation on exactly these root worlds (never resamples)."""
        h, n = self._env(env)
        mh = self._mlp(mlp)
        a = np.ascontiguousarray(actions, dtype=np.int32)
        k, w = len(a), len(worlds)
        _check_dims(w, k, n)
        arr = (self.native.TcDeal * w)(*worlds)
        cont = cont_rng if cont_rng is not None else C.c_uint64(0)
        values = np.zeros(k, dtype=np.float64)
        per_world = np.zeros((w, k), dtype=np.float64)
        status = np.zeros((w, k), dtype=np.uint8)
        work = np.zeros(8, dtype=np.int64)
        bad = C.c_int(-1)
        t0, c0 = time.perf_counter(), time.process_time()
        rc = self.lib.research_evaluate_worlds(h, mh, C.byref(obs), arr, w, a.ctypes.data, k, dd_left, options,
                                               C.byref(cont), values.ctypes.data, per_world.ctypes.data,
                                               status.ctypes.data, w * k, work.ctypes.data, C.byref(bad))
        wall, cpu = time.perf_counter() - t0, time.process_time() - c0
        if rc != 0:
            detail = ""
            if rc == -5:
                detail = f"world {bad.value}: {self.world_consistent(obs, worlds[bad.value])}"
            raise NativeCallError("research_evaluate_worlds", rc, detail)
        return WorldEvaluation(tuple(int(x) for x in a), values, per_world, status,
                               dict(zip(WORK_NAMES, work.tolist())), cpu, wall)


def _check_dims(w: int, k: int, n: int) -> None:
    if not 1 <= w <= MAX_WORLDS or not 1 <= k <= 210:
        raise ValueError(f"dimensions out of range: w={w}, k={k}")
    if w * k > n:
        raise NativeCallError("dimension check", -2, f"w*k={w * k} > env slots {n}")


def _env_of(lib: "ResearchLibrary", env) -> int:
    return lib._env(env)[0]


def row_utility(lib: "ResearchLibrary", env, deal, team0_tricks: int) -> float:
    """The float32 utility record_if_done would add if `deal` ended with `team0_tricks` (C3b tests)."""
    out = C.c_float()
    rc = lib.lib.research_row_utility(_env_of(lib, env), C.byref(deal), team0_tricks, C.byref(out))
    if rc != 0:
        raise NativeCallError("research_row_utility", rc)
    return out.value


def utility_certificate(lib: "ResearchLibrary", env, deal) -> float | None:
    """The native C3b certificate for one ordinary state: its fixed utility, or None."""
    out = C.c_float()
    rc = lib.lib.research_utility_certificate(_env_of(lib, env), C.byref(deal), C.byref(out))
    if rc < 0:
        raise NativeCallError("research_utility_certificate", rc)
    return out.value if rc == 1 else None
