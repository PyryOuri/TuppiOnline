"""Authoritative completed-deal review with a same-shuffle bot replay.

The live runner already retains the canonical :class:`ResearchDealResult` for
every completed deal.  This module deliberately starts from that object rather
than reconstructing cards from a client payload or generating a new shuffle.
Four fresh ``partner_aware_v1`` agents then play the explicit deal from its
original score and dealer under the normal engine transitions.

The result is post-deal information.  It must only be called after the selected
deal is present in ``MatchState.completed_deals``.
"""

from __future__ import annotations

from collections.abc import Mapping

from tuppi_agents import (
    construct_registered_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_engine import (
    DealResult,
    ExplicitDeal,
    ResearchDealResult,
    action_from_data,
    apply_action,
    create_deal_state,
    deal_result_from_state,
    deal_result_to_data,
    observation_for,
)
from tuppi_rules import card_to_code, team_for_seat

from .analysis import (
    COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
    validate_completed_deal_analysis_response,
)
from .match_runner import LiveMatchRunner
from .post_match_diagnostics import (
    REFERENCE_PROFILE_KEY,
    generate_completed_deal_diagnostics,
)
from .projection import project_event_batch


BOT_REPLAY_POLICY = REFERENCE_PROFILE_KEY
_BOT_REPLAY_SPECIFICATION = phase4_specifications_by_profile_key()[BOT_REPLAY_POLICY]
BOT_REPLAY_POLICY_ID = _BOT_REPLAY_SPECIFICATION.agent_id


def generate_completed_deal_review(
    runner: LiveMatchRunner,
    *,
    seat: int,
    deal_number: int,
) -> dict[str, object]:
    """Return diagnostics plus a deterministic four-bot same-deal replay."""

    research = _completed_research_deal(runner, deal_number)
    if type(seat) is not int or seat not in range(4):
        raise ValueError("analysis seat must be an integer in 0..3")

    diagnostics = generate_completed_deal_diagnostics(
        runner,
        seat=seat,
        deal_number=deal_number,
    )
    actual = research.public_result
    bot_result, policy = _run_reference_replay(research)
    response = {
        **diagnostics,
        "schema_version": COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
        "deal_id": research.deal_id,
        "local_team": team_for_seat(seat).value,
        "initial_hands": [
            [card_to_code(card) for card in hand]
            for hand in research.initial_hands
        ],
        "bot_policy": policy,
        "actual_result": deal_result_to_data(actual),
        "bot_replay": deal_result_to_data(bot_result),
        "comparison": _comparison(actual, bot_result, seat=seat),
    }
    return validate_completed_deal_review_against_runner(
        response,
        runner=runner,
        seat=seat,
        deal_number=deal_number,
    )


def validate_completed_deal_review_against_runner(
    value: Mapping[str, object],
    *,
    runner: LiveMatchRunner,
    seat: int,
    deal_number: int,
) -> dict[str, object]:
    """Validate a generated or cached review against authoritative deal data.

    A cached bot transcript is replayed through the production engine.  The
    reference policy itself is not invoked, so reopening a review does not
    recompute the counterfactual decision process.
    """

    research = _completed_research_deal(runner, deal_number)
    actual = research.public_result
    validated = validate_completed_deal_analysis_response(
        value,
        expected_match_ref=runner.match_ref,
        expected_deal_number=deal_number,
        public_events=project_event_batch(actual.events),
    )
    if validated["schema_version"] != COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION:
        raise ValueError("completed-deal review cache uses an obsolete schema")
    if validated["seat"] != seat:
        raise ValueError("completed-deal review cache belongs to another seat")
    if validated["deal_id"] != research.deal_id:
        raise ValueError("completed-deal review cache belongs to another shuffle")

    expected_hands = [
        [card_to_code(card) for card in hand]
        for hand in research.initial_hands
    ]
    if validated["initial_hands"] != expected_hands:
        raise ValueError("completed-deal review hands disagree with the shuffle")
    if validated["actual_result"] != deal_result_to_data(actual):
        raise ValueError("completed-deal review actual result is not authoritative")

    policy = validated["bot_policy"]
    if not isinstance(policy, dict) or policy != _policy_data():
        raise ValueError("completed-deal review policy identity is stale")
    bot_mapping = validated["bot_replay"]
    if not isinstance(bot_mapping, dict):
        raise ValueError("completed-deal bot replay must be an object")
    replayed = _replay_stored_bot_transcript(research, bot_mapping)
    if bot_mapping != deal_result_to_data(replayed):
        raise ValueError("completed-deal bot transcript is not an engine result")
    if validated["comparison"] != _comparison(actual, replayed, seat=seat):
        raise ValueError("completed-deal comparison disagrees with its results")
    return validated


def _completed_research_deal(
    runner: LiveMatchRunner,
    deal_number: int,
) -> ResearchDealResult:
    if not isinstance(runner, LiveMatchRunner):
        raise ValueError("completed-deal review requires a live match runner")
    if (
        type(deal_number) is not int
        or deal_number < 0
        or deal_number >= len(runner.state.completed_deals)
    ):
        raise ValueError("deal is not complete")
    return runner.state.completed_deals[deal_number]


def _initial_state(research: ResearchDealResult):
    actual = research.public_result
    explicit = ExplicitDeal(
        dealer=actual.dealer,
        hands=research.initial_hands,
        claimed_deal_id=research.deal_id,
    )
    return create_deal_state(
        explicit,
        starting_score=actual.score_before,
        match_ref=actual.match_ref,
        deal_ref=actual.deal_ref,
        deal_number=actual.deal_number,
        event_start_index=actual.events[0].event_index,
    )


def _run_reference_replay(
    research: ResearchDealResult,
) -> tuple[DealResult, dict[str, object]]:
    agents = tuple(
        construct_registered_agent(_BOT_REPLAY_SPECIFICATION, seat=seat)
        for seat in range(4)
    )
    state = _initial_state(research)
    accepted = 0
    while not state.complete:
        actor = state.current_actor
        if actor is None:
            raise RuntimeError("bot replay has no current actor")
        action = agents[actor].choose_action(observation_for(state, actor))
        state = apply_action(state, action)
        accepted += 1
        if accepted > 56:
            raise RuntimeError("bot replay exceeded four shows plus 52 card plays")
    return deal_result_from_state(state), _policy_data()


def _policy_data() -> dict[str, object]:
    return {
        "profile": BOT_REPLAY_POLICY,
        "policy_id": BOT_REPLAY_POLICY_ID,
        "determinism": "deterministic",
        "analysis_seed": None,
        "bot_seats": [0, 1, 2, 3],
    }


def _replay_stored_bot_transcript(
    research: ResearchDealResult,
    bot_result: Mapping[str, object],
) -> DealResult:
    shows = bot_result.get("show_actions")
    tricks = bot_result.get("tricks")
    if type(shows) is not list or type(tricks) is not list:
        raise ValueError("bot replay transcript is missing actions")
    serialized_actions: list[dict[str, object]] = []
    for raw in shows:
        if type(raw) is not dict:
            raise ValueError("bot replay show action is invalid")
        serialized_actions.append(
            {
                "type": "show",
                "seat": raw.get("seat"),
                "shown_card": raw.get("shown_card"),
                "declared_contract": raw.get("declared_contract"),
            }
        )
    for raw_trick in tricks:
        if type(raw_trick) is not dict or type(raw_trick.get("plays")) is not list:
            raise ValueError("bot replay trick is invalid")
        for raw_play in raw_trick["plays"]:
            if type(raw_play) is not dict:
                raise ValueError("bot replay play action is invalid")
            serialized_actions.append(
                {
                    "type": "play",
                    "seat": raw_play.get("seat"),
                    "card": raw_play.get("card"),
                }
            )

    state = _initial_state(research)
    for raw in serialized_actions:
        action = action_from_data(raw)
        state = apply_action(state, action)
    if not state.complete:
        raise ValueError("bot replay transcript does not finish the deal")
    return deal_result_from_state(state)


def _signed_points(result: DealResult, team: int) -> int:
    points = result.deal_score.points
    return points if result.deal_score.winner_team.value == team else -points


def _comparison(
    actual: DealResult,
    bot: DealResult,
    *,
    seat: int,
) -> dict[str, object]:
    local_team = team_for_seat(seat).value
    opponent = 1 - local_team
    if actual.score_before != bot.score_before:
        raise ValueError("counterfactual score must start from the actual score")
    actual_points = _signed_points(actual, local_team)
    bot_points = _signed_points(bot, local_team)
    actual_local_after = (
        actual.score_after.team0 if local_team == 0 else actual.score_after.team1
    )
    bot_local_after = bot.score_after.team0 if local_team == 0 else bot.score_after.team1
    actual_opponent_after = (
        actual.score_after.team0 if opponent == 0 else actual.score_after.team1
    )
    bot_opponent_after = (
        bot.score_after.team0 if opponent == 0 else bot.score_after.team1
    )
    actual_margin = actual_local_after - actual_opponent_after
    bot_margin = bot_local_after - bot_opponent_after
    actual_tricks = actual.team_tricks[local_team]
    bot_tricks = bot.team_tricks[local_team]
    return {
        "local_team": local_team,
        "actual_tricks": actual_tricks,
        "bot_tricks": bot_tricks,
        "trick_difference": bot_tricks - actual_tricks,
        "actual_deal_points": actual_points,
        "bot_deal_points": bot_points,
        "deal_point_difference": bot_points - actual_points,
        "actual_match_score_after": actual_local_after,
        "bot_match_score_after": bot_local_after,
        "match_score_difference": bot_local_after - actual_local_after,
        "actual_score_margin_after": actual_margin,
        "bot_score_margin_after": bot_margin,
        "match_score_margin_difference": bot_margin - actual_margin,
    }
