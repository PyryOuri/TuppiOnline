"""Shared validation predicates for stable public identifiers."""

from __future__ import annotations

import re


_MATCH_REF_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,96}")
_DEAL_REF_PATTERN = re.compile(
    r"[A-Za-z0-9_.:-]{1,96}/deal:(?:0|[1-9][0-9]*)"
)
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def is_valid_match_ref(value: object) -> bool:
    """Return whether *value* matches the versioned public schema grammar."""

    return isinstance(value, str) and _MATCH_REF_PATTERN.fullmatch(value) is not None


def is_valid_deal_ref(value: object) -> bool:
    """Return whether *value* is a schema-valid public deal reference."""

    return (
        isinstance(value, str)
        and len(value) <= 128
        and _DEAL_REF_PATTERN.fullmatch(value) is not None
    )


def expected_deal_ref(match_ref: str, deal_number: int) -> str:
    """Build the only deal reference accepted for a match/deal-number pair."""

    return f"{match_ref}/deal:{deal_number}"


def is_sha256_identifier(value: object) -> bool:
    """Return whether *value* is a canonical lower-case SHA-256 identifier."""

    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None
