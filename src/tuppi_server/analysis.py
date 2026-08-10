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
AGENT_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.agents.decision_diagnostics.v1"
PIMC_DIAGNOSTICS_SCHEMA_VERSION = "tuppi.search.pimc_decision_diagnostics.v1"

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
    if response.get("schema_version") == POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION:
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


def _validate_post_match_diagnostics_response(
    response: Mapping[str, object],
    *,
    expected_match_ref: str | None,
    public_events: Sequence[Mapping[str, object]] | None,
) -> dict[str, object]:
    """Validate the real, seat-scoped v2 diagnostics response."""

    _reject_client_private_keys(response)
    if set(response) != _V2_RESPONSE_KEYS:
        raise AnalysisProjectionError("post-match diagnostics response fields are invalid")
    match_ref = _require_text(response["match_ref"], "match_ref", 96)
    if not is_valid_match_ref(match_ref):
        raise AnalysisProjectionError("post-match diagnostics match_ref is invalid")
    if expected_match_ref is not None and match_ref != expected_match_ref:
        raise AnalysisProjectionError("post-match diagnostics belongs to another match")
    seat = _require_int(response["seat"], "seat", minimum=0, maximum=3)

    summary = _require_mapping(response["summary"], "summary")
    if set(summary) != _V2_SUMMARY_KEYS:
        raise AnalysisProjectionError("post-match diagnostics summary fields are invalid")
    deal_count = _require_int(summary["deal_count"], "summary.deal_count", minimum=1)
    diagnostic_count = _require_int(
        summary["diagnostic_count"], "summary.diagnostic_count", minimum=0, maximum=10
    )
    _require_score_pair(summary["final_score"], "summary.final_score")
    _require_int(summary["winner_team"], "summary.winner_team", minimum=0, maximum=1)

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
) -> None:
    if set(analysis) != _V2_ANALYSIS_KEYS:
        raise AnalysisProjectionError(f"{label} fields are invalid")
    if analysis["schema_version"] != POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION:
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
