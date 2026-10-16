"""A06 ReplayFork, A07 NativeFork, A08 hidden-hand invariance, A09 bundle independence,
A10 diagnostic containment, A11 retained vs cold-reset match legs; K05 mode deduction evidence."""

from __future__ import annotations

import ctypes as C
import json
import subprocess
import sys

import numpy as np
import pytest

from tuppi_ai.research.ledger import count
from tuppi_ai.research.lifecycle import (AgentSpec, ModeTracker, RecordingAgent, ReplayMismatch, native_fork,
                                         replay_fork, snapshot)


class Snapshotting(RecordingAgent):
    """Records the agent's full snapshot after every call (research build: includes native config)."""

    def __init__(self, spec, research):
        super().__init__(spec)
        self.research = research
        self.snaps = []
        self.tracker = ModeTracker()

    def choose_action(self, observation):
        action = super().choose_action(observation)
        self.tracker.observe_call(observation, len(observation.legal_actions), self.agent.sooli)
        self.snaps.append(snapshot(self.agent, self.research))
        return action


def a06_hands():
    """A constructed deck where seat 2 holds the lowest cards of every suit (a clear sooli accept)."""
    from tuppi_ai.research.fixtures import hands_of

    H, D, Cl, S = 0, 13, 26, 39
    seat2 = [H + 12, H + 0, H + 1, H + 2, D + 12, D + 0, D + 1, Cl + 12, Cl + 0, Cl + 1, S + 12, S + 0, S + 1]
    seat1 = [H + 11, H + 10, H + 9, H + 8, H + 7, D + 11, D + 10, D + 9, D + 8, D + 7, S + 11, S + 10, S + 9]
    seat0 = [Cl + r for r in range(2, 12)] + [H + 3, H + 4, H + 5]
    seat3 = [H + 6] + [D + r for r in range(2, 7)] + [S + r for r in range(2, 9)]
    assert sorted(seat0 + seat1 + seat2 + seat3) == list(range(52))
    return hands_of([seat0, seat1, seat2, seat3])


@pytest.fixture(scope="module")
def sooli_game(research):
    """Complete search-played smoke deal 1 of 2: best agents (W32) at seats 0 and 2 of a constructed deck."""
    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent, deck_digest, rami_first
    from tuppi_ai.research.runner_v3 import new_match, play_deal

    hands = a06_hands()
    specs = {s: AgentSpec.of("best", s, worlds=32, seed=11) for s in (0, 2)}
    agents = {s: Snapshotting(specs[s], research) for s in (0, 2)}
    agents[1] = RuleAgent(1, CloneGreedyAgent(1), show=rami_first)
    agents[3] = CloneGreedyAgent(3)
    out = play_deal(new_match(), agents, hands)
    count(search_game_ids=["A06-lowdeck-best-seats-0-2-W32"], runner_deal_ids=[deck_digest(hands)])
    assert not out.failed and out.state.phase.value == "DEAL_COMPLETE", out.failure
    return agents, specs, out


def _phases(agent):
    return [(h["observation"]["phase"], len(h["observation"]["legal_actions"])) for h in agent.history]


def test_A06_sequence_covers_cold_offer_give_play_forced_and_heuristic_branches(sooli_game):
    agents, _specs, out = sooli_game
    r = out.state.completed_deals[-1].public_result
    soolaaja = r.soolaaja
    assert soolaaja in (0, 2), "the searched offers declined; no exchange branch to replay"
    calls = _phases(agents[0]) + _phases(agents[2])
    kinds = {p for p, _n in calls}
    assert {"SOOLI_OFFER", "SOOLI_GIVE", "SOOLI_RETURN", "SOOLI_PLAY"} <= kinds, calls
    assert any(n == 1 for _p, n in calls), "no forced call in the sequence"
    first = agents[soolaaja].snaps[0]["searcher"]["native_config"]
    assert agents[soolaaja].history[0]["observation"]["phase"] == "SOOLI_OFFER"
    # K05 evidence: the actual native settings follow the deduced C -> O -> P modes.
    for s in (0, 2):
        for snap, (_before, _phase, mode) in zip(agents[s].snaps, agents[s].tracker.transitions):
            cfg = snap["searcher"]["native_config"]
            got = (cfg["sooli_belief"], cfg["sooli_return_pi"], cfg["sooli_play_heur"], round(cfg["sooli_lambda"], 6))
            assert got == ModeTracker.SETTINGS[mode], (s, mode, got)
    assert first["sooli_belief"] == 17 and first["sooli_play_heur"] == 1  # offer mode after the first call
    partner = (soolaaja + 2) % 4
    ret = [i for i, h in enumerate(agents[partner].history) if h["observation"]["phase"] == "SOOLI_RETURN"]
    assert ret and agents[partner].agent.last_values is None  # heuristic return, no search


def test_A06_replayfork_reproduces_every_call_and_the_final_state(sooli_game, research):
    agents, specs, _out = sooli_game
    for s in (0, 2):
        fork = replay_fork(specs[s], agents[s].history)
        assert [h["action"] for h in fork.history] == [h["action"] for h in agents[s].history]
        assert snapshot(fork.agent, research) == agents[s].snaps[-1]


def test_A06_replayfork_detects_a_diverging_history(sooli_game):
    agents, specs, _out = sooli_game
    s = next(x for x in (0, 2) if any(len(h["observation"]["legal_actions"]) > 1 for h in agents[x].history))
    history = [dict(h) for h in agents[s].history]
    i = next(i for i, h in enumerate(history) if len(h["observation"]["legal_actions"]) > 1)
    legal = history[i]["observation"]["legal_actions"]
    history[i]["action"] = next(a for a in legal if a != history[i]["action"])
    with pytest.raises(ReplayMismatch) as err:
        replay_fork(specs[s], history)
    assert err.value.index == i


def test_A07_nativefork_matches_replayfork_and_forks_are_independent(sooli_game, research):
    from tuppi_ai.research.observation import observation_from_data

    agents, specs, _out = sooli_game
    s = max((0, 2), key=lambda x: len(agents[x].history))
    hist = agents[s].history
    k = next(i for i in range(1, len(hist)) if len(hist[i]["observation"]["legal_actions"]) > 1)
    by_replay = replay_fork(specs[s], hist, upto=k)
    by_native = native_fork(by_replay, research)
    assert snapshot(by_native.agent, research) == snapshot(by_replay.agent, research) == agents[s].snaps[k - 1]
    obs = observation_from_data(hist[k]["observation"])
    a1 = by_replay.choose_action(obs)
    before = snapshot(by_replay.agent, research)
    a2 = by_native.choose_action(obs)
    assert a1 == a2 and by_native.agent.last_values == by_replay.agent.last_values
    assert snapshot(by_native.agent, research) == before == agents[s].snaps[k]
    by_native.agent.searcher.rng.value ^= 0xFFFF  # mutating the fork leaves its source untouched
    research.import_config(by_native.agent.searcher.env,
                           dict(research.env_config(by_native.agent.searcher.env), sooli_belief=0))
    assert snapshot(by_replay.agent, research) == before


def test_A08_changed_hidden_hands_leave_features_and_actions_unchanged(research):
    """F01: the focal seat's complete legal input is identical under two different hidden layouts."""
    from tuppi_engine import match_observation_for, observation_to_data

    import tuppi_ai.native as nat
    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_ai.research.fixtures import (_card_from_code, load_extras, load_fixture, make_truth, nolo_first,
                                            replay)
    from tuppi_engine import apply_match_action

    _p, cases, truth = load_fixture("F01")
    base_obs = cases[0].policy_observation()
    alt = load_extras("F01")["alternative_layout"]
    alt_hands = tuple(tuple(_card_from_code(c) for c in h) for h in alt["hands"])
    assert alt_hands != tuple(tuple(_card_from_code(c) for c in h) for h in truth.initial_hands)
    state = replay(make_truth("alt", alt_hands, []), 0)
    while state.current_actor != base_obs.observing_seat:
        o = match_observation_for(state, state.current_actor)
        state = apply_match_action(state, o.legal_actions[nolo_first(o)])
    alt_obs = match_observation_for(state, base_obs.observing_seat)
    assert observation_to_data(alt_obs) == observation_to_data(base_obs)
    f1 = nat.encode(obs_from_player_observation(base_obs), encoder=2)
    f2 = nat.encode(obs_from_player_observation(alt_obs), encoder=2)
    assert np.array_equal(f1, f2)
    seat = base_obs.observing_seat
    one = AgentSpec.of("best", seat, worlds=16, seed=3).construct()
    two = AgentSpec.of("best", seat, worlds=16, seed=3).construct()
    count(probe_ids=["F01-bid-cold"])
    assert one.choose_action(base_obs) == two.choose_action(alt_obs)
    assert one.last_values == two.last_values
    assert snapshot(one, research) == snapshot(two, research)


def _bundle(index, order_tag):
    from tuppi_ai.research.runner_v3 import PolicyFamily, duplicate_bundle

    cand = PolicyFamily.of("random-a", "random_legal", seeded=True)
    base = PolicyFamily.of("random-b", "random_legal", seeded=True)
    return duplicate_bundle(index, cand, base, namespace="contract-A09")


def test_A09_independent_bundles_do_not_depend_on_order_or_worker_count():
    from tuppi_ai.research.fixtures import deck_digest
    from tuppi_ai.research.streams import shuffled_deck

    forward = [_bundle(i, "fwd") for i in (0, 1)]
    backward = [_bundle(i, "bwd") for i in (1, 0)][::-1]
    count(runner_deal_ids=[deck_digest(shuffled_deck("deal", "contract-A09", i)) for i in (0, 1)])
    for a, b in zip(forward, backward):
        assert a["rows"] == [dict(r, cpu_s=a["rows"][j]["cpu_s"], wall_s=a["rows"][j]["wall_s"],
                                  decision_ms=a["rows"][j]["decision_ms"]) for j, r in enumerate(b["rows"])]
        assert a["value"] == b["value"] and a["resolved"]
    code = ("import json; from tuppi_ai.research.runner_v3 import PolicyFamily, duplicate_bundle;"
            "c=PolicyFamily.of('random-a','random_legal',seeded=True);"
            "b=PolicyFamily.of('random-b','random_legal',seeded=True);"
            "print(json.dumps(duplicate_bundle(1,c,b,namespace='contract-A09')['value']))")
    other = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)
    assert json.loads(other.stdout) == forward[1]["value"]


def test_A09_historical_worker_reuse_links_bundles_and_is_labelled():
    from tuppi_ai.research.runner_v3 import PolicyFamily, historical_order

    cand = PolicyFamily.of("random-a", "random_legal", seeded=True)
    base = PolicyFamily.of("random-b", "random_legal", seeded=True)
    together = historical_order([0, 1], cand, base, namespace="contract-A09")
    alone = historical_order([1], cand, base, namespace="contract-A09")
    assert together[1]["lifecycle"] == "historical_worker_reuse"
    assert together[1]["values"] != alone[0]["values"], "reused agents should carry state across bundles"


def test_A10_diagnostic_evaluation_on_a_fork_never_advances_the_live_agent(sooli_game, research):
    from tuppi_ai.research.observation import observation_from_data
    from tuppi_ai.bridge import obs_from_player_observation

    agents, specs, _out = sooli_game
    s = max((0, 2), key=lambda x: len(agents[x].history))
    live = replay_fork(specs[s], agents[s].history, upto=2)
    before = snapshot(live.agent, research)
    diag = native_fork(live, research)
    obs = observation_from_data(agents[s].history[2]["observation"])
    ids = [a for a in agents[s].history[2]["observation"]["legal_actions"]]
    from tuppi_engine import action_from_data
    from tuppi_ai.bridge import action_id
    ids = [action_id(action_from_data(a)) for a in ids]
    tobs = obs_from_player_observation(obs)
    sr = diag.agent.searcher
    ev, worlds = research.trace_search(sr.env, sr.mlp, tobs, ids, 8, 6, C.c_uint64(sr.rng.value))
    research.evaluate_worlds(sr.env, sr.mlp, tobs, worlds, ids, 6, C.c_uint64(0))
    diag.choose_action(obs)
    assert snapshot(live.agent, research) == before


def test_A11_match_legs_retain_controllers_and_cold_reset_is_a_distinct_instrument():
    from tuppi_ai.research.fixtures import deck_digest
    from tuppi_ai.research.runner_v3 import PolicyFamily, match_leg
    from tuppi_ai.research.streams import shuffled_deck

    cand = PolicyFamily.of("random-a", "random_legal", seeded=True)
    base = PolicyFamily.of("random-b", "random_legal", seeded=True)
    kept = match_leg(0, cand, base, 0, namespace="contract-A11", cap=2)
    reset = match_leg(0, cand, base, 0, namespace="contract-A11", cap=2, lifecycle="cold_reset_per_deal")
    count(runner_deal_ids=[deck_digest(shuffled_deck("deal", "contract-A11", "pair", 0, "deal", i)) for i in (0, 1)])
    assert kept["lifecycle"] == "retained_match_leg" and reset["lifecycle"] == "cold_reset_per_deal"
    assert kept["agents_retained_whole_leg"] and not reset["agents_retained_whole_leg"]
    assert [r["lifecycle"] for r in kept["rows"]] == ["retained_match_leg"] * len(kept["rows"])
    if kept["deals"] == 2 and reset["deals"] == 2:
        # same deck and seeds: deal 0 starts identically, deal 1 starts from retained vs fresh state
        assert kept["rows"][0]["snapshot_ids"] == reset["rows"][0]["snapshot_ids"]
        assert kept["rows"][1]["snapshot_ids"] != reset["rows"][1]["snapshot_ids"]
        assert sum(kept["calls_per_seat"]) > sum(reset["calls_per_seat"])
    assert kept["outcome"] in ("win", "loss", "unresolved")


def test_A10_a_diagnostic_on_the_live_agents_own_environment_changes_no_decision(sooli_game, research):
    """Slots are scratch: evaluating counterfactual worlds in the live env leaves every later choice unchanged."""
    from tuppi_engine import action_from_data

    from tuppi_ai.bridge import action_id, obs_from_player_observation
    from tuppi_ai.research.observation import observation_from_data

    agents, specs, _out = sooli_game
    s = max((0, 2), key=lambda x: len(agents[x].history))
    hist = agents[s].history
    k = next(i for i in range(1, len(hist)) if len(hist[i]["observation"]["legal_actions"]) > 1)
    live = replay_fork(specs[s], hist, upto=k)
    twin = replay_fork(specs[s], hist, upto=k)
    obs = observation_from_data(hist[k]["observation"])
    tobs = obs_from_player_observation(obs)
    ids = [action_id(action_from_data(a)) for a in hist[k]["observation"]["legal_actions"]]
    sr = live.agent.searcher
    ev, worlds = research.trace_search(sr.env, sr.mlp, tobs, ids, 16, 6, C.c_uint64(sr.rng.value ^ 0xABCDEF))
    research.evaluate_worlds(sr.env, sr.mlp, tobs, worlds[::-1], ids, 6, C.c_uint64(1))
    assert snapshot(live.agent, research)["searcher"]["scalar_rng"] == snapshot(twin.agent, research)["searcher"]["scalar_rng"]
    assert live.choose_action(obs) == twin.choose_action(obs)
    assert live.agent.last_values == twin.agent.last_values
    assert snapshot(live.agent, research) == snapshot(twin.agent, research)
