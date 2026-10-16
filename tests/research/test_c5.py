"""C5 contract tests O01-O10: the actual-root information-consistent three-card option."""

from __future__ import annotations

import ctypes as C
from itertools import product

import pytest

from tuppi_ai.research import c5_option as O
from tuppi_ai.research.ledger import count
from tuppi_ai.research.testing import fixture_case


@pytest.fixture(scope="module")
def equity():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity

    return Equity.load(EQUITY)


@pytest.fixture(scope="module")
def f05():
    from tuppi_ai.bridge import action_id, obs_from_player_observation

    case, truth = fixture_case("F05", 0)
    obs = case.policy_observation()
    return {"obs": obs, "tobs": obs_from_player_observation(obs), "ids": [action_id(a) for a in obs.legal_actions],
            "truth": truth}


@pytest.fixture(scope="module")
def solved(f05, mlp, net, equity):
    sup = O.complete_support(f05["obs"])
    model = O.NativeModel(mlp, net.encoder, equity)
    return sup, O.solve_option(f05["tobs"], sup.worlds, model, f05["ids"]), model


def brute_force_plan_value(histories):
    """Independent tiny enumerator: try every key -> action mapping."""
    keys = sorted({k for k, _m, _u in histories})
    actions = {k: sorted(next(u for kk, _m, u in histories if kk == k)) for k in keys}
    best = None
    for choice in product(*(actions[k] for k in keys)):
        plan = dict(zip(keys, choice))
        v = sum(m * u[plan[k]] for k, m, u in histories)
        best = v if best is None else max(best, v)
    return best


def test_O01_support_is_counted_complete_capped_and_model_agreement_is_required(f05):
    from tuppi_ai.research.fixtures import support_worlds

    sup = O.complete_support(f05["obs"])
    assert sup.status == "EXACT_COMPLETE" and sup.native_count == len(sup.worlds) == sup.strict_count
    assert sorted(map(tuple, sup.worlds)) == sorted(map(tuple, support_worlds(f05["tobs"])))  # independent enumerator
    assert O.strict_exclusions(f05["obs"]) == {}  # no verbal show: the strict and native laws coincide here
    small = O.complete_support(f05["obs"], cap=sup.native_count - 1)
    assert small.status == "TOO_LARGE" and small.worlds == []  # never a partial support labelled exact
    some = next(s for s in range(4) if s != f05["tobs"].seat)
    card = next(c for c in range(52) if any(w[some] >> c & 1 for w in sup.worlds))
    mismatch = O.complete_support(f05["obs"], exclusions={some: {card}})
    assert mismatch.status == "CONSTRAINT_MODEL_MISMATCH" and mismatch.worlds == []


def test_O02_reconstruction_preserves_v3_public_history_and_each_clone_sees_only_itself(nat, mlp, net, equity):
    """An ordinary RAMI after two sooli declines, at its three-card boundary (F03's deck, no new deal)."""
    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent, f03_hands, rami_first, walk

    decline = lambda ob: next(i for i, a in enumerate(ob.legal_actions) if not a.play_sooli)  # noqa: E731
    agents = {s: RuleAgent(s, CloneGreedyAgent(s), show=rami_first if s == 1 else None, offer=decline)
              for s in range(4)}
    _st, _h, obs = walk(f03_hands(), agents, stop=lambda st, ob: O.eligible(ob))
    assert obs is not None and obs.ruleset_id.value == "project_target_v3" and len(obs.sooli_decisions) == 2
    sup = O.complete_support(obs)
    assert sup.status == "EXACT_COMPLETE"
    tobs = obs_from_player_observation(obs)
    model = O.NativeModel(mlp, net.encoder, equity)
    for masks in sup.worlds[:4]:
        w = model.world(tobs, masks)
        assert w.ruleset == 3 and w.n_decisions == 2 and w.contract == 1 and w.soolaaja == -1
        for s in range(4):
            if s == tobs.seat:
                continue
            o = nat.observe(w, s)
            assert o.hand == masks[s] and o.hand & tobs.hand == 0 and o.n_decisions == 2 and o.ruleset == 3
    assert O.scope_of(tobs)[-3] == 2  # the declines are part of the option's scope


def test_O03_indistinguishable_worlds_share_one_later_action_distinguishable_ones_need_not():
    fused = [("k", 0.5, {1: 1.0, 2: 0.0}), ("k", 0.5, {1: 0.0, 2: 0.8})]
    value, plan = O.optimise_groups(fused)
    assert plan == {"k": 1} and value == pytest.approx(0.5)            # one compromise b
    assert value < 0.5 * 1.0 + 0.5 * 0.8                                # per-world choice would fuse strategies
    assert value == pytest.approx(brute_force_plan_value(fused))
    split = [("k1", 0.5, {1: 1.0, 2: 0.0}), ("k2", 0.5, {1: 0.0, 2: 0.8})]
    value2, plan2 = O.optimise_groups(split)
    assert plan2 == {"k1": 1, "k2": 2} and value2 == pytest.approx(0.9) == brute_force_plan_value(split)


def test_O04_nonuniform_mass_changes_the_choice_and_key_collisions_are_rejected(f05, solved, mlp, net, equity):
    even = [("k", 0.5, {1: 1.0, 2: 0.0}), ("k", 0.5, {1: 0.0, 2: 1.2})]
    tilted = [("k", 0.8, {1: 1.0, 2: 0.0}), ("k", 0.2, {1: 0.0, 2: 1.2})]
    assert O.optimise_groups(even)[1] == {"k": 2} and O.optimise_groups(tilted)[1] == {"k": 1}
    with pytest.raises(O.KeyCollision):
        O.optimise_groups([("k", 0.5, {1: 1.0}), ("k", 0.5, {1: 0.0, 2: 1.0})])
    sup, _res, _m = solved
    lossy = lambda o: o.seat  # noqa: E731  (drops the play history: merges different observations)
    with pytest.raises(O.KeyCollision):
        O.solve_option(f05["tobs"], sup.worlds, O.NativeModel(mlp, net.encoder, equity), f05["ids"], key_fn=lossy)


def test_O05_O06_O07_complete_option_bounds_and_the_W128_comparator_in_the_same_model(f05, solved, research, mlp,
                                                                                      net, equity):
    from tuppi_ai.research.lifecycle import AgentSpec, RecordingAgent, native_fork, snapshot

    sup, res, _m = solved
    model = O.NativeModel(mlp, net.encoder, equity)
    best_q = res.q[res.chosen]
    # the W128 comparator: its lead, then its own later choices from ONE forked snapshot for every history
    agent = RecordingAgent(AgentSpec.of("best", f05["tobs"].seat, worlds=128, seed=0))
    lead = agent.choose_action(f05["obs"])
    from tuppi_ai.bridge import action_id
    first = action_id(lead)
    after_first = snapshot(agent.agent, research)
    order = [action_id(a) for a in f05["obs"].legal_actions]  # the root's engine legal order (tie order)
    cache, snaps = {}, []

    def later(o):
        key = O.root_key(o)
        if key not in cache:
            fork = native_fork(agent, research)
            snaps.append(snapshot(fork.agent, research))
            ids = [c for c in order if o.hand >> c & 1 and c in __import__("tuppi_ai.native", fromlist=["x"]).legal_obs(o)]
            vals = fork.agent.searcher.action_values(o, ids)
            cache[key] = ids[max(range(len(ids)), key=lambda i: (vals[i], -i))]
        return cache[key]

    w128 = O.policy_value(f05["tobs"], sup.worlds, model, first, later)
    count(probe_ids=["F05-three-card-lead"], native_search_calls=1 + len(cache))
    assert all(s == after_first for s in snaps)                     # O07: no world-dependent controller state
    assert best_q >= w128 - 1e-12                                   # O05: optimum >= a feasible comparator
    assert best_q >= res.q[first] - 1e-12 and res.q[first] >= w128 - 1e-12  # old lead + optimised future option
    lowest = O.policy_value(f05["tobs"], sup.worlds, model, min(f05["ids"]), lambda o: min(
        __import__("tuppi_ai.native", fromlist=["x"]).legal_obs(o)))
    assert best_q >= lowest - 1e-12
    clair = O.root_clairvoyant_value(f05["tobs"], sup.worlds, model, f05["ids"])
    assert clair >= best_q - 1e-12                                  # root-only clairvoyance is an upper bound
    # O06: action-minus-reference gaps can be negative; the optimum-minus-feasible gap never is
    gaps = [res.q[a] - res.q[res.chosen] for a in f05["ids"]]
    assert all(g <= 1e-12 for g in gaps)
    toy = [("k", 1.0, {1: 0.2, 2: 0.7})]
    assert O.optimise_groups(toy)[0] - 0.2 > 0 and 0.2 - O.optimise_groups(toy)[0] < 0  # a negative action gap


def test_O08_the_option_persists_and_unexpected_keys_or_caps_fall_back(f05, solved, mlp, net, equity):
    from tuppi_engine import FirstLegalActionAgent, action_from_data, apply_match_action, match_observation_for

    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import replay

    truth = f05["truth"]
    i = sum(len(t.plays) for t in f05["obs"].completed_tricks) + len(f05["obs"].show_actions)
    state = replay(truth, i)
    root = f05["tobs"].seat
    agent = O.C5Agent(FirstLegalActionAgent(), mlp, net.encoder, equity)
    others = {s: CloneGreedyAgent(s) for s in range(4)}
    from tuppi_engine.state import ACTIVE_PHASES
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        o = match_observation_for(state, seat)
        state = apply_match_action(state, (agent if seat == root else others[seat]).choose_action(o))
    events = [e["event"] for e in agent.log]
    assert events[0] == "option_started" and "fallback" not in events  # the real world is in the support
    assert events.count("option_followed") + events.count("forced") == len(events) - 1
    assert agent.log[0]["support"] == solved[0].native_count
    # an unexpected information key: a trick-12 observation the option never planned for
    off = O.C5Agent(FirstLegalActionAgent(), mlp, net.encoder, equity)
    off.choose_action(f05["obs"])
    fake = match_observation_for(replay(truth, i), root)
    off.option.plan = {}  # nothing matches now
    later_state = replay(truth, i)
    later_state = apply_match_action(later_state, fake.legal_actions[0])
    while later_state.current_actor != root:
        s = later_state.current_actor
        later_state = apply_match_action(later_state, others[s].choose_action(match_observation_for(later_state, s)))
    off.choose_action(match_observation_for(later_state, root))
    assert off.log[-1] == {"event": "fallback", "reason": "unexpected information key (off-support)"}
    capped = O.C5Agent(FirstLegalActionAgent(), mlp, net.encoder, equity, node_cap=5)
    capped.choose_action(f05["obs"])
    assert capped.log[0]["event"] == "fallback" and "node cap" in capped.log[0]["reason"] and capped.option is None


def test_O09_the_suffix_after_the_later_choice_is_forced_and_two_card_states_are_not_eligible(f05, solved):
    sup, res, model = solved
    # after the lead the root holds two cards: at most two later choices, then one forced card
    # (NativeModel.finish raises on any further root choice, so solving without error proves the horizon)
    assert all(1 <= g["max_later_actions"] <= 2 for g in res.groups.values() if g["histories"])
    assert any(g["max_later_actions"] == 2 for g in res.groups.values())  # a real later choice exists
    # a two-card boundary (11 tricks complete) is outside v1 eligibility
    from tuppi_engine import action_from_data, apply_match_action, match_observation_for

    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import replay

    truth = f05["truth"]
    i = sum(len(t.plays) for t in f05["obs"].completed_tricks) + len(f05["obs"].show_actions)
    state = replay(truth, i + 4)
    o = match_observation_for(state, state.current_actor)
    assert len(o.own_hand) == 2 and not O.eligible(o)


def test_O10_one_option_per_deal_and_its_cost_and_coverage_are_recorded(f05, mlp, net, equity):
    from tuppi_engine import FirstLegalActionAgent

    agent = O.C5Agent(FirstLegalActionAgent(), mlp, net.encoder, equity)
    agent.choose_action(f05["obs"])
    first = agent.log[0]
    assert first["event"] == "option_started" and {"support", "nodes", "wall_s", "q", "chosen"} <= set(first)
    n = len(agent.log)
    agent.option = None                     # even with the option spent, the same deal gets no second option
    agent.choose_action(f05["obs"])
    assert len(agent.log) == n
