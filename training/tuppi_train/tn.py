"""The training build's extra native functions (training/native/tuppi_train.c)."""

from __future__ import annotations

import ctypes as C

import numpy as np

from . import TRAIN_LIBRARY  # noqa: F401  (sets the library path before the import below)
from tuppi_ai import native

lib = native.lib
if not hasattr(lib, "tc_ls_begin"):
    raise ImportError(
        f"{lib._name} is not the training build. Run `sh training/build_train.sh` and leave "
        f"TUPPI_NATIVE_LIBRARY unset (or set it to {TRAIN_LIBRARY}).")

_u64p = C.POINTER(C.c_uint64)
lib.tc_train_init.argtypes = []
lib.tc_train_threads.restype = C.c_int
lib.tc_train_set_threads.argtypes = [C.c_int]
lib.tc_ls_begin.argtypes = [C.c_void_p, C.c_int, C.c_int, _u64p]
lib.tc_ls_begin.restype = C.c_int
lib.tc_ls_begin_duplicate.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_int, C.c_int, _u64p, C.c_void_p]
lib.tc_ls_begin_duplicate.restype = C.c_int
lib.tc_ls_observe.argtypes = [C.c_void_p, C.c_int, C.c_int] + [C.c_void_p] * 8 + [C.c_int, C.POINTER(C.c_int),
                                                                                  C.c_void_p]
lib.tc_ls_observe.restype = C.c_int
lib.tc_ls_step.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_int]
lib.tc_ls_step.restype = C.c_int
lib.tc_ls_summary.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
lib.tc_ls_copy_states.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p]
lib.tc_ls_classes.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_void_p]
lib.tc_ls_branch_begin.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int] + [C.c_void_p] * 5
lib.tc_ls_branch_begin.restype = C.c_int
lib.tc_ls_resolve.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p]

lib.tc_train_init()

FEAT1_BYTES = (native.feature_dim(1) + 7) // 8
MASK_BYTES = (native.NUM_ACTIONS + 7) // 8


def threads() -> int:
    """OpenMP threads the parallel loops use (1 after native.set_parallel(False))."""
    return int(lib.tc_train_threads())


def set_threads(n: int) -> None:
    lib.tc_train_set_threads(int(n))


def summary(env: "native.Env", n: int) -> dict:
    out = np.zeros(4, np.int32)
    lib.tc_ls_summary(env._h, n, out.ctypes.data)
    return {"done": int(out[0]), "rami": int(out[1]), "sooli": int(out[2]), "team0_wins": int(out[3])}
