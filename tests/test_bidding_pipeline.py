"""The parked bidding-explanation pipeline (docs/BIDDING_EXPLANATION_PLAN.md).

Features, the readable models, the dataset builder, the rule bidder and the
game database's reproducibility, at toy size so the pipeline stays runnable.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tuppi_ai import bid_models as bm  # noqa: E402
from tuppi_ai.bid_features import FEATURES, bid_features  # noqa: E402

DECK = [r + s for s in "HDCS" for r in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]]


def test_features_of_a_known_hand():
    hand = ["AH", "KH", "QH", "5H", "AD", "2D", "3C", "4C", "7C", "9C", "JS", "10S", "2S"]
    f = bid_features(hand, position=1, own_score=12, opp_score=40)
    assert set(f) == set(FEATURES)
    assert (f["hcp"], f["aces"], f["kings"], f["controls"]) == (14, 2, 1, 5)
    assert f["quick_tricks"] == 3.0 and f["stoppers"] == 2 and f["low_cards"] == 4
    assert (f["longest"], f["shortest"], f["doubletons"]) == (4, 2, 1)
    assert f["red_silent"] == 1.0 and f["black_silent"] == 1.0
    assert f["score_diff"] == -28 and f["opp_to_target"] == 12
    assert f["old_rami_score"] == pytest.approx(15.75)


def _synthetic(n=3000, seed=1):
    rng = random.Random(seed)
    deck = list(DECK)
    rows, gap = [], []
    for i in range(n):
        rng.shuffle(deck)
        f = bid_features(deck[:13], position=i % 4, own_score=0, opp_score=0)
        rows.append(f)
        gap.append(0.004 * (f["hcp"] - 0.5 * f["low_cards"] - (12 if i % 4 == 0 else 13)) + rng.gauss(0, 0.002))
    gap = np.array(gap)
    return rows, gap, (gap > 0).astype(float)


def test_point_count_recovers_a_known_rule_and_round_trips(tmp_path):
    rows, gap, y = _synthetic()
    model = bm.PointCount(["hcp", "low_cards", "aces"]).fit(rows, gap, y)
    assert model.weights == {"hcp": 1.0, "low_cards": -0.5, "aces": 0.0}
    assert (model.predict(rows) == (y > 0.5)).mean() > 0.95
    assert "RAMI" in model.explain(rows[0]) or "NOLO" in model.explain(rows[0])
    bm.save(model, tmp_path / "m.json")
    assert (bm.load(tmp_path / "m.json").predict(rows) == model.predict(rows)).all()


def test_tree_and_threshold_fit_and_describe(tmp_path):
    rows, gap, y = _synthetic()
    tree = bm.Tree(depth=2, min_leaf=50).fit(rows, y, ["hcp", "low_cards", "aces"])
    assert (tree.predict(rows) == (y > 0.5)).mean() > 0.9 and "jos" in tree.describe()
    th = bm.Threshold("hcp").fit(rows, y)
    assert set(th.thresholds) == {0, 1, 2, 3} and (th.predict(rows) == (y > 0.5)).mean() > 0.9
    for model in (tree, th):
        bm.save(model, tmp_path / "x.json")
        assert (bm.load(tmp_path / "x.json").predict(rows) == model.predict(rows)).all()


def test_bid_rows_read_values_gap_and_shadow_bids():
    from bid_dataset import bid_rows

    hands = [DECK[i * 13:(i + 1) * 13] for i in range(4)]
    game = {"index": 7, "dealer": 3, "score": [8, 20], "test": True, "hands": hands,
            "decisions": [{"seat": 0, "phase": "SHOWING", "values": {"60": -0.01, "110": 0.02},
                           "action": {"type": "show", "declared_contract": "RAMI"}},
                          {"seat": 1, "phase": "TRICK_PLAY", "values": {"3": 0.0}, "action": {"type": "play"}}],
            "shadow_bids": [{"seat": 2, "position": 2, "values": {"70": 0.01, "120": -0.03},
                             "action": {"type": "show", "declared_contract": "NOLO"}}]}
    rows = list(bid_rows(game))
    assert [(r["seat"], r["position"], r["shadow"], r["bot_rami"]) for r in rows] == [(0, 0, False, True),
                                                                                       (2, 2, True, False)]
    assert rows[0]["gap"] == pytest.approx(0.03) and rows[1]["gap"] == pytest.approx(-0.04)
    assert rows[0]["own_score"] == 8 and rows[1]["own_score"] == 8 and rows[0]["test"]


def test_rule_bidder_bids_the_rules_contract_with_a_legal_show():
    from tuppi_ai import model as qmodel
    from tuppi_ai.best import EQUITY, ROLLOUT
    from tuppi_ai.equity import Equity
    from tuppi_ai.rule_bidder import RuleBidder
    from tuppi_ai.search import SearchAgent
    from tuppi_engine import ExplicitDeal, begin_explicit_deal, create_match, match_observation_for
    from tuppi_rules import Contract, MatchScore, RulesetId, card_from_code

    net = qmodel.load(ROLLOUT, "cpu")
    table = Equity.load(EQUITY).table
    hands = tuple(tuple(card_from_code(c) for c in DECK[i * 13:(i + 1) * 13]) for i in range(4))
    state = begin_explicit_deal(create_match(initial_score=MatchScore(0, 0), initial_dealer=3, match_ref="rb",
                                             ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=3, hands=hands))
    seat = state.current_actor
    obs = match_observation_for(state, seat)
    for threshold, contract in ((-100.0, Contract.RAMI), (100.0, Contract.NOLO)):
        rule = bm.Threshold("hcp", {p: threshold for p in range(4)})
        bidder = RuleBidder(SearchAgent(net, table, seat, worlds=8, dd_left=2, search_showing=1), rule)
        action = bidder.choose_action(obs)
        assert action in obs.legal_actions and action.declared_contract is contract
        assert bidder.last_values and all(104 <= k < 156 if contract is Contract.RAMI else 52 <= k < 104
                                          for k in bidder.last_values)


def test_game_database_games_depend_only_on_their_index(tmp_path):
    from gen_game_db import load_games, play_chunk

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    play_chunk((0, 2, "db-test", str(a), 2))
    play_chunk((0, 1, "db-test", str(b), 2))
    play_chunk((1, 1, "db-test", str(b), 2))
    ga, gb = list(load_games(a)), list(load_games(b))
    assert [g["decisions"] for g in ga] == [g["decisions"] for g in gb]
    assert [g["shadow_bids"] for g in ga] == [g["shadow_bids"] for g in gb]
    game = ga[0]
    bids = [d for d in game["decisions"] if d["phase"] == "SHOWING"] + game["shadow_bids"]
    assert len({d["seat"] for d in bids}) == 4  # every seat's bid, real or shadow
    assert play_chunk((0, 2, "db-test", str(a), 2))["skipped"]  # resumable
