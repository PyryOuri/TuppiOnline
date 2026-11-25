"""T8: saving, resuming and surviving a write that was cut off."""

from __future__ import annotations

import json

import torch

import tuppi_train
from tuppi_train import checkpoint, vrpo_gpu

V1 = str(tuppi_train.MODELS / "vrpo1_actor_0504.pt")


def config(**extra):
    base = dict(init=V1, panel="vrpo1_actor_0504.pt", games_per_iter=192, minibatch=4096, critic_width=64,
                critic_blocks=1, warmup_min=1, warmup_max=1, actor_ramp=4, eval_every=2, eval_base=16,
                milestone_every=2, save_minutes=1e9, stop_patience=0)
    return vrpo_gpu.Config(**{**base, **extra})


def learner(out, resume):
    torch.set_num_threads(1)
    return vrpo_gpu.Learner(config(), out, torch.device("cpu"), resume=resume)


def strip(row):
    return {k: v for k, v in row.items() if not k.endswith("_s") and k not in ("hours", "rollout_split")}


def test_resume_continues_exactly(tmp_path):
    """Two iterations, save, a new process' worth of objects, one more iteration: the same
    networks, optimizer states and log rows as three iterations in one go."""
    straight = learner(tmp_path / "a", resume=False)
    rows_a = [straight.iterate() for _ in range(3)]

    first = learner(tmp_path / "b", resume=False)
    rows_b = [first.iterate() for _ in range(2)]
    first.save()
    del first
    second = learner(tmp_path / "b", resume=True)
    assert second.iteration == 2
    rows_b.append(second.iterate())

    assert [strip(r) for r in rows_a] == [strip(r) for r in rows_b]
    assert any("eval" in r for r in rows_a) and rows_a[-1]["epochs"] > 0
    sa, sb = straight.state(), second.state()
    for part in ("actor", "critic"):
        for key in sa[part]:
            assert torch.equal(sa[part][key], sb[part][key]), f"{part}.{key}"
    for part in ("opt_a", "opt_c"):
        for ga, gb in zip(sa[part]["state"].values(), sb[part]["state"].values()):
            for key in ga:
                assert torch.equal(torch.as_tensor(ga[key]), torch.as_tensor(gb[key])), f"{part}.{key}"
    assert sa["rng"] == sb["rng"] and sa["actor_iters"] == sb["actor_iters"] and sa["mc_hist"] == sb["mc_hist"]
    logged = [json.loads(line)["iteration"] for line in (tmp_path / "b" / "log.jsonl").read_text().splitlines()]
    assert logged == [1, 2, 3]
    assert (tmp_path / "b" / "actors" / "actor_000002.pt").exists()
    assert (tmp_path / "b" / "best_actor.pt").exists()


def test_policy_against_itself_evaluates_to_zero(tmp_path):
    """Before the actor has moved, the paired evaluation against its own parent is exactly 0."""
    fresh = learner(tmp_path, resume=False)
    result = fresh.evaluate()
    assert result["vrpo1_actor_0504"] == [0.0, 0.0]


def test_lost_rows_are_dropped_from_the_log(tmp_path):
    run = learner(tmp_path, resume=False)
    run.iterate()
    run.save()
    run.iterate()   # logged but never saved: the session died here
    again = learner(tmp_path, resume=True)
    assert again.iteration == 1
    logged = [json.loads(line)["iteration"] for line in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert logged == [1]


def test_a_cut_off_write_leaves_the_previous_state(tmp_path):
    store = checkpoint.Rotating(tmp_path)
    store.save({"iteration": 1, "x": torch.arange(4)})
    store.save({"iteration": 2, "x": torch.arange(5)})
    assert checkpoint.Rotating(tmp_path).load()["iteration"] == 2
    # the next write dies half-way: only its temporary file exists
    target = tmp_path / checkpoint.SLOTS[store.next]
    (tmp_path / (target.name + ".tmp")).write_bytes(b"half a checkpoint")
    assert checkpoint.Rotating(tmp_path).load()["iteration"] == 2
    # the newest slot itself is damaged (a disk that lost the tail of the file)
    newest = tmp_path / checkpoint.SLOTS[1 - store.next]
    newest.write_bytes(newest.read_bytes()[:200])
    recovered = checkpoint.Rotating(tmp_path)
    state = recovered.load()
    assert state["iteration"] == 1 and torch.equal(state["x"], torch.arange(4))
    # and the next save overwrites the damaged slot, not the good one
    recovered.save({"iteration": 3, "x": torch.arange(6)})
    assert checkpoint.Rotating(tmp_path).load()["iteration"] == 3
    assert torch.load(tmp_path / checkpoint.SLOTS[1 - recovered.next], weights_only=False)["iteration"] == 3


def test_nothing_saved_yet(tmp_path):
    assert checkpoint.Rotating(tmp_path / "empty").load() is None


def test_critic_from_another_run(tmp_path):
    """A new run takes a finished run's critic (and its optimizer moments) but starts its
    actor from `init`, not from the other run's drifted actor."""
    first = learner(tmp_path / "first", resume=False)
    for _ in range(3):
        first.iterate()
    first.save()
    assert first.actor_iters > 0
    for source in (tmp_path / "first", tmp_path / "first" / "ckpt", first.store.dir / checkpoint.SLOTS[1 - first.store.next]):
        cfg = config(critic_init=str(source), warmup_max=0)
        second = vrpo_gpu.Learner(cfg, tmp_path / f"second_{source.name}", torch.device("cpu"), resume=False)
        for key, value in first.critic.state_dict().items():
            assert torch.equal(value, second.critic.state_dict()[key]), key
        moments = second.opt_c.state_dict()["state"]
        assert moments and all(torch.equal(moments[i]["exp_avg"], first.opt_c.state_dict()["state"][i]["exp_avg"])
                               for i in moments)
        assert second.opt_c.param_groups[0]["lr"] == cfg.lr_critic
        init = torch.load(V1, weights_only=False)["state"]
        assert all(torch.equal(init[k], v) for k, v in second.actor.state_dict().items())
        assert second.critic_source["iteration"] == 3
        row = second.iterate()
        assert row["epochs"] > 0 and not row["warmup"]   # no warm-up with a trained critic


def test_critic_from_a_vrpo_critic_file(tmp_path):
    first = learner(tmp_path / "first", resume=False)
    torch.save({"config": first.critic.config, "state": first.critic.state_dict()}, tmp_path / "critic_latest.pt")
    second = vrpo_gpu.Learner(config(critic_init=str(tmp_path / "critic_latest.pt")), tmp_path / "second",
                              torch.device("cpu"), resume=False)
    assert torch.equal(second.critic.state_dict()["out.weight"], first.critic.state_dict()["out.weight"])


def test_critic_of_another_shape_is_refused(tmp_path):
    import pytest
    first = learner(tmp_path / "first", resume=False)
    first.save()
    with pytest.raises(ValueError, match="critic shape"):
        vrpo_gpu.Learner(config(critic_init=str(tmp_path / "first"), critic_width=32), tmp_path / "second",
                         torch.device("cpu"), resume=False)


def test_warmup_ends_on_window_means(tmp_path):
    """The warm-up compares the mean error of the last `patience` batches with the `patience`
    before; a single lucky batch neither ends it nor keeps it going."""
    run = vrpo_gpu.Learner(config(warmup_min=4, warmup_max=50, warmup_patience=3, warmup_tol=0.05), tmp_path,
                           torch.device("cpu"), resume=False)
    improving = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.45]
    assert [run._warmup_step(x) for x in improving] == [False] * 7
    # flat but noisy, with one very low batch early in the window
    flat = [0.45, 0.30, 0.46, 0.45, 0.44, 0.46]
    results = [run._warmup_step(x) for x in flat]
    assert results[-1] is True and results[:2] == [False, False]
    assert vrpo_gpu.Learner(config(warmup_max=0), tmp_path / "none", torch.device("cpu"), resume=False).warm is False


def test_a_signal_stops_after_the_iteration_and_saves(tmp_path):
    """SIGTERM (what the notebook sends when its cell is stopped) ends the run after the current
    iteration with a checkpoint, so nothing is lost; the run then resumes from there."""
    import os
    import signal
    import subprocess
    import sys
    import time
    out = tmp_path / "run"
    args = [sys.executable, "-m", "tuppi_train.vrpo_gpu", "--name", "sig", "--out", str(out), "--device", "cpu",
            "--hours", "1", "--init", V1, "--panel", "", "--games-per-iter", "192", "--minibatch", "4096",
            "--critic-width", "64", "--critic-blocks", "1", "--warmup-max", "0", "--milestone-every", "0",
            "--print-every", "1"]
    env = {**os.environ, "PYTHONPATH": str(tuppi_train.REPO / "training")}
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    lines = []
    for line in proc.stdout:   # wait until training is under way
        lines.append(line)
        if line.strip().startswith("1 |"):
            break
    assert lines and lines[-1].strip().startswith("1 |"), "".join(lines)
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    rest = proc.communicate(timeout=300)[0]
    assert proc.returncode == 0, rest
    assert "stopped by a signal" in rest
    saved = checkpoint.Rotating(out / "ckpt").load()
    assert saved is not None and saved["iteration"] >= 1
    logged = [json.loads(line)["iteration"] for line in (out / "log.jsonl").read_text().splitlines()]
    assert logged[-1] == saved["iteration"]
