"""Independent exhaustive N01 reference, intentionally unoptimized.

No sampling, memoization, equivalent-card pruning, or future nolo verifier/search.
Only engine legality filters the unconstrained partitions. The separate hard
model recursion uses capacities/allowed owners, never the accepted engine set.
"""

from collections import Counter
from itertools import combinations

from tuppi_engine import EnginePhase, apply_action, observation_for
from tuppi_engine.errors import EngineValidationError
from tuppi_exact.continuation import hypothetical_continuation
from tuppi_exact.errors import ContinuationError
from tuppi_exact.sampling import HiddenHandAssignment
from tuppi_rules import FULL_DECK, card_to_index
from tuppi_rules.errors import RulesError


def assignment_key(hands):
    """Compare allocations, ignoring only unobservable hidden hand order."""
    return tuple(tuple(sorted(map(card_to_index, hand))) for hand in hands)


def all_partitions(obs):
    played = [p for t in obs.completed_tricks for p in t.plays]
    played.extend(obs.current_trick)
    sizes = [13 - sum(p.seat == s for p in played) for s in range(4)]
    unseen = set(FULL_DECK) - {p.card for p in played} - set(obs.own_hand)
    seats = [s for s in range(4) if s != obs.observing_seat]
    for first in combinations(sorted(unseen, key=card_to_index), sizes[seats[0]]):
        left = unseen - set(first)
        for second in combinations(sorted(left, key=card_to_index), sizes[seats[1]]):
            hands = [None] * 4
            hands[obs.observing_seat] = obs.own_hand
            hands[seats[0]], hands[seats[1]] = first, second
            hands[seats[2]] = tuple(sorted(left - set(second), key=card_to_index))
            owners = {c: s for s in seats for c in hands[s]}
            yield HiddenHandAssignment(obs.observing_seat, tuple(hands), owners, 0)


def engine_worlds(obs):
    accepted = {}
    attempted = 0
    for assignment in all_partitions(obs):
        attempted += 1
        try:
            state = hypothetical_continuation(obs, assignment).state
        except (RulesError, EngineValidationError, ContinuationError):
            continue
        key = assignment_key(assignment.hands)
        assert key not in accepted, "duplicate partition"
        accepted[key] = state
    return attempted, accepted


def hard_assignment_set(model):
    hands = [set(h) for h in model.known_held]
    capacity = list(model.capacity)
    accepted = set()

    def visit(index):
        if index == len(model.unknown_cards):
            assert not any(capacity)
            accepted.add(assignment_key(hands))
            return
        card = model.unknown_cards[index]
        for seat in sorted(model.allowed_seats(card)):
            if capacity[seat]:
                capacity[seat] -= 1
                hands[seat].add(card)
                visit(index + 1)
                hands[seat].remove(card)
                capacity[seat] += 1

    visit(0)
    return accepted


def terminal_counts(state, team):
    if state.phase is not EnginePhase.TRICK_PLAY:
        assert len(state.completed_tricks) == 13
        return Counter({state.team_tricks[team]: 1})
    counts = Counter()
    for action in observation_for(state, state.current_actor).legal_actions:
        counts.update(terminal_counts(apply_action(state, action), team))
    return counts


def cooperative_value(state, team):
    """Independent engine minimax; friendly seats minimize, opponents maximize."""
    if state.phase is not EnginePhase.TRICK_PLAY:
        assert len(state.completed_tricks) == 13
        return state.team_tricks[team]
    values = [cooperative_value(apply_action(state, a), team)
              for a in observation_for(state, state.current_actor).legal_actions]
    return (min if state.current_actor % 2 == team else max)(values)


def assert_at_most(counts, bound):
    assert counts and max(counts) <= bound, f"claimed at-most-{bound}: {dict(counts)}"
