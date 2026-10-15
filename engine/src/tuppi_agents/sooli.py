"""A simple, deterministic sooli behaviour for agents written for ``project_target_v1``.

Under the sooli rulesets (``project_target_v2`` and ``v3``) an agent must also
answer sooli offers, exchange a card and play three-player ace-low tricks.
:class:`SooliFallbackAgent` wraps any engine agent: every non-sooli decision
goes to the wrapped agent unchanged, every sooli decision is taken here from
the observation alone:

* offer: never play sooli (declining is always legal);
* give: the card whose removal leaves the least exposed hand;
* return: the lowest card, preferring other suits than the received card's and
  suits the partner is short in, where the soolaaja is likely to hold cards;
* soolaaja: follow with the highest card that still loses, discard the card
  whose removal leaves the least exposed hand;
* RAMI players: lead the card with the fewest unseen cards below it in a suit
  the soolaaja may still hold; the second RAMI player plays under the leader's
  card (keeping the lowest cards for later leads) and discards high.

Exposure of a soolaaja hand: in each suit, with own cards in ace-low order
m_1 < ... < m_k, the sum over i of how many other live cards lie below m_i
beyond the i - 1 rounds already survived. This is a heuristic, not a solver.
"""

from __future__ import annotations

from tuppi_engine import (
    EnginePhase,
    PlayCardAction,
    PlayerObservation,
    SooliDecisionAction,
    SooliExchangeAction,
)
from tuppi_rules import Card
from tuppi_rules.cards import FULL_DECK
from tuppi_rules.sooli import sooli_rank_value

SOOLI_PHASES = frozenset({EnginePhase.SOOLI_OFFER, EnginePhase.SOOLI_GIVE,
                          EnginePhase.SOOLI_RETURN, EnginePhase.SOOLI_PLAY})


def _exposure(mine, others) -> int:
    total = 0
    for suit in {card.suit for card in mine}:
        own = sorted(sooli_rank_value(c) for c in mine if c.suit is suit)
        rest = [sooli_rank_value(c) for c in others if c.suit is suit]
        for i, rank in enumerate(own):
            below = sum(1 for r in rest if r < rank)
            total += max(0, below - i)
    return total


def _least_exposed_without(hand, others) -> Card:
    return min(hand, key=lambda c: (_exposure([x for x in hand if x != c], others), -sooli_rank_value(c),
                                    c.suit.value))


def _played(observation: PlayerObservation) -> list[Card]:
    cards = [play.card for trick in observation.sooli_tricks for play in trick.plays]
    return cards + [play.card for play in observation.sooli_current_trick]


def sooli_heuristic_action(observation: PlayerObservation):
    """The heuristic's action for a sooli decision (the observation's own legal action)."""

    legal = observation.legal_actions
    if not legal:
        raise ValueError("no decision to take")
    phase = observation.phase
    seat = observation.observing_seat
    hand = list(observation.own_hand)
    if phase is EnginePhase.SOOLI_OFFER:
        return next(a for a in legal if isinstance(a, SooliDecisionAction) and not a.play_sooli)
    if phase is EnginePhase.SOOLI_GIVE:
        others = [c for c in FULL_DECK if c not in hand]
        return SooliExchangeAction(seat=seat, card=_least_exposed_without(hand, others))
    if phase is EnginePhase.SOOLI_RETURN:
        given = observation.sooli_given_card

        def key(card):
            held = sum(1 for c in hand if c.suit is card.suit)
            return (sooli_rank_value(card), given is not None and card.suit is given.suit, held, card.suit.value)
        return SooliExchangeAction(seat=seat, card=min((c for c in hand if c != given), key=key))
    if phase is not EnginePhase.SOOLI_PLAY:
        raise ValueError("not a sooli decision")
    playable = [a.card for a in legal if isinstance(a, PlayCardAction)]
    played = _played(observation)
    current = observation.sooli_current_trick
    unseen = [c for c in FULL_DECK if c not in hand and c not in played]
    if seat == observation.soolaaja:
        led = current[0].card.suit
        high = max(sooli_rank_value(p.card) for p in current if p.card.suit is led)
        follow = [c for c in playable if c.suit is led]
        if follow:
            safe = [c for c in follow if sooli_rank_value(c) < high]
            return PlayCardAction(seat=seat, card=max(safe or follow, key=sooli_rank_value))
        return PlayCardAction(seat=seat, card=_least_exposed_without(playable, unseen))
    if current:  # the other RAMI player, second in the trick
        lead = current[0].card
        follow = [c for c in playable if c.suit is lead.suit]
        if follow:
            under = [c for c in follow if sooli_rank_value(c) < sooli_rank_value(lead)]
            if under:
                return PlayCardAction(seat=seat, card=max(under, key=sooli_rank_value))
            return PlayCardAction(seat=seat, card=min(follow, key=sooli_rank_value))
        return PlayCardAction(seat=seat, card=max(playable, key=lambda c: (sooli_rank_value(c), c.suit.value)))
    void = set()
    for trick in observation.sooli_tricks:
        led = trick.plays[0].card.suit
        for play in trick.plays:
            if play.seat == observation.soolaaja and play.card.suit is not led:
                void.add(led)

    def lead_key(card):
        same = [c for c in unseen if c.suit is card.suit]
        below = sum(1 for c in same if sooli_rank_value(c) < sooli_rank_value(card))
        return (card.suit in void or not same, below, -len(same), sooli_rank_value(card), card.suit.value)
    return PlayCardAction(seat=seat, card=min(playable, key=lead_key))


class SooliFallbackAgent:
    """Delegates everything but sooli decisions to ``base``."""

    def __init__(self, base) -> None:
        self.base = base

    def choose_action(self, observation: PlayerObservation):
        if observation.phase in SOOLI_PHASES:
            return sooli_heuristic_action(observation)
        return self.base.choose_action(observation)

    def __getattr__(self, name):
        return getattr(self.base, name)
