"""The real game's completed-deal analysis: hands, sooli exchange, bot replay, review.

Rooms under project_target_v3 answer the completed-deal analysis endpoint with
tuppi.analysis.real_game_deal.v1 instead of refusing it: the dealt hands, both
exchanged cards of a sooli deal, a same-cards replay by the room's own bots,
the comparison and the seat's review. Cached, persisted, and served from the
store after a restart without running the bots again.
"""

from __future__ import annotations

import random

import pytest

from tuppi_rules import RulesetId, card_to_code
from tuppi_server import real_game_deal_analysis as analysis_module
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_server.real_game_deal_analysis import REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_ui_fixtures.validation import validate_instance

from .test_locked_bids_and_sooli_server import _drive_human_match

V3 = RulesetId.PROJECT_TARGET_V3
SCHEMA = "https://example.invalid/tuppi/schemas/network/completed_deal_analysis.schema.json"


def _all_human_room(manager: RoomManager):
    room, host = manager.create_room(display_name="Yksi", ai_seats=frozenset())
    tokens = {host.seat: host.token}
    for name in ("Kaksi", "Kolme", "Neljä"):
        _, session = manager.join_room(code=room.code, display_name=name)
        tokens[session.seat] = session.token
    for token in tokens.values():
        manager.mark_ready(code=room.code, token=token)
    return room, tokens


def _room_with_a_sooli_deal(manager: RoomManager, seed: str = "analysis"):
    room, tokens = _all_human_room(manager)
    rng = random.Random(seed)
    for _ in range(12):
        _drive_human_match(room.runner, rng, deals=1, prefix=f"d{len(room.runner.state.completed_deals)}-")
        if any(deal.public_result.soolaaja is not None for deal in room.runner.state.completed_deals):
            break
    completed = room.runner.state.completed_deals
    assert any(deal.public_result.soolaaja is not None for deal in completed), "no sooli deal was played"
    manager.persist(room)  # the runner was driven directly, not through the manager
    return room, tokens


def test_real_game_analysis_reveals_hands_exchange_and_a_bot_replay(tmp_path):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _room_with_a_sooli_deal(manager)
    for number, research in enumerate(room.runner.state.completed_deals):
        for seat in (0, 1):
            response = manager.completed_deal_analysis_for_session(
                code=room.code, token=tokens[seat], deal_number=number
            )
            validate_instance(response, SCHEMA)
            assert response["schema_version"] == REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION
            assert response["seat"] == seat and response["local_team"] == seat % 2
            assert response["initial_hands"] == [
                [card_to_code(card) for card in hand] for hand in research.initial_hands
            ]
            sooli = research.public_result.soolaaja is not None
            assert (response["actual_exchange"] is not None) is sooli
            if sooli:
                assert response["actual_exchange"] == {
                    "given": card_to_code(research.sooli_given),
                    "returned": card_to_code(research.sooli_returned),
                }
            replay = response["bot_replay"]
            assert replay["ruleset_id"] == "project_target_v3"
            assert replay["score_before"] == response["actual_result"]["score_before"]
            assert (response["bot_exchange"] is not None) is (replay["sooli"]["soolaaja"] is not None)
            assert response["bot_policy"]["profile"] == TEST_AI_PROFILE_KEY
            assert response["analyses"] == [] and response["review"] is None
            assert response["summary"]["diagnostic_count"] == 0
            # cached: the same envelope again
            assert manager.completed_deal_analysis_for_session(
                code=room.code, token=tokens[seat], deal_number=number
            ) == response


def test_real_game_analysis_is_served_from_the_store_after_a_restart(tmp_path, monkeypatch):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _room_with_a_sooli_deal(manager, seed="restart-analysis")
    first = {
        number: manager.completed_deal_analysis_for_session(code=room.code, token=tokens[2], deal_number=number)
        for number in range(len(room.runner.state.completed_deals))
    }

    def no_bots(*args, **kwargs):
        raise AssertionError("a stored analysis must not run the bots again")

    monkeypatch.setattr(analysis_module, "_construct_ai_agents", no_bots)
    reloaded = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    for number, response in first.items():
        assert reloaded.completed_deal_analysis_for_session(
            code=room.code, token=tokens[2], deal_number=number
        ) == response


def test_a_stale_cached_transcript_is_regenerated(tmp_path):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _all_human_room(manager)
    _drive_human_match(room.runner, random.Random("stale"), deals=1)
    good = manager.completed_deal_analysis_for_session(code=room.code, token=tokens[0], deal_number=0)
    tampered = dict(good, bot_actions=good["bot_actions"][:-1])
    room.completed_deal_analyses[(0, 0)] = tampered
    assert manager.completed_deal_analysis_for_session(code=room.code, token=tokens[0], deal_number=0) == good


def test_real_game_analysis_needs_a_completed_deal_and_a_participant(tmp_path):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _all_human_room(manager)
    with pytest.raises(RoomError, match="deal_not_complete"):
        manager.completed_deal_analysis_for_session(code=room.code, token=tokens[0], deal_number=0)
    with pytest.raises(RoomError, match="invalid_session"):
        manager.completed_deal_analysis_for_session(code=room.code, token="not-a-token", deal_number=0)


def test_the_review_is_embedded_when_the_server_has_a_reviewer(tmp_path):
    class NoFindings:
        reviewer_id = "test-reviewer"

        def review_decisions(self, decisions):
            return []

    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    manager.deal_reviewer = NoFindings()
    room, tokens = _all_human_room(manager)
    _drive_human_match(room.runner, random.Random("review"), deals=1)
    response = manager.completed_deal_analysis_for_session(code=room.code, token=tokens[1], deal_number=0)
    validate_instance(response, SCHEMA)
    review = response["review"]
    assert review["seat"] == 1 and review["reviewer_id"] == "test-reviewer" and review["findings"] == []
    assert review == manager.deal_review_for_session(code=room.code, token=tokens[1], deal_number=0)


def test_tuppi_ai_bots_replay_a_real_game_deal(tmp_path):
    from tuppi_server.match_runner import TUPPI_AI_PROFILE_KEY, tuppi_ai_available

    if not tuppi_ai_available():
        pytest.skip("tuppi_ai is not installed")
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TUPPI_AI_PROFILE_KEY)
    room, tokens = _all_human_room(manager)
    _drive_human_match(room.runner, random.Random("tuppi-ai-analysis"), deals=1)
    response = manager.completed_deal_analysis_for_session(code=room.code, token=tokens[0], deal_number=0)
    validate_instance(response, SCHEMA)
    assert response["bot_policy"]["profile"] == TUPPI_AI_PROFILE_KEY
