"""Completed-deal analysis for the real game (``project_target_v2``/``v3``).

The basic-rules analysis (:mod:`tuppi_server.completed_deal_review`) replays a
deal with the old reference bot under ``project_target_v1`` and carries that
bot's contract estimates and decision diagnostics. The real game needs other
content, so it has its own envelope:

* the four dealt hands and, for a sooli deal, both exchanged cards, so the
  dead hand can be shown;
* a same-cards replay played by the room's own bots (TuppiAI when installed),
  bidding blind under locked bids and playing sooli when one calls it;
* the comparison of that replay with the deal as played;
* the room's after-deal review of the requesting seat (``review``), which
  takes the place of the old decision diagnostics.

Post-deal only: everything here is revealed once the deal is in
``MatchState.completed_deals``, as with the basic-rules analysis.
"""

from __future__ import annotations

from collections.abc import Mapping

from tuppi_engine import (
    DealResult,
    ExplicitDeal,
    ResearchDealResult,
    action_from_data,
    action_to_data,
    apply_action,
    create_deal_state,
    deal_result_from_state,
    deal_result_to_data,
    observation_for,
)
from tuppi_rules import SOOLI_RULESETS, card_to_code, team_for_seat

from .completed_deal_review import _comparison
from .match_runner import LiveMatchRunner, _construct_ai_agents, _for_ruleset


REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION = "tuppi.analysis.real_game_deal.v1"
#: Rulesets analysed here; ``project_target_v1`` keeps the basic-rules analysis.
REAL_GAME_RULESETS = SOOLI_RULESETS

_RESPONSE_KEYS = frozenset(
    {
        "schema_version",
        "match_ref",
        "deal_ref",
        "deal_number",
        "seat",
        "ruleset_id",
        "deal_id",
        "local_team",
        "initial_hands",
        "actual_result",
        "actual_exchange",
        "bot_policy",
        "bot_replay",
        "bot_exchange",
        "bot_actions",
        "comparison",
        "summary",
        "analyses",
        "review",
    }
)
#: Four bids, up to two sooli answers, two exchanged cards and 52 plays.
_MAX_REPLAY_ACTIONS = 60


class RealGameAnalysisError(ValueError):
    """The analysis could not be produced or a cached copy is stale."""


def bot_policy_for(runner: LiveMatchRunner) -> dict[str, object]:
    """The replay bots' identity: the room's own AI profile on all four seats."""

    return {
        "profile": runner.ai_profile_key,
        "policy_id": runner.ai_profile_key,
        # The bots use their own fixed seeds; the transcript is kept, so a
        # reopened analysis is replayed from it rather than recomputed.
        "determinism": "seeded",
        "analysis_seed": None,
        "bot_seats": [0, 1, 2, 3],
    }


def generate_real_game_deal_analysis(
    runner: LiveMatchRunner,
    *,
    seat: int,
    deal_number: int,
    review: Mapping[str, object] | None,
) -> dict[str, object]:
    """Replay the completed deal with four bots and build the seat's envelope."""

    research = _completed_research_deal(runner, deal_number, seat)
    agents = _for_ruleset(
        _construct_ai_agents(frozenset(range(4)), profile_key=runner.ai_profile_key),
        runner.ruleset_id,
    )
    state = _initial_state(research, runner)
    actions = []
    while not state.complete:
        actor = state.current_actor
        if actor is None:
            raise RealGameAnalysisError("bot replay has no current actor")
        action = agents[actor].choose_action(observation_for(state, actor))
        state = apply_action(state, action)
        actions.append(action)
        if len(actions) > _MAX_REPLAY_ACTIONS:
            raise RealGameAnalysisError("bot replay did not finish the deal")
    bot = deal_result_from_state(state)
    actual = research.public_result
    return {
        "schema_version": REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION,
        "match_ref": runner.match_ref,
        "deal_ref": actual.deal_ref,
        "deal_number": deal_number,
        "seat": seat,
        "ruleset_id": runner.ruleset_id.value,
        "deal_id": research.deal_id,
        "local_team": team_for_seat(seat).value,
        "initial_hands": _hands_data(research),
        "actual_result": deal_result_to_data(actual),
        "actual_exchange": _exchange_data(research.sooli_given, research.sooli_returned),
        "bot_policy": bot_policy_for(runner),
        "bot_replay": deal_result_to_data(bot),
        "bot_exchange": _exchange_data(state.sooli_given, state.sooli_returned),
        "bot_actions": [action_to_data(action) for action in actions],
        "comparison": _comparison(actual, bot, seat=seat),
        "summary": _summary(actual, review),
        "analyses": [],
        "review": None if review is None else dict(review),
    }


def validate_real_game_deal_analysis(
    value: Mapping[str, object],
    *,
    runner: LiveMatchRunner,
    seat: int,
    deal_number: int,
) -> dict[str, object]:
    """Check a cached envelope against the authoritative deal.

    The bot transcript is re-applied through the engine rather than recomputed,
    so reopening an analysis does not run the bots again.
    """

    if not isinstance(value, Mapping) or set(value) != _RESPONSE_KEYS:
        raise RealGameAnalysisError("real-game analysis fields are invalid")
    if value["schema_version"] != REAL_GAME_DEAL_ANALYSIS_SCHEMA_VERSION:
        raise RealGameAnalysisError("real-game analysis uses another schema")
    research = _completed_research_deal(runner, deal_number, seat)
    actual = research.public_result
    expected = {
        "match_ref": runner.match_ref,
        "deal_ref": actual.deal_ref,
        "deal_number": deal_number,
        "seat": seat,
        "ruleset_id": runner.ruleset_id.value,
        "deal_id": research.deal_id,
        "local_team": team_for_seat(seat).value,
        "initial_hands": _hands_data(research),
        "actual_result": deal_result_to_data(actual),
        "actual_exchange": _exchange_data(research.sooli_given, research.sooli_returned),
        "bot_policy": bot_policy_for(runner),
    }
    for key, wanted in expected.items():
        if value[key] != wanted:
            raise RealGameAnalysisError(f"real-game analysis {key} is stale")
    raw_actions = value["bot_actions"]
    if type(raw_actions) is not list or len(raw_actions) > _MAX_REPLAY_ACTIONS:
        raise RealGameAnalysisError("real-game bot transcript is invalid")
    state = _initial_state(research, runner)
    try:
        for raw in raw_actions:
            state = apply_action(state, action_from_data(raw))
    except Exception as exc:  # any engine rejection means the cache is unusable
        raise RealGameAnalysisError("real-game bot transcript is not legal") from exc
    if not state.complete:
        raise RealGameAnalysisError("real-game bot transcript does not finish the deal")
    bot = deal_result_from_state(state)
    review = value["review"]
    if review is not None and not isinstance(review, Mapping):
        raise RealGameAnalysisError("real-game analysis review is invalid")
    if (
        value["bot_replay"] != deal_result_to_data(bot)
        or value["bot_exchange"] != _exchange_data(state.sooli_given, state.sooli_returned)
        or value["comparison"] != _comparison(actual, bot, seat=seat)
        or value["summary"] != _summary(actual, review)
        or value["analyses"] != []
    ):
        raise RealGameAnalysisError("real-game analysis disagrees with its transcript")
    return dict(value)


def _completed_research_deal(
    runner: LiveMatchRunner, deal_number: int, seat: int
) -> ResearchDealResult:
    if not isinstance(runner, LiveMatchRunner):
        raise RealGameAnalysisError("real-game analysis requires a live match runner")
    if runner.ruleset_id not in REAL_GAME_RULESETS:
        raise RealGameAnalysisError("the basic rules use the basic-rules analysis")
    if type(seat) is not int or seat not in range(4):
        raise RealGameAnalysisError("analysis seat must be an integer in 0..3")
    if (
        type(deal_number) is not int
        or deal_number < 0
        or deal_number >= len(runner.state.completed_deals)
    ):
        raise RealGameAnalysisError("deal is not complete")
    return runner.state.completed_deals[deal_number]


def _initial_state(research: ResearchDealResult, runner: LiveMatchRunner):
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
        ruleset_id=runner.ruleset_id,
    )


def _hands_data(research: ResearchDealResult) -> list[list[str]]:
    return [[card_to_code(card) for card in hand] for hand in research.initial_hands]


def _exchange_data(given, returned) -> dict[str, str] | None:
    if given is None and returned is None:
        return None
    if given is None or returned is None:
        raise RealGameAnalysisError("a completed sooli exchange has both cards")
    return {"given": card_to_code(given), "returned": card_to_code(returned)}


def _summary(actual: DealResult, review: Mapping[str, object] | None) -> dict[str, object]:
    findings = review.get("findings") if review is not None else None
    return {
        "contract": actual.contract.value,
        "diagnostic_count": len(findings) if isinstance(findings, list) else 0,
        "outcome": actual.outcome.value,
        "points": actual.deal_score.points,
        "score_before": [actual.score_before.team0, actual.score_before.team1],
        "score_after": [actual.score_after.team0, actual.score_after.team1],
        "team_tricks": list(actual.team_tricks),
    }
