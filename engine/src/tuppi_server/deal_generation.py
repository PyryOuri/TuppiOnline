"""Unpredictable live-deal generation.

Research examples use explicit deterministic deals. Live matches deliberately
use ``SystemRandom`` and retain the resulting ``ExplicitDeal`` only inside the
authoritative server runner.
"""

from __future__ import annotations

from random import SystemRandom

from tuppi_engine import ExplicitDeal
from tuppi_rules import FULL_DECK


def generate_live_deal(*, dealer: int, rng: SystemRandom | None = None) -> ExplicitDeal:
    """Create one complete unpredictable four-hand live deal.

    ``rng`` is injectable only for structural tests. Production callers leave
    it unset, which uses the operating system-backed ``SystemRandom`` source.
    The deal id and explicit hands never cross the projection boundary.
    """

    source = rng or SystemRandom()
    deck = list(FULL_DECK)
    source.shuffle(deck)
    hands = tuple(
        tuple(deck[position : position + 13])
        for position in range(0, len(deck), 13)
    )
    return ExplicitDeal(dealer=dealer, hands=hands)
