from __future__ import annotations

import builtins
import contextlib
import io
import socket
import sys

from tuppi_legacy.adapter import (
    RunnerConfig,
    _LegacyRandomRouter,
    execute_legacy_deals,
)
from tuppi_legacy.canonical import canonical_json_line
from tuppi_legacy.constants import ADAPTER_VERSION, ARTIFACT_ID, EMULATOR_SHA256
from tuppi_legacy.deals import generate_deals
from tuppi_legacy.legacy_loader import load_legacy_module


def test_same_explicit_deal_config_and_rng_seed_are_byte_identical(
    example_deal, runner_config
) -> None:
    first = canonical_json_line(execute_legacy_deals(runner_config, [example_deal])[0])
    second = canonical_json_line(execute_legacy_deals(runner_config, [example_deal])[0])
    assert first.encode("utf-8") == second.encode("utf-8")


def test_same_deal_seed_repeats_fully_materialized_deals() -> None:
    first = generate_deals(count=2, seed=88, initial_dealer=1)
    second = generate_deals(count=2, seed=88, initial_dealer=1)
    assert [deal.to_dict() for deal in first] == [deal.to_dict() for deal in second]
    assert [deal.deal_id for deal in first] == [deal.deal_id for deal in second]


def test_structured_result_is_complete_and_internally_consistent(
    example_deal, runner_config
) -> None:
    result = execute_legacy_deals(runner_config, [example_deal])[0]
    legacy = load_legacy_module()

    assert result["artifact_id"] == ARTIFACT_ID
    assert result["adapter_version"] == ADAPTER_VERSION
    assert result["ruleset_id"] == ARTIFACT_ID
    assert result["emulator_sha256"] == EMULATOR_SHA256
    assert result["deal_id"] == result["initial_deal"]["deal_id"]
    assert result["initial_deal"] == example_deal.to_dict()
    assert result["execution"] == {
        "status": "ok",
        "legacy_stdout_parsed": False,
        "stdin_required": False,
        "gui_required": False,
        "network_required": False,
    }
    assert len(result["agents"]) == 4
    assert len(result["card_play_transcript"]) == 52
    assert len(result["tricks"]) == 13
    assert all(
        not action["engine_fallback_applied"]
        for action in result["card_play_transcript"]
    )

    played_cards = [action["card"] for action in result["card_play_transcript"]]
    assert sorted(played_cards) == list(range(52))

    remaining = [list(hand) for hand in example_deal.hands]
    for trick in result["tricks"]:
        lead_suit = legacy.card_suit(trick["plays"][0]["card"])
        pairs = []
        for action in trick["plays"]:
            seat = action["seat"]
            card = action["card"]
            legal = legacy.legal_moves(remaining[seat], lead_suit)
            assert card in legal
            remaining[seat].remove(card)
            pairs.append((seat, card))
        assert trick["winner_seat"] == legacy.trick_winner(pairs)
    assert remaining == [[], [], [], []]

    terminal = result["terminal"]
    assert sum(terminal["tricks_by_player"]) == 13
    assert sum(terminal["tricks_by_team"]) == 13
    assert terminal["tricks_by_team"] == [4, 9]
    assert result["contract"] == "NOLO"
    assert result["declarer"] is None
    assert terminal["legacy_score_after"]["scores"] == [12, 0]
    expected_winner, expected_points = legacy.score_deal(
        result["contract"],
        result["declarer"],
        terminal["tricks_by_team"][0],
        terminal["tricks_by_team"][1],
    )
    assert (terminal["deal_winner_team"], terminal["deal_points"]) == (
        expected_winner,
        expected_points,
    )


def test_empty_show_ban_is_preserved_and_delivered_to_all_agents(
    monkeypatch, example_deal
) -> None:
    legacy = load_legacy_module()
    observed_bans: list[tuple[int, ...]] = []
    original_choose_show_bid = legacy.HeuristicPolicy.choose_show_bid

    def recording_choose_show_bid(hand, seat, score_state, show_banned_ranks):
        observed_bans.append(tuple(sorted(show_banned_ranks)))
        return original_choose_show_bid(hand, seat, score_state, show_banned_ranks)

    monkeypatch.setattr(
        legacy.HeuristicPolicy,
        "choose_show_bid",
        staticmethod(recording_choose_show_bid),
    )
    config = RunnerConfig(
        deal_count=1,
        legacy_rng_seed=2718,
        rollouts=1,
        scoring="rising",
        show_banned_ranks=(),
    )
    result = execute_legacy_deals(config, [example_deal])[0]
    assert observed_bans == [(), (), (), ()]
    assert result["effective_configuration"]["show_banned_ranks"] == []
    assert any("explicit empty show-ban" in item for item in result["fidelity_warnings"])


def test_recording_adapter_matches_plain_legacy_terminal_state(
    example_deal, runner_config
) -> None:
    """Instrumentation must not change the built-in agents' terminal outcome."""

    result = execute_legacy_deals(runner_config, [example_deal])[0]
    legacy = load_legacy_module()
    game = legacy.TuppiGame(
        human_seat=0,
        rollouts=1,
        rising_scoring=True,
        seed=None,
        show_banned_ranks={2, 11, 12, 13},
        analysis_level="none",
    )
    game.players = [
        legacy.MonteCarloAI(seat, legacy.dealer_name(seat), rollouts=1)
        for seat in range(4)
    ]
    game.dealer = example_deal.dealer

    router = _LegacyRandomRouter(2718)
    original_random = legacy.random
    try:
        legacy.random = router
        router.begin_deal(example_deal)
        with contextlib.redirect_stdout(io.StringIO()):
            game.play_one_hand()
        router.finish_deal(1)
    finally:
        legacy.random = original_random

    expected = result["terminal"]["legacy_score_after"]
    assert list(game.score_state.scores) == expected["scores"]
    assert list(game.score_state.totals) == expected["totals"]
    assert game.score_state.rising_team == expected["rising_team"]


def test_headless_execution_does_not_use_input_gui_or_network(
    monkeypatch, example_deal, runner_config
) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("interactive or network function was called")

    monkeypatch.setattr(builtins, "input", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    result = execute_legacy_deals(runner_config, [example_deal])[0]
    assert result["execution"]["status"] == "ok"
    assert "tuppi_gui_client_multi_v8" not in sys.modules
