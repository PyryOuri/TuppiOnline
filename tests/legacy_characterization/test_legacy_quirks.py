from __future__ import annotations

import pytest


def _public_state(legacy):
    return legacy.PublicState(
        contract=legacy.Contract.NOLO,
        declarer=None,
        dealer=0,
        leader=0,
        trick_index=0,
        current_trick=[],
        played_cards=[],
        tricks_won_by_team=(0, 0),
        tricks_won_by_player=(0, 0, 0, 0),
        revealed_show_cards={},
        score_state=legacy.ScoreState(),
    )


def test_legacy_quirk_explicit_empty_show_ban_restores_default(legacy) -> None:
    """Characterizes defective ``value or default`` behavior; not a rules test."""

    game = legacy.TuppiGame(
        rollouts=0, show_banned_ranks=set(), analysis_level="none"
    )
    assert game.show_banned_ranks == {2, 11, 12, 13}


def test_legacy_quirk_public_state_aliases_mutable_score_state(legacy) -> None:
    """Characterizes a mutation hazard in the legacy observation boundary."""

    score = legacy.ScoreState()
    public = _public_state(legacy)
    public.score_state = score
    assert public.score_state is score
    public.score_state.scores = (20, 0)
    assert score.scores == (20, 0)


@pytest.mark.parametrize("rollouts", [0, -1])
def test_legacy_quirk_nonpositive_rollouts_use_heuristic_fallback(
    legacy, monkeypatch, rollouts
) -> None:
    """Pins a silent fallback that the archival runner intentionally rejects."""

    sentinel = legacy.make_card(2, 0)

    def fake_heuristic(hand, pub, seat):
        return sentinel

    def forbidden_estimate(*args, **kwargs):
        raise AssertionError("PIMC estimate must not run for non-positive rollouts")

    monkeypatch.setattr(legacy.HeuristicPolicy, "choose_play_card", fake_heuristic)
    ai = legacy.MonteCarloAI(0, "P0", rollouts=rollouts)
    ai.set_hand([sentinel, legacy.make_card(3, 1)])
    monkeypatch.setattr(ai, "_estimate_value", forbidden_estimate)
    assert ai.choose_play_card(_public_state(legacy), set()) == sentinel

