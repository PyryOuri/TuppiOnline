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
