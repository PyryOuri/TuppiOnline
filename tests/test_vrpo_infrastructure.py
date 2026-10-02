"""Deferred, small CPU checks; importing VRPO requires the isolated native build."""

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import torch

from tuppi_ai.vrpo import Config, VRPO, _host_stats


def test_host_statistics_keep_the_original_host_reduction():
    tensors = [torch.tensor(v, dtype=torch.float32) for v in (0.003, 0.07, 1.1)]
    old = np.array([float(v) for v in tensors], dtype=np.float64)
    np.testing.assert_array_equal(_host_stats(tensors), old)


def test_evaluation_configuration_validation():
    assert Config(eval_every=0, final_eval_base=8192).eval_every == 0
    for kwargs in ({"eval_every": -1}, {"eval_base": 1}, {"final_eval_base": 1}, {"minibatch": 0}):
        with pytest.raises(ValueError):
            Config(**kwargs)


def learner_stub(out, iteration, final_base=8192):
    learner = object.__new__(VRPO)
    learner.cfg = SimpleNamespace(eval_base=2048, final_eval_base=final_base, isolate_eval_rng=True)
    learner.out, learner.iteration, learner._last_check = out, iteration, None
    return learner


def test_finalize_saves_actual_last_actor_between_checks(tmp_path):
    learner = learner_stub(tmp_path, 5)
    (tmp_path / "actor_0004.pt").write_bytes(b"old actor")

    def evaluate(base):
        assert base == 8192
        (tmp_path / "actor_0005.pt").write_bytes(b"final actor")
        (tmp_path / "critic_latest.pt").write_bytes(b"final critic")
        return {"vs_ref": [0.0, 0.01]}

    with patch.object(learner, "_evaluate_and_save", side_effect=evaluate) as work:
        final = learner.finalize()
        work.assert_called_once_with(8192)
    assert (tmp_path / "actor_final.pt").read_bytes() == b"final actor"
    assert not final["reused_periodic_check"]


def test_finalize_reuses_only_matching_iteration_and_sample_size(tmp_path):
    learner = learner_stub(tmp_path, 6)
    learner._last_check = (6, 8192, {"vs_ref": [0, 0.01]})
    (tmp_path / "actor_0006.pt").write_bytes(b"actor")
    (tmp_path / "critic_latest.pt").write_bytes(b"critic")
    with patch.object(learner, "_evaluate_and_save") as work:
        assert learner.finalize()["reused_periodic_check"]
        work.assert_not_called()


def test_smaller_periodic_check_does_not_replace_full_final_check(tmp_path):
    learner = learner_stub(tmp_path, 6)
    learner._last_check = (6, 2048, {})

    def evaluate(base):
        (tmp_path / "actor_0006.pt").write_bytes(b"actor")
        (tmp_path / "critic_latest.pt").write_bytes(b"critic")
        return {}

    with patch.object(learner, "_evaluate_and_save", side_effect=evaluate) as work:
        assert not learner.finalize()["reused_periodic_check"]
        work.assert_called_once_with(8192)


def test_no_empty_run_can_be_finalized(tmp_path):
    with pytest.raises(RuntimeError):
        learner_stub(tmp_path, 0).finalize()


def test_snapshot_export_preserves_cpu_rng_in_isolated_mode(tmp_path):
    learner = learner_stub(tmp_path, 1)
    learner.actor = torch.nn.Linear(2, 2)
    learner.actor.config = {}
    before = torch.random.get_rng_state().clone()
    with patch("tuppi_ai.vrpo.qmodel.QNet", side_effect=lambda **kw: torch.nn.Linear(2, 2)):
        snapshot = learner._actor_cpu()
    assert torch.equal(before, torch.random.get_rng_state())
    for key, value in learner.actor.state_dict().items():
        assert torch.equal(value, snapshot.state_dict()[key])
