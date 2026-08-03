"""The exact late-game solver: perfect-information optimal play, or nothing.

Given a position in which all four hands are known - a real research-private
deal, or a hypothetical continuation built from a sampled assignment - this
module computes the game-theoretic optimum exactly. It never estimates. If a
position is out of budget it raises :class:`SolverBudgetError` rather than
returning a heuristic guess, because a solver that silently degrades into a
heuristic is worse than no solver at all: its numbers keep the authority of an
exact answer while losing the property that earned it.

Why one trick-count minimax covers both contracts
-------------------------------------------------

``project_target_v1`` has no trump suit, always plays 13 tricks, and scores a
deal purely from the team trick split. Both scoring formulas are strictly
monotone in one team's trick count:

* **RAMI.** The declaring team's signed value rises with its own tricks
  (``+4`` per trick above six), and the defenders' stolen-RAMI value also rises
  with *their* tricks (``+8`` per trick above six). So in RAMI *both* teams want
  tricks, and the game is zero-sum in the trick split.
* **NOLO.** The team with fewer tricks wins, and the winner's points rise as its
  tricks fall. So in NOLO both teams want to avoid tricks, and the game is again
  zero-sum in the trick split.

One search therefore suffices: a minimax on team-0's final trick count, with the
polarity taken from the contract. There is no separate NOLO engine and no
separate RAMI engine to keep in agreement.

Why the match score does not change optimal play
------------------------------------------------

Fix the contract and the declarer. The deal outcome is a function of the trick
split alone, and the rising-score transition is a function of the deal outcome
and the starting score alone. So a team's *match* utility is a function of the
trick split alone, and :func:`match_utility_is_monotone` verifies exhaustively
that it is weakly monotone in the same direction as the deal points.

A weakly monotone transform of a zero-sum game leaves the minimax solution an
equilibrium, so **every trick-optimal action is also match-optimal**, at every
score state, under perfect information. The converse fails only by adding ties.
:mod:`tuppi_exact.diagnosis` turns that into a testable claim about the Phase 4
rising-score rules; it is the reason those rules cannot buy anything a
perfect-information player would want.

The statement is about perfect information and nothing else. Under *imperfect*
information a team facing a step-shaped utility - any win resets the opponents'
rise, regardless of margin - may rationally prefer a line that maximizes the
probability of winning over one that maximizes expected points. That is a real
effect, and it is exactly what a later phase's search agent has to represent.

Exactness aids
--------------

Alpha-beta with a transposition table on the incremental value, plus *equivalent
card* reduction: two cards of one suit in one hand are interchangeable when no
unplayed card of that suit sits between them in another hand. Collapsing such a
run is exact, not a heuristic pruning, and it is what brings a late-game
position into range for a pure-Python search.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_engine import (
    DealState,
    EnginePhase,
    PlayCardAction,
)
from tuppi_rules import (
    Card,
    Contract,
    DealScore,
    MatchScore,
    RANK_ORDER,
    SUIT_ORDER,
    Team,
    TRICKS_PER_DEAL,
    card_from_index,
    card_to_index,
    is_match_terminal,
    score_nolo,
    score_rami_for_declarer,
    team_for_seat,
    transition_rising_score,
)

from .continuation import HypotheticalContinuation
from .errors import SolverError, SolverBudgetError


SOLVER_SCHEMA_VERSION = "tuppi.exact.late_game_solution.v1"
SOLVER_ALGORITHM_ID = "tuppi.exact.trick_count_minimax_v1"

#: Default exact-solving budget in remaining tricks. Raising it is a deliberate
#: cost decision, never an accuracy decision: the answer is exact either way.
DEFAULT_MAXIMUM_TRICKS_REMAINING = 5

#: Default hard node ceiling. Reaching it raises rather than truncating.
DEFAULT_NODE_BUDGET = 4_000_000

_RANK_COUNT = len(RANK_ORDER)


# --------------------------------------------------------------------- scoring


def deal_outcome_for_split(
    *,
    contract: Contract,
    declarer: int | None,
    team0_tricks: int,
) -> DealScore:
    """Return the authoritative deal score for one complete trick split."""

    if not isinstance(contract, Contract):
        raise SolverError("contract must be a Contract value")
    if type(team0_tricks) is not int or team0_tricks not in range(
        TRICKS_PER_DEAL + 1
    ):
        raise SolverError("team0_tricks must be an integer in 0..13")
    team1_tricks = TRICKS_PER_DEAL - team0_tricks
    if contract is Contract.NOLO:
        if declarer is not None:
            raise SolverError("a NOLO deal has no declarer")
        return score_nolo(team0_tricks, team1_tricks)
    if declarer is None:
        raise SolverError("a RAMI deal requires a declarer")
    return score_rami_for_declarer(declarer, team0_tricks, team1_tricks)


def match_score_after_split(
    *,
    contract: Contract,
    declarer: int | None,
    team0_tricks: int,
    starting_score: MatchScore,
) -> MatchScore:
    """Return the rising-score state that follows one complete trick split."""

    score = deal_outcome_for_split(
        contract=contract, declarer=declarer, team0_tricks=team0_tricks
    )
    return transition_rising_score(starting_score, score)


def team0_prefers_more_tricks(contract: Contract) -> bool:
    """True when team 0 wants a larger trick count under this contract.

    RAMI rewards tricks for both partnerships - the declarers to make it, the
    defenders to steal it - so both maximize. NOLO penalizes tricks for both, so
    both minimize.
    """

    if not isinstance(contract, Contract):
        raise SolverError("contract must be a Contract value")
    return contract is Contract.RAMI


def match_utility_is_monotone(
    *,
    contract: Contract,
    declarer: int | None,
    starting_score: MatchScore,
    team: Team,
) -> bool:
    """Verify that ``team``'s match utility is weakly monotone in team-0 tricks.

    Utility here is the coarsest honest ordering the rising score supports:
    winning the match outright beats holding a rise, holding a larger rise beats
    a smaller one, and being reset to 0-0 is worst. Every comparison is exact
    integer arithmetic over the fourteen possible trick splits.
    """

    values = [
        _match_utility_value(
            contract=contract,
            declarer=declarer,
            team0_tricks=split,
            starting_score=starting_score,
            team=team,
        )
        for split in range(TRICKS_PER_DEAL + 1)
    ]
    increasing = all(later >= earlier for earlier, later in zip(values, values[1:]))
    decreasing = all(later <= earlier for earlier, later in zip(values, values[1:]))
    wants_more = team0_prefers_more_tricks(contract) == (team is Team.TEAM_0)
    return increasing if wants_more else decreasing


def match_utility_from_score(after: MatchScore, team: Team) -> tuple[int, int]:
    """Return an ordered utility pair for ``team`` at a post-deal score.

    The ordering is the coarsest one the rising score actually supports:

    * a won match is ``(1, 0)`` and a lost match ``(-1, 0)``. **Overshoot past 52
      is worth nothing.** Crediting it would rank a 56-point win above a 52-point
      win and make a rule that stops competing for a worthless margin look
      harmful - exactly the mistake this currency exists to avoid.
    * a nonterminal state is ``(0, own_rise - opponent_rise)``. At most one team is
      ever positive, so this is the own rise when up and the negated opponent rise
      when down.

    This is a documented *ordering*, not a match win probability: a win probability
    would need a model of the deals still to come. It is strong enough for the only
    question asked of it - did this card reach a strictly worse match state than
    exact optimal play - and weak enough to stay exact.
    """

    if not isinstance(after, MatchScore):
        raise SolverError("match_utility_from_score requires a MatchScore")
    if not isinstance(team, Team):
        raise SolverError("match_utility_from_score requires a Team")
    own = after.for_team(team)
    opponent = after.for_team(Team.TEAM_1 if team is Team.TEAM_0 else Team.TEAM_0)
    if is_match_terminal(after):
        return (1, 0) if own >= opponent else (-1, 0)
    return (0, own - opponent)


def _match_utility_value(
    *,
    contract: Contract,
    declarer: int | None,
    team0_tricks: int,
    starting_score: MatchScore,
    team: Team,
) -> tuple[int, int]:
    """Return an ordered utility pair: (match won, own rise) for ``team``."""

    return match_utility_from_score(
        match_score_after_split(
            contract=contract,
            declarer=declarer,
            team0_tricks=team0_tricks,
            starting_score=starting_score,
        ),
        team,
    )


# ---------------------------------------------------------------------- result


@dataclass(frozen=True, slots=True)
class SolvedAction:
    """One legal action with its exact perfect-information consequences."""

    card: Card
    team0_tricks_final: int
    own_team_tricks_final: int
    deal_points: int
    deal_winner: Team
    own_team_wins_deal: bool
    match_score_after: tuple[int, int]
    match_terminal: bool
    match_utility: tuple[int, int]
    equivalent_cards: tuple[Card, ...]

    def to_data(self) -> dict[str, object]:
        from tuppi_rules import card_to_code

        return {
            "card": card_to_code(self.card),
            "deal_points": self.deal_points,
            "deal_winner_team": self.deal_winner.value,
            "equivalent_cards": [
                card_to_code(item) for item in self.equivalent_cards
            ],
            "match_score_after": list(self.match_score_after),
            "match_terminal": self.match_terminal,
            "match_utility": list(self.match_utility),
            "own_team_tricks_final": self.own_team_tricks_final,
            "own_team_wins_deal": self.own_team_wins_deal,
            "team0_tricks_final": self.team0_tricks_final,
        }


@dataclass(frozen=True, slots=True)
class LateGameSolution:
    """The complete exact answer for one perfect-information position."""

    acting_seat: int
    contract: Contract
    declarer: int | None
    tricks_remaining: int
    team0_tricks_so_far: int
    optimal_team0_tricks_final: int
    optimal_own_team_tricks_final: int
    own_team_prefers_more_tricks: bool
    optimal_cards: tuple[Card, ...]
    actions: tuple[SolvedAction, ...]
    nodes_visited: int
    transposition_hits: int
    is_exact: bool = field(default=True, init=False)
    algorithm_id: str = field(default=SOLVER_ALGORITHM_ID, init=False)
    schema_version: str = field(default=SOLVER_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.actions:
            raise SolverError("a solution must describe at least one legal action")
        if not self.optimal_cards:
            raise SolverError("a solution must name at least one optimal card")

    def value_for(self, card: Card) -> SolvedAction:
        for action in self.actions:
            if action.card == card:
                return action
            if card in action.equivalent_cards:
                return action
        raise SolverError("the requested card is not legal in this position")

    def is_optimal(self, card: Card) -> bool:
        """True when playing ``card`` attains the exact optimum."""

        return self.regret_in_tricks(card) == 0

    def regret_in_tricks(self, card: Card) -> int:
        """Own-team tricks given up by playing ``card`` instead of an optimum.

        Zero for every optimal card and strictly positive otherwise. The sign is
        taken from the contract: RAMI rewards own tricks, NOLO penalizes them, so
        "given up" means fewer tricks in RAMI and more tricks in NOLO.
        """

        achieved = self.value_for(card).own_team_tricks_final
        if self.own_team_prefers_more_tricks:
            return self.optimal_own_team_tricks_final - achieved
        return achieved - self.optimal_own_team_tricks_final

    def regret_in_deal_points(self, card: Card) -> int:
        """Signed own-team deal points given up by playing ``card``.

        Positive means the card costs the acting partnership deal value against
        exact optimal play; zero means it is one of the optimal cards.

        Deal points are the wrong currency for judging a *match* rule: a rule that
        deliberately stops competing for a worthless margin will show a positive
        deal-point regret while costing the match nothing. Use
        :meth:`match_utility_regret` for that question.
        """

        optimal = self.value_for(self.optimal_cards[0])
        achieved = self.value_for(card)
        return _signed_own_points(optimal) - _signed_own_points(achieved)

    @property
    def optimal_match_utility(self) -> tuple[int, int]:
        """The acting partnership's match utility under exact optimal play."""

        return self.value_for(self.optimal_cards[0]).match_utility

    def match_utility_for(self, card: Card) -> tuple[int, int]:
        return self.value_for(card).match_utility

    def match_utility_regret(self, card: Card) -> int:
        """Match utility given up by playing ``card``: 0, or positive if worse.

        Returns ``0`` when the card reaches the same match state as optimal play -
        which is the case for every card whose remaining margin the rising score
        discards. This is the currency in which a rising-score rule must be judged.
        """

        optimal = self.optimal_match_utility
        achieved = self.match_utility_for(card)
        if achieved == optimal:
            return 0
        return 1 if achieved < optimal else -1

    def is_match_optimal(self, card: Card) -> bool:
        """True when ``card`` reaches an exactly match-optimal state."""

        return self.match_utility_regret(card) == 0

    def to_data(self) -> dict[str, object]:
        from tuppi_rules import card_to_code

        return {
            "acting_seat": self.acting_seat,
            "actions": [item.to_data() for item in self.actions],
            "algorithm_id": self.algorithm_id,
            "contract": self.contract.value,
            "declarer": self.declarer,
            "is_exact": True,
            "nodes_visited": self.nodes_visited,
            "optimal_cards": [card_to_code(item) for item in self.optimal_cards],
            "optimal_own_team_tricks_final": self.optimal_own_team_tricks_final,
            "optimal_team0_tricks_final": self.optimal_team0_tricks_final,
            "own_team_prefers_more_tricks": self.own_team_prefers_more_tricks,
            "schema_version": self.schema_version,
            "team0_tricks_so_far": self.team0_tricks_so_far,
            "transposition_hits": self.transposition_hits,
            "tricks_remaining": self.tricks_remaining,
        }


# ---------------------------------------------------------------------- search


#: Transposition-entry kinds. A cutoff yields a bound, never an exact value, and
#: storing a bound as if it were exact is the classic way to make an "exact"
#: solver quietly wrong. Every entry therefore records which it is.
_EXACT = 0
_LOWER_BOUND = 1
_UPPER_BOUND = 2


class _Search:
    """Alpha-beta over the incremental team-0 trick count."""

    __slots__ = ("team0_maximizes", "table", "nodes", "hits", "node_budget")

    def __init__(self, *, team0_maximizes: bool, node_budget: int) -> None:
        self.team0_maximizes = team0_maximizes
        self.table: dict[tuple, tuple[int, int]] = {}
        self.nodes = 0
        self.hits = 0
        self.node_budget = node_budget

    def run(
        self,
        hands: tuple[frozenset[int], ...],
        trick: tuple[tuple[int, int], ...],
        actor: int,
        alpha: int,
        beta: int,
    ) -> int:
        self.nodes += 1
        if self.nodes > self.node_budget:
            raise SolverBudgetError(
                f"exact search exceeded the node budget of {self.node_budget}"
            )
        if not any(hands):
            return 0
        key = (hands, trick, actor)
        original_alpha, original_beta = alpha, beta
        cached = self.table.get(key)
        if cached is not None:
            value, kind = cached
            if kind == _EXACT:
                self.hits += 1
                return value
            if kind == _LOWER_BOUND:
                if value >= beta:
                    self.hits += 1
                    return value
                alpha = max(alpha, value)
            else:
                if value <= alpha:
                    self.hits += 1
                    return value
                beta = min(beta, value)

        maximizing = (team_for_seat(actor) is Team.TEAM_0) == self.team0_maximizes
        best: int | None = None
        for card in self._candidates(hands, trick, actor):
            following = list(hands)
            following[actor] = hands[actor] - {card}
            extended = trick + ((actor, card),)
            if len(extended) == 4:
                winner = _trick_winner(extended)
                gain = 1 if team_for_seat(winner) is Team.TEAM_0 else 0
                value = gain + self.run(
                    tuple(following),
                    (),
                    winner,
                    alpha - gain,
                    beta - gain,
                )
            else:
                value = self.run(
                    tuple(following), extended, (actor + 1) % 4, alpha, beta
                )
            if maximizing:
                best = value if best is None else max(best, value)
                alpha = max(alpha, best)
            else:
                best = value if best is None else min(best, value)
                beta = min(beta, best)
            if alpha >= beta:
                break
        if best is None:
            raise SolverError("a nonterminal position produced no legal card")
        if best <= original_alpha:
            kind = _UPPER_BOUND
        elif best >= original_beta:
            kind = _LOWER_BOUND
        else:
            kind = _EXACT
        self.table[key] = (best, kind)
        return best

    def _candidates(
        self,
        hands: tuple[frozenset[int], ...],
        trick: tuple[tuple[int, int], ...],
        actor: int,
    ) -> tuple[int, ...]:
        legal = _legal_indices(hands[actor], trick)
        return _reduce_equivalent(legal, hands, actor, trick)


def _legal_indices(
    hand: frozenset[int], trick: tuple[tuple[int, int], ...]
) -> tuple[int, ...]:
    if not trick:
        return tuple(sorted(hand))
    led_suit = trick[0][1] // _RANK_COUNT
    following = tuple(
        sorted(card for card in hand if card // _RANK_COUNT == led_suit)
    )
    return following or tuple(sorted(hand))


def _separating_cards(
    hands: tuple[frozenset[int], ...],
    actor: int,
    trick: tuple[tuple[int, int], ...],
) -> set[int]:
    """Return every card that can still separate two ranks for the acting seat.

    Two groups qualify, and leaving either out makes the reduction unsound:

    * cards another seat still holds, which decide future tricks;
    * cards **already in the current trick**, which decide *this* trick. A card
      of the led suit sitting between two of the actor's cards means one of them
      beats it and the other does not, so they are not interchangeable even
      though no unplayed hand holds anything between them.

    Cards from completed tricks are excluded: they are out of play and can never
    separate anything again.
    """

    separating: set[int] = set()
    for seat in range(4):
        if seat != actor:
            separating |= hands[seat]
    separating.update(card for _, card in trick)
    return separating


def _equivalence_groups(
    legal: tuple[int, ...],
    hands: tuple[frozenset[int], ...],
    actor: int,
    trick: tuple[tuple[int, int], ...],
) -> dict[int, tuple[int, ...]]:
    """Group interchangeable same-suit cards under one representative.

    Two cards of one suit held by the acting seat are interchangeable when no
    separating card of that suit lies between them: the cards in between are the
    acting seat's own, so whichever is played the rest keep the same relationship
    to every card that can still matter. The reduction is exact, not a heuristic
    pruning, and the representative is the lowest card of its run.
    """

    separating = _separating_cards(hands, actor, trick)
    groups: dict[int, list[int]] = {}
    representative: int | None = None
    for card in legal:
        suit = card // _RANK_COUNT
        if representative is not None and representative // _RANK_COUNT == suit:
            if not any(
                other // _RANK_COUNT == suit and representative < other < card
                for other in separating
            ):
                groups[representative].append(card)
                continue
        representative = card
        groups[representative] = [card]
    return {key: tuple(value) for key, value in groups.items()}


def _reduce_equivalent(
    legal: tuple[int, ...],
    hands: tuple[frozenset[int], ...],
    actor: int,
    trick: tuple[tuple[int, int], ...],
) -> tuple[int, ...]:
    """Return one representative per equivalence run, in canonical order."""

    if len(legal) < 2:
        return legal
    return tuple(_equivalence_groups(legal, hands, actor, trick))


def _trick_winner(trick: tuple[tuple[int, int], ...]) -> int:
    led_suit = trick[0][1] // _RANK_COUNT
    best_seat, best_card = trick[0]
    for seat, card in trick[1:]:
        if card // _RANK_COUNT == led_suit and card > best_card:
            best_seat, best_card = seat, card
    return best_seat


# ------------------------------------------------------------------- interface


def solve_late_game(
    state: DealState,
    *,
    maximum_tricks_remaining: int = DEFAULT_MAXIMUM_TRICKS_REMAINING,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> LateGameSolution:
    """Solve one perfect-information trick-play position exactly.

    ``state`` must be a real or hypothetical :class:`DealState` in
    ``TRICK_PLAY``. The whole state is used, including all four hands, so this
    function is *research-private by construction*: it is never handed to a
    policy through an observation, and no agent may call it on a real deal it is
    playing.
    """

    if not isinstance(state, DealState):
        raise SolverError("solve_late_game requires a DealState")
    if state.phase is not EnginePhase.TRICK_PLAY:
        raise SolverError("the exact solver applies only to trick play")
    if type(maximum_tricks_remaining) is not int or not (
        1 <= maximum_tricks_remaining <= TRICKS_PER_DEAL
    ):
        raise SolverError("maximum_tricks_remaining must be an integer in 1..13")
    if type(node_budget) is not int or node_budget <= 0:
        raise SolverError("node_budget must be a positive integer")

    actor = state.current_actor
    if actor is None:
        raise SolverError("the position has no acting seat")
    contract = state.contract
    if contract is None:
        raise SolverError("trick play requires a resolved contract")

    tricks_remaining = TRICKS_PER_DEAL - len(state.completed_tricks)
    if tricks_remaining > maximum_tricks_remaining:
        raise SolverBudgetError(
            f"{tricks_remaining} tricks remain, above the exact budget of "
            f"{maximum_tricks_remaining}; raise the budget or accept that this "
            "position is out of exact range"
        )

    hands = tuple(
        frozenset(card_to_index(card) for card in state.hands[seat])
        for seat in range(4)
    )
    trick = tuple(
        (play.seat, card_to_index(play.card)) for play in state.current_trick
    )
    team0_so_far = state.team_tricks[0]
    team0_maximizes = team0_prefers_more_tricks(contract)
    own_team = team_for_seat(actor)

    legal = _legal_indices(hands[actor], trick)
    groups = _equivalence_groups(legal, hands, actor, trick)

    solved: list[SolvedAction] = []
    search = _Search(team0_maximizes=team0_maximizes, node_budget=node_budget)
    for representative, run in groups.items():
        following = list(hands)
        following[actor] = hands[actor] - {representative}
        extended = trick + ((actor, representative),)
        if len(extended) == 4:
            winner = _trick_winner(extended)
            gain = 1 if team_for_seat(winner) is Team.TEAM_0 else 0
            value = gain + search.run(
                tuple(following), (), winner, -tricks_remaining, tricks_remaining
            )
        else:
            value = search.run(
                tuple(following),
                extended,
                (actor + 1) % 4,
                -tricks_remaining,
                tricks_remaining,
            )
        team0_final = team0_so_far + value
        solved.append(
            _build_action(
                card=card_from_index(representative),
                equivalent=tuple(card_from_index(item) for item in run),
                team0_final=team0_final,
                contract=contract,
                declarer=state.declarer,
                starting_score=state.starting_score,
                own_team=own_team,
            )
        )

    # The acting seat's preference direction on its *own* tricks follows the
    # contract: RAMI rewards tricks for both partnerships, NOLO penalizes them.
    # Taking the maximum unconditionally would silently invert every NOLO answer.
    prefers_more_own = team0_prefers_more_tricks(contract)
    root_maximizes_team0 = (own_team is Team.TEAM_0) == team0_maximizes
    best_team0 = (
        max(item.team0_tricks_final for item in solved)
        if root_maximizes_team0
        else min(item.team0_tricks_final for item in solved)
    )
    best_own = (
        best_team0 if own_team is Team.TEAM_0 else TRICKS_PER_DEAL - best_team0
    )
    optimal: list[Card] = []
    for item in solved:
        if item.team0_tricks_final == best_team0:
            optimal.extend(item.equivalent_cards)
    return LateGameSolution(
        acting_seat=actor,
        contract=contract,
        declarer=state.declarer,
        tricks_remaining=tricks_remaining,
        team0_tricks_so_far=team0_so_far,
        optimal_team0_tricks_final=best_team0,
        optimal_own_team_tricks_final=best_own,
        own_team_prefers_more_tricks=prefers_more_own,
        optimal_cards=tuple(sorted(set(optimal), key=card_to_index)),
        actions=tuple(sorted(solved, key=lambda item: card_to_index(item.card))),
        nodes_visited=search.nodes,
        transposition_hits=search.hits,
    )


def _signed_own_points(action: SolvedAction) -> int:
    """Own-team deal points, signed positive for a win and negative for a loss."""

    return action.deal_points if action.own_team_wins_deal else -action.deal_points


def _build_action(
    *,
    card: Card,
    equivalent: tuple[Card, ...],
    team0_final: int,
    contract: Contract,
    declarer: int | None,
    starting_score: MatchScore,
    own_team: Team,
) -> SolvedAction:
    score = deal_outcome_for_split(
        contract=contract, declarer=declarer, team0_tricks=team0_final
    )
    after = transition_rising_score(starting_score, score)
    own_tricks = team0_final if own_team is Team.TEAM_0 else (
        TRICKS_PER_DEAL - team0_final
    )
    return SolvedAction(
        card=card,
        team0_tricks_final=team0_final,
        own_team_tricks_final=own_tricks,
        deal_points=score.points,
        deal_winner=score.winner_team,
        own_team_wins_deal=score.winner_team is own_team,
        match_score_after=after.as_tuple(),
        match_terminal=is_match_terminal(after),
        match_utility=match_utility_from_score(after, own_team),
        equivalent_cards=equivalent,
    )


def solve_continuation(
    continuation: HypotheticalContinuation,
    *,
    maximum_tricks_remaining: int = DEFAULT_MAXIMUM_TRICKS_REMAINING,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> LateGameSolution:
    """Solve a hypothetical continuation exactly.

    The result is exact *for that sampled world*, which is the only honest
    reading: it says what optimal play achieves if the opponents' cards really
    lie where the sampler put them, not what the position is worth.
    """

    if not isinstance(continuation, HypotheticalContinuation):
        raise SolverError("solve_continuation requires a HypotheticalContinuation")
    return solve_late_game(
        continuation.state,
        maximum_tricks_remaining=maximum_tricks_remaining,
        node_budget=node_budget,
    )


def is_within_exact_range(
    state: DealState,
    *,
    maximum_tricks_remaining: int = DEFAULT_MAXIMUM_TRICKS_REMAINING,
) -> bool:
    """True when the position is inside the configured exact budget."""

    if not isinstance(state, DealState):
        raise SolverError("is_within_exact_range requires a DealState")
    if state.phase is not EnginePhase.TRICK_PLAY:
        return False
    return TRICKS_PER_DEAL - len(state.completed_tricks) <= maximum_tricks_remaining


def optimal_play_actions(
    state: DealState,
    *,
    maximum_tricks_remaining: int = DEFAULT_MAXIMUM_TRICKS_REMAINING,
) -> tuple[PlayCardAction, ...]:
    """Return every exactly optimal engine play action for the acting seat."""

    solution = solve_late_game(
        state, maximum_tricks_remaining=maximum_tricks_remaining
    )
    return tuple(
        PlayCardAction(seat=solution.acting_seat, card=card)
        for card in solution.optimal_cards
    )


def monotonicity_certificate() -> dict[str, object]:
    """Exhaustively certify the match-utility monotonicity claim.

    Every contract, every legal declarer, both teams, and every reachable
    rising-score state are enumerated. The certificate is data, not prose: if a
    future ruleset broke monotonicity, this would report it.
    """

    scores: list[MatchScore] = [MatchScore()]
    for points in range(4, 60, 4):
        for score in (MatchScore(points, 0), MatchScore(0, points)):
            if not is_match_terminal(score):
                scores.append(score)

    cases = 0
    failures: list[dict[str, object]] = []
    for contract in Contract:
        declarers: tuple[int | None, ...] = (
            (None,) if contract is Contract.NOLO else (0, 1, 2, 3)
        )
        for declarer in declarers:
            for score in scores:
                for team in Team:
                    cases += 1
                    if not match_utility_is_monotone(
                        contract=contract,
                        declarer=declarer,
                        starting_score=score,
                        team=team,
                    ):
                        failures.append(
                            {
                                "contract": contract.value,
                                "declarer": declarer,
                                "starting_score": list(score.as_tuple()),
                                "team": team.value,
                            }
                        )
    return {
        "cases_checked": cases,
        "claim": (
            "For a fixed contract and declarer, each team's match utility is "
            "weakly monotone in the team-0 trick count, in the same direction "
            "as its deal points. Every trick-optimal action is therefore also "
            "match-optimal under perfect information."
        ),
        "failures": failures,
        "holds": not failures,
        "scope": (
            "Perfect information only. Under imperfect information a team whose "
            "utility is step-shaped may rationally prefer maximizing the "
            "probability of a win over maximizing expected points."
        ),
        "schema_version": "tuppi.exact.monotonicity_certificate.v1",
        "score_states_checked": len(scores),
    }


def _suit_of(index: int) -> int:
    return index // _RANK_COUNT


def suit_order_index(card: Card) -> int:
    """Expose the canonical suit index used by the solver's integer encoding."""

    return SUIT_ORDER.index(card.suit)
