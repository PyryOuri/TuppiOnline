"""T7: one update of the new learner equals one update of ai/tuppi_ai/vrpo.py."""

from __future__ import annotations

import copy

import numpy as np
import torch
from conftest import RULESET, rng

import tuppi_train
from tuppi_train import vrpo_gpu
from tuppi_ai import native, vrpo

GAMES = 384
V1 = str(tuppi_train.MODELS / "vrpo1_actor_0504.pt")


def test_update_equals_the_original(make_env, net1, tmp_path, monkeypatch):
    torch.set_num_threads(1)
    d = native.ppo_rollouts(make_env(GAMES), native.Mlp(net1), GAMES, RULESET, rng(55))
    shared = dict(ruleset=RULESET, games_per_iter=GAMES, minibatch=4096, critic_width=96, critic_blocks=1,
                  compile=False, seed=1)

    old_cfg = vrpo.Config(init=V1, baseline=V1, reference=V1, offer_model="", warmup_iters=0,
                          eval_every=10**9, eval_base=8, **shared)
    old = vrpo.VRPO(old_cfg, tmp_path)
    new_cfg = vrpo_gpu.Config(init=V1, panel="", warmup_max=0, actor_ramp=0, eval_every=10**9, eval_base=8,
                              milestone_every=0, **shared)
    new = vrpo_gpu.Learner(new_cfg, tmp_path / "new", torch.device("cpu"), resume=False)
    new.critic.load_state_dict(copy.deepcopy(old.critic.state_dict()))

    monkeypatch.setattr(native, "ppo_rollouts", lambda *a, **k: {key: v.copy() for key, v in d.items()})
    rows_old, rows_new = [], []
    torch.manual_seed(1234)
    for _ in range(2):
        rows_old.append(old.iterate())
    torch.manual_seed(1234)
    for _ in range(2):
        # The original builds a CPU copy of the actor for its native rollouts before every
        # update; initialising that copy draws from the global generator. Same draws here,
        # so that both updates shuffle their minibatches identically.
        new._actor_cpu()
        rows_new.append(new.update({key: v.copy() for key, v in d.items()}))

    for a, b in zip(rows_old, rows_new):
        for key in ("rows", "critic_loss", "mean_abs_delta", "adv_std", "critic_ev", "choice_share", "entropy",
                    "kl", "clip_frac", "epochs"):
            assert a[key] == b[key], key
        assert b["epochs"] > 0   # the actor really was updated
    for name, net_old, net_new in (("actor", old.actor, new.actor), ("critic", old.critic, new.critic)):
        so, sn = net_old.state_dict(), net_new.state_dict()
        for key in so:
            assert torch.equal(so[key], sn[key]), f"{name}.{key}"
    # and it moved away from the initial network
    assert not torch.equal(new.actor.state_dict()["out.weight"], net1.state_dict()["out.weight"])


def test_warmup_keeps_the_actor_frozen(make_env, net1, tmp_path):
    cfg = vrpo_gpu.Config(init=V1, panel="", games_per_iter=128, minibatch=4096, critic_width=64, critic_blocks=1,
                          warmup_min=3, warmup_max=4, warmup_patience=1, warmup_tol=0.0, eval_every=10**9,
                          eval_base=8, milestone_every=0)
    learner = vrpo_gpu.Learner(cfg, tmp_path, torch.device("cpu"), resume=False)
    before = copy.deepcopy(learner.actor.state_dict())
    rows = [learner.iterate() for _ in range(6)]
    trained = [r["epochs"] > 0 for r in rows]
    assert trained[:3] == [False, False, False]     # never before warmup_min
    assert trained[4] and trained[5]                # always after warmup_max
    first = trained.index(True)
    assert abs(rows[first]["lr_actor"] - cfg.lr_actor / 3) < 1e-12   # starts at a third of the rate
    assert rows[5]["lr_actor"] > rows[first]["lr_actor"]
    assert not torch.equal(before["out.weight"], learner.actor.state_dict()["out.weight"])
    assert all(np.isfinite(r["critic_mc_mse"]) for r in rows)


def small(**extra):
    base = dict(init=V1, panel="vrpo1_actor_0504.pt", games_per_iter=192, minibatch=4096, critic_width=64,
                critic_blocks=1, warmup_max=0, actor_ramp=0, eval_every=10**9, eval_base=16, milestone_every=0)
    return vrpo_gpu.Config(**{**base, **extra})


def test_recomputed_log_probabilities_equal_the_samplers_in_float32(tmp_path):
    """In float32 the learner's own log-probabilities are the sampler's (same network, same
    arithmetic, other batches), so recomputing them changes next to nothing."""
    torch.set_num_threads(1)
    rows = []
    for name, flag in (("a", False), ("b", True)):
        learner = vrpo_gpu.Learner(small(recompute_logp=flag), tmp_path / name, torch.device("cpu"), resume=False)
        rows.append(learner.iterate())
    assert rows[0]["logp_shift"] is None
    assert rows[1]["logp_shift"] < 1e-5
    assert abs(rows[0]["kl"] - rows[1]["kl"]) < 1e-5 and rows[0]["rows"] == rows[1]["rows"]


def test_mixed_precision_trains_and_resumes(tmp_path):
    """bf16 and fp16 forward passes: finite statistics, the actor moves, the learner reports how
    far the sampler's log-probabilities were from its own, evaluation stays in float32 (a
    policy against itself is still exactly 0 before it has moved) and a resume restores the
    gradient scalers."""
    torch.set_num_threads(1)
    for amp in ("bf16", "fp16"):
        out = tmp_path / amp
        learner = vrpo_gpu.Learner(small(amp=amp), out, torch.device("cpu"), resume=False)
        assert learner.evaluate()["vrpo1_actor_0504"] == [0.0, 0.0]
        before = {k: v.clone() for k, v in learner.actor.state_dict().items()}
        rows = [learner.iterate() for _ in range(2)]
        for row in rows:
            assert row["epochs"] > 0 and row["logp_shift"] is not None and row["logp_shift"] < 0.2
            for key in ("critic_loss", "adv_std", "kl", "entropy", "critic_mc_mse"):
                assert np.isfinite(row[key]), (amp, key)
        assert not torch.equal(before["out.weight"], learner.actor.state_dict()["out.weight"])
        assert all(torch.isfinite(v).all() for v in learner.actor.state_dict().values())
        assert learner.scale_a.is_enabled() == (amp == "fp16")
        learner.save()
        again = vrpo_gpu.Learner(small(amp=amp), out, torch.device("cpu"), resume=True)
        assert again.iteration == 2
        assert again.scale_a.state_dict() == learner.scale_a.state_dict()
        assert np.isfinite(again.iterate()["kl"])


def test_unknown_precision_is_refused(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="amp"):
        vrpo_gpu.Learner(small(amp="fp8"), tmp_path, torch.device("cpu"), resume=False)
