"""R01-R06 v3 runner and C0.07 statistics (R04, R05, R06, V11 endpoints)."""

from __future__ import annotations

import math
import random
import time

import numpy as np
import pytest

from tuppi_ai.research import statistics as S
from tuppi_ai.research.ledger import count
from tuppi_ai.research.runner_v3 import (PolicyFamily, draw_score, duplicate_bundle, match_leg, match_pair,
                                         new_match, play_deal, score_weights, transition_row, _equity)


def _agents(rules):
    """Clone players with scripted rules on the F03 constructed deck."""
    from tuppi_ai.research.clone_policy import CloneGreedyAgent
    from tuppi_ai.research.fixtures import RuleAgent

    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    return {s: RuleAgent(s, clones[s], **rules.get(s, {})) for s in range(4)}


def _row(out, candidate_team=0):
    return transition_row(out, cluster_id="c", arm="a", rotation=0, assignment=0, source_score=(0, 0), dealer=0,
                          policy_ids=[], snapshot_ids=[], lifecycle="test", candidate_team=candidate_team,
                          equity=_equity())


def _index(pred):
    return lambda ob: next(i for i, a in enumerate(ob.legal_actions) if pred(a))


@pytest.fixture(scope="module")
def decks():
    from tuppi_ai.research.fixtures import _card_from_code, deck_digest, f03_hands, load_fixture

    _p, _c, t02 = load_fixture("F02")
    nolo = tuple(tuple(_card_from_code(c) for c in h) for h in t02.initial_hands)
    count(runner_deal_ids=[deck_digest(nolo), deck_digest(f03_hands())])
    return {"nolo": nolo, "sooli": f03_hands()}


def test_R01_runner_handles_every_v3_deal_path(decks):
    from tuppi_ai.research.fixtures import nolo_first, rami_first

    nolo_all = {s: {"show": nolo_first} for s in range(4)}
    accept, decline = _index(lambda a: a.play_sooli), _index(lambda a: not a.play_sooli)
    paths = {
        "nolo": (decks["nolo"], nolo_all),
        "rami_after_declines": (decks["sooli"], {1: {"show": rami_first}, 2: {"offer": decline}, 0: {"offer": decline}}),
        "first_accepts": (decks["sooli"], {1: {"show": rami_first}, 2: {"offer": accept}}),
        "second_accepts": (decks["sooli"], {1: {"show": rami_first}, 2: {"offer": decline}, 0: {"offer": accept}}),
        # seat 2 keeps its K of hearts, the declarer leads a heart, the soolaaja plays it: immediate failure
        "immediate_solo_failure": (decks["sooli"], {
            1: {"show": rami_first, "play": _index(lambda a: a.card.suit.value == "hearts")},
            2: {"offer": accept, "give": _index(lambda a: a.card.suit.value == "clubs"),
                "play": lambda ob: max(range(len(ob.legal_actions)),
                                       key=lambda i: (ob.legal_actions[i].card.rank.value % 14))}}),
    }
    rows = {}
    for name, (hands, rules) in paths.items():
        out = play_deal(new_match(), _agents(rules), hands)
        assert not out.failed, (name, out.failure)
        rows[name] = (_row(out), out)
    assert rows["nolo"][0].contract == "NOLO" and rows["nolo"][0].soolaaja is None
    r = rows["rami_after_declines"]
    assert r[0].contract == "RAMI" and r[0].soolaaja is None and sum(r[0].team_tricks) == 13
    assert rows["first_accepts"][0].soolaaja == 2 and rows["first_accepts"][0].terminal_type == "sooli"
    assert rows["second_accepts"][0].soolaaja == 0
    fail = rows["immediate_solo_failure"]
    res = fail[1].state.completed_deals[-1].public_result
    assert fail[0].soolaaja == 2 and fail[0].winner_team == 1 and fail[0].points == 24
    assert len(fail[1].decisions) == 1 + 1 + 2 + 3, fail[1].decisions  # show, 1 answer, give+return, 3 plays
    for name, (row, out) in rows.items():
        assert row.next_score is not None and row.candidate_value is not None and not row.failed
        phases = {p for _s, p, _ms in out.decisions}
        if row.soolaaja is not None:
            assert {"SOOLI_OFFER", "SOOLI_GIVE", "SOOLI_RETURN", "SOOLI_PLAY"} <= phases
            dead = (row.soolaaja + 2) % 4
            assert all(not (s == dead and p == "SOOLI_PLAY") for s, p, _ms in out.decisions)


def test_R02_eight_games_share_one_cluster_and_search_teams_are_accepted(research):
    fam_a = PolicyFamily.of("random-a", "random_legal", seeded=True)
    fam_b = PolicyFamily.of("clone", "clone")
    b = duplicate_bundle(0, fam_a, fam_b, namespace="contract-R02")
    from tuppi_ai.research.fixtures import deck_digest
    from tuppi_ai.research.streams import shuffled_deck
    count(runner_deal_ids=[deck_digest(shuffled_deck("deal", "contract-R02", 0))])
    assert len(b["rows"]) == 8 and len({r["cluster_id"] for r in b["rows"]}) == 1
    assert sorted((r["rotation"], r["assignment"]) for r in b["rows"]) == [(r, a) for r in range(4) for a in (0, 1)]
    assert all(r["lifecycle"] == "independent_cold_bundle" for r in b["rows"])
    cand_ids = {tuple(r["policy_ids"][s] for s in range(4) if s % 2 == r["candidate_team"]) for r in b["rows"]}
    assert all(i.startswith("random_legal") for ids in cand_ids for i in ids)
    # searching agents on BOTH teams: constructed by the runner and driven through legal transitions
    best = PolicyFamily.of("best-w16", "best", seeded=True, worlds=16)
    agents = {s: best.spec(s, 7).construct() for s in range(4)}
    from tuppi_ai.search import SearchAgent
    assert all(isinstance(a, SearchAgent) for a in agents.values())
    out = play_deal(new_match(), agents, shuffled_deck("deal", "contract-R02", 0), max_actions=2)
    count(probe_ids=["R02-best-both-teams#0", "R02-best-both-teams#1"])
    assert [s for s, _p, _ms in out.decisions] == [1, 2] and out.failed and "incomplete by design" in out.failure
    assert _row(out).failed and _row(out).candidate_value is None


def test_R03_match_decks_dealer_rotation_and_complementary_seeds():
    fam_a = PolicyFamily.of("random-a", "random_legal", seeded=True)
    fam_b = PolicyFamily.of("first", "first_legal")
    pair = match_pair(3, fam_a, fam_b, namespace="contract-R03", cap=3)
    from tuppi_ai.research.fixtures import deck_digest
    from tuppi_ai.research.streams import shuffled_deck
    count(runner_deal_ids=[deck_digest(shuffled_deck("deal", "contract-R03", "pair", 3, "deal", i)) for i in range(3)])
    a, b = pair["legs"]
    assert (a["candidate_team"], b["candidate_team"]) == (0, 1)
    for leg in (a, b):
        dealers = [r["dealer"] for r in leg["rows"]]
        assert dealers == [i % 4 for i in range(len(dealers))]
        for prev, nxt in zip(leg["rows"], leg["rows"][1:]):
            assert tuple(nxt["source_score"]) == tuple(prev["next_score"])
        assert leg["rows"][0]["source_score"] == (0, 0)
    assert pair["deck_stream"] == "deal|contract-R03|pair|3|deal|<i>"
    seed = pair["seat_seed_base"]
    for leg in (a, b):  # the pair's seat-seed map; only team membership swaps between legs
        want = [(fam_a if s % 2 == leg["candidate_team"] else fam_b).spec(s, seed).spec_id for s in range(4)]
        assert all(tuple(r["policy_ids"]) == tuple(want) for r in leg["rows"])
    assert a["rows"][0]["policy_ids"][0].startswith("random_legal") and b["rows"][0]["policy_ids"][0].startswith("first_legal")


class _Boom:
    handles_sooli = True

    def __init__(self, after):
        self.after, self.calls = after, 0

    def choose_action(self, obs):
        self.calls += 1
        if self.calls > self.after:
            raise RuntimeError("deliberate failure")
        return obs.legal_actions[0]


class _Slow:
    handles_sooli = True

    def choose_action(self, obs):
        time.sleep(0.02)
        return obs.legal_actions[0]


def test_R04_failures_and_time_caps_stay_in_the_ledger_and_caps_are_unresolved(decks):
    from tuppi_engine import FirstLegalActionAgent

    agents = {s: FirstLegalActionAgent() for s in range(4)}
    agents[2] = _Boom(after=3)
    out = play_deal(new_match(), agents, decks["nolo"])
    row = _row(out)
    assert out.failed and row.failed and "deliberate failure" in row.failure and row.candidate_value is None
    slow = {s: FirstLegalActionAgent() for s in range(4)}
    slow[3] = _Slow()
    out = play_deal(new_match(), slow, decks["nolo"], deadline_ms=5)
    assert not out.failed and out.over_deadline >= 13 and _row(out).fallbacks == out.over_deadline
    fam = PolicyFamily.of("random", "random_legal", seeded=True)
    leg = match_leg(0, fam, fam, 0, namespace="contract-A11", cap=1)
    assert leg["outcome"] == "unresolved" and leg["deals"] == 1
    summary = S.match_summary([{"legs": [leg, dict(leg, outcome="win")]}])
    assert summary["unresolved_legs"] == 1
    assert summary["lower_bound"]["mean"] == 0.5 and summary["upper_bound"]["mean"] == 1.0
    assert summary["decided_pairs"]["n"] == 0
    bundles = S.bundle_summary([{"index": 0, "value": 0.1, "resolved": True},
                                {"index": 1, "value": None, "resolved": False}])
    assert bundles["unresolved_bundles"] == [1] and bundles["n"] == 1


def test_R04_match_bounds_are_formed_per_pair_before_averaging():
    legs = lambda *o: {"legs": [{"outcome": x} for x in o]}  # noqa: E731
    pairs = [legs("win", "loss"), legs("win", "unresolved"), legs("failed", "loss"), legs("win", "win")]
    s = S.match_summary(pairs)
    assert s["lower_bound"]["mean"] == pytest.approx((0.5 + 0.5 + 0.0 + 1.0) / 4)
    assert s["upper_bound"]["mean"] == pytest.approx((0.5 + 1.0 + 0.5 + 1.0) / 4)
    assert s["unresolved_legs"] == 1 and s["failed_legs"] == 1 and s["decided_pairs"]["n"] == 2
    assert "descriptive only" in s["descriptive_midpoint_sensitivity"]["label"]
    assert not s["conclusion_robust_to_censoring"]


def test_R05_score_laws_keep_their_weights_and_the_legacy_law_is_not_uniform():
    from tuppi_ai.evaluate import _score_for

    legacy, uni = score_weights("legacy_uniform"), score_weights("uniform25")
    assert len(legacy) == len(uni) == 25
    assert legacy[(0, 0)] == pytest.approx(1 / 13) and legacy[(4, 0)] == pytest.approx(1 / 26)
    assert all(v == pytest.approx(1 / 25) for v in uni.values())
    assert sum(legacy.values()) == pytest.approx(1) and legacy != uni
    for i in range(60):  # the legacy law is evaluate._score_for, verbatim
        assert draw_score("legacy_uniform", "ns", i) == _score_for(i, "uniform", "ns")
    draws = [draw_score("uniform25", "ns", i) for i in range(2000)]
    assert abs(draws.count((0, 0)) / 2000 - 1 / 25) < 0.02


def test_R06_identical_policies_are_analysed_statistically_not_forced():
    fam = PolicyFamily.of("same", "random_legal", seeded=True)
    bundles = [duplicate_bundle(i, fam, fam, namespace="contract-R06") for i in range(2)]
    from tuppi_ai.research.fixtures import deck_digest
    from tuppi_ai.research.streams import shuffled_deck
    count(runner_deal_ids=[deck_digest(shuffled_deck("deal", "contract-R06", i)) for i in range(2)])
    summary = S.bundle_summary(bundles)
    values = [r["candidate_value"] for b in bundles for r in b["rows"]]
    assert any(v != 0 for v in values), "identical-policy games were forced to zero"
    assert summary["n"] == 2 and summary["sd"] is not None and summary["ci95"] is not None


def test_statistics_mean_ci_bootstrap_power_latency():
    m = S.mean_ci([1.0, 2.0, 3.0, 4.0])
    assert m["mean"] == 2.5 and m["sd"] == pytest.approx(math.sqrt(5 / 3))
    assert m["ci95"][0] == pytest.approx(2.5 - S.Z95 * m["sd"] / 2)
    rng = np.random.default_rng(0)
    clusters = {k: [float(rng.normal(k % 3, 0.1)) for _ in range(8)] for k in range(30)}
    seen = []

    def stat(groups):
        seen.append(len(groups))
        return float(np.mean([np.mean(g) for g in groups]))

    boot = S.cluster_bootstrap(clusters, stat, 50, rng)
    assert set(seen) == {30} and boot["ci95"][0] < boot["point"] < boot["ci95"][1]
    assert S.power_n(0.05, 0.001) == pytest.approx(7.85 * 2500)
    assert S.precision_n(1.0, 1.96) == pytest.approx(1.0, rel=1e-3)
    lat = S.latency_summary([1, 2, 3, 100])
    assert lat["n"] == 4 and lat["tail_unstable"] and lat["max_ms"] == 100


def test_V11_reference_noise_cancels_in_differences_not_ratios():
    rng = np.random.default_rng(42)
    cases, R = 4000, 2
    truth = rng.normal(size=cases)
    cand = truth + rng.normal(scale=0.5, size=cases)      # true MSE 0.25
    base = truth + rng.normal(scale=1.0, size=cases)      # true MSE 1.00; true ratio 0.25
    ref = truth[:, None] + rng.normal(scale=1.0, size=(cases, R))  # reference variance 0.5
    e = S.mse_endpoints(cand, base, ref)
    assert e["mean_reference_variance"] == pytest.approx(0.5, rel=0.08)
    assert e["mse_difference"] == pytest.approx(0.25 - 1.0, abs=0.08)
    assert e["corrected_ratio"] == pytest.approx(0.25, abs=0.06)
    assert e["raw_ratio"] > 0.4                           # biased toward 1 by reference noise
    with pytest.raises(ValueError):
        S.mse_endpoints(cand, base, ref[:, :1])            # one replicate cannot estimate its own noise


def test_R04_unresolved_bundles_are_bounded_not_deleted():
    rows = lambda *v: [{"candidate_value": x} for x in v]  # noqa: E731
    bundles = [{"index": 0, "value": 0.1, "resolved": True, "rows": rows(0.1, 0.1)},
               {"index": 1, "value": None, "resolved": False, "rows": rows(0.2, None)}]
    s = S.bundle_summary(bundles)
    assert s["n"] == 1 and s["unresolved_bundles"] == [1] and "descriptive" in s["resolved_only_label"]
    assert s["lower_bound"]["mean"] == pytest.approx((0.1 + (0.2 - 1.0) / 2) / 2)
    assert s["upper_bound"]["mean"] == pytest.approx((0.1 + (0.2 + 1.0) / 2) / 2)
    with pytest.raises(ValueError):
        S.match_summary([{"pair": 0, "legs": []}])


def test_V11_mse_is_averaged_within_case_then_deal_and_bootstrapped_by_deal():
    rng = np.random.default_rng(3)
    # deal A: one case with 1 action; deal B: one case with 9 actions -> deals weigh equally, not rows
    deal = np.array(["A"] + ["B"] * 9)
    case = np.array(["a0"] + ["b0"] * 9)
    truth = np.zeros(10)
    cand = np.where(deal == "A", 2.0, 0.0)          # error 2 in deal A only
    base = np.zeros(10)
    ref = truth[:, None] + np.zeros((10, 2))         # noiseless reference
    e = S.mse_endpoints(cand, base, ref, case, deal)
    assert e["raw_mse_candidate"] == pytest.approx(2.0)   # (4 + 0) / 2 deals, not 4/10 rows
    assert e["deals"] == 2 and "within case" in e["averaging"]
    many = 300
    truth = rng.normal(size=many)
    deals = np.repeat(np.arange(60), 5)
    e2 = S.mse_endpoints(truth + rng.normal(scale=0.5, size=many), truth + rng.normal(size=many),
                         truth[:, None] + rng.normal(scale=1.0, size=(many, 3)), np.arange(many), deals,
                         reps=200, rng=rng)
    lo, hi = e2["mse_difference_ci95"]
    assert lo < e2["mse_difference"] < hi and e2["bootstrap"]["unit"] == "base deal"
    assert e2["corrected_ratio_ci95"] is not None
