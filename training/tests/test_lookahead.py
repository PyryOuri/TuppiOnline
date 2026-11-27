"""The look-ahead (tuppi_train/lookahead.py) against the engine's own search, and its plumbing."""

from __future__ import annotations

import ctypes as C
import json

import numpy as np
import pytest
import torch

from tuppi_train import labels, lockstep, lookahead, tn
from tuppi_ai import model as qmodel
from tuppi_ai import native

lib = tn.lib


def rng(seed: int) -> C.c_uint64:
    return C.c_uint64(seed)


def deal_of(state) -> "native.TcDeal":
    return native.TcDeal.from_buffer_copy(state.tobytes())


def same_states(a, b) -> bool:
    """Equal in every field. (Not a comparison of bytes: the record has padding, which a copy
    need not preserve.)"""
    a, b = np.asarray(a), np.asarray(b)
    return a.shape == b.shape and all(np.array_equal(a[name], b[name]) for name in lookahead.STATE.names)


def engine_worlds(env, state, w, seed) -> np.ndarray:
    ref = native.search_worlds(env, native.observe(deal_of(state), int(state["cur"])), w, rng(seed))
    return np.frombuffer(b"".join(bytes(r) for r in ref), lookahead.STATE)


@pytest.fixture(autouse=True)
def engine_settings():
    """The look-ahead's process-wide engine settings, restored for the other test files."""
    native.set_showing_fix(True)
    native.set_offer_model(None)
    yield
    native.set_showing_fix(False)
    native.set_offer_model(None)
    native.set_belief_keys(True)


@pytest.fixture(scope="module")
def recorded(table, net1):
    """States of greedy self-play with the live bots' sooli play, their masks, and the exact CPU network."""
    env = native.Env(256, 1, table, single_deal=True, encoder=2)
    env.set_sooli(0, False, True, 0.0)
    mlp = native.Mlp(net1)
    native.set_offer_model(None)
    data = labels.collect(env, lockstep.NativeGreedy(mlp), 256, rng(5), p_record=0.05, p_explore=0.0, seed=1)
    return mlp, data


def searcher(table, mlp, lanes=1, lane_games=4096, dd=0):
    return lookahead.Searcher(table, lockstep.NativeGreedy(mlp), 2, lanes, lane_games, heuristic_sooli=True, dd_left=dd)


def all_legal(mask):
    legal = lockstep.unpack_mask(mask)
    cand, k = np.zeros((len(mask), native.MAX_K), np.int32), legal.sum(1).astype(np.int32)
    for i in range(len(mask)):
        cand[i, :k[i]] = np.flatnonzero(legal[i])
    return cand, k


def test_observe_reports_forced_moves(make_env, mlp3):
    """`forced` is the only legal action where there is one, 255 elsewhere, at every step of a batch."""
    env, n = make_env(128), 128
    buf = lockstep.Buffers(env, 2)
    assert lib.tc_ls_begin(env._h, n, 3, C.byref(rng(3))) == 0
    feat, mask = np.zeros((n, buf.fb), np.uint8), np.zeros((n, buf.mb), np.uint8)
    forced, choose, seen = np.zeros(n, np.uint8), lockstep.NativeGreedy(mlp3), 0
    while True:
        k = buf.observe(n, feat, mask, forced=forced)
        if k == 0:
            break
        legal = lockstep.unpack_mask(mask[:k])
        one = legal.sum(1) == 1
        assert np.array_equal(forced[:k], np.where(one, legal.argmax(1), 255))
        seen += int(one.sum())
        buf.step(choose(feat[:k], mask[:k], buf.idx[:k], None)[0], k)
    assert seen > n


def test_worlds_are_the_engines(recorded, table, make_env):
    """Sampled worlds equal the worlds of the engine's search from the same stream, whatever the
    thread count; each keeps the actor's hand and the public record and deals every card once."""
    mlp, d = recorded
    states = np.ascontiguousarray(d["states"][::3][:120])
    seeds = labels.state_seeds(len(states), 3) | np.uint64(1)
    s, w = searcher(table, mlp), 5
    worlds, bad, u = s.sample(states, w, seeds)
    assert not bad.any() and len(worlds) == len(states) * w
    threads = tn.threads()
    try:
        tn.set_threads(1)
        again = s.sample(states, w, seeds)
    finally:
        tn.set_threads(threads)
    assert same_states(worlds, again[0]) and np.array_equal(u, again[2])
    env = make_env(8)
    phases = set()
    for i, st in enumerate(states):
        mine = worlds[i * w:(i + 1) * w]
        assert same_states(engine_worlds(env, st, w, int(seeds[i])), mine)
        me = int(st["cur"])
        phases.add(int(st["phase"]))
        for world in mine:
            assert world["hand"][me] == st["hand"][me] and world["n_played"] == st["n_played"]
            assert np.array_equal(world["play_card"], st["play_card"]) and world["phase"] == st["phase"]
            hands = [int(h) for h in world["hand"]]
            assert sum(bin(h).count("1") for h in hands) == 52 - int(st["n_played"])
            assert hands[0] & hands[1] == 0 and (hands[0] | hands[1]) & hands[2] == 0
            assert (hands[0] | hands[1] | hands[2]) & hands[3] == 0
    assert phases == {native.PH_SHOW, native.PH_PLAY}
    other = worlds.copy()
    other["hand"][3, 1] ^= 1
    assert not same_states(worlds, other)
    padded = worlds.copy()
    padded.view(np.uint8).reshape(len(worlds), -1)[:, 178:] = 7      # the padding bytes of the record
    assert same_states(worlds, padded) and padded.tobytes() != worlds.tobytes()
    assert 0.0 <= u.min() and u.max() < 1.0 and len(np.unique(u)) > len(u) // 2


@pytest.mark.parametrize("dd", [0, 6])
@pytest.mark.parametrize("lanes,lane_games", [(1, 4096), (3, 160)])
def test_values_equal_the_engines_search(recorded, table, make_env, dd, lanes, lane_games):
    """Every world's value of every legal action equals tc_search_world_values exactly: own play
    and solver tail, one lane and several small ones (so the chunking and the lanes are covered,
    and the forced rows that never reach the network)."""
    mlp, d = recorded
    sel = np.flatnonzero((d["states"]["phase"] == native.PH_PLAY) & (d["states"]["n_played"] >= 1))[::7][:40]
    states = np.ascontiguousarray(d["states"][sel])
    seeds = labels.state_seeds(len(states), 4) | np.uint64(1)
    s, w = searcher(table, mlp, lanes, lane_games, dd), 6
    worlds, bad, _ = s.sample(states, w, seeds)
    cand, k = all_legal(d["mask"][sel])
    q = s.play(worlds, w, cand, k, labels.state_seeds(len(states) * w, 9))
    env = make_env(1024)
    env.set_sooli(0, False, True, 0.0)
    for i, st in enumerate(states):
        ref = native.search_world_values(env, mlp, native.observe(deal_of(st), int(st["cur"])), cand[i, :k[i]], w, dd,
                                         rng(int(seeds[i])))
        assert np.array_equal(ref, q[i, :, :k[i]])
        assert not q[i, :, k[i]:].any()
    counts = s.counts()
    assert counts["games"] == w * int(k.sum()) and 0 < counts["net_rows"] < counts["rows"]
    assert np.abs(q).max() > 0


def test_play_does_not_depend_on_lanes_with_soolis(recorded, table):
    """From showing states (sooli offers, exchanges and sooli tricks lie ahead) the values are the
    same for one lane and for several small ones: every world has its own stream."""
    mlp, d = recorded
    sel = np.flatnonzero(d["states"]["phase"] == native.PH_SHOW)[:24]
    states = np.ascontiguousarray(d["states"][sel])
    w = 8
    cand, k = all_legal(d["mask"][sel])
    k = np.minimum(k, 4)
    out = []
    for lanes, lane_games in ((1, 4096), (3, 96)):
        s = searcher(table, mlp, lanes, lane_games)
        worlds, _, _ = s.sample(states, w, labels.state_seeds(len(states), 4))
        out.append(s.play(worlds, w, cand, k, labels.state_seeds(len(states) * w, 9)))
    assert np.array_equal(out[0], out[1]) and np.abs(out[0]).max() > 0
    with pytest.raises(ValueError):
        searcher(table, mlp, 1, 16).play(worlds, w, cand, k, labels.state_seeds(len(states) * w, 9))


@pytest.mark.parametrize("keys", [True, False])
def test_belief_worlds_are_the_engines(recorded, table, make_env, keys):
    """With play inference the resampled worlds equal those of the engine's search (both of its
    scoring paths), and the resampling does concentrate on fewer candidates."""
    mlp, d = recorded
    sel = np.flatnonzero(d["states"]["phase"] == native.PH_PLAY)[::5][:60]
    states = np.ascontiguousarray(d["states"][sel])
    seeds = labels.state_seeds(len(states), 3) | np.uint64(1)
    w, mult = 8, 4

    def logits(feat, mask):
        x = np.unpackbits(feat, axis=1)[:, :native.feature_dim(2)]
        return torch.from_numpy(mlp.forward(x)).masked_fill(~torch.from_numpy(lockstep.unpack_mask(mask)), -1e9)

    native.set_belief_keys(keys)
    env = make_env(64)
    native.set_belief(env, mlp, mult, 2.0, 0.5, True)
    worlds, bad, pick = searcher(table, mlp).belief(states, w, mult, seeds, logits, 2.0, 0.5)
    assert not bad.any()
    for i, st in enumerate(states):
        assert same_states(engine_worlds(env, st, w, int(seeds[i])), worlds[i * w:(i + 1) * w])
    assert np.mean([len(set(p)) for p in pick]) < 0.9 * w
    assert (np.diff(pick, axis=1) >= 0).all()


def test_decide_is_its_definition():
    q = np.zeros((5, 4, 4))
    q[0, :, 1] = [0.02, 0.03, 0.02, 0.03]          # clearly better: chosen
    q[1, :, 1] = [0.002, 0.002, 0.002, 0.002]      # better, but below keep
    q[2, :, 1] = [0.2, -0.15, 0.1, -0.1]           # mean above keep, not above 2 standard errors
    q[3, :, 1] = [0.02, 0.03, 0.02, 0.03]
    q[3, :, 2] = [0.05, 0.06, 0.05, 0.06]          # two pass: the larger gain
    q[4, :, 3] = [0.5, 0.5, 0.5, 0.5]              # beyond its candidate count: ignored
    k = np.array([2, 2, 2, 3, 3], np.int32)
    choice, gain = lookahead.decide(q, k, np.full(5, 0.003), 2.0)
    assert choice.tolist() == [1, 0, 0, 2, 0]
    assert gain == pytest.approx([0.025, 0, 0, 0.055, 0])
    assert lookahead.decide(q, k, np.full(5, 0.03), 2.0)[0].tolist() == [0, 0, 0, 2, 0]
    assert lookahead.decide(q, k, np.full(5, 0.003), 0.0)[0].tolist() == [1, 0, 1, 2, 0]
    # fewer independent worlds: larger standard errors (row 0: gain 0.025, sd 0.0058)
    assert lookahead.decide(q, k, np.full(5, 0.003), 2.0, np.full(5, 0.2))[0].tolist() == [0, 0, 0, 2, 0]
    assert lookahead.effective_worlds(np.array([[0, 1, 2, 3], [0, 0, 1, 1], [5, 5, 5, 5]])).tolist() == [4.0, 2.0, 1.0]


def match(table, net, settings, base=4, lanes=2, lane_games=4096, seed=3, rollout=None, opponent=None):
    env = native.Env(8 * base, 1, table, single_deal=True, encoder=2)
    env.set_sooli(0, False, True, 0.0)
    look = lookahead.build(net, torch.device("cpu"), settings, env, table, rollout_net=rollout, lanes=lanes,
                           lane_games=lane_games, seed=seed)
    plain = lockstep.TorchGreedy(opponent if opponent is not None else net, "cpu", 2)
    return lockstep.duplicate_eval(env, look, plain, base, 3, rng(11), 2), look


def test_chooser(table, net1):
    """With an unreachable margin the look-ahead pair plays the network's own moves: exactly 0
    against it. With the real margin the result is reproducible, does not depend on the lanes, and
    the counters add up. Candidates start with the network's move and respect the limits."""
    settings = lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=1.0)
    never, look = match(table, net1, lookahead.Settings(worlds=4, top=3, min_prob=0.02, keep=1e9, keep_show=1e9))
    assert not never.any() and look.stats["searched"] > 0 and look.stats["switched"] == 0
    a, look_a = match(table, net1, settings)
    b, _ = match(table, net1, settings)
    c, _ = match(table, net1, settings, lanes=3, lane_games=600)
    assert np.array_equal(a, b) and np.array_equal(a, c)
    st = look_a.stats
    assert st["switched"] > 0 and a.any() and st["no_world"] == 0
    assert st["forced"] < st["decisions"] and st["searched"] < st["decisions"] - st["forced"]
    assert 2 * st["searched"] <= st["candidates"] <= 3 * st["searched"]
    assert look_a.searcher.counts()["games"] == 4 * st["candidates"]
    other, _ = match(table, net1, settings, seed=4)
    assert not np.array_equal(a, other)
    no_show, look_n = match(table, net1, lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=1.0, show=False))
    assert look_n.stats["searched"] < st["searched"]

    d = lockstep.rollouts(native.Env(64, 1, table, single_deal=True, encoder=2), lockstep.TorchGreedy(net1, "cpu", 2),
                          64, 3, rng(2))
    anchor, cand, k, legal = look_a.candidates(d["feat"], d["mask"])
    assert np.array_equal(anchor, d["action"]) and np.array_equal(cand[:, 0], anchor)
    mask = lockstep.unpack_mask(d["mask"])
    assert np.array_equal(legal, mask.sum(1)) and (k >= 1).all() and (k <= np.minimum(3, legal)).all()
    for i in np.flatnonzero(k > 1)[:200]:
        assert mask[i, cand[i, :k[i]]].all() and len(set(cand[i, :k[i]])) == k[i]
    assert (k[legal == 1] == 1).all() and (k > 1).any()


def test_belief_chooser_runs_and_differs(table, net1):
    plain, _ = match(table, net1, lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=1.0))
    belief, look = match(table, net1, lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=1.0, belief=3))
    again, _ = match(table, net1, lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=1.0, belief=3), lanes=1)
    assert np.array_equal(belief, again) and not np.array_equal(belief, plain)
    assert look.searcher.seconds["belief"] > 0


def test_lookahead_repairs_a_bad_anchor(table, net1):
    """An untrained network as the anchor and VRPO1 as the play-out policy: the look-ahead pair
    beats the untrained network clearly (a fixed seed; the margin is many standard errors)."""
    torch.manual_seed(0)
    bad = qmodel.QNet(**net1.config).eval()
    settings = lookahead.Settings(worlds=4, top=4, min_prob=0.0, z=1.0)
    values, look = match(table, bad, settings, base=8, rollout=net1, lane_games=16384)
    mean, half = lockstep.interval(values)
    assert mean - 2 * half > 0.01, (mean, half)
    assert look.stats["switched"] > 0.1 * look.stats["searched"]


def test_measure_resumes(tmp_path, table):
    """A run stopped after one chunk and continued gives the chunks of an uninterrupted run, and
    refuses to continue with other settings."""
    settings = lookahead.Settings(worlds=2, top=2, min_prob=0.05, z=1.0)
    kw = dict(chunk=4, seed=5, dev=torch.device("cpu"), lanes=2, lane_games=2048, log=lambda s: None)
    whole = lookahead.measure(tmp_path / "a", "vrpo1_actor_0504.pt", settings, base=8, **kw)
    lookahead.measure(tmp_path / "b", "vrpo1_actor_0504.pt", settings, base=4, **kw)
    resumed = lookahead.measure(tmp_path / "b", "vrpo1_actor_0504.pt", settings, base=8, **kw)
    rows = [[json.loads(line)["values"] for line in (tmp_path / x / "chunks.jsonl").read_text().splitlines()] for x in "ab"]
    assert rows[0] == rows[1] and len(rows[0]) == 2
    assert whole["mean"] == resumed["mean"] and whole["base_deals"] == 8 and whole["searched"] == resumed["searched"]
    assert "VERDICT" in lookahead.verdict(whole) and "A minus B" in lookahead.brief(whole)
    with pytest.raises(SystemExit):
        lookahead.measure(tmp_path / "b", "vrpo1_actor_0504.pt", lookahead.Settings(worlds=3), base=8, **kw)


def test_focused_labels(table, net1, make_env):
    """Focused labels (focus.py) are `labels.branch_labels` restricted to the candidates: the same
    value for the same state, action and seed. Only decisions with at least two candidates are
    labelled, the network's own move is the first, and the rows do not depend on the lanes."""
    from tuppi_train import focus

    def run(lanes, lane_games):
        env = make_env(96)
        anchor = lockstep.TorchGreedy(net1, "cpu", 2)
        s = lookahead.Searcher(table, lockstep.TorchGreedy(net1, "cpu", 2), 2, lanes, lane_games, heuristic_sooli=False)
        timing = {}
        return focus.collect(env, anchor, s, 96, rng(4), top=3, min_prob=0.02, p_explore=0.05, seed=6, timing=timing), timing

    d, timing = run(1, 4096)
    again, _ = run(3, 300)
    for key in d:
        assert np.array_equal(d[key], again[key]), key
    n = len(d["feat"])
    assert n == timing["labelled"] and 0 < n < timing["unforced"] < timing["decisions"] and timing["dropped"] == 0
    k = (d["ids"] != focus.PAD).sum(1)
    assert k.min() >= 2 and k.max() <= 3 and d["explored"].any() and not d["explored"].all()
    assert not d["q"][d["ids"] == focus.PAD].any() and np.abs(d["q"]).max() > 0
    # the first candidate is the network's greedy move on that row
    choice = lockstep.TorchGreedy(net1, "cpu", 2)
    mask = np.zeros((n, tn.MASK_BYTES), np.uint8)
    for j in range(3):
        rows = np.flatnonzero(d["ids"][:, j] != focus.PAD)
        np.bitwise_or.at(mask, (rows, d["ids"][rows, j] >> 3), (0x80 >> (d["ids"][rows, j] & 7)).astype(np.uint8))
    restricted = choice(d["feat"], mask, None, None)[0]
    assert np.array_equal(restricted, d["ids"][:, 0])


def test_focused_values_equal_branch_labels(recorded, table, make_env):
    """One play-out per candidate from the true state is the label of labels.branch_labels for that
    action, with the same seed (sooli tricks by the solver in both)."""
    mlp, d = recorded
    states = np.ascontiguousarray(d["states"][::4][:80])
    seeds = labels.state_seeds(len(states), 9)
    choose = lockstep.NativeGreedy(mlp)
    native.set_branch_share(False)
    ids, q = labels.branch_labels(make_env(4096), states, choose, seeds)
    s = lookahead.Searcher(table, choose, 2, 2, 600, heuristic_sooli=False)
    cand, k = all_legal(d["mask"][::4][:80])
    mine = s.play(states, 1, cand, k, seeds)[:, 0, :]
    for i in range(len(states)):
        assert np.array_equal(ids[i, :k[i]], cand[i, :k[i]])
        assert np.array_equal(q[i, :k[i]], mine[i, :k[i]].astype(np.float16))


def test_measure_sides(tmp_path):
    """Either side can look ahead or be plain: the same pair on both sides gives the mirrored
    result when the sides are swapped (same deals, draws tied to the side's position aside), and a
    look-ahead with an unreachable margin on both sides is exactly 0."""
    never = lookahead.Settings(worlds=2, top=2, min_prob=0.05, keep=1e9, keep_show=1e9)
    kw = dict(base=4, chunk=4, seed=5, dev=torch.device("cpu"), lanes=1, lane_games=2048, log=lambda s: None)
    both = lookahead.measure(tmp_path / "both", "vrpo1_actor_0504.pt", never, opponent_rollout_name="vrpo1_actor_0504.pt", **kw)
    assert both["mean"] == 0.0 and both["changed_base_deals"] == 0.0 and both["searched"] > 0
    settings = lookahead.Settings(worlds=2, top=2, min_prob=0.05, z=0.5)
    a = lookahead.measure(tmp_path / "a", "vrpo1_actor_0504.pt", settings, **kw)
    b = lookahead.measure(tmp_path / "b", "vrpo1_actor_0504.pt", settings, plain=True,
                          opponent_rollout_name="vrpo1_actor_0504.pt", **kw)
    assert a["changed_base_deals"] > 0 and b["changed_base_deals"] > 0 and b["searched"] > 0
    assert json.loads((tmp_path / "b" / "config.json").read_text())["rollout"] == ""
    with pytest.raises(SystemExit):
        lookahead.measure(tmp_path / "c", "vrpo1_actor_0504.pt", settings, plain=True, **kw)


def test_likelihood_network_timing_and_old_runs(tmp_path):
    """A separate likelihood network that is the play-out network gives the same match as the
    default; another one changes it. The log's seconds are the whole match, search_seconds the
    look-ahead's share on every searching side. A run directory written before an option existed
    continues."""
    s = lookahead.Settings(worlds=4, top=2, min_prob=0.05, z=0.5, belief=3, dd_left=6)
    kw = dict(base=4, chunk=4, seed=5, dev=torch.device("cpu"), lanes=1, lane_games=2048, log=lambda s: None,
              rollout_name="vrpo1_actor_0504.pt")
    rows = {}
    for name, extra in (("default", {}), ("same", {"likelihood_name": "vrpo1_actor_0504.pt"}),
                        ("other", {"likelihood_name": "vrpo3_final.pt"}),
                        ("both", {"opponent_rollout_name": "vrpo1_actor_0504.pt", "opponent_likelihood_name": "vrpo3_final.pt"})):
        lookahead.measure(tmp_path / name, "vrpo3_final.pt", s, **kw, **extra)
        rows[name] = json.loads((tmp_path / name / "chunks.jsonl").read_text().splitlines()[0])
    assert rows["default"]["values"] == rows["same"]["values"] != rows["other"]["values"]
    for name, row in rows.items():
        assert 0 < row["search_seconds"] <= row["seconds"] and row["parts"]["belief"] > 0 and row["threads"] == tn.threads()
    assert rows["both"]["games"] > 1.5 * rows["default"]["games"]
    cfg = tmp_path / "default" / "config.json"
    old = {k: v for k, v in json.loads(cfg.read_text()).items() if k not in ("likelihood", "opponent_likelihood", "opponent_rollout")}
    cfg.write_text(json.dumps(old))
    again = lookahead.measure(tmp_path / "default", "vrpo3_final.pt", s, **{**kw, "base": 8})
    assert again["base_deals"] == 8
    with pytest.raises(SystemExit):
        lookahead.measure(tmp_path / "default", "vrpo3_final.pt", s, **kw, likelihood_name="vrpo3_final.pt")


def test_use_cpus_tells_torch_too():
    before = tn.threads()
    try:
        assert tn.use_cpus(2) == 2 and tn.threads() == 2 and torch.get_num_threads() == 2
        assert tn.use_cpus(0) == tn.threads() == torch.get_num_threads() >= 1
    finally:
        tn.use_cpus(before)


def test_scores_per_base_deal(table, net1, make_env):
    """`uniform_scores` is the release evaluator's mix; a score per base deal reaches every game of
    that deal and changes nothing else; a constant array equals the constant score; a policy
    against itself still scores exactly 0."""
    scores = lockstep.uniform_scores(20000, 3)
    assert scores.dtype == np.uint8 and np.array_equal(scores, lockstep.uniform_scores(20000, 3))
    assert not np.array_equal(scores[:100], lockstep.uniform_scores(100, 4))
    lead = scores.max(1)
    assert (scores.min(1) == 0).all() and set(lead.tolist()) == set(range(0, 52, 4))
    assert abs((lead == 0).mean() - 1 / 13) < 0.01 and abs((scores[lead > 0, 0] > 0).mean() - 0.5) < 0.02
    counts = np.bincount(lead // 4, minlength=13)
    assert counts.min() > 0.9 * 20000 / 13 and counts.max() < 1.1 * 20000 / 13

    base, env = 6, make_env(48)
    per_deal = lockstep.uniform_scores(base, 11)
    per_deal[0] = (0, 0)
    per_deal[1] = (36, 0)
    per_deal[2] = (0, 12)
    a_team, a_team2 = np.zeros(48, np.int8), np.zeros(48, np.int8)
    state, state2 = np.zeros(48, lookahead.STATE), np.zeros(48, lookahead.STATE)
    games = np.arange(48, dtype=np.int32)
    assert lib.tc_ls_begin_duplicate_scores(env._h, base, 3, per_deal.ctypes.data, 1, C.byref(rng(5)), a_team.ctypes.data) == 0
    lib.tc_ls_copy_states(env._h, games.ctypes.data, 48, state.ctypes.data)
    assert lib.tc_ls_begin_duplicate(env._h, base, 3, 0, 0, 1, C.byref(rng(5)), a_team2.ctypes.data) == 0
    lib.tc_ls_copy_states(env._h, games.ctypes.data, 48, state2.ctypes.data)
    assert np.array_equal(state["score"], np.repeat(per_deal, 8, axis=0)) and np.array_equal(a_team, a_team2)
    for name in lookahead.STATE.names:
        if name != "score":
            assert np.array_equal(state[name], state2[name]), name

    a = lockstep.TorchGreedy(net1, "cpu", 2)
    b = lockstep.RandomLegal(3)
    const = lockstep.duplicate_eval(make_env(48), a, lockstep.RandomLegal(3), base, 3, rng(7), 2, score=(24, 0))
    array = lockstep.duplicate_eval(make_env(48), a, b, base, 3, rng(7), 2, score=np.tile(np.uint8([24, 0]), (base, 1)))
    assert np.array_equal(const, array)
    assert not lockstep.duplicate_eval(make_env(48), a, a, base, 3, rng(7), 2, score=per_deal).any()
    with pytest.raises(ValueError):
        lockstep.duplicate_eval(make_env(48), a, a, base, 3, rng(7), 2, score=per_deal[:3])


def test_uniform_scores_in_the_matches_and_phase_counters(tmp_path):
    """--scores uniform plays other games than 0-0, resumes, and is refused in a 0-0 run's folder;
    the phase counters add up to the totals; the plain evaluator has the same option."""
    from tuppi_train import evaluate
    s = lookahead.Settings(worlds=4, top=3, min_prob=0.02, z=0.5)
    kw = dict(chunk=4, seed=5, dev=torch.device("cpu"), lanes=1, lane_games=4096, log=lambda s: None)
    zero = lookahead.measure(tmp_path / "zero", "vrpo1_actor_0504.pt", s, base=8, **kw)
    lookahead.measure(tmp_path / "uni", "vrpo1_actor_0504.pt", s, base=4, scores="uniform", **kw)
    uni = lookahead.measure(tmp_path / "uni", "vrpo1_actor_0504.pt", s, base=8, scores="uniform", **kw)
    whole = lookahead.measure(tmp_path / "uni2", "vrpo1_actor_0504.pt", s, base=8, scores="uniform", **kw)
    assert uni["base_deals"] == 8 and uni["mean"] == whole["mean"] != zero["mean"]
    assert json.loads((tmp_path / "uni" / "config.json").read_text())["scores"] == "uniform"
    with pytest.raises(SystemExit):
        lookahead.measure(tmp_path / "zero", "vrpo1_actor_0504.pt", s, base=8, scores="uniform", **kw)
    for r in (zero, uni):
        assert r["phases"] == list(lookahead.PHASES)
        assert sum(r["phase_searched"]) == r["searched"] and sum(r["phase_switched"]) == r["switched"]
        assert sum(r["phase_claimed"]) == pytest.approx(r["claimed_gain"]) and min(r["phase_searched"]) > 0
    net1, net3 = (lockstep_net(n) for n in ("vrpo1_actor_0504.pt", "vrpo3_final.pt"))
    v0 = evaluate.compare(net3, net1, torch.device("cpu"), 16, 3, chunk=8, sooli_play_heuristic=True)
    v1 = evaluate.compare(net3, net1, torch.device("cpu"), 16, 3, chunk=8, sooli_play_heuristic=True, scores="uniform")
    assert v0.shape == v1.shape == (16,) and not np.array_equal(v0, v1)
    assert not evaluate.compare(net1, net1, torch.device("cpu"), 8, 3, scores="uniform").any()


def lockstep_net(name):
    from tuppi_train import symmetry
    return symmetry.load_net(name, "cpu")


def test_calibrate(tmp_path):
    """The recording keeps the plain network's deals, resumes, and its report scores rules by the
    real values: a rule that never changes a move scores exactly 0, and the pieces are consistent."""
    from tuppi_train import calibrate
    s = lookahead.Settings(worlds=6, top=3, min_prob=0.02, dd_left=6)
    kw = dict(chunk=4, dev=torch.device("cpu"), lane_games=4096, rollout_name="vrpo1_actor_0504.pt", log=lambda s: None)
    calibrate.record(tmp_path / "r", "vrpo3_final.pt", s, base=4, **kw)
    first = (tmp_path / "r" / "part_0000.npz").read_bytes()
    calibrate.record(tmp_path / "r", "vrpo3_final.pt", s, base=8, **kw)
    assert (tmp_path / "r" / "part_0000.npz").read_bytes() == first and (tmp_path / "r" / "part_0001.npz").exists()
    with pytest.raises(SystemExit):
        calibrate.record(tmp_path / "r", "vrpo3_final.pt", lookahead.Settings(worlds=7), base=8, **kw)
    d = calibrate.load(tmp_path / "r")
    x = calibrate.quantities(d)
    n = len(d["k"])
    assert d["q"].shape == (n, 6, 3) and d["real"].shape == (n, 3) and (d["k"] >= 2).all() and d["games"].tolist() == [32, 32]
    assert not x["r"][:, 0].any() and not x["m"][:, 0].any() and np.abs(x["r"]).max() > 0
    assert not d["real"][~x["valid"]].any()
    keep = calibrate.rule_value(d, x, np.zeros(n, np.int64))
    assert keep["real"] == 0.0 and keep["claimed"] == 0.0 and keep["changed"] == 0.0
    best = calibrate.choose(x["m"], x["m"] > 0, x["valid"])
    assert ((best == 0) | (x["m"][np.arange(n), best] > 0)).all() and (best < d["k"]).all()
    assert calibrate.rule_value(d, x, best)["claimed"] > 0
    result = calibrate.report(tmp_path / "r", log=lambda s: None)
    assert result["decisions"] == n and "z 2 (current)" in result["rules"]
    assert calibrate.quantities(d, 4)["worlds"] == 4
