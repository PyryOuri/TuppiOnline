"""Meaningful candidate and inference-boundary checks, not strength tests."""
from __future__ import annotations
import ctypes as C
import copy
import json
from pathlib import Path
import types
from unittest.mock import patch

from bootstrap import activate
activate()

import numpy as np
import pytest
import torch
torch.set_num_threads(1)

from candidates import AnalysisAgent, adaptive, agents, map_action, permute_observation
from tuppi_ai import native
from tuppi_ai.search import Searcher
from statistics_tools import compare_traces, match_pair, matches, paired


def test_hard_anchor_retains_current_bid_margin_and_card_margin():
    actor = agents("hard_anchor", worlds=1024, seats=[0])[0]
    assert actor.keep == 0.003 and actor.keep_show == 0.03
    obs = native.TcObs()
    obs.phase = native.PH_SHOW
    with patch.object(actor.blueprint_net, "forward", return_value=torch.tensor([[0., 1., 0.] + [0.] * 153])), \
            patch("candidates.adaptive", return_value=(np.zeros(3), 1, 128)) as price, \
            patch("candidates.native.encode"):
        actor._search(actor.searcher, obs, [0, 1, 2])
    assert price.call_args.kwargs["offsets"].tolist() == [0., 0.03, 0.]
    assert price.call_args.kwargs["preferred"] == 1
    # The final decision cannot accidentally revert to a stale dropped mean.
    assert actor._keep_blueprint(obs, [0, 1, 2], np.array([100., 0., 0.]), 1) == 1


def test_recorded_reference_adaptive_matches_actual_baseline_method():
    def values(env, mlp, obs, ids, batch, tail, rng):
        return np.tile([0.001, 0.003], (batch, 1))[:, ids]
    make = lambda: types.SimpleNamespace(worlds=4, env=None, mlp=None, dd_left=6, rng=None)
    with patch("tuppi_ai.search.native.search_world_values", side_effect=values):
        old = Searcher.adaptive_values(make(), None, [0, 1], 2, 2.5, 0.005)
        obj = make()
        new = adaptive(obj, None, [0, 1], 2, 2.5, 0.005)
    np.testing.assert_array_equal(old[0], new[0])
    assert old[1:] == new[1:]
    assert obj.last_action_worlds == [2, 2]


def test_hard_anchor_changes_the_stale_mean_counterexample():
    calls = []
    def values(env, mlp, obs, ids, batch, tail, rng):
        n = len(calls)
        calls.append(ids)
        a, b = (0.02, 0.008) if n == 0 else (0.05, 0.04)
        data = np.array([[a, b, a + (0.2 if r % 2 else -0.2)] for r in range(batch)])
        return data[:, ids]
    obj = types.SimpleNamespace(worlds=1024, env=None, mlp=None, dd_left=6, rng=None)
    with patch("candidates.native.search_world_values", side_effect=values):
        _, chosen, _ = adaptive(obj, None, [0, 1, 2], 128, 2.5, 0.005, offsets=[0., 0.03, 0.], preferred=1)
    assert chosen == 1
    assert obj.last_action_worlds[1] > 128


def test_bad_adaptive_cap_is_rejected_before_native_work():
    obj = types.SimpleNamespace(worlds=200)
    with patch("candidates.native.search_world_values") as work:
        with pytest.raises(ValueError):
            adaptive(obj, None, [0, 1], 128, 2.5, 0.005)
        work.assert_not_called()


def test_hard_anchor_makes_a_legal_native_bid_through_authoritative_v3():
    from tuppi_engine import ExplicitDeal, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK
    from candidates import configure_native
    configure_native("hard_anchor", serial=True)
    cards = list(FULL_DECK)
    import random
    random.Random("cw-hard-anchor-native-smoke").shuffle(cards)
    hands = tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))
    with trusted_transitions():
        state = begin_explicit_deal(create_match(initial_score=MatchScore(0, 0), initial_dealer=0,
                    match_ref="cw-hard-native", ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=0, hands=hands))
        seat = state.current_actor
        agent = agents("hard_anchor", worlds=256, seats=[seat])[seat]
        observation = match_observation_for(state, seat)
        action = agent.choose_action(observation)
        assert action in observation.legal_actions
        assert agent.last_world_counts
        assert all(128 <= n <= 256 for n in agent.last_world_counts.values())
        assert agent.last_anchor in agent.last_values


def test_colour_preserving_swaps_round_trip_visible_observation():
    d = native.new_deal([sum(1 << c for c in range(s*13, (s+1)*13)) for s in range(4)], 0, ruleset=3)
    o = native.observe(d, d.cur)
    o.n_played = 3
    o.play_card[0:3] = [0, 14, 29]
    for permutation in ((1, 0, 2, 3), (0, 1, 3, 2), (1, 0, 3, 2)):
        assert bytes(permute_observation(permute_observation(o, permutation), permutation)) == bytes(o)
        for action in range(156):
            assert map_action(map_action(action, permutation), permutation) == action
    with pytest.raises(ValueError):
        permute_observation(o, (2, 1, 0, 3))


def test_same_net_shares_weights_but_keeps_mutable_seat_state_separate():
    team = agents("same_net", worlds=8, seats=[0, 2])
    assert team[0].searcher.mlp is team[2].searcher.mlp
    assert team[0].searcher.env is not team[2].searcher.env
    assert team[0].searcher.rng is not team[2].searcher.rng
    assert getattr(team[0].searcher.env, "_team_mlp", None) is None


def test_censored_matches_are_unknown_and_give_identification_bounds():
    row = match_pair({"result": 1., "censored": False, "deals": 2}, {"result": None, "censored": True, "deals": 5})
    summary = matches([row])
    assert row["score"] is None and summary["p_win"] is None and summary["ci95"] is None
    assert summary["p_win_bounds"] == [0.5, 1.0]
    with pytest.raises(ValueError):
        match_pair({"result": 0.5, "censored": True, "deals": 5}, {"result": 1., "censored": False, "deals": 2})


def fixture_result(values):
    return {"schema": "tuppi.cheap_wins.duplicate.v1", "candidate": "baseline", "seed": "x", "ruleset": "project_target_v3",
            "scores": "uniform", "opponent": "baseline", "context": {"package_sha256": "a" * 64, "controller_lifecycle": "fresh_indexed_game", "design": "4_rotations_2_teams"}, "base_deals": 2, "values": values,
            "dependency_versions": {"torch": "fixture", "numpy": "fixture"},
            "deal_records": [{"index": i, "deal_id": str(i) * 64, "score": [0, 0], "value": v,
                               "games": [{"value": v, "rotation": r, "team": t, "fingerprint": "a" * 64}
                                         for r in range(4) for t in (0, 1)]} for i, v in enumerate(values)]}


def test_pairing_rejects_changed_context_missing_parent_and_inconsistent_means():
    ref, candidate = fixture_result([0., 0.]), fixture_result([0.01, -0.02])
    assert paired(candidate, ref)["mean"] == -0.005
    for mutation in (lambda r: r["context"].update(package_sha256="b" * 64),
                     lambda r: r["dependency_versions"].update(torch="different"),
                     lambda r: r["deal_records"].pop(),
                     lambda r: r["deal_records"][0]["games"].__setitem__(1, r["deal_records"][0]["games"][0]),
                     lambda r: r["deal_records"][0]["games"][0].update(value=0.2)):
        broken = copy.deepcopy(candidate)
        mutation(broken)
        with pytest.raises(ValueError):
            paired(broken, ref)


def test_trace_comparison_rejects_mixed_inputs_and_labels_changed_fingerprints():
    ref = {"schema": "tuppi.cheap_wins.full_deals.v1", "candidate": "baseline",
           "context": {"package_sha256": "a" * 64}, "dependency_versions": {"torch": "fixture"},
           "job": {"samples": 2, "worlds": 1024, "seed": "fixture", "scores": "uniform", "serial": True},
           "rows": [{"index": i, "fingerprint": str(i) * 64} for i in range(2)],
           "cpu_seconds": 2., "seconds": 3.}
    candidate = copy.deepcopy(ref)
    candidate["candidate"] = "same_net"
    candidate["cpu_seconds"] = 1.
    assert compare_traces(candidate, ref)["cpu_reference_over_candidate"] == 2.
    changed = copy.deepcopy(candidate)
    changed["rows"][1]["fingerprint"] = "a" * 64
    comparison = compare_traces(changed, ref)
    assert comparison["classification"] == "numerical_or_policy_variant"
    assert comparison["mismatched_deals"] == [1]
    for mutation in (lambda r: r["job"].update(worlds=128),
                     lambda r: r["context"].update(package_sha256="b" * 64),
                     lambda r: r["rows"].pop(),
                     lambda r: r["rows"][1].update(index=0),
                     lambda r: r.update(seconds=0.)):
        broken = copy.deepcopy(candidate)
        mutation(broken)
        with pytest.raises(ValueError):
            compare_traces(broken, ref)


def test_plans_reject_budget_bypass_and_accidental_execution_flags():
    from launch import validate_plan
    out = Path(__file__).resolve().parent
    plan = json.loads((out / "configs/strength_costing.json").read_text())
    assert validate_plan(plan)["workers"] == 1
    for mutation in (lambda p: p.update(execution_enabled=True),
                     lambda p: p.update(budget_cpu_seconds=1),
                     lambda p: p["jobs"][0].update(serial=False),
                     lambda p: p["jobs"][0].update(worlds=200),
                     lambda p: p["jobs"][0].update(arm="unknown")):
        broken = copy.deepcopy(plan)
        mutation(broken)
        with pytest.raises(ValueError):
            validate_plan(broken)
