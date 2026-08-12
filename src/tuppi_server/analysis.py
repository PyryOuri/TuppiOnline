"""Privacy-safe projection of recorded AI decisions for match review.

The live engine and the research agents have deliberately different data
boundaries.  ``DecisionDiagnostics`` is useful inside the server, but it is
not a client contract: it contains score vectors, feature contributions and a
one-way observation commitment.  This module is the narrow boundary between
those two worlds.

Only the deterministic agent diagnostics schema is accepted at this stage.
Search/PIMC diagnostics are rejected explicitly because they carry information
about sampled worlds and search work that must never become a client payload.
The projection constructs every output field itself; it never forwards an
arbitrary diagnostics dictionary.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math
import re

from tuppi_engine import (
    EngineError,
    PlayCardAction,
    ShowAction,
    action_from_data,
    action_to_data,
    canonical_json_bytes,
    strict_json_loads,
)
from tuppi_engine.validation import is_sha256_identifier, is_valid_match_ref


POST_MATCH_ANALYSIS_SCHEMA_VERSION = "tuppi.analysis.post_match.v1"
POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.analysis.post_match.v2"
POST_MATCH_REVIEW_SCHEMA_VERSION = "tuppi.analysis.post_match.v3"
COMPLETED_DEAL_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.analysis.completed_deal.v1"
COMPLETED_DEAL_REVIEW_SCHEMA_VERSION = "tuppi.analysis.completed_deal.v2"
COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION = "tuppi.analysis.completed_deal.v3"
AGENT_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.agents.decision_diagnostics.v1"
PIMC_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.search.pimc_decision_diagnostics.v1"

#: Ranked-diagnostics payload versions, oldest first.  A live server emits the
#: newest; older versions stay acceptable so committed fixtures and a client's
#: locally persisted history keep decoding.
RANKED_ANALYSIS_SCHEMA_VERSIONS: tuple[str, ...] = (
    POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION,
    POST_MATCH_REVIEW_SCHEMA_VERSION,
)
COMPLETED_DEAL_SCHEMA_VERSIONS: tuple[str, ...] = (
    COMPLETED_DEAL_DIAGNOSTICS_SCHEMA_VERSION,
    COMPLETED_DEAL_REVIEW_SCHEMA_VERSION,
    COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
)

_MANDATORY_LIMITATION = (
    "Analyysi käyttää vain analysoidun pelaajan sallittua tietoa ja julkista "
    "tapahtumahistoriaa."
)
_CARD_CODE_PATTERN = re.compile(r"(?:10|[2-9]|[JQKA])[HDCS]")
_CARD_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:10|[2-9]|[JQKA])[HDCS](?![A-Za-z0-9])"
)

# This is intentionally a superset of the search package's deny-list.  The
# adapter is a release boundary, so a new private field must fail closed until
# somebody reviews it rather than silently becoming client-visible.
_FORBIDDEN_KEYS = frozenset(
    {
        "deal_id",
        "deal_ref",
        "evaluator_fixture_id",
        "explicit_deal",
        "full_observation",
        "hands",
        "hidden_hands",
        "information_state",
        "initial_hands",
        "legal_actions",
        "matched_truth",
        "opponent_hand",
        "opponent_hands",
        "private_deal",
        "real_state",
        "rollout_policy_agent_ids",
        "sampled_hands",
        "sampled_worlds",
        "sealed_seed",
        "search_tree",
        "simulation_counts",
        "true_deal_id",
        "true_hands",
        "true_world_index",
        "observation",
        "world_set",
        "worlds",
        "decision_seed",
    }
)

_DIAGNOSTICS_KEYS = frozenset(
    {
        "action_ordering_id",
        "agent_id",
        "candidates",
        "contract",
        "invoked_rule_ids",
        "legal_action_count",
        "match_role",
        "observation_digest",
        "observing_seat",
        "own_hand_size",
        "partner_seat",
        "phase",
        "profile_id",
        "profile_key",
        "schema_version",
        "selected_action",
        "selected_action_order_index",
        "tie_break_applied",
        "tie_break_id",
    }
)
_CANDIDATE_KEYS = frozenset(
    {
        "action",
        "action_order_index",
        "feature_contributions",
        "reason_codes",
        "rule_ids",
        "score_vector",
        "selected",
    }
)
_FEATURE_KEYS = frozenset({"component", "value"})
_ANALYSIS_ID_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_ANALYSIS_KEYS = frozenset(
    {
        "schema_version",
        "analysis_id",
        "match_ref",
        "event_index",
        "deal_number",
        "trick_index",
        "seat",
        "decision_kind",
        "title",
        "summary",
        "played_action",
        "recommended_action",
        "recommendation",
        "alternatives",
        "explanation",
        "limitations",
        "source",
    }
)
_ALTERNATIVE_KEYS = frozenset(
    {"rank", "action", "title", "assessment", "reason"}
)
_CLIENT_PRIVATE_KEYS = frozenset(
    {
        "agent_id",
        "feature_contributions",
        "information_state",
        "observation_digest",
        "profile_id",
        "profile_key",
        "reason_codes",
        "rule_ids",
        "score_vector",
        "selected_action_order_index",
        "simulation_counts",
        "world_set",
    }
)


class AnalysisProjectionError(ValueError):
    """The input cannot be safely projected into the analysis contract."""


@dataclass(frozen=True, slots=True)
class RecordedDecisionAnalysis:
    """Server-side metadata needed to explain one public decision.

    The text fields are supplied by the analysis producer because the engine
    diagnostics intentionally contain stable machine codes, not user-facing
    prose.  They are still bounded and are copied field-by-field only after
    validation.  ``diagnostics`` must be the serialized
    ``DecisionDiagnostics.to_data()`` result.
    """

    match_ref: str
    event_index: int
    deal_number: int
    trick_index: int | None
    seat: int
    played_action: Mapping[str, object]
    title: str
    summary: str
    recommendation: str
    explanation: tuple[str, ...]
    limitations: tuple[str, ...]
    source: str
    diagnostics: Mapping[str, object]

    @classmethod
    def from_data(cls, value: Mapping[str, object]) -> "RecordedDecisionAnalysis":
        """Parse the deliberately small internal record shape.

        Exact keys are required so a private field cannot be smuggled through
        an otherwise accepted record and later be logged or persisted by a
        caller that forgot the boundary.
        """

        if not isinstance(value, Mapping):
            raise AnalysisProjectionError("analysis record must be an object")
        required = {
            "match_ref",
            "event_index",
            "deal_number",
            "trick_index",
            "seat",
            "played_action",
            "title",
            "summary",
            "recommendation",
            "explanation",
            "limitations",
            "source",
            "diagnostics",
        }
        if set(value) != required:
            raise AnalysisProjectionError("analysis record fields are invalid")

        match_ref = _require_text(value["match_ref"], "match_ref", 96)
        if not is_valid_match_ref(match_ref):
            raise AnalysisProjectionError("match_ref is not a valid public identifier")
        event_index = _require_int(value["event_index"], "event_index", minimum=0)
        deal_number = _require_int(value["deal_number"], "deal_number", minimum=0)
        trick_index = value["trick_index"]
        if trick_index is not None:
            trick_index = _require_int(
                trick_index, "trick_index", minimum=0, maximum=12
            )
        seat = _require_int(value["seat"], "seat", minimum=0, maximum=3)
        played_action = _require_mapping(value["played_action"], "played_action")
        title = _require_text(value["title"], "title", 200)
        summary = _require_text(value["summary"], "summary", 2000)
        recommendation = _require_text(
            value["recommendation"], "recommendation", 2000
        )
        explanation = _require_text_array(value["explanation"], "explanation", 1000)
        limitations = _require_text_array(value["limitations"], "limitations", 1000)
        source = _require_text(value["source"], "source", 128)
        diagnostics = _require_mapping(value["diagnostics"], "diagnostics")
        return cls(
            match_ref=match_ref,
            event_index=event_index,
            deal_number=deal_number,
            trick_index=trick_index,
            seat=seat,
            played_action=played_action,
            title=title,
            summary=summary,
            recommendation=recommendation,
            explanation=explanation,
            limitations=limitations,
            source=source,
            diagnostics=diagnostics,
        )


@dataclass(frozen=True, slots=True)
class _ValidatedCandidate:
    action: dict[str, object]
    action_order_index: int
    score_vector: tuple[float, ...]
    rule_ids: tuple[str, ...]
    selected: bool


@dataclass(frozen=True, slots=True)
class _ValidatedDiagnostics:
    phase: str
    selected_action: dict[str, object]
    candidates: tuple[_ValidatedCandidate, ...]


def project_post_match_analysis(
    record: RecordedDecisionAnalysis | Mapping[str, object],
    *,
    public_events: Sequence[Mapping[str, object]],
    visible_card_codes: Iterable[str] | None = None,
) -> dict[str, object]:
    """Project one recorded decision into one client-safe analysis object.

    ``public_events`` must contain serialized
    ``tuppi.engine.public_event.v1`` events.  The target event is the accepted
    action event, so a replay can jump to the exact public point explained by
    the analysis.
    """

    parsed = (
        record
        if isinstance(record, RecordedDecisionAnalysis)
        else RecordedDecisionAnalysis.from_data(record)
    )
    visible = _normalise_visible_cards(visible_card_codes)
    if visible is not None:
        _assert_authorized_card_codes(parsed.diagnostics, visible, "diagnostics")
        _assert_authorized_card_codes(parsed.played_action, visible, "played_action")

    played_action, played_data = _canonical_action(parsed.played_action, "played_action")
    _validate_action_for_seat(played_action, parsed.seat, "played_action")
    diagnostics = _validate_diagnostics(
        parsed.diagnostics,
        seat=parsed.seat,
        visible_card_codes=visible,
    )
    _validate_phase_action(played_action, diagnostics.phase, "played_action")
    event = _event_for_record(parsed, public_events, diagnostics.phase)
    _validate_event_action(event, played_data, parsed)

    if diagnostics.phase == "SHOWING":
        if parsed.trick_index is not None:
            raise AnalysisProjectionError(
                "showing analysis must not have a trick_index"
            )
    elif parsed.trick_index is None:
        raise AnalysisProjectionError("trick-play analysis requires a trick_index")

    ranked = sorted(
        diagnostics.candidates,
        key=lambda candidate: (
            candidate.score_vector,
            -candidate.action_order_index,
        ),
        reverse=True,
    )
    alternatives: list[dict[str, object]] = []
    rank = 2
    for candidate in ranked:
        if candidate.selected:
            continue
        alternatives.append(
            {
                "rank": rank,
                "action": candidate.action,
                "title": _action_title(candidate.action),
                "assessment": "Analysoitu vaihtoehto",
                "reason": (
                    "Laillinen vaihtoehto, jota verrattiin analyysin "
                    "suositukseen."
                ),
            }
        )
        rank += 1

    limitations = list(parsed.limitations)
    if _MANDATORY_LIMITATION not in limitations:
        limitations.append(_MANDATORY_LIMITATION)
    projected: dict[str, object] = {
        "schema_version": POST_MATCH_ANALYSIS_SCHEMA_VERSION,
        "analysis_id": (
            f"{parsed.match_ref}:analysis:{parsed.event_index}:"
            f"{parsed.seat}:{diagnostics.phase.lower()}"
        ),
        "match_ref": parsed.match_ref,
        "event_index": parsed.event_index,
        "deal_number": parsed.deal_number,
        "trick_index": parsed.trick_index,
        "seat": parsed.seat,
        "decision_kind": diagnostics.phase,
        "title": parsed.title,
        "summary": parsed.summary,
        "played_action": played_data,
        "recommended_action": diagnostics.selected_action,
        "recommendation": parsed.recommendation,
        "alternatives": alternatives,
        "explanation": list(parsed.explanation),
        "limitations": limitations,
        "source": parsed.source,
    }
    if len(projected["analysis_id"]) > 128:  # type: ignore[arg-type]
        raise AnalysisProjectionError("derived analysis_id exceeds the public limit")
    if visible is not None:
        _assert_authorized_card_codes(projected, visible, "projected analysis")
    return projected


def project_post_match_analysis_response(
    records: Iterable[RecordedDecisionAnalysis | Mapping[str, object]],
    *,
    public_events: Sequence[Mapping[str, object]],
    match_ref: str | None = None,
    visible_card_codes: Iterable[str] | None = None,
) -> dict[str, object]:
    """Build the versioned response envelope for one completed match."""

    parsed_records = tuple(
        record
        if isinstance(record, RecordedDecisionAnalysis)
        else RecordedDecisionAnalysis.from_data(record)
        for record in records
    )
    if not parsed_records and match_ref is None:
        raise AnalysisProjectionError(
            "an empty analysis response requires an explicit match_ref"
        )
    resolved_match_ref = match_ref or parsed_records[0].match_ref
    if not is_valid_match_ref(resolved_match_ref):
        raise AnalysisProjectionError("match_ref is not a valid public identifier")
    if any(record.match_ref != resolved_match_ref for record in parsed_records):
        raise AnalysisProjectionError("analysis records belong to different matches")

    analyses = [
        project_post_match_analysis(
            record,
            public_events=public_events,
            visible_card_codes=visible_card_codes,
        )
        for record in parsed_records
    ]
    analyses.sort(key=lambda item: (item["event_index"], item["seat"]))  # type: ignore[index]
    analysis_ids = [item["analysis_id"] for item in analyses]
    if len(set(analysis_ids)) != len(analysis_ids):
        raise AnalysisProjectionError("analysis records have duplicate decision ids")
    response = {
        "schema_version": POST_MATCH_ANALYSIS_SCHEMA_VERSION,
        "match_ref": resolved_match_ref,
        "analyses": analyses,
    }
    return validate_post_match_analysis_response(
        response,
        expected_match_ref=resolved_match_ref,
    )


def validate_post_match_analysis_response(
    value: Mapping[str, object],
    *,
    expected_match_ref: str | None = None,
    public_events: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Validate and canonicalize an already projected client response.

    This is used when an analysis envelope is loaded from private disk.  The
    server must not assume that an atomic file is semantically trustworthy:
    schema, action, privacy, and match ownership are checked again before the
    response can be returned to a client.
    """

    response = _require_mapping(value, "post-match analysis response")
    if response.get("schema_version") in RANKED_ANALYSIS_SCHEMA_VERSIONS:
        return _validate_post_match_diagnostics_response(
            response,
            expected_match_ref=expected_match_ref,
            public_events=public_events,
        )
    _reject_client_private_keys(response)
    if set(response) != {"schema_version", "match_ref", "analyses"}:
        raise AnalysisProjectionError("post-match analysis response fields are invalid")
    if response["schema_version"] != POST_MATCH_ANALYSIS_SCHEMA_VERSION:
        raise AnalysisProjectionError("unsupported post-match analysis schema_version")
    match_ref = _require_text(response["match_ref"], "match_ref", 96)
    if not is_valid_match_ref(match_ref):
        raise AnalysisProjectionError("post-match analysis match_ref is invalid")
    if expected_match_ref is not None and match_ref != expected_match_ref:
        raise AnalysisProjectionError("post-match analysis belongs to another match")
    analyses_value = response["analyses"]
    if type(analyses_value) is not list:
        raise AnalysisProjectionError("post-match analyses must be an array")

    seen_ids: set[str] = set()
    seen_decisions: set[tuple[int, int, str]] = set()
    for index, raw_analysis in enumerate(analyses_value):
        analysis = _require_mapping(raw_analysis, f"analyses[{index}]")
        _validate_projected_analysis(analysis, match_ref=match_ref, label=f"analyses[{index}]")
        analysis_id = analysis["analysis_id"]
        assert isinstance(analysis_id, str)
        if analysis_id in seen_ids:
            raise AnalysisProjectionError("post-match analysis ids are duplicated")
        seen_ids.add(analysis_id)
        decision_key = (
            analysis["event_index"],
            analysis["seat"],
            analysis["decision_kind"],
        )
        if decision_key in seen_decisions:
            raise AnalysisProjectionError("post-match decision entries are duplicated")
        seen_decisions.add(decision_key)

    if public_events is not None:
        _validate_response_public_events(response, public_events)

    try:
        canonical = strict_json_loads(
            canonical_json_bytes(dict(response)).decode("utf-8")
        )
    except Exception as exc:
        raise AnalysisProjectionError("post-match analysis is not canonical JSON") from exc
    if type(canonical) is not dict:
        raise AnalysisProjectionError("post-match analysis must remain an object")
    return canonical


_COMPLETED_DEAL_RESPONSE_KEYS = frozenset(
    {
        "schema_version",
        "match_ref",
        "deal_ref",
        "deal_number",
        "seat",
        "summary",
        "analyses",
    }
)
_COMPLETED_DEAL_BOT_REPLAY_RESPONSE_KEYS = _COMPLETED_DEAL_RESPONSE_KEYS | frozenset(
    {
        "deal_id",
        "local_team",
        "initial_hands",
        "bot_policy",
        "actual_result",
        "bot_replay",
        "comparison",
    }
)
_COMPLETED_DEAL_SUMMARY_KEYS = frozenset(
    {
        "contract",
        "diagnostic_count",
        "outcome",
        "points",
        "score_before",
        "score_after",
        "team_tricks",
    }
)
_COMPLETED_DEAL_REVIEW_SUMMARY_KEYS = _COMPLETED_DEAL_SUMMARY_KEYS | frozenset(
    {"reference_agreement"}
)

_BOT_POLICY_KEYS = frozenset(
    {"profile", "policy_id", "determinism", "analysis_seed", "bot_seats"}
)
_DEAL_RESULT_KEYS = frozenset(
    {
        "contract",
        "deal_number",
        "deal_ref",
        "deal_score",
        "dealer",
        "declarer",
        "event_log_id",
        "events",
        "first_leader",
        "forehand",
        "match_ref",
        "match_terminal",
        "next_dealer",
        "outcome",
        "ruleset_id",
        "schema_version",
        "score_after",
        "score_before",
        "show_actions",
        "team_tricks",
        "tricks",
    }
)
_DEAL_SCORE_KEYS = frozenset(
    {"declaring_team", "points", "stolen_rami", "winner_team"}
)
_SHOW_RESULT_KEYS = frozenset(
    {"declared_contract", "seat", "shown_card", "verbal_required"}
)
_TRICK_RESULT_KEYS = frozenset({"leader", "plays", "trick_index", "winner"})
_PLAY_RESULT_KEYS = frozenset({"card", "seat"})
_COMPARISON_KEYS = frozenset(
    {
        "local_team",
        "actual_tricks",
        "bot_tricks",
        "trick_difference",
        "actual_deal_points",
        "bot_deal_points",
        "deal_point_difference",
        "actual_match_score_after",
        "bot_match_score_after",
        "match_score_difference",
        "actual_score_margin_after",
        "bot_score_margin_after",
        "match_score_margin_difference",
    }
)


def validate_completed_deal_analysis_response(
    value: Mapping[str, object],
    *,
    expected_match_ref: str | None = None,
    expected_deal_number: int | None = None,
    public_events: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Validate one seat-scoped, completed-deal diagnostic envelope."""

    response = _require_mapping(value, "completed-deal analysis response")
    _reject_client_private_keys(response)
    schema_version = response.get("schema_version")
    bot_review = schema_version == COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION
    expected_response_keys = (
        _COMPLETED_DEAL_BOT_REPLAY_RESPONSE_KEYS
        if bot_review
        else _COMPLETED_DEAL_RESPONSE_KEYS
    )
    if set(response) != expected_response_keys:
        raise AnalysisProjectionError(
            "completed-deal analysis response fields are invalid"
        )
    schema_version = response["schema_version"]
    if schema_version not in COMPLETED_DEAL_SCHEMA_VERSIONS:
        raise AnalysisProjectionError(
            "unsupported completed-deal analysis schema_version"
        )
    review = schema_version in {
        COMPLETED_DEAL_REVIEW_SCHEMA_VERSION,
        COMPLETED_DEAL_BOT_REPLAY_SCHEMA_VERSION,
    }
    match_ref = _require_text(response["match_ref"], "match_ref", 96)
    if not is_valid_match_ref(match_ref):
        raise AnalysisProjectionError("completed-deal match_ref is invalid")
    if expected_match_ref is not None and match_ref != expected_match_ref:
        raise AnalysisProjectionError("completed-deal analysis belongs to another match")
    deal_number = _require_int(
        response["deal_number"], "deal_number", minimum=0
    )
    if expected_deal_number is not None and deal_number != expected_deal_number:
        raise AnalysisProjectionError("completed-deal analysis targets another deal")
    expected_deal_ref = f"{match_ref}/deal:{deal_number}"
    if response["deal_ref"] != expected_deal_ref:
        raise AnalysisProjectionError("completed-deal deal_ref is invalid")
    seat = _require_int(response["seat"], "seat", minimum=0, maximum=3)

    summary = _require_mapping(response["summary"], "summary")
    expected_summary_keys = (
        _COMPLETED_DEAL_REVIEW_SUMMARY_KEYS if review else _COMPLETED_DEAL_SUMMARY_KEYS
    )
    if set(summary) != expected_summary_keys:
        raise AnalysisProjectionError("completed-deal summary fields are invalid")
    if review:
        _validate_reference_agreement(
            summary["reference_agreement"], "summary.reference_agreement"
        )
    if summary["contract"] not in {"RAMI", "NOLO"}:
        raise AnalysisProjectionError("completed-deal contract is invalid")
    if summary["outcome"] not in {"NOLO", "MADE_RAMI", "STOLEN_RAMI"}:
        raise AnalysisProjectionError("completed-deal outcome is invalid")
    diagnostic_count = _require_int(
        summary["diagnostic_count"],
        "summary.diagnostic_count",
        minimum=0,
        maximum=10,
    )
    _require_int(summary["points"], "summary.points", minimum=0)
    _require_score_pair(summary["score_before"], "summary.score_before")
    _require_score_pair(summary["score_after"], "summary.score_after")
    team_tricks = _require_score_pair(summary["team_tricks"], "summary.team_tricks")
    if sum(team_tricks) != 13:
        raise AnalysisProjectionError("completed-deal team_tricks must total 13")
    analyses = response["analyses"]
    if type(analyses) is not list or len(analyses) != diagnostic_count:
        raise AnalysisProjectionError("completed-deal diagnostic count disagrees")
    if any(
        type(item) is not dict or item.get("deal_number") != deal_number
        for item in analyses
    ):
        raise AnalysisProjectionError("completed-deal analysis contains another deal")

    # Reuse the hardened ranked-decision validation and event binding.  The
    # proxy summary is validation-only and is never returned to the client.
    proxy_summary: dict[str, object] = {
        "deal_count": deal_number + 1,
        "diagnostic_count": diagnostic_count,
        "final_score": summary["score_after"],
        "winner_team": 0,
    }
    if review:
        proxy_summary["reference_agreement"] = summary["reference_agreement"]
    _validate_post_match_diagnostics_response(
        {
            "schema_version": (
                POST_MATCH_REVIEW_SCHEMA_VERSION
                if review
                else POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION
            ),
            "match_ref": match_ref,
            "seat": seat,
            "summary": proxy_summary,
            "analyses": analyses,
        },
        expected_match_ref=match_ref,
        public_events=public_events,
    )
    if bot_review:
        _validate_completed_deal_bot_replay(
            response,
            match_ref=match_ref,
            deal_ref=expected_deal_ref,
            deal_number=deal_number,
            seat=seat,
        )
    try:
        canonical = strict_json_loads(
            canonical_json_bytes(dict(response)).decode("utf-8")
        )
    except Exception as exc:
        raise AnalysisProjectionError(
            "completed-deal analysis is not canonical JSON"
        ) from exc
    if type(canonical) is not dict:
        raise AnalysisProjectionError("completed-deal analysis must remain an object")
    return canonical


def _validate_completed_deal_bot_replay(
    response: Mapping[str, object],
    *,
    match_ref: str,
    deal_ref: str,
    deal_number: int,
    seat: int,
) -> None:
    """Validate the public, post-deal-only replay and comparison extension."""

    deal_id = _require_text(response["deal_id"], "deal_id", 71)
    if not is_sha256_identifier(deal_id):
        raise AnalysisProjectionError("completed-deal deal_id is invalid")
    local_team = _require_int(response["local_team"], "local_team", 0, 1)
    if local_team != seat % 2:
        raise AnalysisProjectionError("completed-deal local_team disagrees with seat")

    hands = response["initial_hands"]
    if type(hands) is not list or len(hands) != 4:
        raise AnalysisProjectionError("completed-deal initial_hands must contain four hands")
    normalized_hands: list[tuple[str, ...]] = []
    for hand_seat, raw_hand in enumerate(hands):
        if type(raw_hand) is not list or len(raw_hand) != 13:
            raise AnalysisProjectionError(
                f"completed-deal initial_hands[{hand_seat}] must contain 13 cards"
            )
        cards = tuple(
            _require_card_code(card, f"initial_hands[{hand_seat}]")
            for card in raw_hand
        )
        if len(set(cards)) != 13:
            raise AnalysisProjectionError("completed-deal hand contains duplicate cards")
        normalized_hands.append(cards)
    if len(set(card for hand in normalized_hands for card in hand)) != 52:
        raise AnalysisProjectionError("completed-deal initial_hands do not form a deck")

    policy = _require_mapping(response["bot_policy"], "bot_policy")
    if set(policy) != _BOT_POLICY_KEYS:
        raise AnalysisProjectionError("completed-deal bot_policy fields are invalid")
    if policy["profile"] != "partner_aware_v1":
        raise AnalysisProjectionError("completed-deal bot policy is invalid")
    _require_text(policy["policy_id"], "bot_policy.policy_id", 256)
    if policy["determinism"] != "deterministic" or policy["analysis_seed"] is not None:
        raise AnalysisProjectionError("completed-deal bot determinism metadata is invalid")
    if policy["bot_seats"] != [0, 1, 2, 3]:
        raise AnalysisProjectionError("completed-deal replay must use four bot seats")

    actual = _validate_review_deal_result(
        response["actual_result"],
        label="actual_result",
        match_ref=match_ref,
        deal_ref=deal_ref,
        deal_number=deal_number,
        hands=normalized_hands,
    )
    bot = _validate_review_deal_result(
        response["bot_replay"],
        label="bot_replay",
        match_ref=match_ref,
        deal_ref=deal_ref,
        deal_number=deal_number,
        hands=normalized_hands,
    )
    for field in ("dealer", "forehand", "score_before"):
        if actual[field] != bot[field]:
            raise AnalysisProjectionError(
                f"completed-deal bot replay {field} differs from the actual deal"
            )

    summary = _require_mapping(response["summary"], "summary")
    expected_summary = {
        "contract": actual["contract"],
        "outcome": actual["outcome"],
        "points": _require_mapping(actual["deal_score"], "actual_result.deal_score")[
            "points"
        ],
        "score_before": actual["score_before"],
        "score_after": actual["score_after"],
        "team_tricks": actual["team_tricks"],
    }
    if any(summary[key] != value for key, value in expected_summary.items()):
        raise AnalysisProjectionError("completed-deal summary disagrees with actual_result")
    _validate_review_comparison(
        response["comparison"],
        actual=actual,
        bot=bot,
        local_team=local_team,
    )


def _validate_review_deal_result(
    value: object,
    *,
    label: str,
    match_ref: str,
    deal_ref: str,
    deal_number: int,
    hands: Sequence[Sequence[str]],
) -> Mapping[str, object]:
    result = _require_mapping(value, label)
    if set(result) != _DEAL_RESULT_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    if result["schema_version"] != "tuppi.engine.deal_result.v1":
        raise AnalysisProjectionError(f"{label}.schema_version is invalid")
    if result["ruleset_id"] != "project_target_v1":
        raise AnalysisProjectionError(f"{label}.ruleset_id is invalid")
    if (
        result["match_ref"] != match_ref
        or result["deal_ref"] != deal_ref
        or result["deal_number"] != deal_number
    ):
        raise AnalysisProjectionError(f"{label} identity is invalid")
    dealer = _require_int(result["dealer"], f"{label}.dealer", 0, 3)
    forehand = _require_int(result["forehand"], f"{label}.forehand", 0, 3)
    if forehand != (dealer + 1) % 4:
        raise AnalysisProjectionError(f"{label}.forehand disagrees with dealer")
    if result["contract"] not in {"RAMI", "NOLO"}:
        raise AnalysisProjectionError(f"{label}.contract is invalid")
    declarer = result["declarer"]
    if result["contract"] == "RAMI":
        _require_int(declarer, f"{label}.declarer", 0, 3)
    elif declarer is not None:
        raise AnalysisProjectionError(f"{label}.NOLO declarer must be null")
    _require_int(result["first_leader"], f"{label}.first_leader", 0, 3)
    if result["outcome"] not in {"NOLO", "MADE_RAMI", "STOLEN_RAMI"}:
        raise AnalysisProjectionError(f"{label}.outcome is invalid")
    score_before = _require_score_pair(result["score_before"], f"{label}.score_before")
    score_after = _require_score_pair(result["score_after"], f"{label}.score_after")
    if type(result["match_terminal"]) is not bool:
        raise AnalysisProjectionError(f"{label}.match_terminal must be a boolean")
    next_dealer = result["next_dealer"]
    if next_dealer is not None:
        _require_int(next_dealer, f"{label}.next_dealer", 0, 3)
    event_log_id = _require_text(result["event_log_id"], f"{label}.event_log_id", 71)
    if not is_sha256_identifier(event_log_id):
        raise AnalysisProjectionError(f"{label}.event_log_id is invalid")
    if type(result["events"]) is not list or not result["events"]:
        raise AnalysisProjectionError(f"{label}.events must be a nonempty array")

    shows = result["show_actions"]
    if type(shows) is not list or not 1 <= len(shows) <= 4:
        raise AnalysisProjectionError(f"{label}.show_actions are invalid")
    expected_show_seats = tuple((forehand + offset) % 4 for offset in range(len(shows)))
    for index, raw in enumerate(shows):
        show = _require_mapping(raw, f"{label}.show_actions[{index}]")
        if set(show) != _SHOW_RESULT_KEYS:
            raise AnalysisProjectionError(f"{label}.show_actions[{index}] fields are invalid")
        show_seat = _require_int(show["seat"], f"{label}.show_actions[{index}].seat", 0, 3)
        if show_seat != expected_show_seats[index]:
            raise AnalysisProjectionError(f"{label}.show_actions are out of order")
        card = _require_card_code(
            show["shown_card"], f"{label}.show_actions[{index}].shown_card"
        )
        if card not in hands[show_seat]:
            raise AnalysisProjectionError(f"{label} shown card is not in the seat's hand")
        if show["declared_contract"] not in {"RAMI", "NOLO"}:
            raise AnalysisProjectionError(f"{label} shown contract is invalid")
        if type(show["verbal_required"]) is not bool:
            raise AnalysisProjectionError(f"{label} verbal_required must be a boolean")
    if result["contract"] == "RAMI":
        if shows[-1]["declared_contract"] != "RAMI":
            raise AnalysisProjectionError(f"{label} RAMI showing did not stop on RAMI")
    elif len(shows) != 4 or any(show["declared_contract"] != "NOLO" for show in shows):
        raise AnalysisProjectionError(f"{label} NOLO showing must contain four NOLO actions")

    tricks = result["tricks"]
    if type(tricks) is not list or len(tricks) != 13:
        raise AnalysisProjectionError(f"{label}.tricks must contain 13 tricks")
    played_by_seat: list[list[str]] = [[], [], [], []]
    winner_counts = [0, 0]
    for index, raw in enumerate(tricks):
        trick = _require_mapping(raw, f"{label}.tricks[{index}]")
        if set(trick) != _TRICK_RESULT_KEYS or trick["trick_index"] != index:
            raise AnalysisProjectionError(f"{label}.tricks[{index}] fields are invalid")
        _require_int(trick["leader"], f"{label}.tricks[{index}].leader", 0, 3)
        winner = _require_int(trick["winner"], f"{label}.tricks[{index}].winner", 0, 3)
        winner_counts[winner % 2] += 1
        plays = trick["plays"]
        if type(plays) is not list or len(plays) != 4:
            raise AnalysisProjectionError(f"{label}.tricks[{index}].plays are invalid")
        for raw_play in plays:
            play = _require_mapping(raw_play, f"{label}.tricks[{index}].plays")
            if set(play) != _PLAY_RESULT_KEYS:
                raise AnalysisProjectionError(f"{label} play fields are invalid")
            play_seat = _require_int(play["seat"], f"{label} play seat", 0, 3)
            played_by_seat[play_seat].append(
                _require_card_code(play["card"], f"{label} played card")
            )
    if any(
        len(played_by_seat[played_seat]) != 13
        or set(played_by_seat[played_seat]) != set(hands[played_seat])
        for played_seat in range(4)
    ):
        raise AnalysisProjectionError(f"{label} transcript does not use the original hands")
    team_tricks = _require_score_pair(result["team_tricks"], f"{label}.team_tricks")
    if team_tricks != tuple(winner_counts) or sum(team_tricks) != 13:
        raise AnalysisProjectionError(f"{label}.team_tricks disagree with the transcript")

    deal_score = _require_mapping(result["deal_score"], f"{label}.deal_score")
    if set(deal_score) != _DEAL_SCORE_KEYS:
        raise AnalysisProjectionError(f"{label}.deal_score fields are invalid")
    _require_int(deal_score["winner_team"], f"{label}.deal_score.winner_team", 0, 1)
    _require_int(deal_score["points"], f"{label}.deal_score.points", 0, 56)
    declaring_team = deal_score["declaring_team"]
    if declaring_team is not None:
        _require_int(declaring_team, f"{label}.deal_score.declaring_team", 0, 1)
    if type(deal_score["stolen_rami"]) is not bool:
        raise AnalysisProjectionError(f"{label}.deal_score.stolen_rami must be a boolean")
    # The production engine is the final scoring validator.  These checks bind
    # the redundant envelope fields before cached transcripts are replayed.
    if result["contract"] == "NOLO" and (
        declaring_team is not None or deal_score["stolen_rami"]
    ):
        raise AnalysisProjectionError(f"{label}.NOLO deal_score is invalid")
    if result["contract"] == "RAMI" and declaring_team != int(declarer) % 2:
        raise AnalysisProjectionError(f"{label}.RAMI declaring team is invalid")
    if score_before == score_after:
        raise AnalysisProjectionError(f"{label} score did not transition")
    return result


def _validate_review_comparison(
    value: object,
    *,
    actual: Mapping[str, object],
    bot: Mapping[str, object],
    local_team: int,
) -> None:
    comparison = _require_mapping(value, "comparison")
    if set(comparison) != _COMPARISON_KEYS:
        raise AnalysisProjectionError("completed-deal comparison fields are invalid")
    if comparison["local_team"] != local_team:
        raise AnalysisProjectionError("completed-deal comparison local_team disagrees")
    for key in _COMPARISON_KEYS - {"local_team"}:
        if type(comparison[key]) is not int:
            raise AnalysisProjectionError(f"comparison.{key} must be an integer")

    actual_tricks = _require_score_pair(actual["team_tricks"], "actual_result.team_tricks")[
        local_team
    ]
    bot_tricks = _require_score_pair(bot["team_tricks"], "bot_replay.team_tricks")[
        local_team
    ]
    actual_score = _require_mapping(actual["deal_score"], "actual_result.deal_score")
    bot_score = _require_mapping(bot["deal_score"], "bot_replay.deal_score")
    actual_points = (
        actual_score["points"]
        if actual_score["winner_team"] == local_team
        else -actual_score["points"]
    )
    bot_points = (
        bot_score["points"]
        if bot_score["winner_team"] == local_team
        else -bot_score["points"]
    )
    actual_after = _require_score_pair(actual["score_after"], "actual_result.score_after")
    bot_after = _require_score_pair(bot["score_after"], "bot_replay.score_after")
    opponent = 1 - local_team
    actual_margin = actual_after[local_team] - actual_after[opponent]
    bot_margin = bot_after[local_team] - bot_after[opponent]
    expected = {
        "local_team": local_team,
        "actual_tricks": actual_tricks,
        "bot_tricks": bot_tricks,
        "trick_difference": bot_tricks - actual_tricks,
        "actual_deal_points": actual_points,
        "bot_deal_points": bot_points,
        "deal_point_difference": bot_points - actual_points,
        "actual_match_score_after": actual_after[local_team],
        "bot_match_score_after": bot_after[local_team],
        "match_score_difference": bot_after[local_team] - actual_after[local_team],
        "actual_score_margin_after": actual_margin,
        "bot_score_margin_after": bot_margin,
        "match_score_margin_difference": bot_margin - actual_margin,
    }
    if comparison != expected:
        raise AnalysisProjectionError("completed-deal comparison arithmetic is invalid")


def _require_card_code(value: object, label: str) -> str:
    card = _require_text(value, label, 3)
    if _CARD_CODE_PATTERN.fullmatch(card) is None:
        raise AnalysisProjectionError(f"{label} is not a canonical card code")
    return card


_V2_RESPONSE_KEYS = frozenset(
    {"schema_version", "match_ref", "seat", "summary", "analyses"}
)
_V2_SUMMARY_KEYS = frozenset(
    {"deal_count", "diagnostic_count", "final_score", "winner_team"}
)
_V2_ANALYSIS_KEYS = _ANALYSIS_KEYS | frozenset(
    {
        "confidence",
        "source_id",
        "reason_code",
        "legal_actions",
        "equivalent_actions",
        "context",
        "quantitative",
    }
)
_V2_CONTEXT_KEYS = frozenset(
    {"contract", "player_role", "trick_number", "current_trick", "score", "team_tricks"}
)
_V2_QUANTITATIVE_KEYS = frozenset(
    {"metric", "chosen_value", "best_value", "difference", "unit"}
)
_V2_SOURCES = frozenset({"Exact", "Rule-based", "Reference"})
_V2_CONFIDENCE = frozenset(
    {"perfect_information_exact", "objective_rule_pattern", "reference_policy_only"}
)
_V2_PLAYER_ROLES = frozenset(
    {"showing_player", "nolo_player", "declarer", "declarer_partner", "defender"}
)

# --------------------------------------------------------------------------- v3
#
# v3 adds three review fields the earlier contract deliberately withheld:
# aggregate reference agreement, the played action's position in the reference
# policy's own ranking, and the scalars behind a RAMI/NOLO choice.
#
# This is a deliberate, documented widening of the client boundary, not an
# accident.  It stays narrow in three ways: every field is constructed here
# rather than forwarded from a ``DecisionDiagnostics`` mapping, the notes come
# from a closed token set, and the private-key guard below is unchanged, so a
# raw diagnostics dictionary still fails closed.  Nothing here reveals another
# seat's card, a hidden hand, an observation digest, or any search/belief value.
_V3_SUMMARY_KEYS = _V2_SUMMARY_KEYS | frozenset({"reference_agreement"})
_V3_ANALYSIS_KEYS = _V2_ANALYSIS_KEYS | frozenset(
    {"reference_ranking", "contract_reasoning"}
)
_AGREEMENT_KEYS = frozenset(
    {
        "reference_profile",
        "decision_count",
        "forced_decision_count",
        "match_count",
        "showing_decision_count",
        "showing_match_count",
        "trick_decision_count",
        "trick_match_count",
        "indifferent_count",
        "top_rank_count",
        "second_rank_count",
        "lower_rank_count",
        "mean_played_rank",
        "mean_legal_action_count",
    }
)
_AGREEMENT_COUNT_KEYS = tuple(
    sorted(
        _AGREEMENT_KEYS - {"reference_profile", "mean_played_rank", "mean_legal_action_count"}
    )
)
_RANKING_KEYS = frozenset(
    {
        "reference_profile",
        "reference_action",
        "played_rank",
        "legal_action_count",
        "strictly_better_count",
        "reference_indifferent",
    }
)
_CONTRACT_REASONING_KEYS = frozenset(
    {"declared_contract", "reference_contract", "metrics", "verdict_notes"}
)
_METRIC_KEYS = frozenset({"name", "value"})
_METRIC_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
#: The closed set of showing-verdict tokens a client may receive.  A policy
#: reason code outside this set is dropped rather than forwarded.
VERDICT_NOTES = frozenset(
    {
        "rami_threshold_met",
        "nolo_veto_applied",
        "rami_declared",
        "nolo_declared",
        "match_protect_terminal_lead",
        "match_reset_opponent_rise",
        "legacy_protect_large_rise",
        "legacy_gamble_for_reset",
        "legacy_expected_value_choice",
    }
)


def _validate_post_match_diagnostics_response(
    response: Mapping[str, object],
    *,
    expected_match_ref: str | None,
    public_events: Sequence[Mapping[str, object]] | None,
) -> dict[str, object]:
    """Validate the real, seat-scoped ranked diagnostics response (v2 or v3)."""

    _reject_client_private_keys(response)
    schema_version = response.get("schema_version")
    if schema_version not in RANKED_ANALYSIS_SCHEMA_VERSIONS:
        raise AnalysisProjectionError("unsupported ranked analysis schema_version")
    review = schema_version == POST_MATCH_REVIEW_SCHEMA_VERSION
    if set(response) != _V2_RESPONSE_KEYS:
        raise AnalysisProjectionError("post-match diagnostics response fields are invalid")
    match_ref = _require_text(response["match_ref"], "match_ref", 96)
    if not is_valid_match_ref(match_ref):
        raise AnalysisProjectionError("post-match diagnostics match_ref is invalid")
    if expected_match_ref is not None and match_ref != expected_match_ref:
        raise AnalysisProjectionError("post-match diagnostics belongs to another match")
    seat = _require_int(response["seat"], "seat", minimum=0, maximum=3)

    summary = _require_mapping(response["summary"], "summary")
    if set(summary) != (_V3_SUMMARY_KEYS if review else _V2_SUMMARY_KEYS):
        raise AnalysisProjectionError("post-match diagnostics summary fields are invalid")
    deal_count = _require_int(summary["deal_count"], "summary.deal_count", minimum=1)
    diagnostic_count = _require_int(
        summary["diagnostic_count"], "summary.diagnostic_count", minimum=0, maximum=10
    )
    _require_score_pair(summary["final_score"], "summary.final_score")
    _require_int(summary["winner_team"], "summary.winner_team", minimum=0, maximum=1)
    if review:
        _validate_reference_agreement(
            summary["reference_agreement"], "summary.reference_agreement"
        )

    analyses = response["analyses"]
    if type(analyses) is not list:
        raise AnalysisProjectionError("post-match diagnostics analyses must be an array")
    if len(analyses) != diagnostic_count or len(analyses) > 10:
        raise AnalysisProjectionError("post-match diagnostics count disagrees with summary")
    seen_ids: set[str] = set()
    seen_decisions: set[tuple[int, int]] = set()
    for index, raw in enumerate(analyses):
        analysis = _require_mapping(raw, f"analyses[{index}]")
        _validate_v2_analysis(
            analysis,
            match_ref=match_ref,
            response_seat=seat,
            deal_count=deal_count,
            schema_version=schema_version,
            label=f"analyses[{index}]",
        )
        analysis_id = analysis["analysis_id"]
        assert isinstance(analysis_id, str)
        if analysis_id in seen_ids:
            raise AnalysisProjectionError("post-match diagnostics ids are duplicated")
        seen_ids.add(analysis_id)
        decision_key = (analysis["event_index"], analysis["seat"])
        if decision_key in seen_decisions:
            raise AnalysisProjectionError("post-match diagnostics repeat a decision")
        seen_decisions.add(decision_key)

    if public_events is not None:
        _validate_response_public_events(response, public_events)
    try:
        canonical = strict_json_loads(
            canonical_json_bytes(dict(response)).decode("utf-8")
        )
    except Exception as exc:
        raise AnalysisProjectionError("post-match diagnostics is not canonical JSON") from exc
    if type(canonical) is not dict:
        raise AnalysisProjectionError("post-match diagnostics must remain an object")
    return canonical


def _validate_v2_analysis(
    analysis: Mapping[str, object],
    *,
    match_ref: str,
    response_seat: int,
    deal_count: int,
    label: str,
    schema_version: str = POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION,
) -> None:
    review = schema_version == POST_MATCH_REVIEW_SCHEMA_VERSION
    if set(analysis) != (_V3_ANALYSIS_KEYS if review else _V2_ANALYSIS_KEYS):
        raise AnalysisProjectionError(f"{label} fields are invalid")
    if analysis["schema_version"] != schema_version:
        raise AnalysisProjectionError(f"{label} schema_version is invalid")
    if analysis["match_ref"] != match_ref:
        raise AnalysisProjectionError(f"{label}.match_ref disagrees")
    analysis_id = _require_text(analysis["analysis_id"], f"{label}.analysis_id", 128)
    if _ANALYSIS_ID_PATTERN.fullmatch(analysis_id) is None:
        raise AnalysisProjectionError(f"{label}.analysis_id is invalid")
    _require_int(analysis["event_index"], f"{label}.event_index", minimum=0)
    _require_int(
        analysis["deal_number"],
        f"{label}.deal_number",
        minimum=0,
        maximum=deal_count - 1,
    )
    seat = _require_int(analysis["seat"], f"{label}.seat", minimum=0, maximum=3)
    if seat != response_seat:
        raise AnalysisProjectionError(f"{label}.seat disagrees with authenticated seat")
    decision_kind = analysis["decision_kind"]
    if decision_kind not in {"SHOWING", "TRICK_PLAY"}:
        raise AnalysisProjectionError(f"{label}.decision_kind is invalid")
    trick_index = analysis["trick_index"]
    if decision_kind == "SHOWING":
        if trick_index is not None:
            raise AnalysisProjectionError(f"{label}.showing trick_index must be null")
    else:
        _require_int(trick_index, f"{label}.trick_index", minimum=0, maximum=12)

    played, played_data = _canonical_action(
        _require_mapping(analysis["played_action"], f"{label}.played_action"),
        f"{label}.played_action",
    )
    recommended, recommended_data = _canonical_action(
        _require_mapping(
            analysis["recommended_action"], f"{label}.recommended_action"
        ),
        f"{label}.recommended_action",
    )
    for action, action_name in (
        (played, "played_action"),
        (recommended, "recommended_action"),
    ):
        _validate_action_for_seat(action, seat, f"{label}.{action_name}")
        _validate_phase_action(action, decision_kind, f"{label}.{action_name}")
    if played_data == recommended_data:
        raise AnalysisProjectionError(f"{label} must compare different actions")

    for field_name, maximum in (
        ("title", 200),
        ("summary", 2000),
        ("recommendation", 2000),
        ("source_id", 128),
        ("reason_code", 128),
    ):
        _require_text(analysis[field_name], f"{label}.{field_name}", maximum)
    source = analysis["source"]
    confidence = analysis["confidence"]
    if source not in _V2_SOURCES:
        raise AnalysisProjectionError(f"{label}.source is invalid")
    if confidence not in _V2_CONFIDENCE:
        raise AnalysisProjectionError(f"{label}.confidence is invalid")
    expected_confidence = {
        "Exact": "perfect_information_exact",
        "Rule-based": "objective_rule_pattern",
        "Reference": "reference_policy_only",
    }[source]
    if confidence != expected_confidence:
        raise AnalysisProjectionError(f"{label}.source and confidence disagree")
    if not _require_text_array(analysis["explanation"], f"{label}.explanation", 1000):
        raise AnalysisProjectionError(f"{label}.explanation must be nonempty")
    if not _require_text_array(analysis["limitations"], f"{label}.limitations", 1000):
        raise AnalysisProjectionError(f"{label}.limitations must be nonempty")

    legal_actions = _validate_v2_action_array(
        analysis["legal_actions"],
        seat=seat,
        decision_kind=decision_kind,
        label=f"{label}.legal_actions",
        require_nonempty=True,
    )
    if tuple(sorted(played_data.items())) not in legal_actions:
        raise AnalysisProjectionError(f"{label}.played_action is not in legal_actions")
    if tuple(sorted(recommended_data.items())) not in legal_actions:
        raise AnalysisProjectionError(f"{label}.recommended_action is not in legal_actions")
    equivalent_actions = _validate_v2_action_array(
        analysis["equivalent_actions"],
        seat=seat,
        decision_kind=decision_kind,
        label=f"{label}.equivalent_actions",
        require_nonempty=False,
    )
    if not equivalent_actions <= legal_actions:
        raise AnalysisProjectionError(f"{label}.equivalent_actions are not legal actions")

    alternatives = analysis["alternatives"]
    if type(alternatives) is not list or len(alternatives) != 1:
        raise AnalysisProjectionError(f"{label}.alternatives must contain one suggestion")
    alternative = _require_mapping(alternatives[0], f"{label}.alternatives[0]")
    if set(alternative) != _ALTERNATIVE_KEYS:
        raise AnalysisProjectionError(f"{label}.alternatives[0] fields are invalid")
    alternative_action, alternative_data = _canonical_action(
        _require_mapping(alternative["action"], f"{label}.alternatives[0].action"),
        f"{label}.alternatives[0].action",
    )
    _validate_action_for_seat(alternative_action, seat, f"{label}.alternatives[0].action")
    _validate_phase_action(
        alternative_action, decision_kind, f"{label}.alternatives[0].action"
    )
    if alternative_data != recommended_data:
        raise AnalysisProjectionError(f"{label}.first alternative is not recommended_action")
    for key, maximum in (("title", 200), ("assessment", 200), ("reason", 1000)):
        _require_text(alternative[key], f"{label}.alternatives[0].{key}", maximum)
    if _require_int(alternative["rank"], f"{label}.alternatives[0].rank", minimum=1) != 1:
        raise AnalysisProjectionError(f"{label}.alternatives[0].rank must be one")

    context = _require_mapping(analysis["context"], f"{label}.context")
    if set(context) != _V2_CONTEXT_KEYS:
        raise AnalysisProjectionError(f"{label}.context fields are invalid")
    if context["contract"] is not None and context["contract"] not in {"RAMI", "NOLO"}:
        raise AnalysisProjectionError(f"{label}.context.contract is invalid")
    player_role = _require_text(
        context["player_role"], f"{label}.context.player_role", 64
    )
    if player_role not in _V2_PLAYER_ROLES:
        raise AnalysisProjectionError(f"{label}.context.player_role is invalid")
    trick_number = context["trick_number"]
    if decision_kind == "SHOWING":
        if trick_number is not None:
            raise AnalysisProjectionError(f"{label}.context.trick_number must be null")
    else:
        _require_int(trick_number, f"{label}.context.trick_number", minimum=1, maximum=13)
        if trick_number != trick_index + 1:
            raise AnalysisProjectionError(f"{label}.context.trick_number disagrees")
    current_trick = context["current_trick"]
    if type(current_trick) is not list or len(current_trick) > 3:
        raise AnalysisProjectionError(f"{label}.context.current_trick is invalid")
    for play_index, play_raw in enumerate(current_trick):
        play = _require_mapping(play_raw, f"{label}.context.current_trick[{play_index}]")
        if set(play) != {"seat", "card"}:
            raise AnalysisProjectionError(f"{label}.context.current_trick fields are invalid")
        _require_int(play["seat"], "current trick seat", minimum=0, maximum=3)
        _canonical_action(
            {"type": "play", "seat": play["seat"], "card": play["card"]},
            "current trick card",
        )
    _require_score_pair(context["score"], f"{label}.context.score")
    _require_score_pair(context["team_tricks"], f"{label}.context.team_tricks")

    quantitative = analysis["quantitative"]
    if quantitative is not None:
        value = _require_mapping(quantitative, f"{label}.quantitative")
        if set(value) != _V2_QUANTITATIVE_KEYS:
            raise AnalysisProjectionError(f"{label}.quantitative fields are invalid")
        _require_text(value["metric"], f"{label}.quantitative.metric", 128)
        _require_text(value["unit"], f"{label}.quantitative.unit", 64)
        for key in ("chosen_value", "best_value", "difference"):
            number = value[key]
            if type(number) not in {int, float} or isinstance(number, bool):
                raise AnalysisProjectionError(f"{label}.quantitative.{key} is not numeric")
            if not math.isfinite(float(number)):
                raise AnalysisProjectionError(f"{label}.quantitative.{key} is not finite")
        if float(value["difference"]) < 0:
            raise AnalysisProjectionError(f"{label}.quantitative.difference is negative")
        if source != "Exact":
            raise AnalysisProjectionError(f"{label}.quantitative requires Exact source")
    elif source == "Exact":
        raise AnalysisProjectionError(f"{label}.Exact diagnostic requires quantitative values")

    if not review:
        return
    _validate_reference_ranking(
        analysis["reference_ranking"],
        seat=seat,
        decision_kind=decision_kind,
        played_data=played_data,
        legal_actions=legal_actions,
        label=f"{label}.reference_ranking",
    )
    reasoning = analysis["contract_reasoning"]
    if decision_kind == "SHOWING":
        declared = played.declared_contract.value
        _validate_contract_reasoning(
            reasoning,
            declared_contract=declared,
            label=f"{label}.contract_reasoning",
        )
    elif reasoning is not None:
        raise AnalysisProjectionError(
            f"{label}.contract_reasoning belongs only to a showing decision"
        )


def _validate_reference_agreement(value: object, label: str) -> None:
    """Check the aggregate agreement block for internal consistency."""

    agreement = _require_mapping(value, label)
    if set(agreement) != _AGREEMENT_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    _require_text(agreement["reference_profile"], f"{label}.reference_profile", 64)
    counts = {
        key: _require_int(agreement[key], f"{label}.{key}", minimum=0)
        for key in _AGREEMENT_COUNT_KEYS
    }
    decisions = counts["decision_count"]
    if counts["showing_decision_count"] + counts["trick_decision_count"] != decisions:
        raise AnalysisProjectionError(f"{label} phase decision counts do not total")
    if counts["showing_match_count"] + counts["trick_match_count"] != counts["match_count"]:
        raise AnalysisProjectionError(f"{label} phase match counts do not total")
    rank_total = (
        counts["top_rank_count"] + counts["second_rank_count"] + counts["lower_rank_count"]
    )
    if rank_total != decisions:
        raise AnalysisProjectionError(f"{label} rank buckets do not total the decisions")
    # The reference's own pick is always rank one, so agreements are exactly the
    # top-rank decisions.  Anything else means the ranking and the match counter
    # were derived from different comparisons.
    if counts["match_count"] != counts["top_rank_count"]:
        raise AnalysisProjectionError(f"{label} match count disagrees with top-rank count")
    for key in ("match_count", "indifferent_count", "forced_decision_count"):
        if counts[key] > decisions:
            raise AnalysisProjectionError(f"{label}.{key} exceeds the decision count")
    # A forced decision has one legal action, so it is always an agreement.
    if counts["forced_decision_count"] > counts["match_count"]:
        raise AnalysisProjectionError(f"{label} forced decisions exceed the agreements")
    if counts["showing_match_count"] > counts["showing_decision_count"]:
        raise AnalysisProjectionError(f"{label}.showing_match_count exceeds its decisions")
    if counts["trick_match_count"] > counts["trick_decision_count"]:
        raise AnalysisProjectionError(f"{label}.trick_match_count exceeds its decisions")
    mean_rank = _require_finite(agreement["mean_played_rank"], f"{label}.mean_played_rank")
    mean_legal = _require_finite(
        agreement["mean_legal_action_count"], f"{label}.mean_legal_action_count"
    )
    if decisions == 0:
        if mean_rank != 0.0 or mean_legal != 0.0:
            raise AnalysisProjectionError(f"{label} means must be zero without decisions")
        return
    if mean_rank < 1.0:
        raise AnalysisProjectionError(f"{label}.mean_played_rank must be at least one")
    if mean_legal < 1.0:
        raise AnalysisProjectionError(f"{label}.mean_legal_action_count must be at least one")
    if mean_rank > mean_legal:
        raise AnalysisProjectionError(f"{label}.mean_played_rank exceeds the legal mean")


def _validate_reference_ranking(
    value: object,
    *,
    seat: int,
    decision_kind: str,
    played_data: Mapping[str, object],
    legal_actions: set[tuple[tuple[str, object], ...]],
    label: str,
) -> None:
    """Check one decision's position inside the reference policy's ranking."""

    ranking = _require_mapping(value, label)
    if set(ranking) != _RANKING_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    _require_text(ranking["reference_profile"], f"{label}.reference_profile", 64)
    action, action_data = _canonical_action(
        _require_mapping(ranking["reference_action"], f"{label}.reference_action"),
        f"{label}.reference_action",
    )
    _validate_action_for_seat(action, seat, f"{label}.reference_action")
    _validate_phase_action(action, decision_kind, f"{label}.reference_action")
    if tuple(sorted(action_data.items())) not in legal_actions:
        raise AnalysisProjectionError(f"{label}.reference_action is not a legal action")
    legal_count = _require_int(
        ranking["legal_action_count"], f"{label}.legal_action_count", minimum=1
    )
    if legal_count != len(legal_actions):
        raise AnalysisProjectionError(f"{label}.legal_action_count disagrees")
    played_rank = _require_int(
        ranking["played_rank"], f"{label}.played_rank", minimum=1, maximum=legal_count
    )
    strictly_better = _require_int(
        ranking["strictly_better_count"],
        f"{label}.strictly_better_count",
        minimum=0,
        maximum=legal_count - 1,
    )
    if strictly_better >= played_rank:
        raise AnalysisProjectionError(
            f"{label}.strictly_better_count is inconsistent with played_rank"
        )
    indifferent = ranking["reference_indifferent"]
    if type(indifferent) is not bool:
        raise AnalysisProjectionError(f"{label}.reference_indifferent must be a boolean")

    # The three states are mutually exclusive and fully determined:
    #   agreed       -> the played action *is* the reference pick: rank 1, none better.
    #   indifferent  -> a different action that scored identically; only the
    #                   documented engine-index tie-break separated them.
    #   disagreement -> at least one action the reference scored strictly higher.
    agreed = action_data == dict(played_data)
    if agreed:
        if played_rank != 1 or strictly_better != 0 or indifferent:
            raise AnalysisProjectionError(
                f"{label}.agreement must rank first with nothing better and no indifference"
            )
        return
    if indifferent:
        if strictly_better != 0 or played_rank == 1:
            raise AnalysisProjectionError(
                f"{label}.reference_indifferent contradicts the recorded position"
            )
    elif strictly_better < 1:
        raise AnalysisProjectionError(
            f"{label}.disagreement requires a strictly better action or indifference"
        )


def _validate_contract_reasoning(
    value: object,
    *,
    declared_contract: str,
    label: str,
) -> None:
    """Check the scalars and closed-set notes behind a RAMI/NOLO comparison."""

    reasoning = _require_mapping(value, label)
    if set(reasoning) != _CONTRACT_REASONING_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    for key in ("declared_contract", "reference_contract"):
        if reasoning[key] not in {"RAMI", "NOLO"}:
            raise AnalysisProjectionError(f"{label}.{key} is invalid")
    if reasoning["declared_contract"] != declared_contract:
        raise AnalysisProjectionError(f"{label}.declared_contract disagrees with the action")
    metrics = reasoning["metrics"]
    if type(metrics) is not list or not metrics:
        raise AnalysisProjectionError(f"{label}.metrics must be a nonempty array")
    seen: set[str] = set()
    for index, raw in enumerate(metrics):
        metric = _require_mapping(raw, f"{label}.metrics[{index}]")
        if set(metric) != _METRIC_KEYS:
            raise AnalysisProjectionError(f"{label}.metrics[{index}] fields are invalid")
        name = _require_text(metric["name"], f"{label}.metrics[{index}].name", 64)
        if _METRIC_NAME_PATTERN.fullmatch(name) is None:
            raise AnalysisProjectionError(f"{label}.metrics[{index}].name is invalid")
        if name in seen:
            raise AnalysisProjectionError(f"{label}.metrics repeat {name}")
        seen.add(name)
        _require_finite(metric["value"], f"{label}.metrics[{index}].value")
    notes = _require_text_array(reasoning["verdict_notes"], f"{label}.verdict_notes", 64)
    if len(set(notes)) != len(notes):
        raise AnalysisProjectionError(f"{label}.verdict_notes are duplicated")
    unknown = sorted(set(notes) - VERDICT_NOTES)
    if unknown:
        raise AnalysisProjectionError(f"{label}.verdict_notes are not recognised: {unknown}")


def _require_finite(value: object, label: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise AnalysisProjectionError(f"{label} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise AnalysisProjectionError(f"{label} is not finite")
    return number


def _validate_v2_action_array(
    value: object,
    *,
    seat: int,
    decision_kind: str,
    label: str,
    require_nonempty: bool,
) -> set[tuple[tuple[str, object], ...]]:
    if type(value) is not list or (require_nonempty and not value):
        raise AnalysisProjectionError(f"{label} must be an array")
    actions: set[tuple[tuple[str, object], ...]] = set()
    for index, raw in enumerate(value):
        action, data = _canonical_action(
            _require_mapping(raw, f"{label}[{index}]"), f"{label}[{index}]"
        )
        _validate_action_for_seat(action, seat, f"{label}[{index}]")
        _validate_phase_action(action, decision_kind, f"{label}[{index}]")
        key = tuple(sorted(data.items()))
        if key in actions:
            raise AnalysisProjectionError(f"{label} contains duplicate actions")
        actions.add(key)
    return actions


def _require_score_pair(value: object, label: str) -> tuple[int, int]:
    if type(value) is not list or len(value) != 2:
        raise AnalysisProjectionError(f"{label} must contain two integers")
    first = _require_int(value[0], f"{label}[0]", minimum=0)
    second = _require_int(value[1], f"{label}[1]", minimum=0)
    return first, second


def _validate_response_public_events(
    response: Mapping[str, object],
    public_events: Sequence[Mapping[str, object]],
) -> None:
    """Bind every stored analysis to the authoritative public event log."""

    match_ref = response["match_ref"]
    assert isinstance(match_ref, str)
    by_index: dict[int, Mapping[str, object]] = {}
    for event in public_events:
        event_mapping = _require_mapping(event, "public event")
        event_index = _require_int(
            event_mapping.get("event_index"),
            "public event event_index",
            minimum=0,
        )
        if event_index in by_index:
            raise AnalysisProjectionError("public event indices are duplicated")
        if event_mapping.get("match_ref") != match_ref:
            raise AnalysisProjectionError("public event belongs to another match")
        if event_mapping.get("schema_version") != "tuppi.engine.public_event.v1":
            raise AnalysisProjectionError("public event schema_version is invalid")
        by_index[event_index] = event_mapping

    analyses = response["analyses"]
    assert isinstance(analyses, list)
    for index, raw_analysis in enumerate(analyses):
        analysis = _require_mapping(raw_analysis, f"analyses[{index}]")
        event_index = analysis["event_index"]
        assert isinstance(event_index, int)
        event = by_index.get(event_index)
        if event is None:
            raise AnalysisProjectionError(
                f"analyses[{index}] event_index is not in public history"
            )
        decision_kind = analysis["decision_kind"]
        expected_type = "show_accepted" if decision_kind == "SHOWING" else "card_played"
        if event.get("event_type") != expected_type:
            raise AnalysisProjectionError(
                f"analyses[{index}] event type does not match decision kind"
            )
        deal_ref = event.get("deal_ref")
        prefix = f"{match_ref}/deal:"
        if not isinstance(deal_ref, str) or not deal_ref.startswith(prefix):
            raise AnalysisProjectionError("public event deal_ref is invalid")
        deal_suffix = deal_ref.removeprefix(prefix)
        if not deal_suffix.isdigit() or int(deal_suffix) != analysis["deal_number"]:
            raise AnalysisProjectionError(
                f"analyses[{index}] deal_number disagrees with public history"
            )
        payload = _require_mapping(event.get("payload"), "public event payload")
        _, played_action = _canonical_action(
            _require_mapping(analysis["played_action"], "played_action"),
            "played_action",
        )
        if decision_kind == "SHOWING":
            expected_action = {
                "type": "show",
                "seat": payload.get("seat"),
                "shown_card": payload.get("shown_card"),
                "declared_contract": payload.get("declared_contract"),
            }
            if played_action != expected_action:
                raise AnalysisProjectionError(
                    f"analyses[{index}] played action disagrees with public history"
                )
        else:
            expected_action = {
                "type": "play",
                "seat": payload.get("seat"),
                "card": payload.get("card"),
            }
            if played_action != expected_action:
                raise AnalysisProjectionError(
                    f"analyses[{index}] played action disagrees with public history"
                )
            if analysis["trick_index"] != payload.get("trick_index"):
                raise AnalysisProjectionError(
                    f"analyses[{index}] trick_index disagrees with public history"
                )


def _validate_projected_analysis(
    analysis: Mapping[str, object], *, match_ref: str, label: str
) -> None:
    if set(analysis) != _ANALYSIS_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    if analysis["schema_version"] != POST_MATCH_ANALYSIS_SCHEMA_VERSION:
        raise AnalysisProjectionError(f"{label} schema_version is invalid")
    analysis_id = _require_text(analysis["analysis_id"], f"{label}.analysis_id", 128)
    if _ANALYSIS_ID_PATTERN.fullmatch(analysis_id) is None:
        raise AnalysisProjectionError(f"{label}.analysis_id is invalid")
    if analysis["match_ref"] != match_ref:
        raise AnalysisProjectionError(f"{label}.match_ref disagrees")
    _require_int(analysis["event_index"], f"{label}.event_index", minimum=0)
    _require_int(analysis["deal_number"], f"{label}.deal_number", minimum=0)
    trick_index = analysis["trick_index"]
    if trick_index is not None:
        _require_int(trick_index, f"{label}.trick_index", minimum=0, maximum=12)
    seat = _require_int(analysis["seat"], f"{label}.seat", minimum=0, maximum=3)
    decision_kind = analysis["decision_kind"]
    if decision_kind not in {"SHOWING", "TRICK_PLAY"}:
        raise AnalysisProjectionError(f"{label}.decision_kind is invalid")
    if decision_kind == "SHOWING" and trick_index is not None:
        raise AnalysisProjectionError(f"{label}.showing trick_index must be null")
    if decision_kind == "TRICK_PLAY" and trick_index is None:
        raise AnalysisProjectionError(f"{label}.trick-play trick_index is required")

    for action_name in ("played_action", "recommended_action"):
        action, _ = _canonical_action(
            _require_mapping(analysis[action_name], f"{label}.{action_name}"),
            f"{label}.{action_name}",
        )
        _validate_action_for_seat(action, seat, f"{label}.{action_name}")
        _validate_phase_action(action, decision_kind, f"{label}.{action_name}")
    for field_name, maximum in (
        ("title", 200),
        ("summary", 2000),
        ("recommendation", 2000),
        ("source", 128),
    ):
        _require_text(analysis[field_name], f"{label}.{field_name}", maximum)
    _require_text_array(analysis["explanation"], f"{label}.explanation", 1000)
    _require_text_array(analysis["limitations"], f"{label}.limitations", 1000)

    alternatives = analysis["alternatives"]
    if type(alternatives) is not list:
        raise AnalysisProjectionError(f"{label}.alternatives must be an array")
    ranks: set[int] = set()
    actions: set[tuple[tuple[str, object], ...]] = set()
    for index, raw_alternative in enumerate(alternatives):
        alternative = _require_mapping(raw_alternative, f"{label}.alternatives[{index}]")
        if set(alternative) != _ALTERNATIVE_KEYS:
            raise AnalysisProjectionError(
                f"{label}.alternatives[{index}] fields are invalid"
            )
        rank = _require_int(
            alternative["rank"],
            f"{label}.alternatives[{index}].rank",
            minimum=1,
        )
        if rank in ranks:
            raise AnalysisProjectionError(f"{label}.alternative ranks are duplicated")
        ranks.add(rank)
        action, canonical_action = _canonical_action(
            _require_mapping(
                alternative["action"],
                f"{label}.alternatives[{index}].action",
            ),
            f"{label}.alternatives[{index}].action",
        )
        _validate_action_for_seat(action, seat, f"{label}.alternatives[{index}].action")
        _validate_phase_action(
            action,
            decision_kind,
            f"{label}.alternatives[{index}].action",
        )
        action_key = tuple(sorted(canonical_action.items()))
        if action_key in actions:
            raise AnalysisProjectionError(f"{label}.alternative actions are duplicated")
        actions.add(action_key)
        for field_name, maximum in (
            ("title", 200),
            ("assessment", 200),
            ("reason", 1000),
        ):
            _require_text(
                alternative[field_name],
                f"{label}.alternatives[{index}].{field_name}",
                maximum,
            )


def _reject_client_private_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _CLIENT_PRIVATE_KEYS:
                raise AnalysisProjectionError(
                    f"post-match response contains private diagnostics key: {key}"
                )
            _reject_client_private_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_client_private_keys(nested)


def _validate_diagnostics(
    raw: Mapping[str, object],
    *,
    seat: int,
    visible_card_codes: frozenset[str] | None,
) -> _ValidatedDiagnostics:
    _reject_forbidden_keys(raw)
    schema_version = raw.get("schema_version")
    if schema_version == PIMC_DIAGNOSTICS_SCHEMA_VERSION:
        raise AnalysisProjectionError(
            "PIMC/search diagnostics are not accepted by the client adapter"
        )
    if schema_version != AGENT_DIAGNOSTICS_SCHEMA_VERSION:
        raise AnalysisProjectionError("unsupported diagnostics schema_version")
    if set(raw) != _DIAGNOSTICS_KEYS:
        raise AnalysisProjectionError("diagnostics fields are invalid")

    phase = raw["phase"]
    if phase not in {"SHOWING", "TRICK_PLAY"}:
        raise AnalysisProjectionError("diagnostics phase is invalid")
    observing_seat = _require_int(raw["observing_seat"], "observing_seat", 0, 3)
    if observing_seat != seat:
        raise AnalysisProjectionError("diagnostics observing seat disagrees")
    partner_seat = _require_int(raw["partner_seat"], "partner_seat", 0, 3)
    if partner_seat != (seat + 2) % 4:
        raise AnalysisProjectionError("diagnostics partner seat disagrees")
    for field_name in ("agent_id", "profile_id", "profile_key", "match_role"):
        _require_text(raw[field_name], field_name, 256)
    observation_digest = _require_text(
        raw["observation_digest"], "observation_digest", 80
    )
    if not is_sha256_identifier(observation_digest):
        raise AnalysisProjectionError("observation_digest is invalid")
    contract = raw["contract"]
    if contract is not None and contract not in {"RAMI", "NOLO"}:
        raise AnalysisProjectionError("diagnostics contract is invalid")
    _require_int(raw["own_hand_size"], "own_hand_size", 1, 13)
    legal_action_count = _require_int(
        raw["legal_action_count"], "legal_action_count", minimum=1
    )
    if raw["action_ordering_id"] != "tuppi.agents.engine_legal_action_order.v1":
        raise AnalysisProjectionError("diagnostics action ordering is invalid")
    if raw["tie_break_id"] != "lowest_engine_legal_action_index_v1":
        raise AnalysisProjectionError("diagnostics tie-break is invalid")
    if type(raw["tie_break_applied"]) is not bool:
        raise AnalysisProjectionError("tie_break_applied must be a boolean")
    _require_rule_id_array(raw["invoked_rule_ids"], "invoked_rule_ids")

    candidates_value = raw["candidates"]
    if type(candidates_value) is not list or not candidates_value:
        raise AnalysisProjectionError("diagnostics candidates must be a nonempty array")
    if len(candidates_value) != legal_action_count:
        raise AnalysisProjectionError("diagnostics candidate count disagrees")

    candidates: list[_ValidatedCandidate] = []
    for index, raw_candidate in enumerate(candidates_value):
        candidate = _validate_candidate(
            raw_candidate,
            seat=seat,
            phase=phase,
            label=f"candidates[{index}]",
        )
        candidates.append(candidate)
    if len({candidate.action_order_index for candidate in candidates}) != len(candidates):
        raise AnalysisProjectionError("candidate action order indices are duplicated")
    selected = [candidate for candidate in candidates if candidate.selected]
    if len(selected) != 1:
        raise AnalysisProjectionError("diagnostics must select exactly one candidate")

    selected_action, selected_data = _canonical_action(
        _require_mapping(raw["selected_action"], "selected_action"),
        "selected_action",
    )
    _validate_action_for_seat(selected_action, seat, "selected_action")
    _validate_phase_action(selected_action, phase, "selected_action")
    if selected_data != selected[0].action:
        raise AnalysisProjectionError("selected candidate disagrees with selected_action")
    selected_index = _require_int(
        raw["selected_action_order_index"],
        "selected_action_order_index",
        minimum=0,
    )
    if selected_index != selected[0].action_order_index:
        raise AnalysisProjectionError("selected action order index is inconsistent")
    best = max(
        candidates,
        key=lambda candidate: (
            candidate.score_vector,
            -candidate.action_order_index,
        ),
    )
    if not best.selected:
        raise AnalysisProjectionError("candidate scores do not reconcile with selection")
    cited_rule_ids = {
        rule_id for candidate in candidates for rule_id in candidate.rule_ids
    }
    if cited_rule_ids != set(raw["invoked_rule_ids"]):
        raise AnalysisProjectionError(
            "invoked_rule_ids must equal the rules cited by candidates"
        )
    if visible_card_codes is not None:
        _assert_authorized_card_codes(raw, visible_card_codes, "diagnostics")
    return _ValidatedDiagnostics(
        phase=phase,
        selected_action=selected_data,
        candidates=tuple(candidates),
    )


def _validate_candidate(
    raw: object,
    *,
    seat: int,
    phase: str,
    label: str,
) -> _ValidatedCandidate:
    candidate = _require_mapping(raw, label)
    if set(candidate) != _CANDIDATE_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    action, action_data = _canonical_action(
        _require_mapping(candidate["action"], f"{label}.action"),
        f"{label}.action",
    )
    _validate_action_for_seat(action, seat, f"{label}.action")
    _validate_phase_action(action, phase, f"{label}.action")
    action_order_index = _require_int(
        candidate["action_order_index"],
        f"{label}.action_order_index",
        minimum=0,
    )
    score_value = candidate["score_vector"]
    if type(score_value) is not list or not score_value:
        raise AnalysisProjectionError(f"{label}.score_vector must be a nonempty array")
    score_vector: list[float] = []
    for value in score_value:
        if type(value) not in {int, float} or isinstance(value, bool):
            raise AnalysisProjectionError(f"{label}.score_vector contains a non-number")
        number = float(value)
        if not math.isfinite(number):
            raise AnalysisProjectionError(f"{label}.score_vector contains a non-finite number")
        score_vector.append(number)

    contributions = candidate["feature_contributions"]
    if type(contributions) is not list or not contributions:
        raise AnalysisProjectionError(
            f"{label}.feature_contributions must be a nonempty array"
        )
    for contribution_index, raw_contribution in enumerate(contributions):
        contribution = _require_mapping(
            raw_contribution,
            f"{label}.feature_contributions[{contribution_index}]",
        )
        if set(contribution) != _FEATURE_KEYS:
            raise AnalysisProjectionError(
                f"{label}.feature_contributions fields are invalid"
            )
        _require_text(contribution["component"], "feature component", 128)
        value = contribution["value"]
        if type(value) not in {int, float} or isinstance(value, bool):
            raise AnalysisProjectionError("feature contribution value is not numeric")
        if not math.isfinite(float(value)):
            raise AnalysisProjectionError("feature contribution value is not finite")

    rule_ids = _require_rule_id_array(candidate["rule_ids"], f"{label}.rule_ids")
    reason_codes = candidate["reason_codes"]
    if type(reason_codes) is not list or any(
        not isinstance(code, str) or not code for code in reason_codes
    ):
        raise AnalysisProjectionError(f"{label}.reason_codes are invalid")
    if type(candidate["selected"]) is not bool:
        raise AnalysisProjectionError(f"{label}.selected must be a boolean")
    return _ValidatedCandidate(
        action=action_data,
        action_order_index=action_order_index,
        score_vector=tuple(score_vector),
        rule_ids=rule_ids,
        selected=candidate["selected"],
    )


def _event_for_record(
    record: RecordedDecisionAnalysis,
    public_events: Sequence[Mapping[str, object]],
    phase: str,
) -> Mapping[str, object]:
    found: Mapping[str, object] | None = None
    seen_indices: set[int] = set()
    for event in public_events:
        if not isinstance(event, Mapping):
            raise AnalysisProjectionError("public event must be an object")
        event_index = _require_int(event.get("event_index"), "event_index", minimum=0)
        if event_index in seen_indices:
            raise AnalysisProjectionError("public event indices are duplicated")
        seen_indices.add(event_index)
        if event.get("match_ref") != record.match_ref:
            raise AnalysisProjectionError("public event belongs to another match")
        if event.get("schema_version") != "tuppi.engine.public_event.v1":
            raise AnalysisProjectionError("public event schema_version is invalid")
        if event_index == record.event_index:
            found = event
    if found is None:
        raise AnalysisProjectionError("analysis event_index is not in public history")

    expected_type = "show_accepted" if phase == "SHOWING" else "card_played"
    if found.get("event_type") != expected_type:
        raise AnalysisProjectionError(
            f"analysis event is not the accepted {phase.lower()} action event"
        )
    deal_ref = found.get("deal_ref")
    prefix = f"{record.match_ref}/deal:"
    if not isinstance(deal_ref, str) or not deal_ref.startswith(prefix):
        raise AnalysisProjectionError("public event deal_ref is invalid")
    deal_suffix = deal_ref.removeprefix(prefix)
    if not deal_suffix.isdigit() or int(deal_suffix) != record.deal_number:
        raise AnalysisProjectionError("analysis deal_number disagrees with event")
    payload = found.get("payload")
    if not isinstance(payload, Mapping):
        raise AnalysisProjectionError("public event payload must be an object")
    return found


def _validate_event_action(
    event: Mapping[str, object],
    played_action: Mapping[str, object],
    record: RecordedDecisionAnalysis,
) -> None:
    payload = event["payload"]
    assert isinstance(payload, Mapping)
    if event["event_type"] == "show_accepted":
        expected = {
            "type": "show",
            "seat": payload.get("seat"),
            "shown_card": payload.get("shown_card"),
            "declared_contract": payload.get("declared_contract"),
        }
        if played_action != expected:
            raise AnalysisProjectionError(
                "played showing action disagrees with public event"
            )
    else:
        expected = {
            "type": "play",
            "seat": payload.get("seat"),
            "card": payload.get("card"),
        }
        if played_action != expected:
            raise AnalysisProjectionError("played card action disagrees with public event")
        if record.trick_index != payload.get("trick_index"):
            raise AnalysisProjectionError("analysis trick_index disagrees with event")


def _canonical_action(
    value: Mapping[str, object], label: str
) -> tuple[ShowAction | PlayCardAction, dict[str, object]]:
    try:
        action = action_from_data(dict(value))
    except (EngineError, TypeError, ValueError) as exc:
        raise AnalysisProjectionError(f"{label} is not a valid engine action") from exc
    return action, action_to_data(action)


def _validate_action_for_seat(
    action: ShowAction | PlayCardAction, seat: int, label: str
) -> None:
    if action.seat != seat:
        raise AnalysisProjectionError(f"{label} seat disagrees with record")


def _validate_phase_action(
    action: ShowAction | PlayCardAction, phase: str, label: str
) -> None:
    if phase == "SHOWING" and not isinstance(action, ShowAction):
        raise AnalysisProjectionError(f"{label} must be a showing action")
    if phase == "TRICK_PLAY" and not isinstance(action, PlayCardAction):
        raise AnalysisProjectionError(f"{label} must be a trick-play action")


def _action_title(action: Mapping[str, object]) -> str:
    if action["type"] == "show":
        return f"Näytä {action['shown_card']} · {action['declared_contract']}"
    return f"Pelaa {action['card']}"


def _reject_forbidden_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in _FORBIDDEN_KEYS:
                raise AnalysisProjectionError(
                    f"diagnostics contain forbidden private key: {key}"
                )
            _reject_forbidden_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_forbidden_keys(nested)


def _normalise_visible_cards(
    values: Iterable[str] | None,
) -> frozenset[str] | None:
    if values is None:
        return None
    result = frozenset(values)
    if any(
        not isinstance(code, str) or _CARD_CODE_PATTERN.fullmatch(code) is None
        for code in result
    ):
        raise AnalysisProjectionError("visible_card_codes contains an invalid card")
    return result


def _assert_authorized_card_codes(
    value: object,
    visible_card_codes: frozenset[str],
    label: str,
) -> None:
    text = _stringify_for_card_scan(value)
    mentioned = set(_CARD_TOKEN_PATTERN.findall(text))
    unknown = sorted(mentioned - visible_card_codes)
    if unknown:
        raise AnalysisProjectionError(
            f"{label} names cards outside the authorized context: {', '.join(unknown)}"
        )


def _stringify_for_card_scan(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, nested in value.items():
            parts.extend(
                (_stringify_for_card_scan(key), _stringify_for_card_scan(nested))
            )
        return " ".join(parts)
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_stringify_for_card_scan(item) for item in value)
    return str(value)


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AnalysisProjectionError(f"{label} must be an object")
    return value


def _require_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise AnalysisProjectionError(f"{label} must be a nonempty bounded string")
    return value


def _require_text_array(value: object, label: str, maximum: int) -> tuple[str, ...]:
    if type(value) is not list:
        raise AnalysisProjectionError(f"{label} must be an array")
    result: list[str] = []
    for item in value:
        result.append(_require_text(item, label, maximum))
    return tuple(result)


def _require_int(
    value: object,
    label: str,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum:
        raise AnalysisProjectionError(f"{label} must be an integer in the allowed range")
    if maximum is not None and value > maximum:
        raise AnalysisProjectionError(f"{label} must be an integer in the allowed range")
    return value


def _require_rule_id_array(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise AnalysisProjectionError(f"{label} is invalid")
    if len(set(value)) != len(value):
        raise AnalysisProjectionError(f"{label} contains duplicates")
    return tuple(value)
