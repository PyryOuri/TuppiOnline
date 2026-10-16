"""Live training odds during a sooli deal, from a pluggable layout sampler.

The exact odds model (:mod:`tuppi_server.training_analysis`) covers four hands
in play. In a sooli deal the sooli partner's hand is dead and the card
exchange is private: a card shown during showing may have changed hands, and
only the two exchanging players know which. The tool therefore asks a
*sampler* (``RoomManager.sooli_odds``; TuppiAI's is
``tuppi_ai.sooli_odds.SooliOdds``) for layouts of the hidden cards consistent
with the seat's own observation, and reports sampled odds in the training
envelope's shape:

* ``suit_splits`` and ``card_locations``: layouts uniform over what the seat
  has seen (facts only);
* ``assumed``: the bot's sooli inference, rule ``sooli_low_hand`` (the
  soolaaja accepted sooli, so its hand is a sooli hand: it passes the bot's
  offer prefilter and low hands are more likely), where the bot uses it: the
  sooli partner choosing the return, and the RAMI pair during sooli play.
  ``prior_probability`` is the share of facts-only layouts that pass the
  prefilter.

The server checks every layout against the observation (the seat's own hand,
no played card, the hand sizes), so a sampler cannot put a card anywhere the
seat could not see it being. A card whose seat is the same in every layout is
reported as known, as the exact tool reports a public card.
"""

from __future__ import annotations

from collections import Counter
from typing import Protocol, Sequence

from tuppi_engine import PlayerObservation
from tuppi_rules import Card, Suit, card_to_code

from .training_analysis import SUIT_ORDER

SOOLI_TRAINING_ANALYSIS_SCHEMA_VERSION = "tuppi.server.training_analysis.sooli.v1"
SOOLI_RULE = "sooli_low_hand"


class SooliOddsSampler(Protocol):
    estimator_id: str

    def informed_applies(self, observation: PlayerObservation) -> bool: ...

    def sample_layouts(
        self, observation: PlayerObservation, *, informed: bool
    ) -> Sequence[Sequence[Sequence[Card]]]: ...

    def prior_probability(self, observation: PlayerObservation) -> float: ...


class SooliTrainingAnalysisError(ValueError):
    """A sampler's layouts disagree with the seat's observation."""


def generate_sooli_training_analysis(
    observation: PlayerObservation, sampler: SooliOddsSampler
) -> dict[str, object]:
    seat = observation.observing_seat
    other_seats = tuple(s for s in range(4) if s != seat)
    played = _played_cards(observation)
    own = frozenset(observation.own_hand)
    cover = sorted(
        (card for card in _deck() if card not in own and card not in played),
        key=card_to_code,
    )
    facts = _checked(sampler.sample_layouts(observation, informed=False), observation, own, played)
    response: dict[str, object] = {
        "schema_version": SOOLI_TRAINING_ANALYSIS_SCHEMA_VERSION,
        "match_ref": observation.match_ref,
        "deal_ref": observation.deal_ref,
        "seat": seat,
        "other_seats": list(other_seats),
        **_sections(facts, other_seats=other_seats, cover=cover),
        "assumed": None,
        "source": {"estimator_id": sampler.estimator_id, "layouts": len(facts)},
        # Null while the defenders are still being asked (no soolaaja yet).
        "sooli": None if observation.soolaaja is None else {
            "soolaaja": observation.soolaaja,
            "dead_seat": (observation.soolaaja + 2) % 4,
        },
    }
    if sampler.informed_applies(observation):
        informed = _checked(
            sampler.sample_layouts(observation, informed=True), observation, own, played
        )
        prior = float(sampler.prior_probability(observation))
        if not 0.0 < prior <= 1.0:
            raise SooliTrainingAnalysisError("prior_probability must be in (0, 1]")
        response["assumed"] = {
            "rules": [SOOLI_RULE],
            "prior_probability": prior,
            **_sections(informed, other_seats=other_seats, cover=cover),
        }
    return response


def _deck() -> tuple[Card, ...]:
    from tuppi_rules.cards import card_from_index

    return tuple(card_from_index(index) for index in range(52))


def _played_cards(observation: PlayerObservation) -> frozenset[Card]:
    cards = {play.card for trick in observation.sooli_tricks for play in trick.plays}
    cards |= {play.card for play in observation.sooli_current_trick}
    return frozenset(cards)


def _checked(layouts, observation, own, played) -> list[tuple[frozenset[Card], ...]]:
    seat = observation.observing_seat
    checked = []
    sizes = None
    for layout in layouts:
        hands = tuple(frozenset(hand) for hand in layout)
        if len(hands) != 4 or hands[seat] != own:
            raise SooliTrainingAnalysisError("a layout changes the seat's own hand")
        held = [card for hand in hands for card in hand]
        if len(held) != len(set(held)) or len(held) + len(played) != 52 or set(held) & played:
            raise SooliTrainingAnalysisError("a layout is not a partition of the unplayed cards")
        layout_sizes = tuple(len(hand) for hand in hands)
        if sizes is None:
            sizes = layout_sizes
        elif layout_sizes != sizes:
            raise SooliTrainingAnalysisError("layouts disagree on hand sizes")
        checked.append(hands)
    if not checked:
        raise SooliTrainingAnalysisError("the sampler returned no layouts")
    return checked


def _sections(layouts, *, other_seats, cover) -> dict[str, object]:
    total = len(layouts)
    counts = {card: Counter() for card in cover}
    for hands in layouts:
        for held_by, hand in enumerate(hands):
            for card in hand:
                if card in counts:  # the seat's own cards are not unknown
                    counts[card][held_by] += 1
    certain = {card: next(iter(c)) for card, c in counts.items() if len(c) == 1}
    locations = [
        {
            "card": card_to_code(card),
            "seat_probabilities": [counts[card][s] / total for s in range(4)],
        }
        for card in cover
    ]
    splits = {}
    for suit in SUIT_ORDER:
        uncertain = [card for card in cover if card.suit is suit and card not in certain]
        known = [
            sum(1 for card, owner in certain.items() if owner == s and card.suit is suit)
            for s in other_seats
        ]
        placement = Counter(
            tuple(sum(1 for card in uncertain if card in hands[s]) for s in other_seats)
            for hands in layouts
        )
        splits[suit.value] = {
            "outstanding": len(uncertain),
            "hand_sizes": [
                len(layouts[0][s]) - sum(1 for owner in certain.values() if owner == s)
                for s in other_seats
            ],
            "known_counts": known,
            "distribution": sorted(
                (
                    {"counts": list(key), "probability": ways / total}
                    for key, ways in placement.items()
                ),
                key=lambda entry: (-entry["probability"], entry["counts"]),
            ),
        }
    return {"suit_splits": splits, "card_locations": locations}
