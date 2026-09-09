"""Runtime behaviour of the declared research candidates.

A *policy* module, deliberately: it may be reached by a running agent, so it
touches no engine-private state, no evaluation package and nothing resembling
sampling. Declarations, specifications and identity live in the harness module
:mod:`research_candidates`; this file only decides actions.

Every override here reads the acting seat's ``PlayerObservation`` and returns a
member of ``observation.legal_actions``, so no override can reach private state
or hand the engine an action it would refuse.
"""

from __future__ import annotations

from typing import Any, Mapping

from tuppi_engine import Action, Agent, PlayerObservation


class OverridePolicy:
    """A base policy plus a declared, observation-only override."""

    __slots__ = ("_agent_id", "_base", "_parameters")

    def __init__(self, *, agent_id: str, base: Agent, parameters: Mapping[str, Any]):
        self._agent_id = agent_id
        self._base = base
        self._parameters = dict(parameters)

    @property
    def identity(self) -> str:
        return self._agent_id

    def choose_action(self, observation: PlayerObservation) -> Action:
        raise NotImplementedError


class NoOpCandidate(OverridePolicy):
    """Returns exactly what the base policy returns."""

    __slots__ = ()

    def choose_action(self, observation: PlayerObservation) -> Action:
        return self._base.choose_action(observation)


class LegalIndexShiftCandidate(OverridePolicy):
    """Move the base choice along the engine's stable legal ordering.

    Deliberately unmotivated: its purpose is to be detectably different, so the
    pipeline can be shown to notice a real difference. It is expected to play
    worse and is never a proposal.
    """

    __slots__ = ()

    def choose_action(self, observation: PlayerObservation) -> Action:
        chosen = self._base.choose_action(observation)
        legal = observation.legal_actions
        if observation.phase.value != self._parameters["phase"] or len(legal) < 2:
            return chosen
        try:
            index = legal.index(chosen)
        except ValueError:  # pragma: no cover - the base policy is contract-bound
            return chosen
        return legal[(index + int(self._parameters["shift"])) % len(legal)]


#: Declared override id -> implementation. The harness resolves through this.
OVERRIDE_IMPLEMENTATIONS = {
    "tuppi.research.noop.v1": NoOpCandidate,
    "tuppi.research.legal_index_shift.v1": LegalIndexShiftCandidate,
}


__all__ = [
    "OVERRIDE_IMPLEMENTATIONS",
    "LegalIndexShiftCandidate",
    "NoOpCandidate",
    "OverridePolicy",
]
