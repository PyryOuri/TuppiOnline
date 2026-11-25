"""Labels and the improvement maths against the repository's CPU implementation."""

from __future__ import annotations

import ctypes as C

import numpy as np
import pytest
import torch
from conftest import RULESET, rng

import tuppi_train
from tuppi_train import improve, labels, lockstep
from tuppi_ai import native, selfplay

V1 = str(tuppi_train.MODELS / "vrpo1_actor_0504.pt")


def constant_offer(bias: float) -> "native.Mlp":
    """An offer model that always (bias >> 0) or never (bias << 0) accepts: no randomness left
    in the sooli phases, so label equality can be exact."""
    from tuppi_ai.value import VNet
    v = VNet(8, 1, in_dim=native.feature_dim(1))
    with torch.no_grad():
        for p in v.parameters():
            p.zero_()
        v.out.bias.fill_(bias)
    return native.Mlp(v, in_dim=v.config["in_dim"], out_dim=1)


def as_structs(states: np.ndarray):
    return (native.TcDeal * len(states)).from_buffer_copy(states.tobytes())


def native_labels(env, mlp, states, dd):
    buf, n = as_structs(states), len(states)
    k = native.encode_states(buf, n, 2)[1].sum(1)
    acts, ks, qs, start = [], [], [], 0
    while start < n:
        stop = start + max(1, int(np.searchsorted(np.cumsum(k[start:]), env.n, side="right")))
        a, kk, q = native.branch_values(env, mlp, buf, stop - start, dd, rng(1), offset=start)
        acts.append(a), ks.append(kk), qs.append(q)
        start = stop
    a, kk, q = np.concatenate(acts), np.concatenate(ks), np.concatenate(qs)
    valid = np.arange(native.MAX_K)[None] < kk[:, None]
    return np.where(valid, a, labels.PAD).astype(np.uint8), np.where(valid, q, 0).astype(np.float16)


@pytest.fixture(scope="module")
def recorded(table, net1):
    env = native.Env(640, 1, table, single_deal=True, encoder=2)
    env.set_sooli(0, False, False, 0.0)
    mlp = native.Mlp(net1)
    data = labels.collect(env, lockstep.NativeGreedy(mlp), 640, rng(5), p_record=0.08, p_explore=0.02, seed=3)
    return mlp, data


def test_recorded_states_are_the_engines(recorded):
    """A recorded state re-encodes to the row the engine showed, its class is tc_record_class,
    and the exploration flag marks exactly the states after a random move in their deal."""
    _, d = recorded
    n = len(d["states"])
    assert n > 1500 and d["dropped"] == 0
    buf = as_structs(d["states"])
    feat, mask = native.encode_states(buf, n, 2)
    assert np.array_equal(np.packbits(feat, axis=1), d["feat"])
    assert np.array_equal(np.packbits(mask, axis=1), d["mask"])
    assert (mask.sum(1) > 1).all()                       # unforced decisions only
    assert np.array_equal(native.record_classes(buf, n), d["cls"])
    assert np.array_equal(labels.record_classes(d["states"]), d["cls"])
    assert 0.05 < d["explored"].mean() < 0.6
    first = {}                                           # per game, flags never go from 1 back to 0
    for game, flag in zip(d["game"], d["explored"]):
        assert flag >= first.get(game, 0)
        first[game] = max(first.get(game, 0), flag)


@pytest.mark.parametrize("offer_bias", [-50.0, 50.0])
@pytest.mark.parametrize("share", [False, True])
@pytest.mark.parametrize("dd", [0, 6])
def test_labels_equal_native_branch_values(recorded, make_env, offer_bias, share, dd):
    """Lockstep labels, driven by the exact CPU forward, equal native.branch_values: own play
    and solver tail, with and without label sharing, sooli always and never accepted (so the
    sooli exchange and its solver are covered)."""
    mlp, d = recorded
    states = d["states"][:900]
    native.set_offer_model(constant_offer(offer_bias))
    native.set_branch_share(share)
    native.set_rollout_chunk(128)
    want_ids, want_q = native_labels(make_env(30000), mlp, states, dd)
    timing = {}
    ids, q = labels.branch_labels(make_env(30000), states, lockstep.NativeGreedy(mlp),
                                  labels.state_seeds(len(states), 9), dd, timing=timing)
    assert np.array_equal(want_ids, ids)
    assert np.array_equal(want_q, q)
    assert (ids != labels.PAD).sum(1).min() >= 2 and np.abs(q.astype(np.float32)).max() > 0
    if dd:
        assert timing["solver"] > 0


def test_labels_do_not_depend_on_the_slots(recorded, make_env):
    """Same labels from a fresh environment, from one that just played other games, in one chunk
    or several, and with real sooli randomness: each state's play-outs use its own seed."""
    mlp, d = recorded
    states = d["states"][:500]
    seeds = labels.state_seeds(len(states), 4)
    choose = lockstep.NativeGreedy(mlp)
    fresh = labels.branch_labels(make_env(20000), states, choose, seeds, 0)
    used = make_env(20000)
    lockstep.rollouts(used, lockstep.RandomLegal(1), 2000, RULESET, rng(77))
    again = labels.branch_labels(used, states, choose, seeds, 0)
    small = labels.branch_labels(make_env(26 * 40), states, choose, seeds, 0)   # 40 states per chunk
    for other in (again, small):
        assert np.array_equal(fresh[0], other[0]) and np.array_equal(fresh[1], other[1])
    other_seeds = labels.branch_labels(make_env(20000), states, choose, labels.state_seeds(len(states), 5), 0)
    assert (fresh[1] == other_seeds[1]).mean() > 0.98      # sooli draws rarely matter


def test_greedy_breaks_ties_to_the_lowest_id():
    v = torch.tensor([[1.0, 3.0, 3.0, float("-inf")], [2.0, 2.0, 2.0, 2.0], [float("-inf"), -1.0, -5.0, -1.0]])
    assert improve.greedy(v).tolist() == [1, 0, 1]
    assert improve.greedy(v.half()).tolist() == [1, 0, 1]


def test_composite_choice_is_its_definition():
    g = torch.Generator().manual_seed(0)
    q, pi = torch.randn(400, 156, generator=g), torch.randn(400, 156, generator=g)
    legal = torch.rand(400, 156, generator=g) < 0.05
    legal[:, 0] = True
    show = torch.arange(400) % 3 == 0
    margin = improve.margins_for(show, 0.03, 0.003)
    new, old = improve.composite_choice(q, pi, legal, margin)
    for r in range(400):
        ids = torch.nonzero(legal[r])[:, 0].tolist()
        o = max(ids, key=lambda a: (pi[r, a].item(), -a))
        assert old[r] == o
        m = (0.03 if show[r] else 0.003) * improve.SCALE
        assert new[r] == max(ids, key=lambda a: (q[r, a].item() + (m if a == o else 0.0), -a))
    huge = improve.composite_choice(q, pi, legal, torch.full((400,), 1e6))
    assert torch.equal(huge[0], huge[1])                 # a large margin keeps the policy
    kept = improve.composite_choice(q, pi, legal, torch.zeros(400), keep=show)
    assert torch.equal(kept[0][show], kept[1][show]) and not torch.equal(kept[0], kept[1])


def test_tail_rows():
    cls = torch.tensor([0, 1, 7, 8, 13, 14, 20, 21, 26], dtype=torch.int8)   # show; NOLO tricks 0,6,7,12; RAMI 0,6,7,12
    assert improve.tail_rows(cls, 6).tolist() == [False, False, False, True, True, False, False, True, True]


@pytest.fixture(scope="module")
def sp_data(recorded, table):
    """Labelled rows in selfplay.py's format, and a selfplay.Learner on the CPU to compare with."""
    mlp, d = recorded
    env = native.Env(30000, 2, table, single_deal=True, encoder=2)
    env.set_sooli(0, False, False, 0.0)
    native.set_offer_model(None)
    native.set_branch_share(False)
    ids, q = labels.branch_labels(env, d["states"], lockstep.NativeGreedy(mlp), labels.state_seeds(len(d["states"]), 1), 0)
    mult = np.linspace(0.5, 2.0, labels.N_CLASSES)
    data = {"feat": d["feat"], "ids": ids, "q": q, "w": improve.importance_weights(d["cls"], mult), "cls": d["cls"],
            "explored": d["explored"]}
    cfg = selfplay.Config(init=V1, baseline=V1, offer_model="", compile=False, selfplay_games=64, label_games=64,
                          eval_base=8, q_steps=40, batch=512, incremental=False)
    torch.manual_seed(0)
    sp = selfplay.Learner(cfg, None)
    native.set_showing_fix(False)
    native.set_branch_share(False)
    return data, sp


def test_teacher_and_gain_equal_selfplay(sp_data, net1):
    """fit_teacher, adv_r2 and heldout_gain against selfplay.Learner.train_q / adv_r2 /
    heldout_gain on the same rows, from the same weights and random draws."""
    data, sp = sp_data
    torch.set_num_threads(1)
    D = improve.to_device(data, "cpu")
    n = len(D["feat"])
    H, T = improve.take(D, torch.arange(0, n // 5)), improve.take(D, torch.arange(n // 5, n))
    spH, spT = ({k: X[k] for k in ("feat", "ids", "q", "w")} for X in (H, T))
    teacher = improve.new_teacher(0, 0, 2, "cpu", warm_from=net1)
    sp.qnet.load_state_dict(teacher.state_dict())
    sp.opt_q = torch.optim.AdamW(sp.qnet.parameters(), lr=sp.cfg.lr_q, weight_decay=sp.cfg.wd_q)
    assert improve.adv_r2(teacher, H, 1951) == sp.adv_r2(spH)
    torch.manual_seed(42)
    want = sp.train_q(spT, spH)
    torch.manual_seed(42)
    got = improve.fit_teacher(teacher, T, H, steps=40, batch=512, lr=sp.cfg.lr_q, wd=sp.cfg.wd_q)
    assert (got["adv_mse"], got["adv_r2"], got["best_step"]) == want
    for key, value in sp.qnet.state_dict().items():
        assert torch.equal(value, teacher.state_dict()[key]), key
    for margin in (0.0, 0.006, 0.05):
        w_mean, w_se, w_changed = sp.heldout_gain(spH, margin)
        g = improve.heldout_gain(net1, teacher, H, margin, margin)
        assert (g["gain"], g["se"], g["changed"]) == pytest.approx((w_mean, w_se, w_changed), rel=1e-9, abs=1e-12)
    labels_sp, diag = sp.composite_labels(spT, 0.006)
    x, m, _, _ = improve._batch(T, torch.arange(len(T["feat"])), 1951)
    with torch.no_grad():
        new, old = improve.composite_choice(teacher(x), net1(x), m, torch.full((len(x),), 0.006 * improve.SCALE))
    assert torch.equal(new, labels_sp) and float((new != old).float().mean()) == pytest.approx(diag["changed"])


def test_gain_options(sp_data, net1):
    """Clean-only gains use only states with no exploration move before them; a restricted
    composite changes nothing in the last tricks; separate margins act on their own rows."""
    data, _ = sp_data
    D = improve.to_device(data, "cpu")
    teacher = improve.new_teacher(0, 0, 2, "cpu", warm_from=net1)
    torch.manual_seed(1)
    improve.fit_teacher(teacher, D, D, steps=30, batch=512)
    full = improve.heldout_gain(net1, teacher, D, 0.0, 0.0)
    clean = improve.heldout_gain(net1, teacher, D, 0.0, 0.0, clean_only=True)
    assert clean["states"] == int(D["clean"].sum()) < full["states"]
    only_clean = improve.heldout_gain(net1, teacher, improve.take(D, torch.nonzero(D["clean"])[:, 0]), 0.0, 0.0)
    assert clean["gain"] == pytest.approx(only_clean["gain"], rel=1e-9)
    no_tail = improve.heldout_gain(net1, teacher, D, 0.0, 0.0, min_tricks_left=6)
    assert 0 < no_tail["changed"] < full["changed"]
    tail = improve.take(D, torch.nonzero(improve.tail_rows(D["cls"], 6))[:, 0])
    assert improve.heldout_gain(net1, teacher, tail, 0.0, 0.0, min_tricks_left=6)["changed"] == 0
    show_only = improve.heldout_gain(net1, teacher, D, 0.0, 1e6)
    play_only = improve.heldout_gain(net1, teacher, D, 1e6, 0.0)
    assert show_only["changed"] + play_only["changed"] == pytest.approx(full["changed"])
    assert show_only["changed"] > 0 and play_only["changed"] > 0


def test_composite_chooser_plays_the_composite(make_env, net1, sp_data):
    """The chooser picks, row by row, what composite_choice defines (also in half precision),
    with the margins by phase and the tail restriction read from the live games."""
    data, _ = sp_data
    D = improve.to_device(data, "cpu")
    teacher = improve.new_teacher(0, 0, 2, "cpu", warm_from=net1)
    torch.manual_seed(2)
    improve.fit_teacher(teacher, D, D, steps=30, batch=512)
    teacher.eval()
    games, seen = 96, {"rows": 0, "diff": 0}
    env = make_env(games)

    def checked(amp, min_left):
        chooser = improve.Composite(net1, teacher, "cpu", env, 0.002, 0.0, min_left, amp)

        def choose(feat, mask, idx, team):
            actions, _ = chooser(feat, mask, idx, team)
            cls = np.zeros(len(idx), np.int8)
            improve.lib.tc_ls_classes(env._h, np.ascontiguousarray(idx, np.int32).ctypes.data, len(idx),
                                      cls.ctypes.data, None)
            x = torch.from_numpy(np.unpackbits(feat, axis=1)[:, :1951])
            legal = torch.from_numpy(lockstep.unpack_mask(mask))
            c = torch.from_numpy(cls)
            with torch.no_grad():
                new, old = improve.composite_choice(
                    improve.forward(teacher, x, amp), improve.forward(net1, x, amp), legal,
                    improve.margins_for(c == 0, 0.002, 0.0), improve.tail_rows(c, min_left) if min_left else None)
            assert np.array_equal(new.numpy(), actions)
            seen["rows"] += len(idx)
            seen["diff"] += int((new != old).sum())
            return actions, None
        return choose, chooser

    for amp, min_left in ((None, 0), (None, 6), (torch.bfloat16, 0)):
        choose, chooser = checked(amp, min_left)
        lockstep.rollouts(env, choose, games, RULESET, rng(3))
        assert chooser.rows > 4000 and chooser.changed > 0
    assert seen["diff"] > 0


def test_direct_improvement_follows_the_labels(sp_data, net1):
    """fit_policy raises the expected label of the net's own choice: fitted and judged on the
    same rows its greedy gain becomes positive; with no steps it is the policy unchanged; a
    restricted gain ignores the last tricks."""
    data, _ = sp_data
    D = improve.to_device(data, "cpu")
    same, info0 = improve.fit_policy(net1, D, D, steps=0)
    assert info0["best_step"] == 0
    assert all(torch.equal(v, net1.state_dict()[k]) for k, v in same.state_dict().items())
    assert improve.greedy_gain(net1, same, D)["changed"] == 0
    torch.manual_seed(3)
    better, info = improve.fit_policy(net1, D, D, steps=120, batch=1024, lr=1e-4, check_every=30, patience=10)
    g = improve.greedy_gain(net1, better, D)
    assert info["best_step"] > 0 and g["gain"] > 0 and g["z"] > 2 and 0 < g["changed"] < 0.5
    assert g["states"] == int(D["clean"].sum())
    early = improve.greedy_gain(net1, better, D, min_tricks_left=6)
    assert 0 < early["changed"] < g["changed"]
    assert not torch.equal(better.state_dict()["out.weight"], net1.state_dict()["out.weight"])
    assert torch.equal(net1.state_dict()["out.weight"], qm_load_v1()["out.weight"])   # the policy itself is untouched


def qm_load_v1():
    return torch.load(V1, weights_only=False)["state"]


def test_mixed_chooser(make_env, net1, mlp3):
    """Mixed plays the first chooser, except in the last tricks, where it plays the second."""
    games = 96
    env = make_env(games)
    a, b = lockstep.TorchGreedy(net1, "cpu"), lockstep.NativeGreedy(mlp3)
    mixed = improve.Mixed(a, b, env, 6)
    seen = {"tail": 0, "other": 0}

    def choose(feat, mask, idx, team):
        actions, _ = mixed(feat, mask, idx, team)
        cls = np.zeros(len(idx), np.int8)
        improve.lib.tc_ls_classes(env._h, np.ascontiguousarray(idx, np.int32).ctypes.data, len(idx), cls.ctypes.data, None)
        tail = improve.tail_rows(torch.from_numpy(cls), 6).numpy()
        assert np.array_equal(actions[tail], b(feat[tail], mask[tail], idx[tail], None)[0])
        assert np.array_equal(actions[~tail], a(feat[~tail], mask[~tail], idx[~tail], None)[0])
        seen["tail"] += int(tail.sum())
        seen["other"] += int((~tail).sum())
        return actions, None

    lockstep.rollouts(env, choose, games, RULESET, rng(2))
    assert seen["tail"] > 1000 and seen["other"] > 1000 and 0 < mixed.changed < mixed.rows
    everywhere = improve.Mixed(a, b, env, 0)
    d1 = lockstep.rollouts(make_env(games), everywhere, games, RULESET, rng(2))
    d2 = lockstep.rollouts(make_env(games), a, games, RULESET, rng(2))
    assert np.array_equal(d1["action"], d2["action"])
