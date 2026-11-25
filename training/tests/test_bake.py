"""Baking the suit-averaged network into a plain one: the loop learns, resumes, and keeps its best."""

from __future__ import annotations

import json

import numpy as np
import torch

import tuppi_train
from tuppi_train import bake, symmetry

V1 = "vrpo1_actor_0504.pt"


def config(**extra):
    base = dict(teacher="sym:" + V1, init=V1, panel=V1, games_per_iter=192, minibatch=2048, eval_every=2,
                eval_base=16, milestone_every=2, save_minutes=1e9, lr=2e-4, lr_decay_iters=4)
    return bake.Config(**{**base, **extra})


def baker(out, resume, **extra):
    torch.set_num_threads(1)
    return bake.Baker(config(**extra), out, torch.device("cpu"), resume=resume)


def strip(row):
    return {k: v for k, v in row.items() if not k.endswith("_s") and k != "hours"}


def test_student_moves_toward_the_teacher(tmp_path):
    """The target is the teacher's policy over the legal actions; training lowers the KL
    divergence on fresh deals and raises the share of decisions with the teacher's choice."""
    b = baker(tmp_path, resume=False, eval_every=10**9, milestone_every=0, lr_decay_iters=0)
    feat, mask, who = b.collect()
    assert who == "teacher" and len(feat) > 5000
    t = b.targets(feat, mask)
    legal = bake._unpack(mask, 156).bool()
    assert torch.allclose(torch.exp(t).masked_fill(~legal, 0).sum(1), torch.ones(len(t)), atol=1e-4)
    assert (legal.sum(1) > 1).all() and (t[~legal] < -1e8).all()
    x = bake._unpack(feat, b.dim)
    with torch.no_grad():   # the target is the averaged network's own policy
        want = torch.log_softmax(symmetry.Symmetric(b.teacher.net)(x).masked_fill(~legal, -1e9), 1)
    assert torch.allclose(t, want, atol=1e-4)
    rows = [b.iterate() for _ in range(12)]
    assert [r["played_by"] for r in rows[:4]] == ["teacher", "student", "teacher", "student"]
    first, last = np.mean([r["kl_first"] for r in rows[:3]]), np.mean([r["kl_first"] for r in rows[-3:]])
    assert last < 0.9 * first
    assert np.mean([r["agree"] for r in rows[-3:]]) > np.mean([r["agree"] for r in rows[:3]])
    assert rows[0]["lr"] == rows[-1]["lr"] == 2e-4
    start = torch.load(tuppi_train.MODELS / V1, weights_only=False)["state"]
    assert not torch.equal(b.student.state_dict()["out.weight"], start["out.weight"])
    assert torch.equal(b.teacher.net.state_dict()["out.weight"], start["out.weight"])   # the teacher never trains


def test_resume_continues_exactly(tmp_path):
    straight = baker(tmp_path / "a", resume=False)
    rows_a = [straight.iterate() for _ in range(3)]
    first = baker(tmp_path / "b", resume=False)
    rows_b = [first.iterate() for _ in range(2)]
    first.save()
    del first
    second = baker(tmp_path / "b", resume=True)
    assert second.iteration == 2
    rows_b.append(second.iterate())
    assert [strip(r) for r in rows_a] == [strip(r) for r in rows_b]
    for key, value in straight.student.state_dict().items():
        assert torch.equal(value, second.student.state_dict()[key]), key
    assert straight.rng.value == second.rng.value and straight.best == second.best
    logged = [json.loads(line)["iteration"] for line in (tmp_path / "b" / "log.jsonl").read_text().splitlines()]
    assert logged == [1, 2, 3]
    assert "eval" in rows_a[1] and set(rows_a[1]["eval"]) == {"vrpo1_actor_0504", "teacher"}
    assert rows_a[2]["lr"] < rows_a[0]["lr"]                 # the cosine schedule
    best = torch.load(tmp_path / "b" / "best_student.pt", weights_only=False)
    assert best["config"] == {"width": 256, "blocks": 2, "encoder": 2} and best["teacher"] == "sym:" + V1
    assert (tmp_path / "b" / "students" / "student_000002.pt").exists()


def test_evaluation_of_the_untrained_student(tmp_path):
    """Before training the student is the base network: exactly 0 against it, and it loses to
    the teacher by what the averaging is worth. Its own suit-averaged self is the teacher."""
    b = baker(tmp_path, resume=False, eval_base=64)
    plain = b.evaluate()
    assert plain["vrpo1_actor_0504"] == [0.0, 0.0] and plain["teacher"][0] < 0
    averaged = b.evaluate(symmetric=True)
    assert averaged["teacher"] == [0.0, 0.0] and averaged["vrpo1_actor_0504"][0] == -plain["teacher"][0]


def test_a_new_larger_student(tmp_path):
    b = baker(tmp_path, resume=False, init="", width=96, blocks=1, eval_every=10**9, milestone_every=0)
    assert b.student.config == {"width": 96, "blocks": 1, "encoder": 2}
    rows = [b.iterate() for _ in range(3)]
    assert all(np.isfinite(r["kl"]) for r in rows) and rows[-1]["kl"] < rows[0]["kl"]
    import pytest
    with pytest.raises(ValueError, match="width"):
        baker(tmp_path / "x", resume=False, init="")
