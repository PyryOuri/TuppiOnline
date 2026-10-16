"""Independent tiny-space behavioural posterior oracle.

This module deliberately uses a direct card-by-card enumeration rather than the
production counted sampler or production posterior.  It is intended for small
late-game and artificial positions only.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from tuppi_engine import PlayerObservation
from tuppi_rules import Card, card_to_index
from tuppi_exact.constraints import HardConstraintModel
from tuppi_exact.sampling import HiddenHandAssignment

from .history import CausalPublicHistory
from .models import BehaviorModel
from .reconstruction import replay_candidate


class ExactEnumerationLimit(ValueError):
    """The independent oracle was asked to enumerate a non-tiny state."""


@dataclass(frozen=True, slots=True)
class ExactBehavioralPosterior:
    assignments: tuple[HiddenHandAssignment, ...]
    normalized_weights: tuple[float, ...]
    log_weights: tuple[float, ...]
    feasible_world_count: int

    def owner_marginals(self, observation: PlayerObservation) -> dict[str, dict[int, float]]:
        model = HardConstraintModel.build(observation)
        result: dict[str, dict[int, float]] = {}
        for card in model.unknown_cards:
            values = {seat: 0.0 for seat in model.allowed_seat_map[card]}
            for assignment, weight in zip(self.assignments, self.normalized_weights, strict=True):
                owner = assignment.sampled_owner[card]
                values[owner] = values.get(owner, 0.0) + weight
            result[card.to_code()] = values
        return result


def enumerate_feasible_assignments(
    observation: PlayerObservation,
    *,
    max_assignments: int | None = None,
) -> tuple[HiddenHandAssignment, ...]:
    """Enumerate each feasible card-owner assignment exactly once."""

    model = HardConstraintModel.build(observation)
    cards = tuple(model.unknown_cards)
    result: list[HiddenHandAssignment] = []
    owner: dict[Card, int] = {}
    remaining = list(model.capacity)

    def visit(position: int) -> None:
        if position == len(cards):
            if any(remaining):
                return
            if max_assignments is not None and len(result) >= max_assignments:
                raise ExactEnumerationLimit(
                    f"feasible set exceeds the configured limit of {max_assignments}"
                )
            hands = [list(model.known_held[seat]) for seat in range(4)]
            for card, seat in owner.items():
                hands[seat].append(card)
            result.append(
                HiddenHandAssignment(
                    observing_seat=model.observing_seat,
                    hands=tuple(
                        tuple(sorted(hand, key=card_to_index)) for hand in hands
                    ),
                    sampled_owner=dict(owner),
                    sample_index=len(result),
                )
            )
            return
        card = cards[position]
        for seat in sorted(model.allowed_seat_map[card]):
            if remaining[seat] <= 0:
                continue
            remaining[seat] -= 1
            owner[card] = seat
            visit(position + 1)
            del owner[card]
            remaining[seat] += 1

    visit(0)
    return tuple(result)


def exact_behavioral_posterior(
    observation: PlayerObservation,
    behavior_model: BehaviorModel,
    *,
    history: CausalPublicHistory | None = None,
    include_showing: bool = True,
    include_trick_play: bool = True,
    actor_seats: tuple[int, ...] | None = None,
) -> ExactBehavioralPosterior:
    """Compute the complete feasible-set posterior for tiny reference states."""

    if not isinstance(observation, PlayerObservation):
        raise TypeError("exact posterior requires an observation")
    public_history = history or CausalPublicHistory.from_observation(observation)
    assignments = enumerate_feasible_assignments(observation)
    actors = (
        tuple(seat for seat in range(4) if seat != observation.observing_seat)
        if actor_seats is None
        else actor_seats
    )
    scores: list[float] = []
    for assignment in assignments:
        replay = replay_candidate(observation, assignment, public_history)
        score = 0.0
        for item, actor_observation in replay.observations_before_actions():
            if item.action.seat not in actors:
                continue
            if item.phase == "SHOWING" and not include_showing:
                continue
            if item.phase == "TRICK_PLAY" and not include_trick_play:
                continue
            score += behavior_model.log_probability(actor_observation, item.action)
        scores.append(score)
    if not scores or not any(math.isfinite(score) for score in scores):
        raise ValueError("exact posterior has no finite behavioural support")
    maximum = max(score for score in scores if math.isfinite(score))
    masses = tuple(math.exp(score - maximum) if math.isfinite(score) else 0.0 for score in scores)
    total = math.fsum(masses)
    return ExactBehavioralPosterior(
        assignments=assignments,
        normalized_weights=tuple(mass / total for mass in masses),
        log_weights=tuple(scores),
        feasible_world_count=len(assignments),
    )
