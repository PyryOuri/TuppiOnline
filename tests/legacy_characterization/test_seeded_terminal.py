from __future__ import annotations

import contextlib
import io


def test_fixed_seeded_legacy_terminal_state_is_characterized(legacy) -> None:
    """Pins one historical runtime result; it is not a normative rules fixture."""

    original_random_state = legacy.random.getstate()
    try:
        game = legacy.TuppiGame(
            human_seat=0,
            rollouts=1,
            rising_scoring=True,
            seed=1729,
            show_banned_ranks={2, 11, 12, 13},
            analysis_level="none",
        )
        game.players = [
            legacy.MonteCarloAI(seat, legacy.dealer_name(seat), rollouts=1)
            for seat in range(4)
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            game.play_one_hand()
        assert game.score_state.scores == (0, 4)
        assert game.score_state.totals == (0, 4)
        assert game.score_state.rising_team == 1
        assert all(player.hand == [] for player in game.players)
    finally:
        legacy.random.setstate(original_random_state)
