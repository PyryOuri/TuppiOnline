"""Immutable, privacy-safe decision diagnostics for deterministic policies.

Diagnostics are produced from exactly the same observation and profile as the
decision, and they never change the decision: a policy computes its full
candidate ranking either way and only the construction of this record is
optional.

Privacy rule: a diagnostics record may contain the observation's *legal
actions* and the selected action, because those are the decision itself, plus
scalar derived features. It never contains another seat's card, the observing
player's full hand, an engine object, an explicit deal, a deal identifier
derived from hidden state, or any evaluator-private value. The observation
digest is a one-way SHA-256 commitment used to prove that two decisions were
taken from the identical observation; it is not a re-derivable copy of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import (
    Action,
    EnginePhase,
    PlayerObservation,
    action_to_data,
    canonical_json_bytes,
    observation_to_data,
)

from .action_scoring import CandidateEvaluation, ScoredActions
from .errors import DiagnosticsError
from .ordering import ACTION_ORDERING_ID, TIE_BREAK_ID, require_observation
from .rule_catalogue import require_rule


DIAGNOSTICS_SCHEMA_VERSION = "tuppi.agents.decision_diagnostics.v1"


def observation_digest(observation: PlayerObservation) -> str:
    """Return a one-way commitment to the exact observation that was seen."""

    import hashlib

    checked = require_observation(observation)
    payload = canonical_json_bytes(observation_to_data(checked))
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True, slots=True)
class CandidateDiagnostic:
    action: dict[str, object]
    action_order_index: int
    score_vector: tuple[float, ...]
    feature_contributions: tuple[tuple[str, float], ...]
    rule_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    selected: bool

    def to_data(self) -> dict[str, object]:
        return {
            "action": self.action,
            "action_order_index": self.action_order_index,
            "feature_contributions": [
                {"component": name, "value": value}
                for name, value in self.feature_contributions
            ],
            "reason_codes": list(self.reason_codes),
            "rule_ids": list(self.rule_ids),
            "score_vector": [float(value) for value in self.score_vector],
            "selected": self.selected,
        }


@dataclass(frozen=True, slots=True)
class DecisionDiagnostics:
    """One deterministic decision, fully explained and privacy-safe."""

    agent_id: str
    profile_id: str
    profile_key: str
    phase: str
    observation_digest: str
    observing_seat: int
    partner_seat: int
    match_role: str
    contract: str | None
    own_hand_size: int
    legal_action_count: int
    action_ordering_id: str
    tie_break_id: str
    tie_break_applied: bool
    selected_action: dict[str, object]
    selected_action_order_index: int
    invoked_rule_ids: tuple[str, ...]
    candidates: tuple[CandidateDiagnostic, ...]
    schema_version: str = field(default=DIAGNOSTICS_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("agent_id", self.agent_id),
            ("profile_id", self.profile_id),
            ("profile_key", self.profile_key),
            ("observation_digest", self.observation_digest),
        ):
            if not isinstance(value, str) or not value:
                raise DiagnosticsError(f"{label} must be a nonempty string")
        if not self.observation_digest.startswith("sha256:"):
            raise DiagnosticsError("observation_digest must be a sha256 commitment")
        if self.phase not in (EnginePhase.SHOWING.value, EnginePhase.TRICK_PLAY.value):
            raise DiagnosticsError("diagnostics phase must be SHOWING or TRICK_PLAY")
        if type(self.candidates) is not tuple or not self.candidates:
            raise DiagnosticsError("diagnostics require at least one candidate")
        if len(self.candidates) != self.legal_action_count:
            raise DiagnosticsError(
                "candidate count must equal the legal action count"
            )
        selected = tuple(item for item in self.candidates if item.selected)
        if len(selected) != 1:
            raise DiagnosticsError("exactly one candidate must be marked selected")
        if selected[0].action != self.selected_action:
            raise DiagnosticsError(
                "selected candidate disagrees with the recorded selected action"
            )
        if selected[0].action_order_index != self.selected_action_order_index:
            raise DiagnosticsError("selected action order index is inconsistent")
        best = max(
            self.candidates,
            key=lambda item: (tuple(item.score_vector), -item.action_order_index),
        )
        if not best.selected:
            raise DiagnosticsError(
                "candidate scores do not reconcile with the selected action"
            )
        for rule_id in self.invoked_rule_ids:
            require_rule(rule_id)
        cited = {
            rule_id for item in self.candidates for rule_id in item.rule_ids
        }
        if cited != set(self.invoked_rule_ids):
            raise DiagnosticsError(
                "invoked_rule_ids must be exactly the rules cited by candidates"
            )
        if self.action_ordering_id != ACTION_ORDERING_ID:
            raise DiagnosticsError("unexpected action ordering identifier")
        if self.tie_break_id != TIE_BREAK_ID:
            raise DiagnosticsError("unexpected tie-break identifier")

    def to_data(self) -> dict[str, object]:
        return {
            "action_ordering_id": self.action_ordering_id,
            "agent_id": self.agent_id,
            "candidates": [item.to_data() for item in self.candidates],
            "contract": self.contract,
            "invoked_rule_ids": list(self.invoked_rule_ids),
            "legal_action_count": self.legal_action_count,
            "match_role": self.match_role,
            "observation_digest": self.observation_digest,
            "observing_seat": self.observing_seat,
            "own_hand_size": self.own_hand_size,
            "partner_seat": self.partner_seat,
            "phase": self.phase,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
            "schema_version": self.schema_version,
            "selected_action": self.selected_action,
            "selected_action_order_index": self.selected_action_order_index,
            "tie_break_applied": self.tie_break_applied,
            "tie_break_id": self.tie_break_id,
        }


def build_diagnostics(
    *,
    observation: PlayerObservation,
    scored: ScoredActions,
    agent_id: str,
    profile_id: str,
    profile_key: str,
    match_role: str,
) -> DecisionDiagnostics:
    checked = require_observation(observation)
    if not isinstance(scored, ScoredActions):
        raise DiagnosticsError("diagnostics require a ScoredActions ranking")
    best_key = scored.selected.selection_key[0]
    tied = sum(
        1
        for item in scored.candidates
        if tuple(float(value) for value in item.score_vector) == best_key
    )
    candidates = tuple(
        _candidate_diagnostic(item, selected=item.action_order_index == scored.selected_index)
        for item in scored.candidates
    )
    invoked = tuple(
        sorted({rule_id for item in scored.candidates for rule_id in item.rule_ids})
    )
    return DecisionDiagnostics(
        agent_id=agent_id,
        profile_id=profile_id,
        profile_key=profile_key,
        phase=checked.phase.value,
        observation_digest=observation_digest(checked),
        observing_seat=checked.observing_seat,
        partner_seat=checked.partner_seat,
        match_role=match_role,
        contract=None if checked.contract is None else checked.contract.value,
        own_hand_size=len(checked.own_hand),
        legal_action_count=len(scored.candidates),
        action_ordering_id=ACTION_ORDERING_ID,
        tie_break_id=TIE_BREAK_ID,
        tie_break_applied=tied > 1,
        selected_action=action_to_data(scored.action),
        selected_action_order_index=scored.selected_index,
        invoked_rule_ids=invoked,
        candidates=candidates,
    )


def _candidate_diagnostic(
    candidate: CandidateEvaluation, *, selected: bool
) -> CandidateDiagnostic:
    return CandidateDiagnostic(
        action=action_to_data(candidate.action),
        action_order_index=candidate.action_order_index,
        score_vector=tuple(float(value) for value in candidate.score_vector),
        feature_contributions=candidate.feature_contributions,
        rule_ids=candidate.rule_ids,
        reason_codes=candidate.reason_codes,
        selected=selected,
    )


def assert_no_foreign_cards(
    diagnostics: DecisionDiagnostics, forbidden_card_codes: frozenset[str]
) -> None:
    """Raise when a diagnostics record mentions a card it must not know about."""

    if not isinstance(diagnostics, DecisionDiagnostics):
        raise DiagnosticsError("expected a DecisionDiagnostics value")
    payload = canonical_json_bytes(diagnostics.to_data()).decode("utf-8")
    import re

    for code in sorted(forbidden_card_codes):
        if re.search(rf'"{re.escape(code)}"', payload):
            raise DiagnosticsError(
                f"diagnostics leaked a card that the agent cannot see: {code}"
            )
