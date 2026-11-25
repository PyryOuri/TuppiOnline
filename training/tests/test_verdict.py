"""The verdict run as a whole, at toy size: steps resume, results are cached, settings are pinned."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest

import tuppi_train

ARGS = ["--main", "vrpo1_actor_0504.pt", "--control", "vrpo1_actor_0504.pt", "--panel", "", "--states", "1200",
        "--control-states", "800", "--shard-states", "600", "--curve", "500", "--games", "128", "--label-slots", "8000",
        "--warm-steps", "20", "--big-steps", "20", "--big-width", "32", "--big-blocks", "1", "--batch", "256",
        "--check-every", "10", "--select-base", "16", "--confirm-base", "24", "--panel-base", "8", "--eval-chunk", "16",
        "--direct-steps", "250",
        "--amp", "off", "--device", "cpu"]


def run(out, *extra, hours="1"):
    env = {**os.environ, "PYTHONPATH": str(tuppi_train.REPO / "training")}
    return subprocess.run([sys.executable, "-m", "tuppi_train.verdict", "--out", str(out), "--hours", hours, *ARGS, *extra],
                          capture_output=True, text=True, env=env)


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    out = tmp_path_factory.mktemp("verdict")
    first = run(out, hours="0")                      # no time at all: nothing is done, nothing breaks
    assert first.returncode == 0 and "time is up before: data main 0" in first.stdout
    assert not (out / "data").exists()
    done = run(out)
    assert done.returncode == 0, done.stderr[-2000:]
    return out, done.stdout


def test_run_reaches_a_verdict(finished):
    out, text = finished
    R = json.loads((out / "results.json").read_text())
    assert R["verdict"]["verdict"] in ("GO", "STOP", "INCONCLUSIVE") and "VERDICT:" in text
    assert set(R["data"]) == {"main", "control"} and len(R["data"]["main"]) == 2
    assert {"main_q0_warm_500", "main_q0_warm_all", "main_q6_warm_all", "main_q0_big_all", "main_q6_big_all",
            "control_q0_warm_all", "control_q6_warm_all"} <= set(R["teachers"])
    for t in R["teachers"].values():
        assert np.isfinite(t["adv_r2"]) and len(t["margins"]) == 2 and "gain_early" in t
    assert "gain_on_q0" in R["teachers"]["main_q6_warm_all"] and "gain_on_q0" not in R["teachers"]["main_q0_warm_all"]
    # directly improved networks: one training run per label kind, a candidate at each step count
    assert set(R["policies"]) == {f"{tag}_{kind}_direct_s{n}" for tag in ("main", "control") for kind in ("q0", "q6")
                                  for n in (100, 250)}
    assert set(R["direct_runs"]) == {"main_q0_direct", "main_q6_direct", "control_q0_direct", "control_q6_direct"}
    for name, t in R["policies"].items():
        assert (out / "policies" / f"{name}.pt").exists() and np.isfinite(t["gain"]["gain"])
    M = R["matches"]
    assert M["main_self"]["mean"] == 0.0 and M["main_self"]["ci95"] == 0.0     # a policy against itself
    select_main = {k for k in M if k.startswith("select_main_")}
    assert len(select_main) == 4 * 3 + 2 * 2          # four teachers x three margin settings, two kinds x two step counts
    assert {"select_main_q0_warm_all_m0.03_0.012", "select_main_q6_big_all_m0.12_0.06", "select_main_q6_direct_s250",
            "confirm_main", "confirm_main_early_only", "confirm_control"} <= set(M)
    assert M["select_main_q0_warm_all_m0.06_0.03"]["candidate"]["margins"] == [0.06, 0.03]
    assert M["confirm_main"]["seed"] != M["select_main_q0_warm_all_m0.03_0.012"]["seed"]   # confirmed on other deals
    assert M["confirm_main_early_only"]["candidate"]["min_left"] == 6
    best = max(select_main, key=lambda k: M[k]["mean"])
    assert R["verdict"]["main"]["candidate"] == best[len("select_"):]                    # chosen by play
    assert M["confirm_main"]["candidate"] == M[best]["candidate"]
    z = np.load(out / "data" / "main" / "shard_001.npz")
    assert z["q0"].shape == z["q6"].shape == z["ids"].shape and len(z["mult"]) == 27
    assert (np.load(out / "data" / "main" / "shard_000.npz")["mult"] == 1).all()   # the first shard measures


def test_class_multipliers():
    """Classes whose decisions matter more often are recorded more; rare classes keep 1."""
    from tuppi_train import verdict
    n = 900
    cls = np.repeat(np.array([0, 5, 20], np.int8), 300)
    ids = np.full((n, 26), 156, np.uint8)
    ids[:, :2] = (3, 4)
    q = np.zeros((n, 26), np.float16)
    q[:300, 1] = 0.5                       # class 0: every decision matters
    q[300:450, 1] = 0.5                    # class 5: half of them
    mult = verdict.class_multipliers(ids, q, cls)   # class 20: none; overall half
    assert mult[0] == 2.0 and mult[5] == 1.0 and mult[20] == 0.25
    assert (np.delete(mult, [0, 5, 20]) == 1).all()
    assert (verdict.class_multipliers(ids, q, cls, min_states=301) == 1).all()


def test_rerun_does_nothing_and_changes_nothing(finished):
    out, _ = finished
    before = (out / "results.json").read_text()
    stamps = {p: p.stat().st_mtime_ns for p in out.rglob("*.npz")} | {p: p.stat().st_mtime_ns for p in out.rglob("*.pt")}
    again = run(out)
    assert again.returncode == 0 and "VERDICT:" in again.stdout
    assert json.loads((out / "results.json").read_text()) == json.loads(before)
    assert stamps == {p: p.stat().st_mtime_ns for p in stamps}


def test_other_settings_are_refused(finished):
    out, _ = finished
    other = run(out, "--amp", "bf16")
    assert other.returncode != 0 and "this run was started with" in (other.stderr + other.stdout)


def test_a_lost_step_is_redone(finished):
    """Deleting one teacher and the verdict (as a session lost mid-way would leave things)
    makes exactly that teacher and the matches run again."""
    out, _ = finished
    R = json.loads((out / "results.json").read_text())
    (out / "teachers" / "main_q6_big_all.pt").unlink()
    del R["verdict"]
    (out / "results.json").write_text(json.dumps(R))
    again = run(out)
    assert again.returncode == 0 and again.stdout.count("teacher ") >= 1
    assert "teacher main_q6_big_all:" in again.stdout and "teacher main_q0_big_all:" not in again.stdout
    assert "data main shard" not in again.stdout and "VERDICT:" in again.stdout
