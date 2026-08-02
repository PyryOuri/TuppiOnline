"""Transparent candidate scoring, ranking, and deterministic selection.

Every Phase 4 policy scores *all* of its legal actions and then takes the
lexicographic maximum. There are no nested undocumented conditionals: a rule
contributes a named component to a fixed-length score vector, and the vector
order *is* the rule priority. Selection is therefore reproducible, explainable,
and mechanically checkable:

* every legal action appears in the ranking exactly once;
* the selected action is the deterministic maximum under the profile;
* ties are broken only by the lowest engine legal-action index.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from tuppi_engine import Action, PlayerObservation

from .errors import AgentsValidationError, PolicyError
from .ordering import TIE_BREAK_ID, ordered_legal_actions
from .rule_catalogue import require_rule


ACTION_SCORING_SCHEMA_VERSION = "tuppi.agents.action_scoring.v1"


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """One legal action's immutable score under one profile."""

    action: Action
    action_order_index: int
    component_names: tuple[str, ...]
    score_vector: tuple[float, ...]
    rule_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    schema_version: str = field(default=ACTION_SCORING_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.action_order_index) is not int or self.action_order_index < 0:
            raise AgentsValidationError("action_order_index must be nonnegative")
        if type(self.component_names) is not tuple or type(self.score_vector) is not tuple:
            raise AgentsValidationError("score components must be immutable tuples")
        if len(self.component_names) != len(self.score_vector):
            raise AgentsValidationError(
                "score vector length must match the component-name length"
            )
        if not self.component_names:
            raise AgentsValidationError("a candidate needs at least one component")
        if len(set(self.component_names)) != len(self.component_names):
            raise AgentsValidationError("component names must be unique")
        for value in self.score_vector:
            if type(value) not in (int, float) or value != value:
                raise AgentsValidationError("score components must be finite numbers")
        if type(self.rule_ids) is not tuple or not self.rule_ids:
            raise AgentsValidationError("a candidate must cite at least one rule")
        if tuple(sorted(set(self.rule_ids))) != tuple(sorted(self.rule_ids)):
            raise AgentsValidationError("candidate rule IDs must be unique")
        for rule_id in self.rule_ids:
            require_rule(rule_id)
        if type(self.reason_codes) is not tuple:
            raise AgentsValidationError("reason codes must be an immutable tuple")
        for code in self.reason_codes:
            if not isinstance(code, str) or not code or not code.replace("_", "").isalnum():
                raise AgentsValidationError(
                    "reason codes must be short machine-readable tokens"
                )

    @property
    def feature_contributions(self) -> tuple[tuple[str, float], ...]:
        return tuple(
            (name, float(value))
            for name, value in zip(self.component_names, self.score_vector, strict=True)
        )

    @property
    def selection_key(self) -> tuple[tuple[float, ...], int]:
        """Higher is better; a lower engine action index wins a tie."""

        return (tuple(float(value) for value in self.score_vector), -self.action_order_index)


@dataclass(frozen=True, slots=True)
class ScoredActions:
    """The complete ranking of an observation's legal actions."""

    candidates: tuple[CandidateEvaluation, ...]
    selected_index: int
    tie_break_id: str = field(default=TIE_BREAK_ID, init=False)
    schema_version: str = field(default=ACTION_SCORING_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.candidates) is not tuple or not self.candidates:
            raise AgentsValidationError("a ranking requires at least one candidate")
        indices = tuple(item.action_order_index for item in self.candidates)
        if indices != tuple(range(len(self.candidates))):
            raise AgentsValidationError(
                "candidates must cover every legal action index exactly once"
            )
        lengths = {len(item.score_vector) for item in self.candidates}
        names = {item.component_names for item in self.candidates}
        if len(lengths) != 1 or len(names) != 1:
            raise AgentsValidationError(
                "all candidates in one decision must share the score layout"
            )
        if self.selected_index not in range(len(self.candidates)):
            raise AgentsValidationError("selected_index is out of range")
        best = max(self.candidates, key=lambda item: item.selection_key)
        if best.action_order_index != self.selected_index:
            raise AgentsValidationError(
                "selected_index is not the deterministic lexicographic maximum"
            )

    @property
    def selected(self) -> CandidateEvaluation:
        return self.candidates[self.selected_index]

    @property
    def action(self) -> Action:
        return self.selected.action

    def ranked(self) -> tuple[CandidateEvaluation, ...]:
        """Return candidates from best to worst under the documented order."""

        return tuple(
            sorted(self.candidates, key=lambda item: item.selection_key, reverse=True)
        )


CandidateScorer = Callable[[Action, int], CandidateEvaluation]


def score_legal_actions(
    observation: PlayerObservation, scorer: CandidateScorer
) -> ScoredActions:
    """Score every legal action in engine order and take the maximum."""

    actions = ordered_legal_actions(observation)
    candidates: list[CandidateEvaluation] = []
    for index, action in enumerate(actions):
        candidate = scorer(action, index)
        if not isinstance(candidate, CandidateEvaluation):
            raise PolicyError("a scorer must return a CandidateEvaluation")
        if candidate.action is not action or candidate.action_order_index != index:
            raise PolicyError("a scorer must evaluate the action it was given")
        candidates.append(candidate)
    frozen = tuple(candidates)
    best = max(frozen, key=lambda item: item.selection_key)
    return ScoredActions(candidates=frozen, selected_index=best.action_order_index)


def component_layout(names: Sequence[str]) -> tuple[str, ...]:
    """Freeze and validate an ordered score-component layout."""

    layout = tuple(names)
    if not layout or len(set(layout)) != len(layout):
        raise AgentsValidationError("a score layout must be nonempty and unique")
    for name in layout:
        if not isinstance(name, str) or not name or not name.replace("_", "").isalnum():
            raise AgentsValidationError("score component names must be simple tokens")
    return layout
