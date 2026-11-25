"""The network side of the lockstep collector: forward, sampling, statistics."""

from __future__ import annotations

import numpy as np
import torch
from conftest import RULESET, rng

from tuppi_train import lockstep, tn
from tuppi_ai import native


def test_torch_forward_equals_native_forward(make_env, net1):
    """T5a: PyTorch and the C forward agree on real rows, and choose the same actions."""
    games = 256
    d = lockstep.rollouts(make_env(games), lockstep.RandomLegal(1), games, RULESET, rng(3))
    x = np.unpackbits(d["feat"], axis=1)[:, :native.feature_dim(2)]
    q_native = native.Mlp(net1).forward(x)
    with torch.no_grad():
        q_torch = net1(torch.from_numpy(x)).numpy()
    assert np.abs(q_native - q_torch).max() < 2e-3   # logits are of order 10
    legal = lockstep.unpack_mask(d["mask"])
    a_native = np.where(legal, q_native, -np.inf).argmax(1)
    a_torch, _ = lockstep.TorchGreedy(net1, "cpu")(d["feat"], d["mask"], None, None)
    assert (a_native == a_torch).mean() > 0.999


def test_sampler_follows_the_softmax(make_env, net1):
    """T5b: on one fixed decision, sampled frequencies match softmax(logits) over the legal
    actions (chi-square), nothing illegal is ever drawn, and the returned log-probabilities
    are the log of those probabilities."""
    games = 256
    d = lockstep.rollouts(make_env(games), lockstep.RandomLegal(2), games, RULESET, rng(4))
    legal = lockstep.unpack_mask(d["mask"])
    x = np.unpackbits(d["feat"], axis=1)[:, :native.feature_dim(2)]
    with torch.no_grad():
        q = net1(torch.from_numpy(x)).double().numpy()
    q = np.where(legal, q, -np.inf)
    p = np.exp(q - q.max(1, keepdims=True))
    p /= p.sum(1, keepdims=True)
    # a decision with several actions that are all likely enough to be counted
    row = int(np.argmax((p > 0.05).sum(1)))
    assert (p[row] > 0.05).sum() >= 3
    n = 40000
    sampler = lockstep.TorchSampler(net1, "cpu", 1.0, torch.Generator().manual_seed(9))
    actions, logp = sampler(np.repeat(d["feat"][row:row + 1], n, 0), np.repeat(d["mask"][row:row + 1], n, 0),
                            None, None)
    assert legal[row][actions].all()
    assert np.abs(logp - np.log(p[row][actions])).max() < 1e-4
    seen = np.bincount(actions, minlength=native.NUM_ACTIONS)
    keep = p[row] * n >= 5
    chi2 = (((seen - p[row] * n) ** 2)[keep] / (p[row] * n)[keep]).sum()
    assert chi2 < 3 * keep.sum() + 20   # far beyond any plausible chance deviation
    assert seen[~keep].sum() <= (p[row][~keep].sum() * n) * 3 + 20


def test_forced_decisions_have_zero_log_probability(make_env, net1):
    games = 256
    sampler = lockstep.TorchSampler(net1, "cpu", 1.0, torch.Generator().manual_seed(1))
    d = lockstep.rollouts(make_env(games), sampler, games, RULESET, rng(6))
    forced = lockstep.unpack_mask(d["mask"]).sum(1) == 1
    assert forced.any() and (d["logp"][forced] == 0).all()
    assert (d["logp"] <= 0).all() and np.isfinite(d["logp"]).all()


def test_sampled_rollouts_look_like_native_ones(make_env, net1):
    """T6: independent deals played by the same policy through the two collectors agree on
    everything the policy controls: decisions per deal, how often it bids RAMI, how often a
    sooli is played, the mix of action types and the mean behaviour log-probability.
    (Not a proof: T3 to T5 are the exact tests. This one would catch a wrong temperature,
    a wrong mask or a sampler bias.)"""
    games = 6144
    env_n, env_l = make_env(games), make_env(games)
    dn = native.ppo_rollouts(env_n, native.Mlp(net1), games, RULESET, rng(101))
    sampler = lockstep.TorchSampler(net1, "cpu", 1.0, torch.Generator().manual_seed(2))
    dl = lockstep.rollouts(env_l, sampler, games, RULESET, rng(202))
    cn, cl = tn.summary(env_n, games), tn.summary(env_l, games)

    def z_share(k1, k2, n=games):
        p1, p2 = k1 / n, k2 / n
        p = (p1 + p2) / 2
        return abs(p1 - p2) / np.sqrt(max(1e-12, 2 * p * (1 - p) / n))

    assert z_share(cn["rami"], cl["rami"]) < 4
    assert z_share(cn["sooli"], cl["sooli"]) < 4
    assert z_share(cn["team0_wins"], cl["team0_wins"]) < 4
    def per_deal(d, weights=None):
        return np.bincount(d["deal"], weights=weights, minlength=games)

    def z_mean(a, b):
        return abs(a.mean() - b.mean()) / np.sqrt(a.var() / len(a) + b.var() / len(b) + 1e-18)

    assert abs(per_deal(dn).mean() - 54) < 2                 # about 54 decisions a deal
    assert z_mean(per_deal(dn), per_deal(dl)) < 4
    for lo, hi in ((0, 52), (52, 104), (104, 156)):          # card plays, shows of either contract
        kn = per_deal(dn, ((dn["action"] >= lo) & (dn["action"] < hi)).astype(float))
        kl = per_deal(dl, ((dl["action"] >= lo) & (dl["action"] < hi)).astype(float))
        assert kn.sum() > 0 and z_mean(kn, kl) < 4, (lo, kn.mean(), kl.mean())
    # log-probability of the chosen actions, summed per deal: sensitive to temperature and masking
    assert z_mean(per_deal(dn, dn["logp"].astype(float)), per_deal(dl, dl["logp"].astype(float))) < 4
