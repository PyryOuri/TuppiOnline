"""Dan 1.1: visible EV-limited NOLO habit and conservative Nelli 1.1 bids.

Use propose_action -> authoritative apply -> commit_action in cancellable callers.
choose_action is a synchronous serial-loop convenience with idempotent polling.
"""
from __future__ import annotations

import copy
import ctypes as C
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from . import native
from .bridge import action_id, obs_from_player_observation
from .lite import LiteAgent, MODEL, MODEL_V4, ROOT, initial_cursor, shared_equity, shared_mlp

BOT_NAME = "Dan 1.1"
PROFILE_SCHEMA = "tuppi.personality.dan11.v1"
CHECKPOINT_SCHEMA = "tuppi.controller.dan11.v1"
REASONS = ("outside", "forced", "no_high_card", "base_high_card", "allowance_exhausted",
           "loss_rejected", "accepted", "sampling_failed", "invalid_values")


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class DanConfig:
    worlds: int = 64
    lead_loss: float = .03
    second_loss: float = .02
    deal_loss: float = .05
    uncertainty: float = 2.0
    epsilon: float = 1e-12
    rami_margin: float = 14.0

    def __post_init__(self):
        if type(self.worlds) is not int or not 2 <= self.worlds <= 64:
            raise ValueError("Dan supports 2..64 fixed worlds")
        values = (self.lead_loss, self.second_loss, self.deal_loss, self.uncertainty, self.epsilon, self.rami_margin)
        if any(type(x) not in (float, int) or not math.isfinite(x) for x in values):
            raise ValueError("Dan configuration must be finite numbers")
        if not (0 <= self.second_loss <= self.lead_loss <= 1 and 0 <= self.deal_loss <= 1
                and 0 <= self.uncertainty <= 10 and 0 <= self.epsilon <= 1e-6 and 0 <= self.rami_margin <= 20):
            raise ValueError("Invalid Dan loss configuration")


class NativeConfig(C.Structure):
    _fields_ = [("worlds", C.c_int)] + [(k, C.c_double) for k in
        ("lead_loss", "second_loss", "deal_loss", "uncertainty", "epsilon", "rami_margin")]


class NativeBidResult(C.Structure):
    _fields_ = [(k, C.c_int) for k in ("action", "nelli_action", "nolo_action", "rami_action", "reason")] + [
        (k, C.c_double) for k in ("nolo_score", "rami_score", "gap", "margin")]


class NativeContext(C.Structure):
    _fields_ = [("rng", C.c_uint64), ("remaining", C.c_double)]


class NativeResult(C.Structure):
    _fields_ = [(k, C.c_int) for k in ("action", "baseline", "best", "reason", "k", "worlds", "trick", "position")] + [
        (k, C.c_double) for k in ("allowance", "charge", "before", "after")] + [
        (k, C.c_double * 13) for k in ("means", "losses", "gaps_base", "gaps_best", "se_base", "se_best")]


native._sym("tc_dan_allowance").argtypes = [C.POINTER(native.TcObs), C.POINTER(NativeConfig)]
native._sym("tc_dan_allowance").restype = C.c_double
native._sym("tc_dan_select").argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.c_int,
    C.c_double, C.c_double, C.c_double, C.c_double, C.POINTER(NativeResult)]
native._sym("tc_dan_select").restype = C.c_int
native._sym("tc_dan_choose").argtypes = [C.c_void_p, C.c_void_p, C.POINTER(native.TcObs), C.c_void_p,
    C.c_int, C.c_int, C.POINTER(NativeConfig), C.POINTER(NativeContext), C.POINTER(NativeResult)]
native._sym("tc_dan_choose").restype = C.c_int
native._sym("tc_dan_bid_select").argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_double, C.POINTER(NativeBidResult)]
native._sym("tc_dan_bid_select").restype = C.c_int
native._sym("tc_dan_bid").argtypes = [C.c_void_p, C.POINTER(native.TcObs), C.c_void_p, C.c_int,
    C.c_double, C.POINTER(NativeBidResult)]
native._sym("tc_dan_bid").restype = C.c_int


def native_config(config: DanConfig) -> NativeConfig:
    return NativeConfig(**asdict(config))


def diagnostic(result: NativeResult, ids) -> dict:
    out = {k: getattr(result, k) for k in ("action", "baseline", "best", "worlds", "trick", "position",
                                         "allowance", "charge", "before", "after")}
    out["reason"] = REASONS[result.reason]
    out["cards"] = [{"action": int(ids[i]), **{k: getattr(result, k)[i] for k in
        ("means", "losses", "gaps_base", "gaps_best", "se_base", "se_best")}} for i in range(result.k)]
    return out


@lru_cache(maxsize=1)
def identities():
    files = {"model": MODEL, "bid_model": MODEL_V4, "equity": ROOT / "models/equity_incumbent.json"}
    hashes = {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in files.items()}
    # Behaviour and binary identities are separate; saved controllers fail closed
    # across a different build or model rather than pretending replay equivalence.
    source_files = ("native/tuppi_dan.c", "native/tuppi_dan.h", "tuppi_ai/dan.py")
    hashes["guard_code"] = _hash({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in source_files})
    runtime = hashlib.sha256(Path(native.lib._name).read_bytes()).hexdigest()
    return hashes, runtime


@dataclass(frozen=True)
class DanDecision:
    action: object
    token: str
    diagnostics: dict


class DanAgent:
    handles_sooli = True
    name = BOT_NAME

    def __init__(self, seat: int, config: DanConfig | None = None):
        if type(seat) is not int or seat not in range(4):
            raise ValueError("seat must be in 0..3")
        self.seat, self.config = seat, config or DanConfig()
        hashes, self.runtime = identities()
        self.profile = _hash({"schema": PROFILE_SCHEMA, "name": BOT_NAME, "config": asdict(self.config), **hashes,
                              "continuation": "plain-vrpo3", "dd_left": 0, "belief": "hard-feasible-uniform"})
        self._base = LiteAgent(seat)
        self._bid_mlp = shared_mlp(MODEL_V4)
        self._env = None
        self._state = {"deal_ref": None, "remaining": float(self.config.deal_loss),
                       "eval_rng": 0xDAA00000 + seat, "base_rng": initial_cursor(seat), "revision": 0}
        self._pending = self._receipt = None

    def _environment(self):
        if self._env is None:
            self._env = native.Env(self.config.worlds * 13, 0, equity=shared_equity(),
                                   single_deal=True, encoder=self._base.mlp.encoder)
        return self._env

    def _decision(self, payload, legal):
        choices = {action_id(a): a for a in legal}
        if payload["action"] not in choices:
            raise ValueError("Saved Dan decision is not legal in this observation")
        return DanDecision(choices[payload["action"]], payload["token"], copy.deepcopy(payload["diagnostics"]))

    def propose_action(self, observation) -> DanDecision:
        if observation.observing_seat != self.seat or observation.current_actor != self.seat:
            raise ValueError("Dan requires his own acting observation")
        legal = observation.legal_actions
        obs = obs_from_player_observation(observation)
        if not legal or obs.ruleset != 3:
            raise ValueError("Dan requires nonterminal project_target_v3 play")
        ids = np.ascontiguousarray([action_id(a) for a in legal], dtype=np.int32)
        key = _hash([observation.deal_ref, bytes(obs).hex(), ids.tolist()])
        for cached in (self._pending, self._receipt):
            if cached is not None and cached["observation"] == key:
                return self._decision(cached, legal)
        next_state = copy.deepcopy(self._state)
        if next_state["deal_ref"] != observation.deal_ref:
            next_state["deal_ref"] = observation.deal_ref
            next_state["remaining"] = float(self.config.deal_loss)
        # The base agent's sole mutable policy cursor is restored before every
        # proposal, then rolled back until the caller accepts the action.
        bidding = None
        self._base.rng.value = next_state["base_rng"]
        try:
            if obs.phase == native.PH_SHOW:
                bid = NativeBidResult()
                rc = native.lib.tc_dan_bid(self._bid_mlp._h, C.byref(obs), ids.ctypes.data, len(ids),
                    self.config.rami_margin, C.byref(bid))
                if rc:
                    raise ValueError(f"Invalid Dan 1.1 bidding input ({rc})")
                base = bid.action
                bidding = {k: getattr(bid, k) for k in ("action", "nelli_action", "nolo_action", "rami_action",
                    "nolo_score", "rami_score", "gap", "margin")}
                bidding["reason"] = ("nelli_nolo", "rami_kept", "rami_margin_veto", "forced_contract")[bid.reason]
            else:
                base = action_id(self._base.choose_action(observation))
            next_state["base_rng"] = self._base.rng.value
        finally:
            self._base.rng.value = self._state["base_rng"]
        context = NativeContext(next_state["eval_rng"], next_state["remaining"])
        cfg, result = native_config(self.config), NativeResult()
        allowance = native.lib.tc_dan_allowance(C.byref(obs), C.byref(cfg))
        needs_env = allowance > 0 and len(ids) > 1 and base % 13 < 11 and base < 52 and any(
            0 <= a < 52 and a % 13 >= 11 for a in ids) and context.remaining > self.config.epsilon
        env = self._environment() if needs_env else None
        rc = native.lib.tc_dan_choose(env._h if env else None, self._base.mlp._h, C.byref(obs),
            ids.ctypes.data, len(ids), base, C.byref(cfg), C.byref(context), C.byref(result))
        if rc:
            raise ValueError(f"Invalid Dan guard input ({rc})")
        next_state.update(eval_rng=context.rng, remaining=context.remaining, revision=next_state["revision"]+1)
        payload = {"observation": key, "before": _hash(self._state), "next": next_state,
                   "action": result.action, "diagnostics": diagnostic(result, ids)}
        if bidding is not None:
            payload["diagnostics"]["bidding"] = bidding
        payload["token"] = _hash(payload)
        self._pending = payload
        return self._decision(payload, legal)

    def commit_action(self, decision: DanDecision) -> None:
        if self._receipt and self._receipt["token"] == decision.token:
            if action_id(decision.action) != self._receipt["action"]:
                raise ValueError("Dan receipt action changed")
            return
        p = self._pending
        if p is None or p["token"] != decision.token or p["before"] != _hash(self._state):
            raise ValueError("Stale or unknown Dan proposal")
        if action_id(decision.action) != p["action"]:
            raise ValueError("Dan proposal action changed")
        self._state = copy.deepcopy(p["next"])
        self._receipt, self._pending = p, None

    def abort_action(self) -> None:
        self._pending = None

    def choose_action(self, observation):
        """Serial engine-loop adapter. Cancellable hosts must use proposal/commit."""
        d = self.propose_action(observation)
        self.commit_action(d)
        return d.action

    def checkpoint(self) -> dict:
        return copy.deepcopy({"schema": CHECKPOINT_SCHEMA, "name": BOT_NAME, "seat": self.seat, "config": asdict(self.config),
            "profile": self.profile, "runtime": self.runtime, "state": self._state,
            "pending": self._pending, "receipt": self._receipt})

    def _validate_state(self, state):
        if not isinstance(state, dict) or set(state) != set(self._state):
            raise ValueError("Invalid Dan state fields")
        if state["deal_ref"] is not None and (not isinstance(state["deal_ref"], str) or not state["deal_ref"]):
            raise ValueError("Invalid Dan deal reference")
        if type(state["remaining"]) not in (int, float) or not math.isfinite(state["remaining"]) or not 0 <= state["remaining"] <= self.config.deal_loss:
            raise ValueError("Invalid Dan remaining allowance")
        for k in ("eval_rng", "base_rng"):
            if type(state[k]) is not int or not 0 <= state[k] < 2**64:
                raise ValueError("Invalid Dan random cursor")
        if type(state["revision"]) is not int or state["revision"] < 0:
            raise ValueError("Invalid Dan revision")

    @classmethod
    def from_checkpoint(cls, record: dict):
        required = {"schema", "name", "seat", "config", "profile", "runtime", "state", "pending", "receipt"}
        if not isinstance(record, dict) or set(record) != required or record["schema"] != CHECKPOINT_SCHEMA or record["name"] != BOT_NAME:
            raise ValueError("Invalid Dan checkpoint")
        obj = cls(record["seat"], DanConfig(**record["config"]))
        if record["profile"] != obj.profile or record["runtime"] != obj.runtime:
            raise ValueError("Dan profile/model/runtime mismatch")
        obj._validate_state(record["state"])
        for name in ("pending", "receipt"):
            item = record[name]
            if item is None:
                continue
            if not isinstance(item, dict) or set(item) != {"observation", "before", "next", "action", "diagnostics", "token"}:
                raise ValueError("Invalid Dan pending decision")
            if item["token"] != _hash({k: v for k, v in item.items() if k != "token"}):
                raise ValueError("Corrupt Dan decision token")
            obj._validate_state(item["next"])
            if name == "pending" and item["before"] != _hash(record["state"]):
                raise ValueError("Stale Dan pending state")
            if name == "receipt" and item["next"] != record["state"]:
                raise ValueError("Stale Dan receipt")
        obj._state = copy.deepcopy(record["state"])
        obj._pending, obj._receipt = copy.deepcopy(record["pending"]), copy.deepcopy(record["receipt"])
        return obj

    def close(self):
        if self._env is not None:
            native.lib.tc_env_free(self._env._h)
            self._env._h = None
            self._env = None
