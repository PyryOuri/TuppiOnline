"""The suit symmetry maps against the engine, and the averaged network."""

from __future__ import annotations

import numpy as np
import pytest
import torch
from conftest import rng

import tuppi_train
from tuppi_train import labels, lockstep, symmetry
from tuppi_ai import native

DIM = 1951


@pytest.fixture(scope="module")
def recorded(table, net1):
    """Unforced decisions from self-play with exploration: showing and card play, every trick."""
    env = native.Env(1024, 1, table, single_deal=True, encoder=2)
    env.set_sooli(0, False, False, 0.0)
    d = labels.collect(env, lockstep.TorchGreedy(net1, "cpu"), 1024, rng(7), p_record=0.25, p_explore=0.05, seed=2)
    assert len(d["states"]) > 8000 and (d["cls"] == 0).sum() > 300
    return d


def engine_encode(states: np.ndarray):
    buf = (native.TcDeal * len(states)).from_buffer_copy(states.tobytes())
    return native.encode_states(buf, len(states), 2)


@pytest.mark.parametrize("view", [1, 2, 3])
def test_maps_equal_the_engine(recorded, view):
    """Relabel the suits of a full state and let the engine encode it: its features are the
    original features with the columns permuted by feature_perm, and its legal actions are the
    original ones permuted by action_perm."""
    suits = symmetry.SUIT_PERMS[view]
    states = recorded["states"]
    feat, mask = engine_encode(states)
    feat_p, mask_p = engine_encode(symmetry.permute_states(states, suits))
    assert np.array_equal(feat_p, feat[:, symmetry.feature_perm(suits)])
    ap = symmetry.action_perm(suits)
    assert np.array_equal(mask_p[:, ap], mask)
    assert not np.array_equal(feat_p, feat) and not np.array_equal(mask_p, mask)   # the relabelling does something
    # the sample exercises the encoder: nearly every column that moves is set somewhere
    moved = symmetry.feature_image(suits) != np.arange(DIM)
    assert moved.sum() > 800 and (feat[:, moved].any(0)).mean() > 0.9
    # encoder 1 is the first 1223 columns
    assert np.array_equal(symmetry.feature_perm(suits, 1), symmetry.feature_perm(suits)[:1223])


def test_views_form_the_group():
    ident = np.arange(DIM)
    assert np.array_equal(symmetry.feature_perm(symmetry.SUIT_PERMS[0]), ident)
    assert np.array_equal(symmetry.action_perm(symmetry.SUIT_PERMS[0]), np.arange(156))
    f = [symmetry.feature_perm(s) for s in symmetry.SUIT_PERMS]
    a = [symmetry.action_perm(s) for s in symmetry.SUIT_PERMS]
    for v in (1, 2, 3):
        assert np.array_equal(f[v][f[v]], ident) and np.array_equal(a[v][a[v]], np.arange(156))   # swaps undo themselves
        assert sorted(f[v]) == list(range(DIM)) and sorted(a[v]) == list(range(156))
    assert np.array_equal(f[1][f[2]], f[3]) and np.array_equal(a[1][a[2]], a[3])
    # colours are kept: a red card stays red, so a show keeps its contract and its verbal flag
    for v in (1, 2, 3):
        cp = symmetry.card_perm(symmetry.SUIT_PERMS[v])
        assert all((c // 26) == (cp[c] // 26) and c % 13 == cp[c] % 13 for c in range(52))


def test_symmetric_network_is_the_average_over_relabelled_states(recorded, net1):
    """Symmetric(net) equals the long way round: relabel the full state, encode it with the
    engine, run the plain network, map the logits back, average."""
    states = recorded["states"][:3000]
    feat, mask = engine_encode(states)
    sym = symmetry.Symmetric(net1).eval()
    with torch.no_grad():
        got = sym(torch.from_numpy(feat)).numpy()
        want = np.zeros_like(got)
        for suits in symmetry.SUIT_PERMS:
            f = engine_encode(symmetry.permute_states(states, suits))[0]
            want += net1(torch.from_numpy(f)).numpy()[:, symmetry.action_perm(suits)] / 4
    assert np.abs(got - want).max() < 1e-4
    legal = mask.astype(bool)
    plain = np.where(legal, net1(torch.from_numpy(feat)).detach().numpy(), -np.inf).argmax(1)
    averaged = np.where(legal, got, -np.inf).argmax(1)
    assert 0.03 < (plain != averaged).mean() < 0.6      # the plain network is far from symmetric
    assert sym.encoder == 2 and sym.config["symmetric"] == [0, 1, 2, 3] and sym.config["width"] == 256


def test_symmetric_network_is_invariant(recorded, net1):
    """The averaged network gives the corresponding logits in every view, the plain one does not;
    view_of produces the relabelled row and target."""
    feat, mask = engine_encode(recorded["states"][:2000])
    x, legal = torch.from_numpy(feat), torch.from_numpy(mask.astype(bool))
    sym = symmetry.Symmetric(net1).eval()
    with torch.no_grad():
        base = sym(x)
        plain = net1(x)
        cache: dict = {}
        for view in (1, 2, 3):
            xv, lv, tv = symmetry.view_of(x, legal, base, view, cache=cache)
            suits = symmetry.SUIT_PERMS[view]
            assert torch.equal(xv, x[:, torch.from_numpy(symmetry.feature_perm(suits))])
            assert torch.equal(lv[:, torch.from_numpy(symmetry.action_perm(suits))], legal)
            assert (sym(xv) - tv).abs().max() < 1e-4            # invariant
            assert (net1(xv) - symmetry.view_of(x, legal, plain, view, cache=cache)[2]).abs().max() > 0.1   # not
        assert len(cache) == 3
        same = symmetry.view_of(x, legal, base, 0)
        assert same[0] is x and same[1] is legal and same[2] is base


def test_symmetric_network_plays(make_env, net1):
    """It is a drop-in network for the choosers, and a symmetric network against itself scores 0."""
    sym = symmetry.Symmetric(net1).eval()
    a = lockstep.TorchGreedy(sym, "cpu")
    v = lockstep.duplicate_eval(make_env(8 * 24), a, a, 24, 3, rng(4))
    assert np.array_equal(v, np.zeros(24))
    w = lockstep.duplicate_eval(make_env(8 * 24), a, lockstep.TorchGreedy(net1, "cpu"), 24, 3, rng(4))
    assert np.abs(w).max() > 0


def test_load_net_prefix():
    plain = symmetry.load_net("vrpo1_actor_0504.pt", "cpu")
    sym = symmetry.load_net("sym:vrpo1_actor_0504.pt", "cpu")
    assert not isinstance(plain, symmetry.Symmetric) and isinstance(sym, symmetry.Symmetric)
    assert not sym.training and torch.equal(sym.net.state_dict()["out.weight"], plain.state_dict()["out.weight"])
    assert symmetry.load_net(str(tuppi_train.MODELS / "vrpo1_actor_0504.pt"), "cpu").config["width"] == 256
