"""best.RAMI_MARGIN: off by default (bidding unchanged), wired into the live factory when set."""

import tuppi_ai.best as best


def test_rami_margin_is_off_by_default():
    assert best.RAMI_MARGIN == 0.0
    agent = best.best_agents([0], worlds=128)[0]
    assert agent.rami_bonus == 0.0


def test_rami_margin_reaches_the_live_agents(monkeypatch):
    monkeypatch.setattr(best, "RAMI_MARGIN", 0.02)
    agent = best.best_agents([1], worlds=1024)[1]
    assert agent.rami_bonus == -0.02
    assert best.best_agents([1], worlds=128, team_rollout=False)[1].rami_bonus == 0.0  # research B0 untouched


def test_keep_show_is_deployed_and_reaches_the_agents(monkeypatch):
    assert best.KEEP_SHOW == 0.03  # deployed 2026-10-02 (owner's decision)
    assert best.best_agents([0], worlds=128)[0].keep_show == 0.03
    monkeypatch.setattr(best, "KEEP_SHOW", None)
    assert best.best_agents([0], worlds=128)[0].keep_show is None
    assert best.best_agents([0], worlds=128, team_rollout=False)[0].keep_show is None


def test_review_bid_threshold_follows_keep_show(monkeypatch):
    from tuppi_ai.review import KIND_BID, DealReviewer
    r = DealReviewer.best(worlds=16, confirm_worlds=32)
    monkeypatch.setattr(best, "KEEP_SHOW", None)
    assert r._min_cost(KIND_BID) == r.min_cost
    monkeypatch.setattr(best, "KEEP_SHOW", 0.03)
    assert r._min_cost(KIND_BID) == 0.03 and r._min_cost("lead") == r.min_cost


def test_live_opponent_model_is_the_strong_policy():
    from pathlib import Path
    assert Path(best.OPPONENT_ROLLOUT).name == "vrpo1_actor_0504.pt"
    live = best.best_agents([1], worlds=128)[1]
    b0 = best.best_agents([1], worlds=128, team_rollout=False)[1]
    import torch
    live_w = next(iter(live.net.state_dict().values()))
    b0_w = next(iter(b0.net.state_dict().values()))
    assert not torch.equal(live_w, b0_w)  # B0 keeps the clone
