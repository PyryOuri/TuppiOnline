"""Dan's decision boundaries, transactional state, real rollouts and native entry parity."""
import copy
import ctypes as C
import json
from pathlib import Path

import numpy as np
import pytest

from tuppi_ai import native
from tuppi_ai.bridge import action_id, obs_from_player_observation
from tuppi_ai.dan import BOT_NAME, DanAgent, DanConfig, NativeConfig, NativeContext, NativeResult, NativeBidResult, native_config
from tuppi_ai.dan_preview import fixed_roots, root
from tuppi_ai.lite import LiteAgent, shared_equity
from tuppi_engine import apply_match_action, match_observation_for

native.set_parallel(False)

def select(ids, values, baseline=0, allowance=.002, remaining=.004, z=2):
    ids = np.ascontiguousarray(ids, dtype=np.int32)
    rows = np.ascontiguousarray(values, dtype=np.float64)
    out = NativeResult()
    rc = native.lib.tc_dan_select(ids.ctypes.data, len(ids), baseline, rows.ctypes.data, len(rows),
                                  allowance, remaining, z, 1e-12, C.byref(out))
    return rc, out


@pytest.mark.parametrize("trick", range(1, 5))
@pytest.mark.parametrize("position", range(1, 5))
def test_context_is_relative_to_the_current_trick(trick, position):
    obs = native.TcObs()
    obs.ruleset, obs.phase, obs.contract, obs.trick_size, obs.soolaaja = 3, 1, 0, 4, -1
    obs.n_played = (trick-1)*4 + position-1
    cfg = native_config(DanConfig())
    expected = .03 if trick <= 3 and position == 1 else .02 if trick <= 2 and position == 2 else 0
    for seat in range(4):
        obs.seat = seat
        assert native.lib.tc_dan_allowance(C.byref(obs), C.byref(cfg)) == expected


@pytest.mark.parametrize("field,value", [("contract", 1), ("phase", 0), ("phase", 6), ("trick_size", 3),
                                         ("soolaaja", 2), ("ruleset", 1)])
def test_non_nolo_and_nonordinary_play_are_excluded(field, value):
    obs = native.TcObs()
    obs.ruleset, obs.phase, obs.contract, obs.trick_size, obs.soolaaja = 3, 1, 0, 4, -1
    setattr(obs, field, value)
    cfg = native_config(DanConfig())
    assert native.lib.tc_dan_allowance(C.byref(obs), C.byref(cfg)) == 0


def test_small_relative_loss_can_be_accepted_even_when_all_values_are_negative():
    rc, r = select([0, 11, 12], [[-.040, -.041, -.043]]*64)
    assert rc == 0 and r.action == 11 and r.reason == 6
    assert r.charge == pytest.approx(.001) and r.after == pytest.approx(.003)
    rc, r = select([0, 11], [[.010, -.020]]*64)
    assert rc == 0 and r.action == 0 and r.reason == 5 and r.after == .004


def test_second_position_has_a_smaller_allowance_and_budget_can_block_a_small_sacrifice():
    matrix = [[0, -.0015]]*64
    assert select([0, 11], matrix)[1].action == 11
    assert select([0, 11], matrix, allowance=.001)[1].action == 0
    assert select([0, 11], matrix, remaining=.001)[1].action == 0


def test_all_cards_are_considered_not_only_base_and_first_high_card():
    r = select([0, 11, 12, 1], [[0, -.02, -.001, 0]]*64)[1]
    assert r.action == 12
    # Both high cards look close to the base, but another ordinary card is much better.
    r = select([0, 11, 12, 1], [[0, -.001, -.001, .02]]*64)[1]
    assert r.action == 0 and r.best == 1


def test_uncertainty_uses_paired_differences_and_rejects_an_unclear_loss():
    spread = np.linspace(-.08, .08, 64)
    r = select([0, 11], np.column_stack((spread, spread-.001)))[1]
    assert r.action == 11 and r.se_base[1] < 1e-15
    r = select([0, 11], [[0, -.05], [0, .05]]*32)[1]
    assert r.action == 0 and r.se_base[1] > .005


def test_high_card_ties_use_action_id_and_improvements_never_replenish_budget():
    r = select([12, 0, 11], [[.02, 0, .02]]*64)[1]
    assert r.action == 11 and r.charge == 0 and r.after == .004


@pytest.mark.parametrize("ids,rows,baseline", [([0, 0], [[0, 0]]*2, 0), ([0, 11], [[0, float("nan")]]*2, 0),
    ([0, 11], [[0, float("inf")]]*2, 0), ([0, 11], [[0, 2]]*2, 0), ([0, 11], [[0, 0]]*2, 1)])
def test_invalid_value_inputs_fail_closed(ids, rows, baseline):
    rc, r = select(ids, rows, baseline)
    assert rc != 0 and r.action == baseline and r.charge == 0


@pytest.fixture(scope="module")
def eligible():
    return fixed_roots(2)


def test_pending_replay_abort_commit_and_reload_do_not_double_spend(eligible):
    _, _, state = eligible[0]
    obs = match_observation_for(state, state.current_actor)
    agent = DanAgent(state.current_actor)
    before = agent.checkpoint()["state"]
    decision = agent.propose_action(obs)
    assert agent.checkpoint()["state"] == before
    assert agent.propose_action(obs) == decision
    saved = agent.checkpoint()
    restored = DanAgent.from_checkpoint(json.loads(json.dumps(saved)))
    assert restored.propose_action(obs) == decision
    agent.abort_action()
    assert agent.propose_action(obs) == decision
    next_state = apply_match_action(state, decision.action)
    agent.commit_action(decision)
    once = agent.checkpoint()
    agent.commit_action(decision)
    assert agent.checkpoint() == once
    resumed = DanAgent.from_checkpoint(json.loads(json.dumps(once)))
    assert resumed.choose_action(obs) == decision.action
    assert resumed.checkpoint() == once
    restored.commit_action(decision)
    assert restored.checkpoint() == once
    assert next_state is not None
    for a in (agent, restored, resumed): a.close()


def test_an_actual_native_override_debits_only_after_acceptance(eligible):
    # A deliberately permissive test profile exercises the positive path. The
    # Default allowances are not changed by this positive-path test.
    _, _, state = eligible[0]
    obs = match_observation_for(state, state.current_actor)
    dan = DanAgent(state.current_actor, DanConfig(lead_loss=1, second_loss=.5, deal_loss=1))
    d = dan.propose_action(obs)
    assert d.diagnostics["reason"] == "accepted" and action_id(d.action) % 13 >= 11
    assert d.diagnostics["charge"] > 0
    assert dan.checkpoint()["state"]["remaining"] == 1
    apply_match_action(state, d.action)
    dan.commit_action(d)
    assert dan.checkpoint()["state"]["remaining"] == pytest.approx(1-d.diagnostics["charge"])
    after = dan.checkpoint()
    dan.commit_action(d)
    assert dan.checkpoint() == after
    dan.close()


def test_stale_proposal_is_rejected_and_each_new_deal_resets_once(eligible):
    seed, plays, first = eligible[0]
    obs = match_observation_for(first, first.current_actor)
    agent = DanAgent(first.current_actor)
    one = agent.propose_action(obs)
    # An explicitly different authoritative deal reference creates a different proposal.
    other_state = root(seed+4, plays)
    other = match_observation_for(other_state, other_state.current_actor)
    two = agent.propose_action(other)
    with pytest.raises(ValueError): agent.commit_action(one)
    agent.commit_action(two)
    saved = agent.checkpoint()
    saved["state"]["remaining"] = 0
    saved["receipt"] = None
    restored = DanAgent.from_checkpoint(saved)
    reset = restored.propose_action(obs)
    assert reset.diagnostics["before"] == DanConfig().deal_loss
    restored.commit_action(reset)
    post = restored.checkpoint()
    restored.propose_action(obs)
    assert restored.checkpoint()["state"] == post["state"]
    agent.close(); restored.close()


@pytest.mark.parametrize("field,value", [("runtime", "wrong"), ("profile", "wrong")])
def test_identity_mismatch_is_refused(field, value):
    record = DanAgent(0).checkpoint()
    record[field] = value
    with pytest.raises(ValueError): DanAgent.from_checkpoint(record)


def test_outside_context_preserves_base_choice_and_all_cursors():
    agents = {s: DanAgent(s) for s in range(4)}
    for plays in (2, 3, 9, 12):
        state = root(1, plays)
        obs = match_observation_for(state, state.current_actor)
        dan = agents[state.current_actor]
        normal = LiteAgent(state.current_actor)
        before = dan.checkpoint()["state"]["eval_rng"]
        d = dan.propose_action(obs)
        assert d.action == normal.choose_action(obs) and d.diagnostics["reason"] == "outside"
        dan.commit_action(d)
        assert dan.checkpoint()["state"]["eval_rng"] == before
    for a in agents.values(): a.close()


def test_follow_suit_candidates_are_the_engine_legal_set(eligible):
    state = root(2, 1)
    obs = match_observation_for(state, state.current_actor)
    dan = DanAgent(state.current_actor)
    d = dan.propose_action(obs)
    legal = {action_id(a) for a in obs.legal_actions}
    assert action_id(d.action) in legal
    assert all(x["action"] in legal for x in d.diagnostics["cards"])
    dan.close()


def test_native_browser_entry_matches_python_transaction(eligible):
    from tuppi_ai.lite import ROOT
    lib = native.lib
    lib.tb_dispose()
    lib.tb_load_model.argtypes = [C.c_int]*6 + [C.c_void_p]
    lib.tb_configure.argtypes = [C.c_int, C.c_void_p]
    lib.tb_dan_choose_observation.argtypes = [C.POINTER(native.TcObs), C.c_void_p, C.c_int,
        C.POINTER(NativeConfig), C.POINTER(C.c_uint64), C.POINTER(NativeContext), C.POINTER(NativeResult)]
    manifest = json.loads((ROOT / "models/compact/models.json").read_text())
    for record in manifest["models"]:
        if record["role"] not in (0, 1, 2): continue
        data = np.fromfile(ROOT / "models/compact" / record["file"], dtype=np.float32)
        cfg = record["config"]
        assert lib.tb_load_model(record["role"], record["in_dim"], cfg["width"], cfg["blocks"], cfg["encoder"],
                                  len(data), data.ctypes.data) == 0
    eq = np.ascontiguousarray(shared_equity())
    assert lib.tb_configure(128, eq.ctypes.data) == 0
    from tuppi_ai.dan11_bidding import observations
    for _, _, observation in observations(4):
        dan = DanAgent(observation.observing_seat)
        decision = dan.propose_action(observation)
        raw = obs_from_player_observation(observation)
        ids = np.ascontiguousarray([action_id(a) for a in observation.legal_actions], dtype=np.int32)
        saved = dan.checkpoint()["state"]
        cfg, result = native_config(DanConfig()), NativeResult()
        context = NativeContext(saved["eval_rng"], DanConfig().deal_loss)
        brng = C.c_uint64(saved["base_rng"])
        chosen = lib.tb_dan_choose_observation(C.byref(raw), ids.ctypes.data, len(ids), C.byref(cfg),
            C.byref(brng), C.byref(context), C.byref(result))
        assert chosen == action_id(decision.action)
        assert context.rng == saved["eval_rng"] and brng.value == saved["base_rng"]
        assert context.remaining == DanConfig().deal_loss
        dan.close()
    for _, _, state in eligible:
        obs = match_observation_for(state, state.current_actor)
        dan = DanAgent(state.current_actor)
        d = dan.propose_action(obs)
        before = dan.checkpoint()["state"]
        context = NativeContext(before["eval_rng"], DanConfig().deal_loss)
        base_rng = C.c_uint64(before["base_rng"])
        cfg, result = native_config(DanConfig()), NativeResult()
        raw = obs_from_player_observation(obs)
        ids = np.ascontiguousarray([action_id(a) for a in obs.legal_actions], dtype=np.int32)
        chosen = lib.tb_dan_choose_observation(C.byref(raw), ids.ctypes.data, len(ids), C.byref(cfg),
            C.byref(base_rng), C.byref(context), C.byref(result))
        assert chosen == action_id(d.action)
        assert result.charge == d.diagnostics["charge"]
        assert context.rng == dan.checkpoint()["pending"]["next"]["eval_rng"]
        assert context.remaining == dan.checkpoint()["pending"]["next"]["remaining"]
        dan.close()
    # Reconfiguration must replace the equity table in already-created Dan
    # environments too, not leave a stale table from the previous game.
    altered = np.full((25, 2), .5, dtype=np.float64)
    assert lib.tb_configure(128, altered.ctypes.data) == 0
    _, _, state = eligible[0]
    observation = match_observation_for(state, state.current_actor)
    raw = obs_from_player_observation(observation)
    ids = np.ascontiguousarray([action_id(a) for a in observation.legal_actions], dtype=np.int32)
    dan = DanAgent(state.current_actor)
    base = action_id(dan._base.choose_action(observation))
    env = native.Env(64*13, 0, equity=altered, single_deal=True, encoder=dan._base.mlp.encoder)
    cfg = native_config(DanConfig())
    left, right = NativeContext(999, DanConfig().deal_loss), NativeContext(999, DanConfig().deal_loss)
    expected, actual = NativeResult(), NativeResult()
    assert lib.tc_dan_choose(env._h, dan._base.mlp._h, C.byref(raw), ids.ctypes.data, len(ids), base,
        C.byref(cfg), C.byref(left), C.byref(expected)) == 0
    brng = C.c_uint64(dan.checkpoint()["state"]["base_rng"])
    assert lib.tb_dan_choose_observation(C.byref(raw), ids.ctypes.data, len(ids), C.byref(cfg),
        C.byref(brng), C.byref(right), C.byref(actual)) == expected.action
    assert list(actual.means) == list(expected.means)
    native.lib.tc_env_free(env._h); env._h = None
    dan.close()
    lib.tb_dispose()


def test_terminal_preview_starts_and_accepts_quit():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, "tools/play_dan.py", "--deals", "1"], input="q\n",
        capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], timeout=15)
    assert result.returncode == 0, result.stderr
    assert "You are seat 0" in result.stdout and "Your action" in result.stdout
    assert BOT_NAME in result.stdout


@pytest.mark.parametrize("nolo,rami,expected", [(0, .25, 52), (0, .5, 104), (0, 1, 104), (.5, 0, 52), (0, 0, 52)])
def test_bidding_margin_only_vetoes_borderline_nelli_rami(nolo, rami, expected):
    ids = np.array([52, 104], dtype=np.int32)
    scores = np.zeros(156, dtype=np.float32)
    scores[52], scores[104] = nolo, rami
    result = NativeBidResult()
    assert native.lib.tc_dan_bid_select(ids.ctypes.data, 2, scores.ctypes.data, .5, C.byref(result)) == 0
    assert result.action == expected
    if result.nelli_action < 104:
        assert result.action == result.nelli_action


def test_bidding_never_forces_an_illegal_nolo_when_only_rami_is_available():
    ids = np.array([104, 105], dtype=np.int32)
    scores = np.zeros(156, dtype=np.float32)
    scores[105] = 1
    result = NativeBidResult()
    assert native.lib.tc_dan_bid_select(ids.ctypes.data, 2, scores.ctypes.data, 20, C.byref(result)) == 0
    assert result.action == result.nelli_action == 105 and result.reason == 3


def test_name_and_new_version_are_in_checkpoint():
    dan = DanAgent(1)
    record = dan.checkpoint()
    assert dan.name == record["name"] == "Dan 1.1"
    legacy = copy.deepcopy(record)
    legacy["schema"] = "tuppi.controller.dan.v1"
    with pytest.raises(ValueError): DanAgent.from_checkpoint(legacy)


def test_real_bidding_matches_nelli11_or_changes_rami_to_nolo():
    from tuppi_ai.dan11_bidding import observations
    from tuppi_ai.lite import C1H, MODEL_V4
    agents = {s:DanAgent(s) for s in range(4)}
    nellis = {s:LiteAgent(s, options=C1H, model=MODEL_V4) for s in range(4)}
    for _, _, obs in observations(16):
        decision = agents[obs.observing_seat].propose_action(obs)
        nelli = action_id(nellis[obs.observing_seat].choose_action(obs))
        actual = action_id(decision.action)
        assert decision.diagnostics["bidding"]["nelli_action"] == nelli
        assert actual in {action_id(a) for a in obs.legal_actions}
        if actual != nelli:
            assert nelli >= 104 and actual < 104
        assert decision.diagnostics["worlds"] == 0
    for dan in agents.values(): dan.close()
