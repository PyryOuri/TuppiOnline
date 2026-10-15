"""Hypothetical continuation states: a sampled world made playable.

A sampled hidden-hand assignment is only useful if something can be *played* on
it. This module turns one assignment plus one observation into a complete
:class:`tuppi_engine.DealState` that the clean engine accepts, so a solver or a
rollout runs against the real rules rather than against a private re-implementation.

The construction deliberately takes the long route. It rebuilds the four initial
13-card hands - the observer's real hand, each opponent's sampled cards, plus the
cards each seat has publicly played - and then **replays the entire public action
history through the ordinary engine transitions**. Nothing is stitched together
by hand and no invariant is asserted locally, so every guarantee comes from the
engine that owns it:

* an assignment that violates a proven void makes a replayed follow-suit
  violation, and the engine rejects it;
* an assignment that contradicts a public show action makes ``verbal_required``
  disagree with the hand, and the engine rejects it;
* an assignment that misplaces even one card fails the state's own hand-history
  reconciliation.

That is the design point worth keeping: the engine is the referee for the
sampler's soundness, so an unsound constraint model cannot silently produce a
plausible-looking hypothetical.

**Hypothetical states are labelled, always.** Every continuation carries a
distinct ``match_ref`` prefix, an explicit ``is_hypothetical`` flag, and the
identity of the observation it was derived from. A hypothetical deal must never
enter a result record, a bank, or a report as if it had been dealt. Its
``deal_id`` genuinely differs from the real deal's, because the hands differ -
which is the property that makes the mistake detectable rather than invisible.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import (
    DealState,
    EnginePhase,
    ExplicitDeal,
    PlayCardAction,
    PlayerObservation,
    ShowAction as EngineShowAction,
    apply_action,
    create_deal_state,
)
from tuppi_rules import Card, card_to_index

from .errors import ContinuationError
from .sampling import HiddenHandAssignment


CONTINUATION_SCHEMA_VERSION = "tuppi.exact.hypothetical_continuation.v1"

#: Every hypothetical match reference starts with this prefix. It is checked, not
#: merely documented, so a hypothetical state cannot be mistaken for a real one.
HYPOTHETICAL_MATCH_REF_PREFIX = "hypothetical"


@dataclass(frozen=True, slots=True)
class HypotheticalContinuation:
    """One engine-validated continuation of a real observation.

    ``state`` is a genuine :class:`DealState`: the same type the engine uses for
    a dealt deal, at the same decision point, with the same public history. Only
    the unobserved hands differ, and only because they were sampled.
    """

    state: DealState
    observing_seat: int
    source_match_ref: str
    source_deal_ref: str
    sample_index: int
    is_hypothetical: bool = field(default=True, init=False)
    visibility: str = field(default="research_private_hypothetical", init=False)
    schema_version: str = field(default=CONTINUATION_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.state, DealState):
            raise ContinuationError("a continuation wraps a DealState")
        if not self.state.match_ref.startswith(HYPOTHETICAL_MATCH_REF_PREFIX):
            raise ContinuationError(
                "a hypothetical continuation must carry a hypothetical match_ref"
            )
        if type(self.observing_seat) is not int or self.observing_seat not in range(4):
            raise ContinuationError("observing seat must be an integer in 0..3")

    @property
    def current_actor(self) -> int | None:
        return self.state.current_actor

    def provenance(self) -> dict[str, object]:
        """Canonical provenance that never contains a card."""

        return {
            "is_hypothetical": True,
            "observing_seat": self.observing_seat,
            "phase": self.state.phase.value,
            "sample_index": self.sample_index,
            "schema_version": CONTINUATION_SCHEMA_VERSION,
            "source_deal_ref": self.source_deal_ref,
            "source_match_ref": self.source_match_ref,
            "tricks_completed": len(self.state.completed_tricks),
            "usage_rule": (
                "A hypothetical continuation is search input only. It must never "
                "be recorded as a dealt deal, entered into a bank, or counted as "
                "an observation."
            ),
            "visibility": "research_private_hypothetical",
        }


def reconstruct_initial_hands(
    observation: PlayerObservation, assignment: HiddenHandAssignment
) -> tuple[tuple[Card, ...], ...]:
    """Return the four initial 13-card hands implied by the assignment.

    Each seat's initial hand is exactly what it still holds plus what it has
    already played, both of which are known: the first from the assignment, the
    second from the public record.

    Order matters, for one specific reason. The engine derives legal-action order
    from the order of the cards in a hand, and Phase 4's tie-break is the lowest
    legal-action index, so hand order can change a policy's choice.

    * The **observing seat's** current order is known, so it is preserved
      exactly: its own cards come first in the observed order and its played
      cards are appended, and removing the played cards during replay leaves the
      observed order intact.
    * Every **other seat's** original order is not public and is not even
      meaningful to the observer, so it is canonicalized by deck index. A
      hypothetical therefore *cannot* reproduce the real deal's ``deal_id``, which
      is a feature: it makes a hypothetical structurally impossible to confuse
      with a deal that was actually dealt.
    """

    if not isinstance(observation, PlayerObservation):
        raise ContinuationError("reconstruct_initial_hands requires an observation")
    if not isinstance(assignment, HiddenHandAssignment):
        raise ContinuationError("reconstruct_initial_hands requires an assignment")
    if assignment.observing_seat != observation.observing_seat:
        raise ContinuationError("the assignment belongs to a different seat")

    seat = observation.observing_seat
    played: list[list[Card]] = [[], [], [], []]
    for trick in observation.completed_tricks:
        for play in trick.plays:
            played[play.seat].append(play.card)
    for play in observation.current_trick:
        played[play.seat].append(play.card)

    hands: list[tuple[Card, ...]] = []
    for index in range(4):
        held = tuple(assignment.hands[index])
        overlap = set(held) & set(played[index])
        if overlap:
            raise ContinuationError("a played card was also assigned as held")
        if index == seat:
            ordered = tuple(observation.own_hand) + tuple(played[index])
            if set(ordered) != set(held) | set(played[index]):
                raise ContinuationError(
                    "the assignment altered the observing seat's own hand"
                )
        else:
            ordered = tuple(
                sorted(set(held) | set(played[index]), key=card_to_index)
            )
        if len(ordered) != 13 or len(set(ordered)) != 13:
            raise ContinuationError(
                f"reconstructed hand for seat {index} has {len(set(ordered))} "
                "distinct cards, not 13"
            )
        hands.append(ordered)
    return tuple(hands)


def hypothetical_continuation(
    observation: PlayerObservation,
    assignment: HiddenHandAssignment,
    *,
    match_ref: str | None = None,
) -> HypotheticalContinuation:
    """Build the engine-validated continuation for one sampled assignment.

    The public action history is replayed through :func:`apply_action`, so the
    resulting state is reachable under ``project_target_v1`` by construction.
    """

    if not isinstance(observation, PlayerObservation):
        raise ContinuationError("hypothetical_continuation requires an observation")
    hands = reconstruct_initial_hands(observation, assignment)
    reference = match_ref or _default_match_ref(observation, assignment)
    if not reference.startswith(HYPOTHETICAL_MATCH_REF_PREFIX):
        raise ContinuationError(
            "an explicit continuation match_ref must keep the hypothetical prefix"
        )

    state = create_deal_state(
        ExplicitDeal(dealer=observation.dealer, hands=hands),
        starting_score=observation.match_score,
        match_ref=reference,
        deal_ref=f"{reference}/deal:0",
        deal_number=0,
        event_start_index=0,
    )
    for action in observation.show_actions:
        state = apply_action(
            state,
            EngineShowAction(
                seat=action.seat,
                shown_card=action.shown_card,
                declared_contract=action.declared_contract,
            ),
        )
    for trick in observation.completed_tricks:
        for play in trick.plays:
            state = apply_action(state, PlayCardAction(seat=play.seat, card=play.card))
    for play in observation.current_trick:
        state = apply_action(state, PlayCardAction(seat=play.seat, card=play.card))

    _require_same_decision_point(observation, state)
    return HypotheticalContinuation(
        state=state,
        observing_seat=observation.observing_seat,
        source_match_ref=observation.match_ref,
        source_deal_ref=observation.deal_ref,
        sample_index=assignment.sample_index,
    )


def continuations_for(
    observation: PlayerObservation,
    assignments: tuple[HiddenHandAssignment, ...],
) -> tuple[HypotheticalContinuation, ...]:
    """Build one continuation per assignment, in the order they were drawn."""

    if type(assignments) is not tuple or not assignments:
        raise ContinuationError("continuations_for requires a nonempty tuple")
    return tuple(
        hypothetical_continuation(observation, assignment)
        for assignment in assignments
    )


def _default_match_ref(
    observation: PlayerObservation, assignment: HiddenHandAssignment
) -> str:
    from tuppi_eval.serialization import content_digest

    digest = content_digest(
        {
            "sample_index": assignment.sample_index,
            "schema_version": CONTINUATION_SCHEMA_VERSION,
            "source_deal_ref": observation.deal_ref,
            "source_match_ref": observation.match_ref,
            "tricks_completed": len(observation.completed_tricks),
        }
    )
    return f"{HYPOTHETICAL_MATCH_REF_PREFIX}:{digest[:32]}"


def _require_same_decision_point(
    observation: PlayerObservation, state: DealState
) -> None:
    """Assert that the replay landed on the observation's own decision point."""

    if state.phase is not observation.phase:
        raise ContinuationError(
            f"replay reached {state.phase.value}, not {observation.phase.value}"
        )
    if state.current_actor != observation.current_actor:
        raise ContinuationError("replay reached a different acting seat")
    if state.phase not in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        raise ContinuationError("a continuation must stop at an open decision")
    if len(state.completed_tricks) != len(observation.completed_tricks):
        raise ContinuationError("replay produced a different completed-trick count")
    if state.current_trick != observation.current_trick:
        raise ContinuationError("replay produced a different partial trick")
    if state.team_tricks != observation.team_tricks:
        raise ContinuationError("replay produced different team trick totals")
    if tuple(state.hands[observation.observing_seat]) != tuple(observation.own_hand):
        raise ContinuationError(
            "replay altered the observing seat's own hand or its order"
        )
