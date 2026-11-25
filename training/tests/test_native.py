"""Exact tests of the training library against the hosted sources (no PyTorch)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest
from conftest import RULESET, by_deal_step, rng

import tuppi_train
from tuppi_train import lockstep, tn
from tuppi_ai import native

ROW_KEYS = ("feat", "hidden", "mask", "action", "logp", "team", "deal", "step")


def digest(d: dict) -> str:
    order = by_deal_step(d)
    h = hashlib.sha256()
    for key in ROW_KEYS:
        h.update(np.ascontiguousarray(d[key][order]).tobytes())
    h.update(np.ascontiguousarray(d["reward"]).tobytes())
    return h.hexdigest()


def test_training_library_is_loaded():
    """T1: the import passed native.py's struct-size check, and this is the training build."""
    assert native.lib._name == str(tuppi_train.TRAIN_LIBRARY)
    assert hasattr(native.lib, "tc_ls_begin") and hasattr(native.lib, "tc_train_init")


def test_threads_change_nothing(make_env, mlp3):
    """T2a: the OpenMP loops give the results of the serial loops, bit for bit."""
    if len(os.sched_getaffinity(0)) < 2:
        pytest.skip("one CPU: nothing runs in parallel here")
    games, base = 1024, 96
    native.set_rollout_chunk(8)   # many small chunks: the most interleaving

    def run():
        d = native.ppo_rollouts(make_env(games), mlp3, games, RULESET, rng(11))
        v = native.duplicate_eval(make_env(8 * base), mlp3, mlp3, base, RULESET, rng(12), temperature=1.0)
        return d, v

    tn.set_threads(8)
    assert tn.threads() == 8
    d_par, v_par = run()
    native.set_parallel(False)
    assert tn.threads() == 1
    d_ser, v_ser = run()
    assert len(d_par["action"]) == len(d_ser["action"]) > 40 * games
    assert digest(d_par) == digest(d_ser)
    assert np.array_equal(v_par, v_ser)


STOCK_SCRIPT = """
import ctypes as C, hashlib, json, sys
import numpy as np
sys.path[:0] = [{ai!r}, {tests!r}]
from tuppi_ai import native
from tuppi_ai.equity import Equity
from tuppi_ai.best import EQUITY
assert not hasattr(native.lib, "tc_ls_begin")
table = Equity.load(EQUITY).table
blob = np.load({model!r})
w, b, e = (int(x) for x in blob["shape"])
mlp = native.Mlp.from_flat(blob["weights"], w, b, e)
def env(n):
    x = native.Env(n, 1, table, single_deal=True, encoder=e); x.set_sooli(0, False, False, 0.0); return x
native.set_rollout_chunk(8)
d = native.ppo_rollouts(env({games}), mlp, {games}, 3, C.c_uint64(11))
v = native.duplicate_eval(env(8 * {base}), mlp, mlp, {base}, 3, C.c_uint64(12), temperature=1.0)
order = np.lexsort((d["step"], d["deal"]))
h = hashlib.sha256()
for key in {keys!r}:
    h.update(np.ascontiguousarray(d[key][order]).tobytes())
h.update(np.ascontiguousarray(d["reward"]).tobytes())
print(json.dumps({{"rows": int(len(d["action"])), "digest": h.hexdigest(), "eval": hashlib.sha256(v.tobytes()).hexdigest()}}))
"""


def test_same_as_the_hosted_build(make_env, mlp3):
    """T2b: the training library, on 8 threads, against an unmodified build of the hosted
    sources (training/build_train.sh --stock) in its own process."""
    if not tuppi_train.STOCK_LIBRARY.exists():
        pytest.skip("no reference build: sh training/build_train.sh --stock")
    games, base = 512, 64
    script = STOCK_SCRIPT.format(ai=str(tuppi_train.REPO / "ai"), tests=os.path.dirname(__file__),
                                 model=str(tuppi_train.MODELS / "vrpo3_final.lite.npz"), games=games, base=base,
                                 keys=ROW_KEYS)
    env = {**os.environ, "TUPPI_NATIVE_LIBRARY": str(tuppi_train.STOCK_LIBRARY), "OPENBLAS_NUM_THREADS": "1"}
    stock = json.loads(subprocess.run([sys.executable, "-c", script], env=env, check=True, capture_output=True,
                                      text=True).stdout.strip().splitlines()[-1])
    native.set_rollout_chunk(8)
    tn.set_threads(8)
    d = native.ppo_rollouts(make_env(games), mlp3, games, RULESET, rng(11))
    v = native.duplicate_eval(make_env(8 * base), mlp3, mlp3, base, RULESET, rng(12), temperature=1.0)
    assert stock["rows"] == len(d["action"])
    assert stock["digest"] == digest(d)
    assert stock["eval"] == hashlib.sha256(v.tobytes()).hexdigest()


def test_lockstep_replays_native_rollouts(make_env, mlp3):
    """T3: fed the actions of a native rollout, the lockstep engine produces the same rows
    (features, masks, hidden hands, teams, steps) and the same rewards, and leaves the
    shared rng where the native function left it."""
    games = 1536
    r_native, r_lock = rng(777), rng(777)
    d = native.ppo_rollouts(make_env(games), mlp3, games, RULESET, r_native)
    env = make_env(games)
    r = lockstep.rollouts(env, lockstep.Replay(d, games), games, RULESET, r_lock, burn_rng=True)
    assert r_native.value == r_lock.value
    a, b = by_deal_step(d), by_deal_step(r)
    for key in ("feat", "hidden", "mask", "action", "team", "deal", "step"):
        assert np.array_equal(d[key][a], r[key][b]), key
    assert np.array_equal(d["reward"], r["reward"])
    counts = tn.summary(env, games)
    assert counts["done"] == games and 0 < counts["sooli"] < games  # sooli deals were part of the test


def test_lockstep_rows_do_not_depend_on_threads(make_env):
    """The lockstep rows come out in a fixed order: same arrays on 1 and on 8 threads."""
    games = 512

    def run():
        return lockstep.rollouts(make_env(games), lockstep.RandomLegal(3), games, RULESET, rng(5))

    tn.set_threads(8)
    par = run()
    native.set_parallel(False)
    ser = run()
    for key in ROW_KEYS + ("reward",):
        assert np.array_equal(par[key], ser[key]), key


def test_lockstep_duplicate_equals_native(make_env, mlp3, mlp4):
    """T4a: the lockstep duplicate evaluation, driven by the exact CPU forward and with the
    native seeds, gives the per-deal values of native.duplicate_eval."""
    base = 64
    want = native.duplicate_eval(make_env(8 * base), mlp4, mlp3, base, RULESET, rng(31))
    got = lockstep.duplicate_eval(make_env(8 * base), lockstep.NativeGreedy(mlp4), lockstep.NativeGreedy(mlp3),
                                  base, RULESET, rng(31), paired=False)
    assert np.array_equal(want, got)
    assert np.abs(want).max() > 0


def test_paired_duplicate_of_a_policy_against_itself_is_zero(make_env, mlp3):
    """T4b: with paired seeds a policy against itself scores exactly 0 on every base deal.
    (With the native seeds it does not: the sooli heuristics draw differently in the two
    team assignments, which is noise in every native evaluation.)"""
    base = 96
    a = lockstep.NativeGreedy(mlp3)
    paired = lockstep.duplicate_eval(make_env(8 * base), a, a, base, RULESET, rng(41), paired=True)
    assert np.array_equal(paired, np.zeros(base))
    unpaired = lockstep.duplicate_eval(make_env(8 * base), a, a, base, RULESET, rng(41), paired=False)
    native_self = native.duplicate_eval(make_env(8 * base), mlp3, mlp3, base, RULESET, rng(41))
    assert np.array_equal(unpaired, native_self)


def test_illegal_actions_are_reported(make_env):
    games = 64

    def bad(feat, mask, idx, team):
        return np.full(len(idx), 155, np.uint8), None

    with pytest.raises(RuntimeError, match="illegal"):
        lockstep.rollouts(make_env(games), bad, games, RULESET, rng(1))
