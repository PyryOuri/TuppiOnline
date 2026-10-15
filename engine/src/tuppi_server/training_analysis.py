"""Live, in-hand training odds: suit-split and card-location probabilities.

Unlike :mod:`tuppi_server.post_match_diagnostics` and
:mod:`tuppi_server.completed_deal_review`, this module is deliberately
*mid-deal*.  It never touches the exact late-game solver or any hidden engine
state directly: every number here is derived from
:class:`tuppi_exact.HardConstraintModel`, built from nothing but the
requesting seat's own formal :class:`~tuppi_engine.PlayerObservation` (own
hand plus public history) - exactly the information already legally available
to that human player.

Both halves of the response are computed from that one model, so they cannot
contradict each other: the per-card ownership frequencies and the per-suit
split law are two views of the same exact assignment count.  That mattered
enough to build the split law here rather than reuse
``tuppi_valuation.suits.general_split_distribution``, which conditions only on
hand sizes and proven voids and therefore disagrees with the full model
wherever a show exclusion has ruled cards out.

A "uniform over hard-feasible assignments" probability is not a claim about
how the real opponents actually play; see the module docstring of
``tuppi_exact.counting``.  It is the same "assume nothing else is known"
baseline a printed suit-break odds table uses, which is why it is useful
training material rather than a leak of private state: a player could in
principle compute every one of these numbers by hand from what they can
already see.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from tuppi_agents import PublicInference
from tuppi_engine import PlayerObservation
from tuppi_exact import (
    ClassAllocation,
    CountingPlan,
    ELIGIBLE_SHOW_CARDS_BY_COLOR,
    ExactError,
    HardConstraintModel,
    bounded_compositions,
    count_plan,
    derive_show_exclusions,
    exact_uniform_marginals,
    multinomial,
)
from tuppi_rules import Card, Color, Contract, Rank, Suit, card_to_code


TRAINING_ANALYSIS_SCHEMA_VERSION = "tuppi.server.training_analysis.v1"

#: Fixed suit order in the response payload. The client presents suits in the
#: player's own configured order and does not depend on this one.
SUIT_ORDER: tuple[Suit, ...] = (Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS)

#: Top-level keys a training-analysis response may ever contain.  Kept as an
#: explicit allow-list, matching the deny-by-default convention the rest of
#: ``tuppi_server``'s analysis boundary uses, even though nothing here is
#: assembled from an external or forwarded dictionary.
_RESPONSE_KEYS = frozenset(
    {
        "schema_version",
        "match_ref",
        "deal_ref",
        "seat",
        "other_seats",
        "suit_splits",
        "card_locations",
        "assumed",
    }
)




class TrainingAnalysisError(ValueError):
    """An exact training-odds invariant failed, so no answer is returned."""


def generate_training_analysis(
    observation: PlayerObservation, *, with_assumptions: bool = True
) -> dict[str, object]:
    """Return the seat-scoped live training odds for one observation.

    Meaningful any time a deal is in progress, whether or not it is currently
    ``observation.observing_seat``'s turn to act. The caller is expected to
    reject a match that has not yet started or has already finished before
    this is reached (see ``LiveMatchRunner.training_analysis``).

    ``with_assumptions=False`` leaves ``assumed`` null: the behavioural rules
    were measured on the old reference bots and do not hold for TuppiAI's
    (TuppiAI ``tools/odds_calibration.py``: ``show_lowest`` violated in 358 of
    506 firings, the trick-play rules in 18-27%; the assumed view scored worse
    than the exact odds and excluded the true holder of 7.6% of cards).
    """

    model = HardConstraintModel.build(observation)
    other_seats = tuple(seat for seat in range(4) if seat != model.observing_seat)
    plan = CountingPlan.build(model)
    total = count_plan(plan)
    if total <= 0:
        raise TrainingAnalysisError("the observation admits no feasible assignment")

    response: dict[str, object] = {
        "schema_version": TRAINING_ANALYSIS_SCHEMA_VERSION,
        "match_ref": observation.match_ref,
        "deal_ref": observation.deal_ref,
        "seat": observation.observing_seat,
        "other_seats": list(other_seats),
        "suit_splits": _suit_splits(model, other_seats=other_seats),
        "card_locations": _card_locations(model),
        "assumed": _assumed_sections(
            observation, other_seats=other_seats, hard_total=total
        ) if with_assumptions else None,
    }
    if set(response) != _RESPONSE_KEYS:  # pragma: no cover - constructed above
        raise TrainingAnalysisError("training analysis produced unexpected fields")
    return response


def _suit_splits(
    model: HardConstraintModel,
    *,
    other_seats: tuple[int, ...],
) -> dict[str, object]:
    """The split law for all four suits, from one already-built model."""

    plan = CountingPlan.build(model)
    total = count_plan(plan)
    if total <= 0:
        raise TrainingAnalysisError("the model admits no feasible assignment")
    return {
        suit.value: _suit_split(
            model, plan=plan, total=total, suit=suit, other_seats=other_seats
        )
        for suit in SUIT_ORDER
    }


def behavioural_exclusions(
    observation: PlayerObservation,
) -> tuple[frozenset[Card], ...]:
    """Cards a seat would not still hold if it plays the obvious card.

    Every rule here rests on one idea, and which card it points at depends
    entirely on the contract: **shed the card you can least afford to keep.**
    In NOLO that is the highest card you can safely be rid of; in RAMI it is
    the cheapest one that does the job.

    ``show_lowest`` (both contracts)
        A show made without speaking picked the *lowest* eligible card of the
        contract's normal colour, so the seat holds no eligible card of that
        colour beneath it. Unanimous in measurement, 140 of 140 choices. It is
        the only rule here that fires before a card is led, and the widest:
        the shown card's rank and suit are public, and the hierarchy fixes
        which cards were candidates.
    ``duck_high`` (NOLO)
        A follower that went under the trick played the largest card that
        still loses, so it holds nothing of that suit between its card and the
        trick's high card. 0 violations in 158 firings.
    ``win_high_last`` (NOLO)
        A *fourth* seat that took the trick played its highest of the suit.
        0 in 348. The qualifier is load-bearing: an earlier seat can still be
        overtaken, so it plays its *lowest* winner — 76.5% — preferring
        somebody else took the trick.
    ``follow_low`` (RAMI)
        A follower that did not win played its lowest of the suit, so it holds
        nothing of that suit beneath its card. 0 in 249.

    Two candidates were measured and rejected: ``win_high`` applied to every
    NOLO follower (206 violations in 371) and RAMI ``cheapest_winner``
    (5 in 133), the latter despite being the name of the baseline's own rule.

    The observing seat is skipped throughout. Its hand is known outright, so
    an assumption about it is never needed and a wrong one would contradict
    the very hand the engine supplied.
    """

    own = observation.observing_seat
    excluded: list[set[Card]] = [set(), set(), set(), set()]

    for action in observation.show_actions:
        if action.seat == own:
            continue
        firing = show_rule_firing(
            seat=action.seat,
            shown_card=action.shown_card,
            declared_contract=action.declared_contract,
            verbal_required=action.verbal_required,
        )
        if firing is not None:
            excluded[firing.seat] |= firing.excluded

    contract = observation.contract
    if contract is None:
        return tuple(frozenset(item) for item in excluded)

    for plays, winner in _tricks_with_winner(observation):
        led = plays[0].card.suit
        highest = plays[0].card.rank.value
        for index, play in enumerate(plays[1:], start=1):
            firing = play_rule_firing(
                contract=contract,
                led=led,
                highest=highest,
                play=play,
                is_final=index == len(plays) - 1 and winner is not None,
                wins_trick=winner == play.seat,
            )
            if firing is not None and play.seat != own:
                excluded[firing.seat] |= firing.excluded
            if play.card.suit is led:
                highest = max(highest, play.card.rank.value)
    return tuple(frozenset(item) for item in excluded)


def _tricks_with_winner(observation: PlayerObservation):
    """Every trick so far, with its winner where the trick is finished."""

    for trick in observation.completed_tricks:
        yield tuple(trick.plays), trick.winner
    if observation.current_trick:
        yield tuple(observation.current_trick), None


@dataclass(frozen=True, slots=True)
class RuleFiring:
    """One behavioural assumption applied to one public action.

    Shared by the live inference and by ``tools/measure_rule_validity.py``, so
    a rule can never be measured in a form other than the one that ships.
    """

    rule: str
    seat: int
    excluded: frozenset[Card]


def show_rule_firing(
    *,
    seat: int,
    shown_card: Card,
    declared_contract: Contract,
    verbal_required: bool,
) -> "RuleFiring | None":
    """``show_lowest``: a silent show picked the lowest eligible card.

    Takes the pieces rather than an action object because the two callers hold
    different types — the live path has the rules ``ShowAction`` with its
    derived flag, while a replay of accepted actions has the engine one and
    must derive the flag from the hand.
    """

    if verbal_required:
        return None  # a spoken show is already a hard fact, and a stronger one
    colour = Color.RED if declared_contract is Contract.RAMI else Color.BLACK
    limit = shown_card.rank.value
    excluded = frozenset(
        card
        for card in ELIGIBLE_SHOW_CARDS_BY_COLOR[colour]
        if card.rank.value < limit
    )
    return RuleFiring("show_lowest", seat, excluded) if excluded else None


def play_rule_firing(
    *,
    contract: Contract,
    led: Suit,
    highest: int,
    play,
    is_final: bool,
    wins_trick: bool,
) -> "RuleFiring | None":
    """Whichever assumption bears on one played card, with what it asserts.

    ``highest`` is the best card of the led suit played *before* this one.
    """

    if play.card.suit is not led:
        return None  # a discard; the void it proves is already a hard fact
    rank = play.card.rank.value
    if contract is Contract.NOLO:
        if rank < highest:
            return _firing("duck_high", play.seat, led, range(rank + 1, highest))
        if is_final and wins_trick:
            return _firing(
                "win_high_last", play.seat, led, range(rank + 1, Rank.ACE.value + 1)
            )
        return None
    if rank < highest:
        return _firing("follow_low", play.seat, led, range(Rank.TWO.value, rank))
    return None


def _firing(rule: str, seat: int, suit: Suit, span) -> "RuleFiring | None":
    excluded = frozenset(Card(suit=suit, rank=Rank(value)) for value in span)
    return RuleFiring(rule, seat, excluded) if excluded else None


def applied_rule_ids(observation: PlayerObservation) -> tuple[str, ...]:
    """Which assumptions actually bear on this position, for the client."""

    rules = ["show_lowest"]
    if observation.contract is Contract.NOLO:
        rules += ["duck_high", "win_high_last"]
    elif observation.contract is Contract.RAMI:
        rules.append("follow_low")
    return tuple(rules)


def _assumed_sections(
    observation: PlayerObservation,
    *,
    other_seats: tuple[int, ...],
    hard_total: int,
) -> dict[str, object] | None:
    """The same two sections again, under the behavioural assumptions.

    ``None`` when the assumptions cannot hold: either they contradict each
    other, or they exclude every possible holder of some card. That is not a
    failure to hide — it is a proof that somebody did not play the obvious
    card, which is worth telling the player.

    ``prior_probability`` is how much of a leap the assumptions are: the share
    of hard-feasible assignments that also satisfy them. It is exact, being
    one count divided by another. A low number does not mean the read is
    wrong — it means the read is doing a lot of work, and that the cost of it
    being wrong is correspondingly high. Ducking two ranks below the trick's
    high card, for instance, asserts something that was under even money
    beforehand.
    """

    exclusions = behavioural_exclusions(observation)
    if not any(exclusions):
        return None
    cover = HardConstraintModel.build(observation).unknown_cards
    show = derive_show_exclusions(observation)
    combined = tuple(show[seat] | exclusions[seat] for seat in range(4))
    try:
        model = HardConstraintModel.from_inference(
            PublicInference.build(observation), combined
        )
        assumed_total = count_plan(CountingPlan.build(model))
        if assumed_total <= 0:
            return None
        splits = _suit_splits(model, other_seats=other_seats)
        locations = _card_locations(model, cover=cover)
    except (ExactError, TrainingAnalysisError):
        return None
    return {
        "rules": list(applied_rule_ids(observation)),
        "prior_probability": float(Fraction(assumed_total, hard_total)),
        "suit_splits": splits,
        "card_locations": locations,
    }


def _suit_split(
    model: HardConstraintModel,
    *,
    plan: CountingPlan,
    total: int,
    suit: Suit,
    other_seats: tuple[int, ...],
) -> dict[str, object]:
    """Exact split law for one suit's still-unknown cards.

    ``known_counts`` reports the cards of the suit whose owner is already
    public (a shown card), which the split law deliberately excludes: those
    seats hold them with certainty, so mixing them into a probability
    distribution would understate what the player already knows.
    """

    counts = _suit_split_counts(
        plan=plan,
        total=total,
        suit=suit,
        other_seats=other_seats,
    )
    distribution = sorted(
        (
            {
                "counts": list(placement),
                "probability": float(Fraction(ways, total)),
            }
            for placement, ways in counts.items()
        ),
        key=lambda entry: (-entry["probability"], entry["counts"]),
    )
    return {
        "outstanding": sum(1 for card in model.unknown_cards if card.suit is suit),
        "hand_sizes": [model.capacity[seat] for seat in other_seats],
        "known_counts": [
            sum(1 for card in model.known_held[seat] if card.suit is suit)
            for seat in other_seats
        ],
        "distribution": distribution,
    }


def _suit_split_counts(
    *,
    plan: CountingPlan,
    total: int,
    suit: Suit,
    other_seats: tuple[int, ...],
) -> dict[tuple[int, ...], int]:
    """Count feasible assignments by how ``suit`` splits across ``other_seats``.

    The counting plan already collapses interchangeable cards into equivalence
    classes. Splitting each class into its cards *of this suit* and the rest
    leaves the total count unchanged - two classes with the same allowed-seat
    set are the same transportation problem - so the suit's placement can be
    enumerated over class-level counts rather than over individual cards, and
    the remainder handed back to the ordinary exact counter.

    The returned counts sum to ``total`` by construction; that identity is
    checked, because an off-by-one here would quietly produce a plausible but
    wrong probability rather than an error.
    """

    suit_groups: list[tuple[tuple[int, ...], int]] = []
    other_classes: list[ClassAllocation] = []
    for item in plan.classes:
        in_suit = sum(1 for card in item.cards if card.suit is suit)
        rest = tuple(card for card in item.cards if card.suit is not suit)
        if in_suit:
            suit_groups.append((item.allowed_seats, in_suit))
        if rest:
            other_classes.append(
                ClassAllocation(allowed_seats=item.allowed_seats, cards=rest)
            )

    # A seat with no residual capacity never appears in the plan's seat order,
    # and holds none of the unknown cards.
    seat_index = {seat: index for index, seat in enumerate(other_seats)}
    totals: dict[tuple[int, ...], int] = {}

    def walk(
        index: int,
        capacities: tuple[int, ...],
        placed: tuple[int, ...],
        ways: int,
    ) -> None:
        if index == len(suit_groups):
            remainder = _count_remaining(
                seat_order=plan.seat_order,
                capacities=capacities,
                classes=tuple(other_classes),
            )
            if remainder:
                totals[placed] = totals.get(placed, 0) + ways * remainder
            return
        allowed_seats, size = suit_groups[index]
        positions = tuple(plan.seat_order.index(seat) for seat in allowed_seats)
        bounds = tuple(capacities[position] for position in positions)
        for split in bounded_compositions(size, bounds):
            following = list(capacities)
            placement = list(placed)
            for position, value in zip(positions, split):
                following[position] -= value
                placement[seat_index[plan.seat_order[position]]] += value
            walk(
                index + 1,
                tuple(following),
                tuple(placement),
                ways * multinomial(size, split),
            )

    walk(0, plan.capacities, (0,) * len(other_seats), 1)
    if sum(totals.values()) != total:
        raise TrainingAnalysisError("suit split counts disagree with the exact total")
    return totals


def _count_remaining(
    *,
    seat_order: tuple[int, ...],
    capacities: tuple[int, ...],
    classes: tuple[ClassAllocation, ...],
) -> int:
    """Exactly count the assignments of the non-suit cards that remain.

    Mirrors the trimming :meth:`CountingPlan.without` performs after pinning:
    a seat whose capacity is now spent leaves the problem, and a class that
    loses every allowed seat makes the remainder infeasible.
    """

    surviving = tuple(
        seat for seat, value in zip(seat_order, capacities) if value > 0
    )
    remaining = tuple(value for value in capacities if value > 0)
    if not classes:
        return 1 if not any(remaining) else 0
    trimmed: list[ClassAllocation] = []
    for item in classes:
        allowed = tuple(seat for seat in item.allowed_seats if seat in surviving)
        if not allowed:
            return 0
        trimmed.append(ClassAllocation(allowed_seats=allowed, cards=item.cards))
    return count_plan(
        CountingPlan(
            seat_order=surviving,
            capacities=remaining,
            classes=tuple(trimmed),
        )
    )


def _card_locations(
    model: HardConstraintModel,
    *,
    cover: tuple[Card, ...] | None = None,
) -> list[dict[str, object]]:
    """Exact per-seat ownership probability for every still-unknown card.

    Every entry's four probabilities sum to 1.0; the requesting seat's own
    entry is always 0.0 since an unknown card cannot sit in a hand with no
    residual capacity (``HardConstraintModel`` enforces this invariant).

    ``cover`` names cards the caller needs an entry for even if this model has
    already settled them. An assumption strong enough to prove an owner drops
    that card from ``unknown_cards`` entirely, and a client blending this list
    against the hard-fact one needs the two to line up; a proven card is
    reported as a certainty at its owner rather than silently disappearing.
    """

    marginals = exact_uniform_marginals(model)
    entries = [
        {
            "card": card_to_code(card),
            "seat_probabilities": [float(value) for value in marginals[card]],
        }
        for card in model.unknown_cards
    ]
    if cover is not None:
        settled = set(model.unknown_cards)
        for card in cover:
            if card in settled:
                continue
            owner = model.proven_owner(card)
            if owner is None:
                continue
            certain = [0.0, 0.0, 0.0, 0.0]
            certain[owner] = 1.0
            entries.append(
                {"card": card_to_code(card), "seat_probabilities": certain}
            )
    return sorted(entries, key=lambda entry: entry["card"])
