"""The browser's W1024/PIB8 controller, without PyTorch or hidden-hand input.

One serial worker owns the native globals. Its immutable networks are loaded
once; callers restore each seat's three-word context before every decision.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import json
from pathlib import Path

import numpy as np

from . import native
from .bridge import action_id, obs_from_player_observation

ROOT = Path(__file__).resolve().parents[1]
WORLDS, INFERENCE = 1024, 8


def model_identity(directory: Path | None = None) -> dict:
    directory = ROOT / "models/compact" if directory is None else Path(directory)
    blob = (directory / "models.json").read_bytes()
    manifest = json.loads(blob)
    if (manifest.get("schema") != "tuppi.browser.assets.v1" or manifest.get("api_version") != 1
            or manifest.get("ruleset") != "project_target_v3"
            or [r.get("file") for r in manifest.get("models", [])] !=
               ["vrpo1_actor_0504.f32", "vrpo3_final.f32"]
            or manifest.get("equity", {}).get("file") != "equity.f64"):
        raise ValueError("invalid compact model manifest")
    expected = [(0, 256, 2, 804508), (1, 512, 4, 3185820)]
    for record, (role, width, blocks, count) in zip(manifest["models"], expected):
        if (record["role"] != role or record["config"] != {"width": width, "blocks": blocks, "encoder": 2}
                or record["in_dim"] != 1951 or record["out_dim"] != 156 or record["count"] != count
                or record["bytes"] != count * 4):
            raise ValueError("unsupported compact model dimensions")
    for record in [*manifest["models"], manifest["equity"]]:
        data = (directory / record["file"]).read_bytes()
        if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            raise ValueError("compact model hash mismatch")
    if manifest["equity"]["bytes"] != 400:
        raise ValueError("invalid compact equity table")
    return {"manifest": manifest, "sha256": hashlib.sha256(blob).hexdigest()}


def initial_context(seat: int) -> list[int]:
    if type(seat) is not int or seat not in range(4):
        raise ValueError("invalid controller seat")
    rng = (2 * seat) * 2654435761 + 1
    return [rng & 0xffffffff, rng >> 32, 0]


def validate_context(context) -> list[int]:
    if (type(context) not in (list, tuple) or len(context) != 3
            or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in context)
            or context[2] > 2):
        raise ValueError("invalid compact controller context")
    return list(context)


class CompactController:
    def __init__(self, directory: Path | None = None):
        directory = ROOT / "models/compact" if directory is None else Path(directory)
        identity = model_identity(directory)
        self.model_sha256 = identity["sha256"]
        self.lib = lib = native.lib
        lib.tb_load_model.argtypes = [C.c_int] * 6 + [C.POINTER(C.c_float)]
        lib.tb_configure.argtypes = [C.c_int, C.POINTER(C.c_double)]
        lib.tb_configure_bot.argtypes = [C.c_int, C.c_int]
        lib.tb_configure_inference.argtypes = [C.c_int, C.c_int]
        lib.tb_set_human_seats.argtypes = [C.c_int]
        lib.tb_restore_context.argtypes = [C.c_int, C.c_uint32, C.c_uint32, C.c_int]
        lib.tb_context.argtypes = [C.c_int, C.c_int]
        lib.tb_context.restype = C.c_uint32
        lib.tb_choose_observation.argtypes = [C.POINTER(native.TcObs), C.POINTER(C.c_int32), C.c_int]
        lib.tb_values.argtypes = [C.POINTER(C.c_int32), C.POINTER(C.c_double)]
        lib.tb_dispose.argtypes = []
        lib.tb_dispose.restype = None
        if lib.tb_observation_size() != C.sizeof(native.TcObs):
            raise RuntimeError("compact observation ABI mismatch")
        try:
            for r in identity["manifest"]["models"]:
                flat = np.fromfile(directory / r["file"], dtype="<f4")
                if not np.isfinite(flat).all() or lib.tb_load_model(r["role"], r["in_dim"],
                        r["config"]["width"], r["config"]["blocks"], r["config"]["encoder"],
                        len(flat), flat.ctypes.data_as(C.POINTER(C.c_float))):
                    raise RuntimeError("compact model load failed")
            equity = np.fromfile(directory / "equity.f64", dtype="<f8")
            if not np.isfinite(equity).all() or lib.tb_configure(WORLDS, equity.ctypes.data_as(C.POINTER(C.c_double))):
                raise RuntimeError("compact controller configuration failed")
            if lib.tb_configure_bot(2, 0) or lib.tb_configure_inference(INFERENCE, 1):
                raise RuntimeError("compact inference configuration failed")
        except BaseException:
            lib.tb_dispose()
            raise

    def choose(self, observation, context, human_seats=()):
        context = validate_context(context)
        people = frozenset(human_seats)
        if any(type(s) is not int or s not in range(4) for s in people):
            raise ValueError("invalid human seats")
        obs = obs_from_player_observation(observation)
        seat = observation.observing_seat
        legal = list(observation.legal_actions)
        ids = [action_id(a) for a in legal]
        ordered = (C.c_int32 * len(ids))(*ids)
        if self.lib.tb_set_human_seats(sum(1 << s for s in people)) or self.lib.tb_restore_context(seat, *context):
            raise RuntimeError("compact controller restore failed")
        selected = self.lib.tb_choose_observation(C.byref(obs), ordered, len(ids))
        if selected not in ids:
            raise RuntimeError(f"compact controller failed ({selected})")
        next_context = [int(self.lib.tb_context(seat, f)) for f in range(3)]
        value_ids, values = (C.c_int32 * 210)(), (C.c_double * 210)()
        count = self.lib.tb_values(value_ids, values)
        return legal[ids.index(selected)], next_context, {int(value_ids[i]): values[i] for i in range(count)}

    def close(self):
        self.lib.tb_dispose()
