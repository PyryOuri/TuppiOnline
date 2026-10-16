"""N06: exact repeated-subproblem caching for the security search.

The question is narrow: can memoising identical subproblems cut engine
transitions without changing a single root value, label or action? Nothing here
is a heuristic. No world is dropped, no probability is introduced and no
correctness limit is relaxed; a cache miss simply costs what it always cost.

## The key, and why it is sufficient

The value of an information class depends only on how the deal can still be
played out, so the key carries exactly that and nothing about how the position
was reached:

* the **root information key**, so nothing is ever transplanted between roots;
* **objective and control model**, since a cached number means nothing without
  the question it answers;
* the **starting score**, kept for conservatism even though N04's objective is
  a trick count and does not read it;
* **current actor**, the **public partial trick** in order, and the
  **accumulated team tricks**;
* the controlled seat's **remaining hand in its own order**, because canonical
  showing and tie behaviour depend on that order rather than on a sorted set;
* the **complete set of feasible remaining allocations**, one entry per world,
  each seat's cards sorted because the order of unseen cards is not observable,
  and the set itself sorted so world enumeration order cannot split a key.

Two positions sharing that key have the same remaining cards in the same hands,
the same turn and the same accumulated totals, so the reachable game is
identical and the value must be. The allocation set is carried in full: suit
lengths or the union of unknown cards would merge genuinely different positions
and are never used.

## What is cached, and what is not

Values and **optimal action sets**, never plans. A plan's keys hash the whole
public history, so a plan borrowed from another history would name keys that do
not exist here. The value is history-independent; the *choice* among equally
valued actions is not, because the inherited v2 ranking reads the observation.
So the second pass re-applies that ranking against the current observation and
rebuilds the plan for this history, which keeps baseline ties exactly where the
uncached path puts them. The rebuilt plan is then handed to N03 unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import EnginePhase, observation_for
from tuppi_rules import card_to_index

from .certificates import ControlModel, OBJECTIVE
from .support import semantic_observation_key

DEFAULT_MAX_ENTRIES = 200_000


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stores: int = 0
    rejected_full: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    def diagnostics(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "lookups": self.lookups,
            "stores": self.stores,
            "rejected_when_full": self.rejected_full,
        }


class SecurityCache:
    """A bounded exact memo. Full means stop storing, never start guessing."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._values: dict = {}
        self.stats = CacheStats()

    def __len__(self) -> int:
        return len(self._values)

    @property
    def entries(self) -> int:
        return len(self._values)

    def get(self, key):
        found = self._values.get(key)
        if found is None:
            self.stats.misses += 1
        else:
            self.stats.hits += 1
        return found

    def put(self, key, value) -> None:
        if key in self._values:
            return
        if len(self._values) >= self.max_entries:
            self.stats.rejected_full += 1
            return
        self._values[key] = value
        self.stats.stores += 1

    def diagnostics(self) -> dict:
        return {"entries": self.entries, "max_entries": self.max_entries,
                **self.stats.diagnostics()}


def position_key(states, *, seat: int, root_key: str, control: ControlModel):
    """The history-independent identity of one information class.

    Built only from the hypothetical states the search already holds, all of
    which were inferred from the root observation. No field of the real deal is
    consulted, and no component of the key names a single hidden world: the
    allocation set is carried whole and sorted.
    """

    first = states[0]
    own = tuple(card_to_index(card) for card in first.hands[seat])
    trick = tuple((play.seat, card_to_index(play.card)) for play in first.current_trick)
    allocations = tuple(
        sorted(
            tuple(
                tuple(sorted(card_to_index(card) for card in state.hands[other]))
                for other in range(4)
                if other != seat
            )
            for state in states
        )
    )
    return (
        root_key,
        OBJECTIVE,
        control.value,
        (first.starting_score.team0, first.starting_score.team1),
        first.current_actor,
        trick,
        tuple(first.team_tricks),
        own,
        allocations,
    )


def search_value(states, *, seat, team, meter, cache, root_key):
    """Pass one: the exact value, memoised, with the optimal action set.

    Deliberately does not consult the v2 ranking. Ordering among equally valued
    actions is a property of the current history, settled in pass two.
    """

    meter.nodes += 1
    if states[0].phase is not EnginePhase.TRICK_PLAY:
        return max(state.team_tricks[team] for state in states), None

    key = position_key(states, seat=seat, root_key=root_key, control=ControlModel.SINGLE_SEAT)
    cached = cache.get(key)
    if cached is not None:
        return cached

    actor = states[0].current_actor
    if actor != seat:
        union: dict = {}
        for state in states:
            for action in observation_for(state, actor).legal_actions:
                union.setdefault(action, []).append(state)
        worst = -1
        for action, subset in union.items():
            value, _ = search_value(
                tuple(meter.step(state, action) for state in subset),
                seat=seat, team=team, meter=meter, cache=cache, root_key=root_key,
            )
            worst = max(worst, value)
        cache.put(key, (worst, None))
        return worst, None

    common = set(observation_for(states[0], seat).legal_actions)
    for state in states[1:]:
        common &= set(observation_for(state, seat).legal_actions)
    scored: dict = {}
    for action in sorted(common, key=lambda a: card_to_index(a.card)):
        value, _ = search_value(
            tuple(meter.step(state, action) for state in states),
            seat=seat, team=team, meter=meter, cache=cache, root_key=root_key,
        )
        scored[action] = value
    best = min(scored.values())
    optimal = frozenset(action for action, value in scored.items() if value == best)
    cache.put(key, (best, optimal))
    return best, optimal


def extract_plan(states, *, seat, team, meter, cache, root_key, prefer):
    """Pass two: rebuild a plan for *this* history from the cached optima.

    Only one own action is followed per node, so this pass walks a fraction of
    the search tree. Every opposition branch is still visited, because the plan
    has to name an action at every own key those branches can reach.

    A bounded cache can refuse to store, so an own node may arrive here without
    an entry. That is recomputed rather than treated as an error: running out of
    memo space is allowed to cost time and is never allowed to cost an answer.
    """

    if states[0].phase is not EnginePhase.TRICK_PLAY:
        return {}

    actor = states[0].current_actor
    if actor != seat:
        merged: dict = {}
        union: dict = {}
        for state in states:
            for action in observation_for(state, actor).legal_actions:
                union.setdefault(action, []).append(state)
        for action, subset in union.items():
            branch = extract_plan(
                tuple(meter.step(state, action) for state in subset),
                seat=seat, team=team, meter=meter, cache=cache,
                root_key=root_key, prefer=prefer,
            )
            for key, chosen in branch.items():
                if merged.setdefault(key, chosen) != chosen:
                    raise AssertionError("two branches demand different actions at one key")
        return merged

    classes: dict = {}
    for state in states:
        observation = observation_for(state, seat)
        classes.setdefault(semantic_observation_key(observation), []).append(
            (state, observation)
        )
    merged = {}
    for information_key, members in classes.items():
        subset = tuple(state for state, _ in members)
        cached = cache.get(position_key(
            subset, seat=seat, root_key=root_key, control=ControlModel.SINGLE_SEAT
        ))
        if cached is None or cached[1] is None:
            _value, optimal = search_value(
                subset, seat=seat, team=team, meter=meter, cache=cache, root_key=root_key
            )
            if optimal is None:  # pragma: no cover - an own node always has one
                raise AssertionError("an own node produced no optimal action set")
        else:
            optimal = cached[1]
        # The tie is settled against this history's observation, which is what
        # keeps the cached path on the same baseline action as the plain search.
        action = prefer(members[0][1], optimal)
        branch = extract_plan(
            tuple(meter.step(state, action) for state in subset),
            seat=seat, team=team, meter=meter, cache=cache,
            root_key=root_key, prefer=prefer,
        )
        for key, chosen in branch.items():
            if merged.setdefault(key, chosen) != chosen:
                raise AssertionError("two branches demand different actions at one key")
        merged[information_key] = action
    return merged
