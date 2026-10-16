"""C2 contract tests B01-B08: consequential blind bids with clone predecessors."""

from __future__ import annotations

import ctypes as C

import numpy as np
import pytest

from tuppi_ai.research import c2_blind_bids as c2
from tuppi_ai.research.ledger import count
from tuppi_ai.research.testing import fixture_case, tobs_of


def alternative_world(research, env, obs):
    """F01's validated alternative layout (the forehand clone bids RAMI) as an explicit root world.

    Constructed, not sampled: it guarantees an unreached (E = 0) row in the batch.
    The earlier locked bids are placeholders (first legal NOLO card), as in the
    native sampler's F reconstruction.
    """
    import tuppi_ai.native as nat
    from tuppi_ai.research.fixtures import load_extras
    from tuppi_ai.research.observation import FULL_DECK_MASK  # noqa: F401

    alt = load_extras("F01")["alternative_layout"]
    from tuppi_rules.cards import card_from_code, card_to_index
    masks = [sum(1 << card_to_index(card_from_code(c)) for c in h) for h in alt["hands"]]
    w = nat.TcDeal()
    C.pointer(w)[0] = research.sample_worlds(env, obs, 1, C.c_uint64(1))[0]
    for s in range(4):
        w.hand[s] = masks[s]
    for i, seat in enumerate(c2.predecessor_seats(obs.dealer, obs.n_shows)):
        valid = nat.lib.tc_valid_show_cards(masks[seat], 0)
        card = (valid & -valid).bit_length() - 1
        w.show_seat[i], w.show_card[i], w.show_contract[i] = seat, card, 0
        w.show_verbal[i] = nat.lib.tc_verbal_required(card, 0)
    assert research.world_consistent(obs, w) == "ok"
    return w


@pytest.fixture(scope="module")
def focal(research, nat, table, net):
    case, truth = fixture_case("F01", 0)
    obs = tobs_of(case)
    env = nat.Env(128 * 26, 0, table, single_deal=True, encoder=2)
    sampled = research.sample_worlds(env, obs, 23, C.c_uint64(2024))
    worlds = sampled + [alternative_world(research, env, obs)]
    count(probe_ids=["F01-bid-cold"])
    return {"case": case, "obs": obs, "ids": list(case.ordered_action_ids), "worlds": worlds, "env": env,
            "sampled": sampled}


@pytest.fixture(scope="module")
def clone(mlp, net):
    return c2.ClonePredecessor(mlp, net.encoder)


@pytest.fixture(scope="module")
def batch(research, mlp, focal, clone):
    return c2.evaluate(research, focal["env"], mlp, focal["obs"], focal["ids"], focal["worlds"], predecessor=clone)


def test_B01_forehand_all_pass_and_never_pass_controls(research, mlp, focal, clone):
    case, _t = fixture_case("F01", 1)  # forehand: no predecessor, E = 1
    fore = tobs_of(case)
    ids = list(case.ordered_action_ids)
    worlds = research.sample_worlds(focal["env"], fore, 12, C.c_uint64(7))
    count(probe_ids=["F01-forehand-bid-play-mode"])
    b = c2.evaluate(research, focal["env"], mlp, fore, ids, worlds, predecessor=clone)
    assert b.focal_position == 0 and b.event.all() and all(s == [] for s in b.schedule)
    assert np.array_equal(b.gaps["R"], b.gaps["F"]) and np.array_equal(b.gaps["RC"], b.gaps["F"])
    obs, ids, worlds = focal["obs"], focal["ids"], focal["worlds"][:12]
    all_pass = c2.evaluate(research, focal["env"], mlp, obs, ids, worlds,
                           predecessor=c2.ClonePredecessor(None, 2, rule=c2.always(0)), variants=("F", "R"))
    assert all_pass.event.all() and np.array_equal(all_pass.gaps["R"], all_pass.gaps["F"])
    never = c2.evaluate(research, focal["env"], mlp, obs, ids, worlds,
                        predecessor=c2.ClonePredecessor(None, 2, rule=c2.always(1)))
    assert not never.event.any() and never.hits == 0
    for v in ("R", "RC"):
        assert np.all(never.gaps[v] == 0.0) and np.isfinite(never.gaps[v]).all()
        assert never.conditional_gaps[v] is None  # undefined, not fabricated
    assert all(len(s) == 1 for s in never.schedule)  # stopped at the forehand's RAMI


def test_B02_predecessor_bids_are_focal_independent_and_match_the_engine_observation(research, mlp, focal, clone):
    """Each predecessor's input is its own masked observation; the engine builds the same one."""
    from tuppi_engine import apply_match_action, match_observation_for

    import tuppi_ai.native as nat
    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import card, deck_digest, make_truth, nolo_first, replay

    obs, worlds = focal["obs"], focal["worlds"]
    a = c2.evaluate(research, focal["env"], mlp, obs, focal["ids"], worlds, predecessor=clone, variants=("F", "R"))
    b = c2.evaluate(research, focal["env"], mlp, obs, list(reversed(focal["ids"]))[:3], worlds, predecessor=clone,
                    variants=("R",))
    assert np.array_equal(a.event, b.event) and a.schedule == b.schedule
    seats = c2.predecessor_seats(obs.dealer, obs.n_shows)
    engine_decks = []
    for w in worlds[:3]:
        hands = tuple(tuple(card(c) for c in range(52) if w.hand[s] >> c & 1) for s in range(4))
        engine_decks.append(deck_digest(hands))
        state = replay(make_truth("c2", hands, [], score=(obs.score[0], obs.score[1]), dealer=obs.dealer), 0)
        for pos, seat in enumerate(seats):
            eo = match_observation_for(state, seat)
            native_obs = c2.precommit_observation(w, seat, pos)
            engine_tc = obs_from_player_observation(eo)
            assert bytes(engine_tc) == bytes(native_obs), (pos, seat)
            assert eo.bids_locked == pos and eo.show_actions == ()
            got = CloneGreedyAgent(seat).choose_action(eo)
            from tuppi_ai.bridge import action_id
            assert action_id(got) == clone.bid(native_obs)
            state = apply_match_action(state, eo.legal_actions[nolo_first(eo)])
    count(runner_deal_ids=engine_decks)


def test_B03_out_of_event_rows_are_zero_but_stay_in_the_denominator(batch):
    W = len(batch.event)
    assert 0 < batch.hits < W, f"need both outcomes in the batch, got {batch.hits}/{W}"
    assert not batch.event[-1]  # the constructed alternative layout: the forehand clone bids RAMI
    d_f = batch.y["F"] - batch.y["F"][:, [batch.ref_index]]
    assert np.allclose(batch.gaps["R"], d_f[batch.event].sum(axis=0) / W)
    assert np.allclose(batch.conditional_gaps["R"], d_f[batch.event].mean(axis=0))
    assert np.allclose(batch.gaps["R"], batch.conditional_gaps["R"] * batch.reach_frequency)
    assert all(batch.schedule[i][-1][1] >= 104 for i in np.nonzero(~batch.event)[0])  # stopped at a RAMI


def test_B04_reconstructed_prefix_cards_come_from_the_predecessor_hand_and_obey_the_tiers(batch, focal):
    import tuppi_ai.native as nat

    for w, calls, hit in zip(focal["worlds"], batch.schedule, batch.event):
        if not hit:
            continue
        rc = c2.with_chosen_shows(w, calls)
        for i, (seat, bid) in enumerate(calls):
            cardi = bid - 52
            assert rc.show_seat[i] == seat and rc.show_contract[i] == 0
            assert w.hand[seat] >> cardi & 1
            assert nat.lib.tc_valid_show_cards(w.hand[seat], 0) >> cardi & 1
            assert rc.show_verbal[i] == nat.lib.tc_verbal_required(cardi, 0)
        assert bytes(rc.hand) == bytes(w.hand)


def test_B05_joint_layouts_differ_from_a_product_of_marginals():
    toy = c2.joint_vs_product_toy()
    from fractions import Fraction
    assert toy["joint"] == Fraction(1, 15) and toy["product_of_marginals"] == Fraction(4, 25) and toy["differ"]


def test_B06_ablations_separate_reach_weighting_from_card_selection(batch, focal):
    import tuppi_ai.native as nat

    # F and R share every value; they differ only by the 1(E) weights
    d_f = batch.y["F"] - batch.y["F"][:, [batch.ref_index]]
    assert np.allclose(batch.gaps["F"], d_f.mean(axis=0))
    # RC changes only the shown cards: hands identical, and unreached rows are identical to F
    assert np.array_equal(batch.y["RC"][~batch.event], batch.y["F"][~batch.event])
    changed = [i for i, (w, c) in enumerate(zip(focal["worlds"], batch.schedule)) if batch.event[i]
               and any(w.show_card[j] != b - 52 for j, (_s, b) in enumerate(c))]
    assert changed, "the clone chose the sampler's card everywhere; RC would be indistinguishable from R"
    assert batch.work["F"]["first_actions"] == batch.work["RC"]["first_actions"]  # one common target


def test_B07_clone_predecessors_are_stateless_and_the_reached_schedule_is_recorded(research, mlp, focal, clone):
    first = [clone.bid(c2.precommit_observation(w, s, p)) for w in focal["worlds"][:4]
             for p, s in enumerate(c2.predecessor_seats(focal["obs"].dealer, focal["obs"].n_shows))]
    again = [clone.bid(c2.precommit_observation(w, s, p)) for w in focal["worlds"][:4]
             for p, s in enumerate(c2.predecessor_seats(focal["obs"].dealer, focal["obs"].n_shows))]
    assert first == again  # repeated diagnostic queries change nothing
    b = c2.evaluate(research, focal["env"], mlp, focal["obs"], focal["ids"], focal["worlds"][:6], predecessor=clone,
                    variants=("R",))
    for calls, hit in zip(b.schedule, b.event):
        seats = [s for s, _b in calls]
        assert seats == c2.predecessor_seats(focal["obs"].dealer, focal["obs"].n_shows)[:len(seats)]
        assert hit == (len(seats) == focal["obs"].n_shows and all(x < 104 for _s, x in calls))


def test_B08_conditional_and_unconditional_units_are_distinct_and_denominators_stored(batch):
    s = batch.summary()
    assert s["W"] == len(batch.event) and s["hits"] == batch.hits
    assert s["reach_frequency"] == pytest.approx(batch.hits / s["W"])
    assert "per blind commitment" in s["units"]["unconditional"] and "NOT comparable" in s["units"]["conditional"]
    j = next(i for i in range(len(batch.ids)) if i != batch.ref_index and batch.conditional_gaps["R"][i] != 0)
    assert s["unconditional_gap_per_commitment"]["R"][j] != s["conditional_gap_when_reached"]["R"][j]
