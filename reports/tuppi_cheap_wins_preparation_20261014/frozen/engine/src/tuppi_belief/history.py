"""Causal public action histories.

The history is reconstructed from the formal observation, so the current action
is never accidentally included.  It contains no private state and is immutable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import Action, PlayCardAction, PlayerObservation, ShowAction


HISTORY_SCHEMA_VERSION = "tuppi.belief.causal_public_history.v1"


@dataclass(frozen=True, slots=True)
class PublicAction:
    """One public action in causal order, before the current observation."""

    sequence: int
    action: Action
    phase: str
    schema_version: str = field(default=HISTORY_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("history sequence must be a nonnegative integer")
        if not isinstance(self.action, (ShowAction, PlayCardAction)):
            raise TypeError("history action must be an engine action")
        if self.phase not in {"SHOWING", "TRICK_PLAY"}:
            raise ValueError("history phase must be SHOWING or TRICK_PLAY")


@dataclass(frozen=True, slots=True)
class CausalPublicHistory:
    """The public prefix legally available at one decision point."""

    actions: tuple[PublicAction, ...]
    schema_version: str = field(default=HISTORY_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if type(self.actions) is not tuple:
            raise TypeError("history actions must be a tuple")
        if tuple(item.sequence for item in self.actions) != tuple(range(len(self.actions))):
            raise ValueError("history sequences must be contiguous")

    @classmethod
    def from_observation(cls, observation: PlayerObservation) -> "CausalPublicHistory":
        if not isinstance(observation, PlayerObservation):
            raise TypeError("history requires a PlayerObservation")
        actions: list[PublicAction] = []
        sequence = 0
        for show in observation.show_actions:
            actions.append(
                PublicAction(
                    sequence=sequence,
                    action=ShowAction(
                        seat=show.seat,
                        shown_card=show.shown_card,
                        declared_contract=show.declared_contract,
                    ),
                    phase="SHOWING",
                )
            )
            sequence += 1
        for trick in observation.completed_tricks:
            for play in trick.plays:
                actions.append(
                    PublicAction(
                        sequence=sequence,
                        action=PlayCardAction(seat=play.seat, card=play.card),
                        phase="TRICK_PLAY",
                    )
                )
                sequence += 1
        for play in observation.current_trick:
            actions.append(
                PublicAction(
                    sequence=sequence,
                    action=PlayCardAction(seat=play.seat, card=play.card),
                    phase="TRICK_PLAY",
                )
            )
            sequence += 1
        return cls(actions=tuple(actions))

    def prefix_before(self, sequence: int) -> "CausalPublicHistory":
        if type(sequence) is not int or sequence < 0 or sequence > len(self.actions):
            raise ValueError("history prefix is outside the available range")
        return CausalPublicHistory(actions=self.actions[:sequence])

    @property
    def showing_actions(self) -> tuple[PublicAction, ...]:
        return tuple(item for item in self.actions if item.phase == "SHOWING")

    @property
    def trick_actions(self) -> tuple[PublicAction, ...]:
        return tuple(item for item in self.actions if item.phase == "TRICK_PLAY")
