"""The teaching pilot (tuppi_train/teach.py) and the look-ahead options it uses."""

from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from tuppi_train import calibrate, lookahead, teach
from tuppi_ai import native


@pytest.fixture(autouse=True)
def engine_settings():
    yield
    native.set_showing_fix(False)
    native.set_offer_model(None)


def test_choices_and_targets():
    d = {"m": np.float32([[0, 0.02, 0.01, 0], [0, 0.02, 0, 0], [0, 0.001, 0, 0], [0, 0.02, 0.05, 0.9]]),
         "se": np.float32([[0, 0.005, 0.001, 0], [0, 0.015, 0, 0], [0, 0.0001, 0, 0], [0, 0.03, 0.01, 0.0]]),
         "k": np.int8([3, 2, 2, 3]), "phase": np.int8([2, 2, 3, 1]), "effective": np.float32([8, 8, 8, 8])}
    # phase 2 needs 1 standard error, phase 3 none, phase 1 two; the margin is 0.003; padding never
    assert teach.choices(d).tolist() == [1, 1, 0, 2]
    assert teach.choices(d, z_by_phase=(2, 2, 2, 2)).tolist() == [1, 0, 0, 2]
    assert teach.choices(d, keep=0.03).tolist() == [0, 0, 0, 2]
    logits = torch.tensor([[1.0, 5.0, 2.0, -1e9], [3.0, 0.0, 1.0, 2.0]])
    t = teach.targets(logits, torch.tensor([1, 0]), torch.tensor([2, 0]))
    assert t.tolist() == [[1.0, 2.0, 5.0, -1e9], [3.0, 0.0, 1.0, 2.0]]


def test_phase_filter_and_sharper_inference(table, net1):
    """--phases restricts the look-ahead to the marked phases; the likelihood's temperature and
    uniform share change the resampled worlds."""
    from test_lookahead import match
    native.set_showing_fix(True)
    _, late = match(table, net1, lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=0.5, phases="0,0,1,1"))
    assert late.stats["phase_searched"][:2] == [0, 0] and min(late.stats["phase_searched"][2:]) > 0
    soft, _ = match(table, net1, lookahead.Settings(worlds=6, top=3, min_prob=0.02, z=0.5, belief=4), base=8)
    sharp, _ = match(table, net1, lookahead.Settings(worlds=6, top=3, min_prob=0.02, z=0.5, belief=4, belief_t=0.5,
                                                     belief_eps=0.05), base=8)
    assert not np.array_equal(soft, sharp)


def test_record_fit_and_compare(tmp_path):
    """Labels are recorded in the chosen phases and resumed; a fit runs end to end, keeps a
    network of the original's shape, and reports play; two recordings of the same decisions
    compare, and a recording of other decisions is refused."""
    s = lookahead.Settings(worlds=6, top=3, min_prob=0.02, belief=3, phases="0,0,1,1")
    kw = dict(games=96, dev=torch.device("cpu"), lane_games=8192, log=lambda x: None)
    assert teach.record(tmp_path / "t", "vrpo1_actor_0504.pt", s, hours=1, max_shards=1, **kw) == 1
    first = (tmp_path / "t" / "labels" / "shard_00000.npz").read_bytes()
    assert teach.record(tmp_path / "t", "vrpo1_actor_0504.pt", s, hours=1, max_shards=2, **kw) == 2
    assert (tmp_path / "t" / "labels" / "shard_00000.npz").read_bytes() == first
    with pytest.raises(SystemExit):
        teach.record(tmp_path / "t", "vrpo1_actor_0504.pt", lookahead.Settings(worlds=7, phases="0,0,1,1"), hours=1, **kw)
    d = teach.load_labels(tmp_path / "t")
    n = len(d["k"])
    assert n > 500 and set(np.unique(d["phase"]).tolist()) == {2, 3} and (d["k"] >= 2).all()
    assert d["feat"].shape == (n, 244) and d["m"].shape == (n, 3) and not d["m"][:, 0].any() and (d["se"] >= 0).all()
    assert (teach.choices(d) < d["k"]).all() and 0 < (teach.choices(d) > 0).mean() < 0.6
    r = teach.fit(tmp_path / "t", "vrpo1_actor_0504.pt", torch.device("cpu"), steps=6, batch=256, lr=1e-4, snapshots=2,
                  eval_base=16, match_pairs=8, log=lambda x: None)
    assert set(r["snapshots"]) == {"3", "6"} and r["best_step"] in (3, 6) and (tmp_path / "t" / "taught.pt").exists()
    assert 0 <= r["before"]["changed"] < 0.2 and r["before"]["kept"] > 0.9       # the rule's changes are not the net's moves
    assert r["snapshots"]["6"]["changed"] >= r["before"]["changed"] and r["matches"]["pairs"] == 8
    assert json.loads((tmp_path / "t" / "fit.json").read_text())["decisions"] == n
    from tuppi_ai import model as qmodel
    assert qmodel.load(tmp_path / "t" / "taught.pt", "cpu").config == qmodel.load(
        __import__("tuppi_train").MODELS / "vrpo1_actor_0504.pt", "cpu").config

    base = lookahead.Settings(worlds=6, top=3, min_prob=0.02, belief=3)
    kw = dict(base=8, chunk=4, dev=torch.device("cpu"), lane_games=4096, log=lambda x: None)
    calibrate.record(tmp_path / "soft", "vrpo1_actor_0504.pt", base, **kw)
    calibrate.record(tmp_path / "sharp", "vrpo1_actor_0504.pt", lookahead.Settings(worlds=6, top=3, min_prob=0.02, belief=3,
                                                                                    belief_t=0.5, belief_eps=0.05), **kw)
    out = calibrate.compare([tmp_path / "soft", tmp_path / "sharp"], log=lambda x: None)
    assert set(out) == {"soft", "sharp"} and "all worlds, z 2" in out["sharp"]["rules"]
    assert out["soft"]["rules"] != out["sharp"]["rules"]
    calibrate.record(tmp_path / "other", "vrpo1_actor_0504.pt", base, seed=4001, **kw)
    with pytest.raises(SystemExit):
        calibrate.compare([tmp_path / "soft", tmp_path / "other"], log=lambda x: None)


def test_reference_bank(tmp_path, table):
    """--bank keeps what another implementation needs to reproduce a decision: the state, the seed
    of its worlds, the mean gains and the specified rule's choice. From the state and the seed the
    engine draws the very worlds the recording used."""
    from tuppi_train import lockstep, tn
    from tuppi_ai import model as qmodel
    import tuppi_train
    s = lookahead.Settings(worlds=6, top=3, min_prob=0.02)
    calibrate.record(tmp_path / "bank", "vrpo1_actor_0504.pt", s, base=4, chunk=4, dev=torch.device("cpu"), lane_games=4096,
                     log=lambda x: None, bank=True)
    z = np.load(tmp_path / "bank" / "part_0000.npz")
    n = len(z["k"])
    states = np.ascontiguousarray(z["state"]).view(lookahead.STATE).reshape(-1)
    assert len(states) == n == len(z["seed"]) and z["mean_gain"].shape == (n, 3) and z["spec_choice"].max() <= 2
    assert (z["spec_choice"] < z["k"]).all() and not z["mean_gain"][:, 0].any()
    net = qmodel.load(tuppi_train.MODELS / "vrpo1_actor_0504.pt", "cpu")
    searcher = lookahead.Searcher(table, lockstep.TorchGreedy(net, "cpu", 2), 2, 1, 4096, True, 0, None)
    native.set_showing_fix(True)
    native.set_offer_model(None)
    worlds, bad, _ = searcher.sample(states, 6, z["seed"])
    cand = np.zeros((n, lookahead.MAX_K), np.int32)
    cand[:, :3] = z["cand"]
    play = states["phase"] == native.PH_PLAY          # no sooli can follow: the play-outs draw nothing
    q = searcher.play(worlds, 6, cand, z["k"], np.ones(n * 6, np.uint64))
    assert play.sum() > 50 and np.abs(q[play][:, :, :3] - z["q"][play]).max() < 1e-6
    gain = (q[:, :, :3] - q[:, :, :1]).mean(1)
    assert np.abs(gain[play] - z["mean_gain"][play]).max() < 1e-6
