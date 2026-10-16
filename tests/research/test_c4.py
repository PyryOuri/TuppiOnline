"""C4.01 contract tests X01, X02, X03, X07, X09, X10: legal exchange scorers, tables and four-arm replay."""

from __future__ import annotations

import ctypes as C

import numpy as np
import pytest

from tuppi_ai.research import c4_exchange as X
from tuppi_ai.research.testing import fixture_case


@pytest.fixture(scope="module")
def give_obs():
    return fixture_case("F03", 0)[0].policy_observation()


@pytest.fixture(scope="module")
def return_obs():
    return fixture_case("F04", 0)[0].policy_observation()


def test_X01_stage_features_masks_ace_low_and_no_156_head(give_obs, return_obs):
    feat, legal = X.give_features(give_obs)
    own = sorted(X._card_index(c) for c in give_obs.own_hand)
    assert feat.shape == (X.FEATURE_WIDTH,) and feat[0] == 1 and feat[1] == 0 and legal == own and len(legal) == 13
    assert all(feat[2 + c] == 1 for c in own) and feat[2:54].sum() == 13
    assert X.ace_low_index(12) == 0 and X.ace_low_index(0) == 1 and X.ace_low_index(11) == 12  # A, 2, K of hearts
    assert all(feat[2 + 52 + X.ace_low_index(c)] == 1 for c in own)
    rfeat, rlegal = X.return_features(return_obs)
    g = X._card_index(return_obs.sooli_given_card)
    p = X.receiver_original_hand(return_obs)
    assert len(return_obs.own_hand) == 14 and len(p) == 13 and g not in p and rlegal == p
    assert rfeat[1] == 1 and rfeat[2 + 160 + g] == 1 and all(rfeat[2 + c] == 1 for c in p) and rfeat[2 + g] == 0
    with pytest.raises(X.IllegalExchangeInput):
        X.give_features(return_obs)
    with pytest.raises(X.IllegalExchangeInput):
        X.return_features(give_obs)
    net = X.exchange_scorer(1)
    s = X.scores(net, feat)
    assert s.shape == (52,) and net[-1].out_features == 52  # one score per physical card, never the 156 head
    agent = X.ExchangePolicyAgent(base=None, give_net=net)
    a = agent.choose_action(give_obs)
    assert a in give_obs.legal_actions and X._card_index(a.card) == X.greedy(s, legal)
    dist = X.masked_distribution(s, legal)
    assert set(dist) == set(legal) and abs(sum(dist.values()) - 1) < 1e-12


def test_X01_switched_off_wrapper_delegates_exactly():
    class Base:
        handles_sooli = True
        calls = 0

        def choose_action(self, obs):
            Base.calls += 1
            return obs.legal_actions[-1]

    obs = fixture_case("F03", 0)[0].policy_observation()
    wrapped = X.ExchangePolicyAgent(Base())
    assert wrapped.choose_action(obs) == obs.legal_actions[-1] and Base.calls == 1 and wrapped.decisions == []


def _swap_layout(truth, upto, seats, keep):
    """Swap one card between two seats (never a card in `keep`) and replay the same legal history."""
    from tuppi_ai.research.fixtures import replay
    from tuppi_ai.research.records import OfflineTruth

    a, b = seats
    ha, hb = list(truth.initial_hands[a]), list(truth.initial_hands[b])
    for ca in ha:
        for cb in hb:
            if ca in keep or cb in keep:
                continue
            hands = [list(h) for h in truth.initial_hands]
            hands[a][hands[a].index(ca)] = cb
            hands[b][hands[b].index(cb)] = ca
            alt = OfflineTruth(truth.cluster_id, truth.ruleset, truth.dealer, truth.starting_score,
                               tuple(tuple(h) for h in hands), truth.action_history)
            try:
                return replay(alt, upto)
            except Exception:
                continue
    raise AssertionError("no legal swap")


def test_X02_features_and_policies_ignore_other_hidden_hands(give_obs, return_obs):
    from tuppi_engine import match_observation_for, observation_to_data

    from tuppi_ai.research.fixtures import load_fixture
    net = X.exchange_scorer(2)
    _p, c3, t3 = load_fixture("F03")
    state = _swap_layout(t3, len(t3.action_history), (0, 3), keep={"8H"})
    alt_give = match_observation_for(state, give_obs.observing_seat)
    assert observation_to_data(alt_give) == c3[0].observation
    f1, l1 = X.give_features(give_obs)
    f2, l2 = X.give_features(alt_give)
    assert np.array_equal(f1, f2) and l1 == l2
    assert X.masked_distribution(X.scores(net, f1), l1) == X.masked_distribution(X.scores(net, f2), l2)
    import json
    from tuppi_ai.research.fixtures import TRUTH_DIR
    from tuppi_ai.research.records import OfflineTruth
    t4 = OfflineTruth.from_data(json.loads((TRUTH_DIR / "F04.truth.json").read_text()))
    state = _swap_layout(t4, len(t4.action_history), (1, 3), keep={"8H"})
    alt_ret = match_observation_for(state, return_obs.observing_seat)
    assert observation_to_data(alt_ret) == observation_to_data(return_obs)
    r1, rl1 = X.return_features(return_obs)
    r2, rl2 = X.return_features(alt_ret)
    assert np.array_equal(r1, r2) and rl1 == rl2


@pytest.fixture(scope="module")
def pre_give():
    from tuppi_ai.research.fixtures import _card_from_code, load_fixture, native_deal_after

    _p, _c, t3 = load_fixture("F03")
    hands = tuple(tuple(_card_from_code(c) for c in h) for h in t3.initial_hands)
    return native_deal_after(hands, list(t3.action_history))


def test_X03_full_169_branch_table_with_recorded_cost(pre_give):
    table = X.payoff_table(pre_give)
    assert len(table.gives) == 13 and table.survival.shape == (13, 13) and table.cost["continuations"] == 169
    assert set(np.unique(table.survival)) <= {0, 1} and set(np.unique(table.pi_proxy)) <= {0, 1}
    for g, rets in table.returns.items():
        assert len(rets) == 13 and g not in rets
    assert table.cost["cpu_s_per_continuation"] > 0
    assert "never the primary outcome" in table.labels["pi_proxy"]
    assert len(np.unique(table.survival)) == 2, "a constant table cannot discriminate conventions"


def test_X07_four_arm_replay_with_matched_snapshots_and_separate_state_variants(research):
    """Old/new giver x old/new returner from one accepted pre-give state (the A06 smoke deal's soolaaja)."""
    from test_c0_lifecycle import a06_hands  # the constructed deck of the complete search smoke deal

    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent, rami_first, walk
    from tuppi_ai.research.lifecycle import AgentSpec, RecordingAgent, native_fork, snapshot

    import tuppi_ai.native as nat
    from tuppi_ai.bridge import mask_of

    hands = a06_hands()
    # the pre-give position, reached with the same legal history as the smoke deal's (searched accept replaced
    # by the heuristic's here: the arms only need one common accepted pre-give state)
    agents = {s: RuleAgent(s, CloneGreedyAgent(s), show=rami_first if s == 1 else None) for s in range(4)}
    _st, history, give_o = walk(hands, agents, stop=lambda st, o: o.phase.value == "SOOLI_GIVE")
    assert give_o is not None
    S = give_o.observing_seat
    spec_s = AgentSpec.of("best", S, worlds=32, seed=11)
    controller = RecordingAgent(spec_s)          # the soolaaja's playing controller at the pre-give point
    base_snap = snapshot(controller.agent, research)
    new_give, new_ret = X.exchange_scorer(3), X.exchange_scorer(4)
    from tuppi_ai.research.fixtures import native_deal_after
    pre = native_deal_after(hands, history)
    results = {}
    for giver in ("old", "new"):
        for returner in ("old", "new"):
            fork = native_fork(controller, research)  # every arm starts from the SAME controller snapshot
            assert snapshot(fork.agent, research) == base_snap
            if giver == "old":
                g_action = fork.choose_action(give_o)         # the frozen searched give
            else:
                g_action = X.ExchangePolicyAgent(None, give_net=new_give).choose_action(give_o)
            d = nat.TcDeal()
            C.pointer(d)[0] = pre
            assert nat.lib.tc_apply(C.byref(d), X.EXCHANGE + X._card_index(g_action.card)) == 0
            ret_obs = nat.observe(d, d.cur)
            if returner == "old":
                r = nat.sooli_policy(ret_obs, C.c_uint64(1))  # the frozen heuristic return
            else:
                from tuppi_engine import apply_match_action, match_observation_for
                from tuppi_ai.research.fixtures import make_truth, replay
                from tuppi_engine import action_to_data
                eng = replay(make_truth("x4", hands, history + [action_to_data(g_action)]),
                             len(history) + 1)
                ro = match_observation_for(eng, eng.current_actor)
                r = X.EXCHANGE + X._card_index(X.ExchangePolicyAgent(None, return_net=new_ret).choose_action(ro).card)
            assert nat.lib.tc_apply(C.byref(d), r) == 0
            results[(giver, returner)] = {"survived": X.heuristic_continuation(d),
                                          "controller_after_exchange": snapshot(fork.agent, research)}
    J = {k: v["survived"] for k, v in results.items()}
    interaction = J[("new", "new")] - J[("new", "old")] - J[("old", "new")] + J[("old", "old")]
    assert interaction in (-2, -1, 0, 1, 2)
    old_state = results[("old", "old")]["controller_after_exchange"]
    natural_state = results[("new", "old")]["controller_after_exchange"]
    assert natural_state == base_snap and old_state != base_snap  # natural: no give search ran
    # shadow variant: run the frozen give search on a fork to establish W128's advancement, then override
    shadow = native_fork(controller, research)
    shadow.choose_action(give_o)
    assert snapshot(shadow.agent, research) == old_state


def test_X09_privately_transferred_shown_card_and_defender_ignorance(research, nat, table):
    """F03's deck, dealer 3: seat 0 shows 4C, seat 1 declares RAMI, seat 2 declines, seat 0 accepts
    (scripted: a synthetic acceptance) and gives its shown 4C to the partner."""
    from tuppi_engine import match_observation_for

    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent, f03_hands, rami_first, walk

    def show0(o):
        return next(i for i, a in enumerate(o.legal_actions) if a.declared_contract.value == "NOLO"
                    and a.shown_card.suit.value == "clubs" and a.shown_card.rank.value == 4)

    rules = {0: RuleAgent(0, CloneGreedyAgent(0), show=show0,
                          offer=lambda o: next(i for i, a in enumerate(o.legal_actions) if a.play_sooli),
                          give=lambda o: next(i for i, a in enumerate(o.legal_actions)
                                              if a.card.suit.value == "clubs" and a.card.rank.value == 4)),
             1: RuleAgent(1, CloneGreedyAgent(1), show=rami_first),
             2: RuleAgent(2, CloneGreedyAgent(2), offer=lambda o: next(i for i, a in enumerate(o.legal_actions)
                                                                        if not a.play_sooli)),
             3: RuleAgent(3, CloneGreedyAgent(3))}
    state, _h, o = walk(f03_hands(), rules, dealer=3,
                        stop=lambda st, ob: ob.phase.value == "SOOLI_PLAY" and ob.observing_seat in (1, 3))
    assert o is not None and o.soolaaja == 0
    shown = [s for s in o.show_actions if s.seat == 0]
    assert shown and shown[0].shown_card.suit.value == "clubs"
    assert o.sooli_given_card is None and o.sooli_returned_card is None  # defenders never see the exchange
    partner_obs = match_observation_for(state, 2)
    assert partner_obs.sooli_given_card == shown[0].shown_card        # the partner knows
    four_c = 26 + 2
    env = nat.Env(64, 0, table, single_deal=True, encoder=2)
    where_def = {s for w in research.sample_worlds(env, obs_from_player_observation(o), 64, C.c_uint64(5))
                 for s in range(4) if w.hand[s] >> four_c & 1}
    assert where_def == {0, 2}  # a defender keeps both locations of the privately moved shown card
    # the dead partner never acts for the rest of the deal
    from tuppi_engine import apply_match_action
    from tuppi_engine.state import ACTIVE_PHASES
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        assert seat != 2
        state = apply_match_action(state, rules[seat].choose_action(match_observation_for(state, seat)))


def test_X10_population_denominators_splits_and_the_legacy_bank_guard():
    from tuppi_ai.research.records import SplitLeakError, SplitRegistry, parent_deal_id

    records = [{"deal_id": parent_deal_id("c4-dev", i), "offers": offers}
               for i, offers in enumerate([[(2, False), (0, True)], [(1, False), (3, False)], [(2, True)]])]
    pop = X.accepted_population(records, "frozen-offer:W128", "DEV")
    assert (pop["offers_made"], pop["offers_accepted"], pop["offers_rejected"]) == (5, 2, 3)
    assert pop["source_deals"] == 3 and len(pop["accepted_states"]) == 2
    X.check_confirmation_source(dict(pop, split="CONFIRM"))
    with pytest.raises(ValueError):
        X.check_confirmation_source(dict(pop, ruleset="project_target_v2"))
    with pytest.raises(ValueError):
        X.check_confirmation_source(dict(pop, generator="tools/sooli_bank.py"))
    with pytest.raises(ValueError):
        X.check_confirmation_source(dict(pop, offers_rejected=4))
    reg = SplitRegistry()
    for r in records:
        reg.assign(r["deal_id"], "DEV")
    with pytest.raises(SplitLeakError):
        reg.check_record(records[0]["deal_id"], "CONFIRM")  # a whole source deal stays in its split
