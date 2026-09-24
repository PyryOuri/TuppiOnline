"""Live training odds during a sooli deal: a sampler answers, the server checks.

Without a sampler the endpoint still refuses sooli deals. With one it returns
tuppi.server.training_analysis.sooli.v1: facts-only odds, and the bot's sooli
inference as the ``assumed`` view where the bot uses it. Every layout is
checked against the seat's observation, so a sampler cannot move the seat's
own cards or bring back a played one.
"""

from __future__ import annotations

import random

import pytest

from tuppi_engine import EnginePhase, action_from_data
from tuppi_rules import RulesetId
from tuppi_server.match_runner import TEST_AI_PROFILE_KEY
from tuppi_server.rooms import RoomError, RoomManager
from tuppi_ui_fixtures.validation import validate_instance

from .test_real_game_deal_analysis import _all_human_room

V3 = RulesetId.PROJECT_TARGET_V3
SCHEMA = "https://example.invalid/tuppi/schemas/network/training_analysis.schema.json"


def _room_in_sooli_play(manager, seed="sooli-odds", tricks=1):
    """An all-human v3 room whose current deal is a sooli with `tricks` tricks played."""
    rng = random.Random(seed)
    for _ in range(60):
        room, tokens = _all_human_room(manager)
        runner = room.runner
        n = 0
        while not runner.state.completed_deals:
            if runner.collecting_bids():
                for seat in range(4):
                    options = runner.bidding(seat)["options"] if runner.collecting_bids() else []
                    if options:
                        runner.submit(seat=seat, client_action_id=f"b{n}", match_ref=runner.match_ref,
                                      expected_event_index=runner.event_cursor,
                                      action=action_from_data(rng.choice(options)))
                        n += 1
                continue
            deal = runner.state.active_deal
            if deal.phase is EnginePhase.SOOLI_PLAY and len(deal.sooli_tricks) >= tricks:
                return room, tokens
            seat = runner.current_actor
            legal = runner.observation(seat)["legal_actions"]
            if deal.phase is EnginePhase.SOOLI_OFFER:
                action = next(a for a in legal if a["play_sooli"])  # every defender says yes
            else:
                action = rng.choice(legal)
            runner.submit(seat=seat, client_action_id=f"a{n}", match_ref=runner.match_ref,
                          expected_event_index=runner.event_cursor, action=action_from_data(action))
            n += 1
    raise AssertionError("no sooli deal reached play")


class TrueStateSampler:
    """A stand-in: shuffles the true unseen cards among the other seats, keeping hand sizes."""

    estimator_id = "test-shuffle"

    def __init__(self, runner, informed=True, worlds=200, corrupt=None):
        self.runner, self.informed, self.worlds, self.corrupt = runner, informed, worlds, corrupt

    def informed_applies(self, observation):
        return self.informed

    def sample_layouts(self, observation, *, informed):
        hands = [list(hand) for hand in self.runner.state.active_deal.hands]
        seat = observation.observing_seat
        others = [s for s in range(4) if s != seat]
        pool = [card for s in others for card in hands[s]]
        rng = random.Random(informed)
        layouts = []
        for _ in range(self.worlds):
            rng.shuffle(pool)
            layout, start = [None] * 4, 0
            layout[seat] = tuple(hands[seat])
            for s in others:
                layout[s] = tuple(pool[start:start + len(hands[s])])
                start += len(hands[s])
            layouts.append(tuple(layout))
        if self.corrupt == "own":
            layouts[0] = tuple(layouts[0][s] if s != seat else layouts[0][seat][1:] for s in range(4))
        if self.corrupt == "played":
            played = self.runner.state.active_deal.sooli_tricks[0].plays[0].card
            other = others[0]
            layouts[0] = tuple(
                layouts[0][s] + (played,) if s == other else layouts[0][s] for s in range(4)
            )
        return layouts

    def prior_probability(self, observation):
        return 0.4


def test_without_a_sampler_sooli_odds_stay_unavailable(tmp_path):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _room_in_sooli_play(manager)
    with pytest.raises(RoomError, match="analysis_unavailable_in_sooli"):
        manager.training_analysis_for_session(code=room.code, token=tokens[0])


def test_a_sampler_answers_with_checked_sampled_odds(tmp_path):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _room_in_sooli_play(manager)
    deal = room.runner.state.active_deal
    for seat in range(4):
        manager.sooli_odds = TrueStateSampler(room.runner, informed=seat % 2 == 0)
        response = manager.training_analysis_for_session(code=room.code, token=tokens[seat])
        validate_instance(response, SCHEMA)
        assert response["schema_version"] == "tuppi.server.training_analysis.sooli.v1"
        assert response["seat"] == seat
        assert response["sooli"] == {"soolaaja": deal.soolaaja, "dead_seat": (deal.soolaaja + 2) % 4}
        played = {play.card for trick in deal.sooli_tricks for play in trick.plays}
        codes = {entry["card"] for entry in response["card_locations"]}
        own = {card for card in deal.hands[seat]}
        from tuppi_rules import card_to_code
        assert codes.isdisjoint(card_to_code(card) for card in own | played)
        for entry in response["card_locations"]:
            assert entry["seat_probabilities"][seat] == 0.0
            assert sum(entry["seat_probabilities"]) == pytest.approx(1.0)
        if seat % 2 == 0:
            assert response["assumed"]["rules"] == ["sooli_low_hand"]
            assert response["assumed"]["prior_probability"] == 0.4
        else:
            assert response["assumed"] is None


@pytest.mark.parametrize("corrupt", ["own", "played"])
def test_a_layout_that_contradicts_the_observation_is_refused(tmp_path, corrupt):
    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    room, tokens = _room_in_sooli_play(manager)
    manager.sooli_odds = TrueStateSampler(room.runner, corrupt=corrupt)
    with pytest.raises(RoomError, match="analysis_unavailable_in_sooli"):
        manager.training_analysis_for_session(code=room.code, token=tokens[0])


def test_tuppi_ai_sooli_inference_lowers_the_soolaajas_hand(tmp_path):
    from tuppi_server.match_runner import tuppi_ai_available

    if not tuppi_ai_available():
        pytest.skip("tuppi_ai is not installed")
    from tuppi_ai.sooli_odds import SooliOdds
    from tuppi_rules import card_from_code

    manager = RoomManager(tmp_path, ruleset_id=V3, ai_profile_key=TEST_AI_PROFILE_KEY)
    manager.sooli_odds = SooliOdds(worlds=1000)
    room, tokens = _room_in_sooli_play(manager, seed="tuppi-ai-odds")
    deal = room.runner.state.active_deal
    rami_player = (deal.soolaaja + 1) % 4
    response = manager.training_analysis_for_session(code=room.code, token=tokens[rami_player])
    validate_instance(response, SCHEMA)
    assumed = response["assumed"]
    assert assumed is not None and 0 < assumed["prior_probability"] <= 1

    def expected_rank(locations):
        # expected rank of a card in the soolaaja's hand, over the unseen cards
        weight = total = 0.0
        for entry in locations:
            p = entry["seat_probabilities"][deal.soolaaja]
            weight += p
            total += p * card_from_code(entry["card"]).rank.value
        return total / weight

    assert expected_rank(assumed["card_locations"]) < expected_rank(response["card_locations"])
    # the same position gives the same numbers
    assert manager.training_analysis_for_session(code=room.code, token=tokens[rami_player]) == response
