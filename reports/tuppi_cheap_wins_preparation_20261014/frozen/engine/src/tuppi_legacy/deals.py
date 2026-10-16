"""Validated, fully materialized legacy deals and stable deal generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .canonical import canonical_json_bytes
from .constants import (
    CARD_ENCODING,
    DEAL_GENERATOR_ID,
    DEAL_SCHEMA_VERSION,
    DEAL_SET_SCHEMA_VERSION,
)
from .errors import DealValidationError

_DEAL_KEYS = {
    "schema_version",
    "deal_id",
    "card_encoding",
    "hands",
    "dealer",
    "source",
}
_DEAL_SET_KEYS = {"schema_version", "deals"}


@dataclass(frozen=True)
class Deal:
    """A complete deal in seat order, including card order within each hand."""

    deal_id: str
    hands: tuple[tuple[int, ...], ...]
    dealer: int
    source: Mapping[str, Any]
    schema_version: str = DEAL_SCHEMA_VERSION
    card_encoding: str = CARD_ENCODING

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "deal_id": self.deal_id,
            "card_encoding": self.card_encoding,
            "hands": [list(hand) for hand in self.hands],
            "dealer": self.dealer,
            "source": dict(self.source),
        }

    def flat_deck(self) -> list[int]:
        return [card for hand in self.hands for card in hand]


class _Sha256CounterRandom:
    """Small stable byte stream used only for external deal generation."""

    def __init__(self, seed: int, deal_index: int):
        self._prefix = (
            f"tuppi-legacy-deal-v1\nseed={seed}\nindex={deal_index}\n".encode("ascii")
        )
        self._counter = 0
        self._buffer = bytearray()

    def _fill(self, size: int) -> None:
        while len(self._buffer) < size:
            counter = self._counter.to_bytes(16, "big")
            self._buffer.extend(hashlib.sha256(self._prefix + counter).digest())
            self._counter += 1

    def _uint64(self) -> int:
        self._fill(8)
        chunk = bytes(self._buffer[:8])
        del self._buffer[:8]
        return int.from_bytes(chunk, "big")

    def randbelow(self, upper: int) -> int:
        if upper <= 0:
            raise ValueError("upper must be positive")
        space = 1 << 64
        limit = space - (space % upper)
        while True:
            value = self._uint64()
            if value < limit:
                return value % upper


def _stable_shuffle(cards: list[int], *, seed: int, deal_index: int) -> None:
    rng = _Sha256CounterRandom(seed, deal_index)
    for index in range(len(cards) - 1, 0, -1):
        other = rng.randbelow(index + 1)
        cards[index], cards[other] = cards[other], cards[index]


def _deal_identity_payload(
    hands: Sequence[Sequence[int]], dealer: int
) -> dict[str, Any]:
    """Return only intrinsic deal data; provenance must not change identity."""

    return {
        "schema_version": DEAL_SCHEMA_VERSION,
        "card_encoding": CARD_ENCODING,
        "hands": [list(hand) for hand in hands],
        "dealer": dealer,
    }


def compute_deal_id(hands: Sequence[Sequence[int]], dealer: int) -> str:
    """Identify intrinsic cards/dealer, independently of file provenance."""

    digest = hashlib.sha256(canonical_json_bytes(_deal_identity_payload(hands, dealer)))
    return f"sha256:{digest.hexdigest()}"


def make_deal(
    *,
    hands: Sequence[Sequence[int]],
    dealer: int,
    source: Mapping[str, Any],
    expected_deal_id: str | None = None,
) -> Deal:
    if type(dealer) is not int or dealer not in range(4):
        raise DealValidationError("dealer must be an integer in the range 0..3")
    if not isinstance(hands, (list, tuple)) or len(hands) != 4:
        raise DealValidationError("hands must contain exactly four ordered hands")
    if not isinstance(source, Mapping) or not source:
        raise DealValidationError("source must be a non-empty JSON object")

    normalized: list[tuple[int, ...]] = []
    for seat, hand in enumerate(hands):
        if not isinstance(hand, (list, tuple)) or len(hand) != 13:
            raise DealValidationError(f"hand for seat {seat} must contain exactly 13 cards")
        normalized_hand: list[int] = []
        for position, card in enumerate(hand):
            if type(card) is not int or card not in range(52):
                raise DealValidationError(
                    f"card at seat {seat}, position {position} must be an integer in 0..51"
                )
            normalized_hand.append(card)
        normalized.append(tuple(normalized_hand))

    flat = [card for hand in normalized for card in hand]
    if len(set(flat)) != 52:
        duplicates = sorted(card for card in set(flat) if flat.count(card) > 1)
        raise DealValidationError(
            "deal must contain each of the 52 cards exactly once; "
            f"duplicate cards: {duplicates or 'unknown'}"
        )

    try:
        canonical_json_bytes(dict(source))
    except (TypeError, ValueError) as exc:
        raise DealValidationError(f"source must contain canonical JSON values: {exc}") from exc

    deal_id = compute_deal_id(normalized, dealer)
    if expected_deal_id is not None and expected_deal_id != deal_id:
        raise DealValidationError(
            f"deal_id mismatch: file has {expected_deal_id!r}, calculated {deal_id!r}"
        )
    return Deal(deal_id=deal_id, hands=tuple(normalized), dealer=dealer, source=dict(source))


def validate_deal(deal: Deal) -> None:
    """Revalidate even programmatically constructed Deal instances."""

    if not isinstance(deal, Deal):
        raise DealValidationError("each supplied deal must be a Deal instance")
    if deal.schema_version != DEAL_SCHEMA_VERSION:
        raise DealValidationError(
            f"unsupported deal schema_version {deal.schema_version!r}"
        )
    if deal.card_encoding != CARD_ENCODING:
        raise DealValidationError(f"unsupported card_encoding {deal.card_encoding!r}")
    make_deal(
        hands=deal.hands,
        dealer=deal.dealer,
        source=deal.source,
        expected_deal_id=deal.deal_id,
    )


def generate_deals(*, count: int, seed: int, initial_dealer: int = 0) -> list[Deal]:
    if type(count) is not int or count <= 0:
        raise DealValidationError("deal count must be a positive integer")
    if type(seed) is not int:
        raise DealValidationError("deal seed must be an integer")
    if type(initial_dealer) is not int or initial_dealer not in range(4):
        raise DealValidationError("initial dealer must be an integer in the range 0..3")

    deals: list[Deal] = []
    for deal_index in range(count):
        deck = list(range(52))
        _stable_shuffle(deck, seed=seed, deal_index=deal_index)
        hands = [deck[seat * 13 : (seat + 1) * 13] for seat in range(4)]
        source = {
            "kind": "generated",
            "algorithm": DEAL_GENERATOR_ID,
            "seed": seed,
            "deal_index": deal_index,
        }
        deals.append(
            make_deal(
                hands=hands,
                dealer=(initial_dealer + deal_index) % 4,
                source=source,
            )
        )
    return deals


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        parts = []
        if missing:
            parts.append(f"missing {sorted(missing)}")
        if extra:
            parts.append(f"unknown {sorted(extra)}")
        raise DealValidationError(f"{context} has invalid fields: {', '.join(parts)}")


def deal_from_dict(value: Any) -> Deal:
    if not isinstance(value, dict):
        raise DealValidationError("deal must be a JSON object")
    _require_exact_keys(value, _DEAL_KEYS, "deal")
    if value["schema_version"] != DEAL_SCHEMA_VERSION:
        raise DealValidationError(
            f"unsupported deal schema_version {value['schema_version']!r}; "
            f"expected {DEAL_SCHEMA_VERSION!r}"
        )
    if value["card_encoding"] != CARD_ENCODING:
        raise DealValidationError(
            f"unsupported card_encoding {value['card_encoding']!r}; expected {CARD_ENCODING!r}"
        )
    if not isinstance(value["deal_id"], str):
        raise DealValidationError("deal_id must be a string")
    return make_deal(
        hands=value["hands"],
        dealer=value["dealer"],
        source=value["source"],
        expected_deal_id=value["deal_id"],
    )


def load_deals(path: str | Path) -> list[Deal]:
    deal_path = Path(path)
    try:
        with deal_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise DealValidationError(f"deal file does not exist: {deal_path}") from exc
    except UnicodeDecodeError as exc:
        raise DealValidationError(f"deal file is not valid UTF-8: {deal_path}") from exc
    except json.JSONDecodeError as exc:
        raise DealValidationError(
            f"deal file is not valid JSON at line {exc.lineno}, column {exc.colno}: {deal_path}"
        ) from exc
    except OSError as exc:
        raise DealValidationError(f"could not read deal file {deal_path}: {exc}") from exc

    if not isinstance(value, dict):
        raise DealValidationError("deal file root must be a JSON object")
    schema_version = value.get("schema_version")
    if schema_version == DEAL_SCHEMA_VERSION:
        return [deal_from_dict(value)]
    if schema_version == DEAL_SET_SCHEMA_VERSION:
        _require_exact_keys(value, _DEAL_SET_KEYS, "deal set")
        raw_deals = value["deals"]
        if not isinstance(raw_deals, list) or not raw_deals:
            raise DealValidationError("deal set must contain a non-empty deals array")
        return [deal_from_dict(item) for item in raw_deals]
    raise DealValidationError(
        f"unsupported or missing deal-file schema_version {schema_version!r}"
    )


def deal_set_to_dict(deals: Iterable[Deal]) -> dict[str, Any]:
    materialized = list(deals)
    for deal in materialized:
        validate_deal(deal)
    items = [deal.to_dict() for deal in materialized]
    if not items:
        raise DealValidationError("cannot serialize an empty deal set")
    return {"schema_version": DEAL_SET_SCHEMA_VERSION, "deals": items}


def compute_deal_set_digest(deals: Iterable[Deal]) -> str:
    payload = deal_set_to_dict(deals)
    return f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"
