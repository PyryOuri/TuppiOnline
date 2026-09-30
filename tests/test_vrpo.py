"""VRPO pieces: the native on-policy trajectories and the Expected SARSA(lambda) trace."""

import ctypes as C
from pathlib import Path

import numpy as np
import pytest
import torch

from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.value import _unpack
from tuppi_ai.vrpo import HIDDEN_BITS, pack_hidden, trace

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "models" / "sp1_policy_043.pt"


def slow_trace(qa, v, team, reward, deal, step, lam):
    """Reference: per deal, backwards, everything from the acting team's side."""
    G = np.zeros(len(qa))
    for dl in np.unique(deal):
        rows = np.where(deal == dl)[0]
        rows = rows[np.argsort(step[rows])]
        run = 0.0
        for j in range(len(rows) - 1, -1, -1):
            t = rows[j]
            side = 1.0 if team[t] == 0 else -1.0
            if j == len(rows) - 1:
                delta, cont = reward[dl] * side - qa[t], 0.0
            else:
                u = rows[j + 1]
                f = 1.0 if team[u] == team[t] else -1.0
                delta, cont = f * v[u] - qa[t], f * run
            run = delta + lam * cont
            G[t] = run
    return G


def test_trace_matches_reference():
    rng = np.random.default_rng(3)
    lengths = [5, 1, 9, 3]
    deal = np.concatenate([np.full(n, i) for i, n in enumerate(lengths)])
    step = np.concatenate([np.arange(n) for n in lengths])
    perm = rng.permutation(len(deal))  # rows in any order
    deal, step = deal[perm], step[perm]
    n = len(deal)
    qa, v = rng.normal(size=n), rng.normal(size=n)
    team = rng.integers(0, 2, n)
    reward = rng.normal(size=len(lengths))
    index = torch.full((len(lengths), max(lengths)), -1, dtype=torch.long)
    index[torch.from_numpy(deal), torch.from_numpy(step)] = torch.arange(n)
    G, _ = trace(torch.tensor(qa, dtype=torch.float32), torch.tensor(v, dtype=torch.float32),
                 torch.from_numpy(team), torch.tensor(reward, dtype=torch.float32), index, 0.9)
    np.testing.assert_allclose(G.numpy(), slow_trace(qa, v, team, reward, deal, step, 0.9), atol=1e-5)
    # lambda = 1 with a zero critic: G is the Monte Carlo return from each acting team's side
    G1, _ = trace(torch.zeros(n), torch.zeros(n), torch.from_numpy(team), torch.tensor(reward, dtype=torch.float32),
                  index, 1.0)
    np.testing.assert_allclose(G1.numpy(), np.where(team == 0, 1.0, -1.0) * reward[deal], atol=1e-6)


def test_pack_hidden_roundtrip():
    rng = np.random.default_rng(1)
    h = rng.integers(0, 2 ** 52, size=(7, 3), dtype=np.uint64)
    bits = _unpack(torch.from_numpy(pack_hidden(h)), HIDDEN_BITS).numpy().astype(np.uint64)
    back = (bits.reshape(7, 3, 52) << np.arange(52, dtype=np.uint64)).sum(2)
    np.testing.assert_array_equal(back, h)


@pytest.mark.skipif(not POLICY.exists(), reason="SP1 policy not present")
def test_rollouts_are_consistent():
    torch.set_num_threads(1)
    net = qmodel.load(POLICY, "cpu").eval()
    mlp = native.Mlp(net)
    env = native.Env(64, 5, None, single_deal=True, encoder=net.encoder)
    env.set_sooli(0, False, False, 0.0)
    d = native.ppo_rollouts(env, mlp, 64, 3, C.c_uint64(9), 1.0)
    n, dim = len(d["action"]), native.feature_dim(net.encoder)
    assert 64 * 40 < n < 64 * 64
    # every deal's steps run 0..len-1 exactly once
    for dl in range(64):
        s = np.sort(d["step"][d["deal"] == dl])
        np.testing.assert_array_equal(s, np.arange(len(s)))
    mask = _unpack(torch.from_numpy(d["mask"]), native.NUM_ACTIONS).bool()
    assert bool(mask[torch.arange(n), torch.from_numpy(d["action"].astype(np.int64))].all())
    # the behaviour log-probabilities are the network's softmax over the legal actions
    x = _unpack(torch.from_numpy(d["feat"]), dim)
    with torch.no_grad():
        lp = torch.log_softmax(net(x).masked_fill(~mask, -1e9), 1)
    lp = lp[torch.arange(n), torch.from_numpy(d["action"].astype(np.int64))].numpy()
    np.testing.assert_allclose(lp, d["logp"], atol=2e-3)
    # the hidden hands are disjoint
    h = d["hidden"]
    assert not np.any(h[:, 0] & h[:, 1]) and not np.any(h[:, 0] & h[:, 2]) and not np.any(h[:, 1] & h[:, 2])
    assert np.isfinite(d["reward"]).all() and np.abs(d["reward"]).max() < 1.0
