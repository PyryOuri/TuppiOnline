"""C2.02 contract tests (B02, B06, B07, B08) for SEARCHING predecessors modelled by isolated forks.

W8 predecessor searches keep the workload tiny: the tests check the fork,
cache and schedule mechanics, not bidding strength.
"""

from __future__ import annotations

import ctypes as C

import numpy as np
import pytest

from tuppi_ai.research import c2_blind_bids as c2
from tuppi_ai.research.ledger import count
from tuppi_ai.research.lifecycle import AgentSpec, RecordingAgent, native_fork, snapshot
from tuppi_ai.research.testing import fixture_case, tobs_of


@pytest.fixture(scope="module")
def setup(research, nat, table, mlp):
    case, _t = fixture_case("F01", 0)
    obs = tobs_of(case)
    env = nat.Env(128 * 26, 0, table, single_deal=True, encoder=2)
    worlds = research.sample_worlds(env, obs, 2, C.c_uint64(77))
    seats = c2.predecessor_seats(obs.dealer, obs.n_shows)
    live = {s: RecordingAgent(AgentSpec.of("best", s, worlds=8, seed=5)) for s in seats}
    before = {s: snapshot(live[s].agent, research) for s in seats}
    preds = {s: c2.SearchPredecessor(live[s], research, "best:W8:seed5", obs.dealer, (obs.score[0], obs.score[1]))
             for s in seats}
    batch = c2.evaluate_with_search_predecessors(research, env, mlp, obs, list(case.ordered_action_ids), worlds, preds)
    count(probe_ids=[f"C2.02-w{wi}-seat{s}" for wi, calls in enumerate(batch.schedule) for s, _b in calls])
    return {"obs": obs, "ids": list(case.ordered_action_ids), "env": env, "worlds": worlds, "live": live,
            "before": before, "preds": preds, "batch": batch, "seats": seats}


def test_B07_modelled_queries_never_touch_the_live_predecessors(setup, research):
    for s in setup["seats"]:
        assert snapshot(setup["live"][s].agent, research) == setup["before"][s]
        assert setup["live"][s].history == []  # the live controller was never asked
    b = setup["batch"]
    assert b.work["predecessor_queries"] == sum(len(c) for c in b.schedule)
    for calls in b.schedule:  # the modelled schedule stops at the first RAMI, in bidding order
        seats = [s for s, _bid in calls]
        assert seats == setup["seats"][:len(seats)]


def test_B07_a_cache_hit_reproduces_the_call_and_its_state_advancement(setup, research):
    seat = setup["seats"][0]
    pred = setup["preds"][seat]
    searches = pred.searches
    bid = pred.bid_for(setup["worlds"][0], seat, 0)
    assert pred.searches == searches  # cache hit
    assert bid == setup["batch"].schedule[0][0][1]
    obs = pred._engine_observation(setup["worlds"][0], seat, 0)
    fork = native_fork(setup["live"][seat], research)
    from tuppi_ai.bridge import action_id
    assert action_id(fork.choose_action(obs)) == bid
    entry = next(v for v in pred.cache.values() if v["bid"] == bid)
    assert snapshot(fork.agent, research) == entry["post_call_snapshot"]  # the advancement a hit stands for
    assert entry["post_call_snapshot"] != setup["before"][seat]           # a real search did advance it


def test_B02_predecessor_bids_are_computed_once_and_reused_for_every_focal_action(setup, research, mlp):
    before = {s: p.searches for s, p in setup["preds"].items()}
    again = c2.evaluate_with_search_predecessors(research, setup["env"], mlp, setup["obs"], setup["ids"][::-1][:3],
                                                 setup["worlds"], setup["preds"])
    assert np.array_equal(again.event, setup["batch"].event) and again.schedule == setup["batch"].schedule
    assert {s: p.searches for s, p in setup["preds"].items()} == before  # every call was a cache hit


def test_B06_B08_ablations_and_units_with_searching_predecessors(setup):
    b = setup["batch"]
    d_f = b.y["F"] - b.y["F"][:, [b.ref_index]]
    assert np.allclose(b.gaps["R"], (d_f * b.event[:, None]).sum(axis=0) / len(b.event))
    assert np.array_equal(b.y["RC"][~b.event], b.y["F"][~b.event])
    s = b.summary()
    assert s["W"] == 2 and s["hits"] == b.hits and "NOT comparable" in s["units"]["conditional"]
    for w, calls, hit in zip(setup["worlds"], b.schedule, b.event):
        if hit:
            rc = c2.with_chosen_shows(w, calls)
            for i, (seat, bid) in enumerate(calls):
                assert w.hand[seat] >> (bid - 52) & 1  # the searched card is the predecessor's own
