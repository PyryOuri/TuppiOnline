"""Minimal deterministic agent protocol and non-strategic test utilities."""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from typing import Protocol

from tuppi_rules import card_to_code

from .actions import Action, PlayCardAction, ShowAction
from .errors import AgentProtocolError
from .observations import PlayerObservation


class Agent(Protocol):
    @property
    def identity(self) -> str:
        ...

    def choose_action(self, observation: PlayerObservation) -> Action:
        ...


class FirstLegalActionAgent:
    """Choose the first action in the engine's documented stable ordering."""

    @property
    def identity(self) -> str:
        return "first_legal_action_v1"

    def choose_action(self, observation: PlayerObservation) -> Action:
        if not isinstance(observation, PlayerObservation):
            raise AgentProtocolError("agent requires a PlayerObservation")
        if not observation.legal_actions:
            raise AgentProtocolError("observation contains no legal action")
        return observation.legal_actions[0]


class FixedScriptAgent:
    """Consume a fixed seat-specific action sequence without inspecting state."""

    def __init__(self, actions: Iterable[Action]) -> None:
        try:
            normalized = tuple(actions)
        except TypeError as exc:
            raise AgentProtocolError("script actions must be iterable") from exc
        if any(not isinstance(action, (ShowAction, PlayCardAction)) for action in normalized):
            raise AgentProtocolError("script contains a non-engine action")
        self._actions = normalized
        self._position = 0
        self._identity = _script_identity(normalized)

    @property
    def identity(self) -> str:
        return self._identity

    @property
    def remaining(self) -> int:
        return len(self._actions) - self._position

    def choose_action(self, observation: PlayerObservation) -> Action:
        if not isinstance(observation, PlayerObservation):
            raise AgentProtocolError("script agent requires a PlayerObservation")
        if self._position >= len(self._actions):
            raise AgentProtocolError(
                f"script exhausted for acting seat {observation.observing_seat}"
            )
        action = self._actions[self._position]
        if action.seat != observation.observing_seat:
            raise AgentProtocolError(
                "next scripted action belongs to a different seat"
            )
        self._position += 1
        return action

    def assert_consumed(self) -> None:
        if self.remaining:
            raise AgentProtocolError(
                f"script has {self.remaining} unconsumed action(s)"
            )


def _script_identity(actions: tuple[Action, ...]) -> str:
    data = []
    for action in actions:
        if isinstance(action, ShowAction):
            data.append(
                {
                    "card": card_to_code(action.shown_card),
                    "contract": action.declared_contract.value,
                    "seat": action.seat,
                    "type": "show",
                }
            )
        else:
            data.append(
                {
                    "card": card_to_code(action.card),
                    "seat": action.seat,
                    "type": "play",
                }
            )
    canonical = json.dumps(
        {"actions": data, "schema_version": "tuppi.engine.agent_script_identity.v1"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"fixed_script_v1:sha256:{hashlib.sha256(canonical).hexdigest()}"
