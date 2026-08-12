from __future__ import annotations

from functools import cache
import json
from pathlib import Path
import random

import pytest

import tuppi_server.completed_deal_review as review_module
import tuppi_server.match_runner as match_runner_module
from tuppi_engine import ExplicitDeal, action_from_data, deal_result_to_data
from tuppi_rules import (
    FULL_DECK,
    card_to_code,
    score_nolo,
    score_rami_for_declarer,
)
from tuppi_server.analysis import COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION
from tuppi_server.completed_deal_review import (
    BOT_REPLAY_POLICY_ID,
    generate_completed_deal_review,
)
from tuppi_server.match_runner import LiveMatchRunner
from tuppi_server.persistence import FileRoomStore
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_ui_fixtures.validation import validate_instance


def _deterministic_deals(count: int = 50) -> list[ExplicitDeal]:
    random_source = random.Random(260810)
    deals: list[ExplicitDeal] = []
    for deal_number in range(count):
        cards = list(FULL_DECK)
        random_source.shuffle(cards)
        deals.append(
            ExplicitDeal(
                dealer=deal_number % 4,
                hands=tuple(
                    tuple(cards[seat * 13 : (seat + 1) * 13])
                    for seat in range(4)
                ),
            )
        )
    return deals


def _played_runner(*, match_ref: str, until_terminal: bool) -> LiveMatchRunner:
    remaining = iter(_deterministic_deals())
    original = match_runner_module.generate_live_deal

    def deterministic_deal(*, dealer: int) -> ExplicitDeal:
        deal = next(remaining)
        assert deal.dealer == dealer
        return deal

    match_runner_module.generate_live_deal = deterministic_deal
    try:
        runner = LiveMatchRunner(
            match_ref=match_ref,
            ai_seats=frozenset({1, 2, 3}),
        )
        action_index = 0
        while not runner.terminal and (
            until_terminal or not runner.state.completed_deals
        ):
            observation = runner.observation(0)
            runner.submit(
                seat=0,
                client_action_id=f"review-human:{action_index}",
                match_ref=runner.match_ref,
                expected_event_index=runner.event_cursor,
                action=action_from_data(observation["legal_actions"][-1]),
            )
            action_index += 1
    finally:
        match_runner_module.generate_live_deal = original
    assert runner.state.completed_deals
    if until_terminal:
        assert runner.terminal
    else:
        assert not runner.terminal
    return runner


def _all_human_nolo_runner(*, seed: int) -> LiveMatchRunner:
    """Play one deterministic all-human transcript that never declares RAMI."""

    random_source = random.Random(seed)
    original = match_runner_module.generate_live_deal

    def deterministic_deal(*, dealer: int) -> ExplicitDeal:
        cards = list(FULL_DECK)
        random_source.shuffle(cards)
        return ExplicitDeal(
            dealer=dealer,
            hands=tuple(
                tuple(cards[seat * 13 : (seat + 1) * 13])
                for seat in range(4)
            ),
        )

    match_runner_module.generate_live_deal = deterministic_deal
    try:
        runner = LiveMatchRunner(
            match_ref=f"completed-deal-nolo-scenario-{seed}",
            ai_seats=frozenset(),
            auto_run_ai=False,
        )
        action_index = 0
        while not runner.state.completed_deals:
            actor = runner.current_actor
            assert actor is not None
            observation = runner.observation(actor)
            legal = observation["legal_actions"]
            assert isinstance(legal, list) and legal
            if observation["phase"] == "SHOWING":
                raw = next(
                    action
                    for action in legal
                    if action["declared_contract"] == "NOLO"
                )
            else:
                raw = legal[0]
            acknowledgement = runner.submit(
                seat=actor,
                client_action_id=f"forced-nolo:{action_index}",
                match_ref=runner.match_ref,
                expected_event_index=runner.event_cursor,
                action=action_from_data(raw),
            )
            assert acknowledgement["status"] == "accepted"
            action_index += 1
    finally:
        match_runner_module.generate_live_deal = original
    return runner


@cache
def _terminal_runner() -> LiveMatchRunner:
    return _played_runner(match_ref="completed-deal-bot-review-test", until_terminal=True)


@cache
def _reviews() -> tuple[dict[str, object], ...]:
    runner = _terminal_runner()
    return tuple(
        generate_completed_deal_review(runner, seat=0, deal_number=deal_number)
        for deal_number in range(len(runner.state.completed_deals))
    )


def test_bot_replay_uses_the_exact_authoritative_deal_and_four_bot_seats() -> None:
    runner = _terminal_runner()
    response = _reviews()[0]
    research = runner.state.completed_deals[0]
    actual = response["actual_result"]
    bot = response["bot_replay"]
    assert isinstance(actual, dict)
    assert isinstance(bot, dict)

    assert response["schema_version"] == COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION
    assert response["deal_id"] == research.deal_id
    assert response["initial_hands"] == [
        [card_to_code(card) for card in hand]
        for hand in research.initial_hands
    ]
    assert actual == deal_result_to_data(research.public_result)
    assert bot["dealer"] == actual["dealer"]
    assert bot["forehand"] == actual["forehand"]
    assert bot["score_before"] == actual["score_before"]
    assert bot["match_ref"] == actual["match_ref"]
    assert bot["deal_ref"] == actual["deal_ref"]
    assert response["bot_policy"]["profile"] == "partner_aware_v1"
    assert response["bot_policy"]["bot_seats"] == [0, 1, 2, 3]
    assert response["bot_policy"]["determinism"] == "deterministic"
    assert response["bot_policy"]["analysis_seed"] is None
    assert len(bot["tricks"]) == 13
    assert sum(bot["team_tricks"]) == 13

    initial = response["initial_hands"]
    for result in (actual, bot):
        for seat in range(4):
            played = {
                play["card"]
                for trick in result["tricks"]
                for play in trick["plays"]
                if play["seat"] == seat
            }
            assert played == set(initial[seat])


def test_bots_choose_showing_and_contract_independently_from_the_human_transcript() -> None:
    response = _reviews()[0]
    actual = response["actual_result"]
    bot = response["bot_replay"]
    assert actual["contract"] == "RAMI"
    assert bot["contract"] == "NOLO"
    assert actual["show_actions"] != bot["show_actions"]
    assert len(bot["show_actions"]) == 4
    assert all(show["declared_contract"] == "NOLO" for show in bot["show_actions"])

    rami = next(
        item["bot_replay"] for item in _reviews() if item["bot_replay"]["contract"] == "RAMI"
    )
    assert rami["show_actions"][-1]["declared_contract"] == "RAMI"
    assert len(rami["show_actions"]) < 4, "RAMI must stop showing immediately"


def test_actual_and_bot_results_use_production_nolo_made_and_stolen_rami_scoring() -> None:
    seen: set[str] = set()
    saw_eight_point_stolen_rami = False
    for response in _reviews():
        for result in (response["actual_result"], response["bot_replay"]):
            seen.add(result["outcome"])
            tricks = result["team_tricks"]
            if result["contract"] == "NOLO":
                expected = score_nolo(*tricks)
            else:
                expected = score_rami_for_declarer(result["declarer"], *tricks)
            assert result["deal_score"] == {
                "declaring_team": (
                    None
                    if expected.declaring_team is None
                    else expected.declaring_team.value
                ),
                "points": expected.points,
                "stolen_rami": expected.stolen_rami,
                "winner_team": expected.winner_team.value,
            }
            if result["outcome"] == "STOLEN_RAMI":
                declaring_team = result["declarer"] % 2
                opponent_tricks = tricks[1 - declaring_team]
                assert result["deal_score"]["points"] == 8 * (opponent_tricks - 6)
                saw_eight_point_stolen_rami |= result["deal_score"]["points"] == 8
    assert {"NOLO", "MADE_RAMI", "STOLEN_RAMI"} <= seen
    assert saw_eight_point_stolen_rami


def test_deterministic_acceptance_matrix_covers_all_contract_combinations() -> None:
    nolo_vs_rami = generate_completed_deal_review(
        _all_human_nolo_runner(seed=1),
        seat=0,
        deal_number=0,
    )
    nolo_vs_nolo = generate_completed_deal_review(
        _all_human_nolo_runner(seed=3),
        seat=0,
        deal_number=0,
    )
    rami_vs_nolo = next(
        review
        for review in _reviews()
        if review["bot_replay"]["contract"] == "NOLO"
    )
    rami_vs_rami = next(
        review
        for review in _reviews()
        if review["bot_replay"]["contract"] == "RAMI"
    )

    assert (nolo_vs_nolo["actual_result"]["contract"], nolo_vs_nolo["bot_replay"]["contract"]) == (
        "NOLO",
        "NOLO",
    )
    assert (nolo_vs_rami["actual_result"]["contract"], nolo_vs_rami["bot_replay"]["contract"]) == (
        "NOLO",
        "RAMI",
    )
    assert (rami_vs_nolo["actual_result"]["contract"], rami_vs_nolo["bot_replay"]["contract"]) == (
        "RAMI",
        "NOLO",
    )
    assert (rami_vs_rami["actual_result"]["contract"], rami_vs_rami["bot_replay"]["contract"]) == (
        "RAMI",
        "RAMI",
    )
    assert any(
        review["actual_result"]["outcome"] == "STOLEN_RAMI"
        for review in _reviews()
    )


def test_comparison_is_signed_from_the_authenticated_players_partnership() -> None:
    runner = _terminal_runner()
    even = generate_completed_deal_review(runner, seat=0, deal_number=0)
    odd = generate_completed_deal_review(runner, seat=1, deal_number=0)
    even_comparison = even["comparison"]
    odd_comparison = odd["comparison"]
    assert even_comparison["local_team"] == 0
    assert odd_comparison["local_team"] == 1
    assert even_comparison["actual_deal_points"] == -odd_comparison["actual_deal_points"]
    assert even_comparison["bot_deal_points"] == -odd_comparison["bot_deal_points"]
    assert even_comparison["deal_point_difference"] == -odd_comparison["deal_point_difference"]
    assert even_comparison["trick_difference"] == -odd_comparison["trick_difference"]


def test_replay_is_deterministic_and_schema_valid() -> None:
    runner = _terminal_runner()
    first = generate_completed_deal_review(runner, seat=0, deal_number=0)
    second = generate_completed_deal_review(runner, seat=0, deal_number=0)
    assert first == second
    validate_instance(
        first,
        "https://example.invalid/tuppi/schemas/network/completed_deal_analysis.schema.json",
    )


def test_completed_deal_review_cache_survives_restart_without_rerunning_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RoomManager(tmp_path)
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.runner = _played_runner(
        match_ref=f"room-{room.code.lower()}",
        until_terminal=False,
    )
    room.lifecycle = "playing"
    manager.persist(room)

    first = manager.completed_deal_analysis_for_session(
        code=room.code,
        token=host.token,
        deal_number=0,
    )
    canonical = json.loads(json.dumps(first, sort_keys=True))
    first["comparison"]["bot_tricks"] = 99
    second = manager.completed_deal_analysis_for_session(
        code=room.code,
        token=host.token,
        deal_number=0,
    )
    assert second == canonical, "a caller cannot mutate the cached response"

    monkeypatch.setattr(
        review_module,
        "_run_reference_replay",
        lambda research: (_ for _ in ()).throw(AssertionError("policy reran")),
    )
    restored = RoomManager(tmp_path)
    third = restored.completed_deal_analysis_for_session(
        code=room.code,
        token=host.token,
        deal_number=0,
    )
    assert third == canonical


def test_cache_invalidates_on_analysis_schema_or_policy_change(tmp_path: Path) -> None:
    store = FileRoomStore(tmp_path)
    response = _reviews()[0]
    store.save_completed_deal_analysis(
        room_code="ABC123",
        deal_number=0,
        seat=0,
        response=response,
        analysis_schema_version=COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
        bot_policy_id=BOT_REPLAY_POLICY_ID,
    )
    assert store.load_completed_deal_analysis(
        room_code="ABC123",
        deal_number=0,
        seat=0,
        analysis_schema_version="tuppi.analysis.completed_deal.v4",
        bot_policy_id=BOT_REPLAY_POLICY_ID,
    ) is None
    assert store.load_completed_deal_analysis(
        room_code="ABC123",
        deal_number=0,
        seat=0,
        analysis_schema_version=COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
        bot_policy_id="agent:sha256:future-policy-id",
    ) is None


def test_analysis_is_unavailable_during_live_deal_and_live_payload_has_no_hands() -> None:
    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    room.runner = LiveMatchRunner(
        match_ref=f"room-{room.code.lower()}",
        ai_seats=frozenset(),
        auto_run_ai=False,
    )
    live = room.runner.reconnect(seat=0, last_applied_event_index=-1)
    serialized = json.dumps(live, sort_keys=True)
    assert "initial_hands" not in serialized
    assert "bot_replay" not in serialized
    with pytest.raises(RoomError, match="deal_not_complete"):
        manager.completed_deal_analysis_for_session(
            code=room.code,
            token=host.token,
            deal_number=0,
        )


def test_product_review_does_not_import_or_open_evaluation_banks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(review_module.__file__).read_text(encoding="utf-8")
    assert "tuppi_eval" not in source
    assert "deal_bank" not in source
    assert "sealed" not in source.lower()

    original_open = Path.open

    def reject_bank_access(path: Path, *args, **kwargs):
        normalized = str(path).lower()
        if "/banks/" in normalized or "sealed" in normalized:
            raise AssertionError(f"analysis opened evaluation material: {path}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_bank_access)
    response = generate_completed_deal_review(
        _terminal_runner(),
        seat=0,
        deal_number=0,
    )
    assert response["bot_policy"]["profile"] == "partner_aware_v1"
