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
                                                                                  C.c_void_p, C.c_void_p]
lib.tc_ls_observe.restype = C.c_int
lib.tc_ls_step.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_int]
lib.tc_ls_step.restype = C.c_int
lib.tc_ls_summary.argtypes = [C.c_void_p, C.c_int, C.c_void_p]
lib.tc_ls_copy_states.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p]
lib.tc_ls_classes.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_void_p]
lib.tc_ls_branch_begin.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int] + [C.c_void_p] * 5
lib.tc_ls_branch_begin.restype = C.c_int
lib.tc_ls_resolve.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.c_void_p, C.c_void_p]
lib.tc_ls_sample_worlds.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_void_p, C.c_int, C.c_double] + [C.c_void_p] * 3
lib.tc_ls_sample_worlds.restype = C.c_int
lib.tc_ls_search_begin.argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_int] + [C.c_void_p] * 4
lib.tc_ls_search_begin.restype = C.c_int
lib.tc_ls_history.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int] + [C.c_void_p] * 4
lib.tc_ls_history.restype = None

lib.tc_train_init()

FEAT1_BYTES = (native.feature_dim(1) + 7) // 8
MASK_BYTES = (native.NUM_ACTIONS + 7) // 8


def threads() -> int:
    """OpenMP threads the parallel loops use (1 after native.set_parallel(False))."""
    return int(lib.tc_train_threads())


def set_threads(n: int) -> None:
    lib.tc_train_set_threads(int(n))


def use_cpus(n: int = 0) -> int:
    """Engine threads = n, or every CPU this process may use (n = 0). Returns the count.

    PyTorch shares the OpenMP runtime with the engine. Its MKL builds reset the runtime's thread
    count to the physical cores (6 of Colab's 12) when PyTorch first does parallel work, whatever
    was set before; telling PyTorch the count as well keeps it."""
    import os
    if n <= 0:
        n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
    try:
        import torch
        torch.set_num_threads(n)
    except ImportError:
        pass
    set_threads(n)
    return n


def use_all_cpus() -> int:
    return use_cpus(0)


def summary(env: "native.Env", n: int) -> dict:
    out = np.zeros(4, np.int32)
    lib.tc_ls_summary(env._h, n, out.ctypes.data)
    return {"done": int(out[0]), "rami": int(out[1]), "sooli": int(out[2]), "team0_wins": int(out[3])}
