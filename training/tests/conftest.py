"""Shared fixtures. Every test here runs on the CPU; see training/README.md."""

from __future__ import annotations

import ctypes as C
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tuppi_train  # noqa: E402  (selects the training library)
from tuppi_train import tn  # noqa: E402
from tuppi_ai import native  # noqa: E402

RULESET = 3


@pytest.fixture(scope="session")
def table():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    return Equity.load(EQUITY).table


@pytest.fixture
def make_env(table):
    def make(n: int, encoder: int = 2):
        env = native.Env(n, 1, table, single_deal=True, encoder=encoder)
        env.set_sooli(0, False, False, 0.0)
        return env
    return make


def lite_mlp(name: str) -> "native.Mlp":
    blob = np.load(tuppi_train.MODELS / name)
    width, blocks, encoder = (int(x) for x in blob["shape"])
    return native.Mlp.from_flat(blob["weights"], width, blocks, encoder)


@pytest.fixture(scope="session")
def mlp3():
    """VRPO3 (512x4) in native memory, without PyTorch."""
    return lite_mlp("vrpo3_final.lite.npz")


@pytest.fixture(scope="session")
def mlp4():
    return lite_mlp("vrpo4_final.lite.npz")


@pytest.fixture(scope="session")
def net1():
    """VRPO1 (256x2) as a torch network on the CPU: small enough for fast tests."""
    from tuppi_ai import model as qmodel
    return qmodel.load(tuppi_train.MODELS / "vrpo1_actor_0504.pt", "cpu")


@pytest.fixture(autouse=True)
def native_defaults():
    """Process-wide native settings back to their defaults after each test."""
    yield
    native.set_parallel(True)
    native.set_offer_model(None)
    native.set_rollout_chunk(32)
    native.set_branch_share(False)
    native.set_showing_fix(False)
    native.lib.tc_set_dd_extra_nolo(0)
    tn.set_threads(max(1, len(__import__("os").sched_getaffinity(0))))


def rng(seed: int) -> C.c_uint64:
    return C.c_uint64(seed)


def by_deal_step(d: dict) -> np.ndarray:
    return np.lexsort((d["step"], d["deal"]))
