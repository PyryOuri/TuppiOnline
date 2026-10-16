"""Canonical private content identities shared across state boundaries."""

from __future__ import annotations

import hashlib
import json

from tuppi_rules import CARD_ENCODING_ID, RULESET_ID, Card, card_to_code


DEAL_IDENTITY_SCHEMA_VERSION = "tuppi.engine.deal_identity.v1"


def deal_identity_data(
    *, dealer: int, hands: tuple[tuple[Card, ...], ...]
) -> dict[str, object]:
    return {
        "card_encoding": CARD_ENCODING_ID,
        "dealer": dealer,
        "hands": [[card_to_code(card) for card in hand] for hand in hands],
        "ruleset_id": RULESET_ID.value,
        "schema_version": DEAL_IDENTITY_SCHEMA_VERSION,
    }


def calculate_deal_id(
    *, dealer: int, hands: tuple[tuple[Card, ...], ...]
) -> str:
    canonical = json.dumps(
        deal_identity_data(dealer=dealer, hands=hands),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
