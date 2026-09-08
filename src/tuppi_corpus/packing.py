"""Fixed-width binary encodings for the parts of a deal that must be stored.

The corpus stores only what replay cannot recompute.  An observation is a pure
function of ``(explicit deal, action prefix, seat)``, and
``tests/agents/test_conformance.py`` already proves a selected action does not
depend on ``match_ref``, output paths, or observation construction count - so a
deal's four hands and its ordered actions are a complete record of it, and every
feature vector, legal action set and inferred void is derived rather than kept.
``docs/database/phase7_charter.md`` §3.1 puts the size difference at three orders
of magnitude against storing serialised observations.

Two encodings carry that:

* **hands** - two bits of owning seat per card, indexed by
  ``tuppi_rules.cards.card_to_index``: 13 bytes, and canonical, because it has
  no ordering freedom to disagree about.
* **actions** - one byte per played card in play order, plus one byte per show
  action.  Seats are omitted because they are derivable: showing passes
  clockwise from the forehand, and within a trick play passes clockwise from the
  leader, whose identity follows from the previous trick's winner.

``CARD_ENCODING_ID`` is pinned in the run manifest.  If the deck's index order
ever changed, every stored hand would silently mean something else, so the
manifest records the encoding rather than assuming it.
"""

from __future__ import annotations

from tuppi_rules import Card, Contract
from tuppi_rules.cards import CARD_ENCODING_ID, card_from_index, card_to_index

from .errors import CorpusFormatError


PACKING_SCHEMA_VERSION = "tuppi.corpus.packing.v1"

CARD_ENCODING = CARD_ENCODING_ID

#: Packed hands are *sets* per seat, so the order a hand was dealt in is not
#: recoverable from them.  That order is behaviourally material - it changed the
#: selected action in 3 of 12 measured deals, because a hand's order reaches
#: ``legal_actions`` and some tie-breaks resolve on the lowest legal index, the
#: effect ``docs/agents/baseline_profiles.md`` calls out as the legacy
#: min-information convention.  Generation therefore canonicalises the explicit
#: deal *before playing it*, so that what is stored fully determines what was
#: played.  Without this the corpus would be silently unreplayable.
HAND_ORDER_ID = "canonical_deck_order_v1"


def canonical_hands(hands):
    """Each hand in deck-index order.  Play this, then store it."""

    return tuple(tuple(sorted(hand, key=card_to_index)) for hand in hands)

HANDS_BYTES = 13
PLAYS_BYTES = 52
SHOWS_BYTES = 4
TRICK_WINNERS_BYTES = 4

#: Sentinel for an unused action slot.  52 card indices occupy 0..51, so 255 can
#: never be a card.
EMPTY = 0xFF

_CONTRACT_TO_BIT = {Contract.NOLO: 0, Contract.RAMI: 1}
_BIT_TO_CONTRACT = {0: Contract.NOLO, 1: Contract.RAMI}


# ---------------------------------------------------------------------- hands


def pack_hands(hands: tuple[tuple[Card, ...], ...]) -> bytes:
    """Two bits of owning seat per card index, over the whole deck."""

    if type(hands) is not tuple or len(hands) != 4:
        raise CorpusFormatError("a deal has exactly four hands")
    owners = bytearray(HANDS_BYTES)
    seen = 0
    for seat, hand in enumerate(hands):
        if len(hand) != 13:
            raise CorpusFormatError("every hand holds exactly thirteen cards")
        for card in hand:
            index = card_to_index(card)
            if seen >> index & 1:
                raise CorpusFormatError("a card was dealt to two seats")
            seen |= 1 << index
            slot, shift = divmod(index, 4)
            owners[slot] |= seat << (shift * 2)
    if seen != (1 << 52) - 1:
        raise CorpusFormatError("the four hands do not partition the deck")
    return bytes(owners)


def unpack_hands(payload: bytes) -> tuple[tuple[Card, ...], ...]:
    """The four hands, each in canonical deck order."""

    if len(payload) != HANDS_BYTES:
        raise CorpusFormatError(f"packed hands must be {HANDS_BYTES} bytes")
    hands: tuple[list[Card], ...] = ([], [], [], [])
    for index in range(52):
        slot, shift = divmod(index, 4)
        hands[payload[slot] >> (shift * 2) & 0b11].append(card_from_index(index))
    if any(len(hand) != 13 for hand in hands):
        raise CorpusFormatError("packed hands do not partition the deck evenly")
    return tuple(tuple(hand) for hand in hands)


# --------------------------------------------------------------------- actions


def pack_plays(cards: tuple[Card, ...]) -> bytes:
    """One byte of card index per played card, in play order."""

    if len(cards) > PLAYS_BYTES:
        raise CorpusFormatError("a deal cannot contain more than 52 plays")
    payload = bytearray([EMPTY]) * PLAYS_BYTES
    for position, card in enumerate(cards):
        payload[position] = card_to_index(card)
    return bytes(payload)


def unpack_plays(payload: bytes) -> tuple[Card, ...]:
    if len(payload) != PLAYS_BYTES:
        raise CorpusFormatError(f"packed plays must be {PLAYS_BYTES} bytes")
    cards: list[Card] = []
    for value in payload:
        if value == EMPTY:
            break
        cards.append(card_from_index(value))
    return tuple(cards)


def pack_shows(shows: tuple[tuple[Card, Contract], ...]) -> bytes:
    """Card index in the low six bits, declared contract in bit six."""

    if len(shows) > SHOWS_BYTES:
        raise CorpusFormatError("at most four seats may show")
    payload = bytearray([EMPTY]) * SHOWS_BYTES
    for position, (card, contract) in enumerate(shows):
        if contract not in _CONTRACT_TO_BIT:
            raise CorpusFormatError("a show declares NOLO or RAMI")
        payload[position] = card_to_index(card) | (_CONTRACT_TO_BIT[contract] << 6)
    return bytes(payload)


def unpack_shows(payload: bytes) -> tuple[tuple[Card, Contract], ...]:
    if len(payload) != SHOWS_BYTES:
        raise CorpusFormatError(f"packed shows must be {SHOWS_BYTES} bytes")
    shows: list[tuple[Card, Contract]] = []
    for value in payload:
        if value == EMPTY:
            break
        shows.append(
            (card_from_index(value & 0b0011_1111), _BIT_TO_CONTRACT[value >> 6 & 0b1])
        )
    return tuple(shows)


# -------------------------------------------------------------- trick winners


def pack_trick_winners(winners: tuple[int, ...]) -> bytes:
    """Two bits per trick.  Redundant with the plays, and free as a checksum."""

    if len(winners) > 13:
        raise CorpusFormatError("a deal has at most thirteen tricks")
    value = 0
    for index, winner in enumerate(winners):
        if type(winner) is not int or winner not in range(4):
            raise CorpusFormatError("a trick winner is a seat in 0..3")
        value |= winner << (index * 2)
    # The count is recoverable from the plays, so an all-zero tail is a seat-0
    # sweep rather than an absence; nothing reads past the known trick count.
    return value.to_bytes(TRICK_WINNERS_BYTES, "little")


def unpack_trick_winners(payload: bytes, count: int) -> tuple[int, ...]:
    if len(payload) != TRICK_WINNERS_BYTES:
        raise CorpusFormatError(f"packed winners must be {TRICK_WINNERS_BYTES} bytes")
    if type(count) is not int or count not in range(14):
        raise CorpusFormatError("trick count must be an integer in 0..13")
    value = int.from_bytes(payload, "little")
    return tuple(value >> (index * 2) & 0b11 for index in range(count))


__all__ = [
    "CARD_ENCODING",
    "EMPTY",
    "HAND_ORDER_ID",
    "canonical_hands",
    "HANDS_BYTES",
    "PACKING_SCHEMA_VERSION",
    "PLAYS_BYTES",
    "SHOWS_BYTES",
    "TRICK_WINNERS_BYTES",
    "pack_hands",
    "pack_plays",
    "pack_shows",
    "pack_trick_winners",
    "unpack_hands",
    "unpack_plays",
    "unpack_shows",
    "unpack_trick_winners",
]
