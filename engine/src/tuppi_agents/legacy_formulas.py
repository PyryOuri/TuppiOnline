"""Pure re-implementation of the frozen legacy hand-strength arithmetic.

This module is a *port*, not a wrapper: it imports nothing from
``tuppi_legacy`` and touches no legacy object. Expression order, constants, and
loop order are preserved so that the ported values are bit-identical to the
frozen emulator's on the same platform, which the characterization tests check
directly against the Archive.

Only the deterministic public-information arithmetic is ported. The frozen
Monte Carlo estimator, its determinization sampling, and its shared global RNG
are deliberately absent.
"""

from __future__ import annotations

import math
from typing import Sequence

from tuppi_rules import Card, Rank

from .errors import AgentsValidationError
from .ordering import legacy_suit_precedence


LEGACY_FORMULA_ID = "legacy_v9_rs_nhi_binomial_ev_v1"

_TRICKS = 13
_BINOM_COEF_13: tuple[int, ...] = tuple(math.comb(_TRICKS, k) for k in range(_TRICKS + 1))


def legacy_suit_lengths(hand: Sequence[Card]) -> tuple[int, int, int, int]:
    """Return suit lengths in the frozen legacy suit order (S, H, D, C).

    The order is preserved because the legacy sum over suit lengths is a
    floating-point sum whose result depends on its term order.
    """

    lengths = [0, 0, 0, 0]
    for card in hand:
        if not isinstance(card, Card):
            raise AgentsValidationError("legacy suit lengths require Card values")
        lengths[legacy_suit_precedence(card.suit)] += 1
    return (lengths[0], lengths[1], lengths[2], lengths[3])


def legacy_high_card_points(hand: Sequence[Card]) -> int:
    points = 0
    for card in hand:
        rank = card.rank.value
        if rank == 14:
            points += 4
        elif rank == 13:
            points += 3
        elif rank == 12:
            points += 2
        elif rank == 11:
            points += 1
    return points


def rami_strength(hand: Sequence[Card]) -> float:
    """Port of ``rami_strength_RS``."""

    high = legacy_high_card_points(hand)
    lengths = legacy_suit_lengths(hand)
    ds_long = 0.5 * sum(max(0, length - 4) for length in lengths)
    sci = sum((length - 3.25) ** 2 for length in lengths)
    aces = sum(1 for card in hand if card.rank.value == 14)
    return high + ds_long + 0.2 * sci + 0.5 * aces


def nolo_hand_index(hand: Sequence[Card]) -> float:
    """Port of ``nolo_hand_index_NHI``; lower is a better NOLO hand."""

    lengths = legacy_suit_lengths(hand)
    voids = sum(1 for length in lengths if length == 0)
    singletons = sum(1 for length in lengths if length == 1)
    doubletons = sum(1 for length in lengths if length == 2)
    longest = max(lengths)
    top_five = sum(1 for card in hand if card.rank.value >= 10)
    honours = sum(1 for card in hand if card.rank.value >= 11)
    exits = sum(1 for card in hand if card.rank.value in (2, 3, 4))
    return (
        2 * top_five
        + 1 * honours
        - 1.5 * exits
        - 3 * voids
        - 2 * singletons
        - 1 * doubletons
        + 0.5 * max(0, longest - 5)
    )


def sigmoid(value: float) -> float:
    """Port of the frozen numerically stable logistic."""

    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def probability_rami_make(strength: float) -> float:
    return sigmoid((strength - 15.34) / 3.48)


def probability_nolo_win(index: float) -> float:
    return sigmoid((9.8 - index) / 2.8)


def binomial_pmf_13(successes: int, probability: float) -> float:
    return (
        _BINOM_COEF_13[successes]
        * (probability**successes)
        * ((1 - probability) ** (_TRICKS - successes))
    )


def binomial_cdf_13(successes: int, probability: float) -> float:
    return sum(binomial_pmf_13(index, probability) for index in range(successes + 1))


def solve_probability_for_cdf6(target: float) -> float:
    """Port of ``_solve_p_for_cdf6``: 40-step bisection, no early exit."""

    clamped = min(max(target, 1e-6), 1 - 1e-6)
    low, high = 1e-4, 1 - 1e-4
    for _ in range(40):
        middle = (low + high) / 2
        if binomial_cdf_13(6, middle) < clamped:
            high = middle
        else:
            low = middle
    return (low + high) / 2


def solve_probability_for_tail(target: float) -> float:
    """Port of ``_solve_p_for_tail_ge7``."""

    clamped = min(max(target, 1e-6), 1 - 1e-6)
    goal = 1 - clamped
    low, high = 1e-4, 1 - 1e-4
    for _ in range(40):
        middle = (low + high) / 2
        if binomial_cdf_13(6, middle) > goal:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def expected_value_rami(strength: float) -> float:
    """Port of ``approx_EV_rami_from_RS``.

    The score table used here is the ``project_target_v1`` RAMI table as well:
    ``4*(t-6)`` to a declaring team taking ``t >= 7`` tricks, and ``-8*(7-t)``
    to it otherwise, because the defenders collect ``8*(13-t-6)``.
    """

    probability = solve_probability_for_tail(probability_rami_make(strength))
    value = 0.0
    for tricks in range(0, 14):
        mass = binomial_pmf_13(tricks, probability)
        points = 4 * (tricks - 6) if tricks >= 7 else -8 * (7 - tricks)
        value += mass * points
    return value


def expected_value_nolo(index: float) -> float:
    """Port of ``approx_EV_nolo_from_NHI``.

    The table matches ``project_target_v1`` exactly: the side with fewer tricks
    scores ``4*(7 - fewer tricks)``.
    """

    probability = solve_probability_for_cdf6(probability_nolo_win(index))
    value = 0.0
    for tricks in range(0, 14):
        mass = binomial_pmf_13(tricks, probability)
        points = 4 * (7 - tricks) if tricks <= 6 else -4 * (tricks - 6)
        value += mass * points
    return value


def nolo_discard_liability(card: Card) -> float:
    """Port of the frozen ``_nolo_discard_any`` liability table."""

    rank = card.rank.value
    if rank == Rank.ACE.value:
        return 4.0
    if rank == Rank.KING.value:
        return 3.0
    if rank == Rank.QUEEN.value:
        return 2.0
    if rank == Rank.JACK.value:
        return 1.0
    if rank == Rank.TEN.value:
        return 0.5
    if rank == Rank.NINE.value:
        return 0.25
    return 0.0


def legacy_suit_strength(hand: Sequence[Card], suit_index: int) -> float:
    """Port of the frozen RAMI lead suit score, including its 0.01 length term."""

    lengths = legacy_suit_lengths(hand)
    weight = 0.0
    for card in hand:
        if legacy_suit_precedence(card.suit) != suit_index:
            continue
        rank = card.rank.value
        if rank == 14:
            weight += 4
        elif rank == 13:
            weight += 3
        elif rank == 12:
            weight += 2
        elif rank == 11:
            weight += 1
    weight += 0.5 * max(0, lengths[suit_index] - 3)
    weight += 0.01 * lengths[suit_index]
    return weight
