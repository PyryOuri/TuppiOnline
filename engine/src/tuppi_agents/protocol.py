"""The Phase 4 agent boundary and the shared deterministic policy base.

A Phase 4 policy receives exactly one thing: a frozen
:class:`tuppi_engine.PlayerObservation`. It never receives engine state, an
initial deal, another seat's hand, a research result, a fixture or match-stream
identity, a hidden-state-derived deal identifier, an evaluator object, an event
writer, or a mutable reference into engine state. The constructor takes only an
immutable agent identity and an immutable profile.

Diagnostics travel on a separate trusted channel. ``choose_action`` is the
engine-facing method and returns only the action; ``decide`` additionally
returns the ranking and, on request, a privacy-safe diagnostics record. Both
paths compute the identical ranking, so switching diagnostics on cannot change
play.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from tuppi_engine import Action, EnginePhase, PlayerObservation

from .action_scoring import ScoredActions
from .diagnostics import DecisionDiagnostics, build_diagnostics
from .errors import ObservationBoundaryError, PolicyError
from .features import PublicFeatures, build_features
from .ordering import require_observation
from .profiles import HeuristicProfile


@runtime_checkable
class ObservationOnlyAgent(Protocol):
    """The engine-facing protocol every Phase 4 agent satisfies."""

    @property
    def identity(self) -> str:
        ...

    def choose_action(self, observation: PlayerObservation) -> Action:
        ...


@dataclass(frozen=True, slots=True)
class Decision:
    """One deterministic decision plus its optional explanation."""

    action: Action
    scored: ScoredActions
    diagnostics: DecisionDiagnostics | None


class RuleBasedPolicy:
    """Base class for every deterministic Phase 4 strategic policy."""

    def __init__(self, *, agent_id: str, profile: HeuristicProfile) -> None:
        if not isinstance(agent_id, str) or not agent_id:
            raise PolicyError("a policy requires a nonempty agent identity")
        if not isinstance(profile, HeuristicProfile):
            raise PolicyError("a policy requires an immutable HeuristicProfile")
        self._agent_id = agent_id
        self._profile = profile

    # ------------------------------------------------------------- properties

    @property
    def identity(self) -> str:
        return self._agent_id

    @property
    def profile(self) -> HeuristicProfile:
        return self._profile

    # ------------------------------------------------------------- engine API

    def choose_action(self, observation: PlayerObservation) -> Action:
        """Return the selected action; never builds a diagnostics record."""

        return self._rank(observation)[0].action

    # ---------------------------------------------------- trusted diagnostics

    def decide(
        self, observation: PlayerObservation, *, diagnostics: bool = True
    ) -> Decision:
        checked = require_observation(observation)
        scored, features = self._rank(checked)
        record = None
        if diagnostics:
            record = build_diagnostics(
                observation=checked,
                scored=scored,
                agent_id=self._agent_id,
                profile_id=self._profile.profile_id,
                profile_key=self._profile.profile_key,
                match_role=features.deal.match_role.value,
            )
        return Decision(action=scored.action, scored=scored, diagnostics=record)

    def explain(self, observation: PlayerObservation) -> DecisionDiagnostics:
        record = self.decide(observation, diagnostics=True).diagnostics
        if record is None:  # pragma: no cover - decide always builds one here
            raise PolicyError("diagnostics were requested but not produced")
        return record

    # ---------------------------------------------------------------- interna

    def _rank(
        self, observation: PlayerObservation
    ) -> tuple[ScoredActions, PublicFeatures]:
        checked = require_observation(observation)
        if checked.current_actor != checked.observing_seat:
            raise ObservationBoundaryError(
                "a policy may act only on its own acting observation"
            )
        features = build_features(
            checked, include_inference=self._profile.uses_public_inference
        )
        if checked.phase is EnginePhase.SHOWING:
            scored = self.score_showing_actions(checked, features)
        elif checked.phase is EnginePhase.TRICK_PLAY:
            scored = self.score_play_actions(checked, features)
        else:
            raise PolicyError(f"policies cannot act in {checked.phase.value}")
        if not isinstance(scored, ScoredActions):
            raise PolicyError("a policy must return a ScoredActions ranking")
        if scored.action not in checked.legal_actions:
            raise PolicyError("a policy selected an action outside the legal set")
        return (scored, features)

    # ------------------------------------------------------- subclass contract

    def score_showing_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        raise NotImplementedError

    def score_play_actions(
        self, observation: PlayerObservation, features: PublicFeatures
    ) -> ScoredActions:
        raise NotImplementedError


class DiagnosticsRecordingAgent:
    """A trusted wrapper that captures diagnostics without changing play.

    The evaluator never uses this wrapper: it is the explicit separate channel
    for examples, documentation, and the diagnostics-overhead ablation.
    """

    def __init__(self, delegate: RuleBasedPolicy) -> None:
        if not isinstance(delegate, RuleBasedPolicy):
            raise PolicyError("the diagnostics wrapper requires a RuleBasedPolicy")
        self._delegate = delegate
        self._records: list[DecisionDiagnostics] = []

    @property
    def identity(self) -> str:
        return self._delegate.identity

    @property
    def records(self) -> tuple[DecisionDiagnostics, ...]:
        return tuple(self._records)

    def choose_action(self, observation: PlayerObservation) -> Action:
        decision = self._delegate.decide(observation, diagnostics=True)
        if decision.diagnostics is not None:
            self._records.append(decision.diagnostics)
        return decision.action
