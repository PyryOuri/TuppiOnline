"""Domain-separated experiment streams (C0.03, C1-03).

Every experimental random stream is derived from a namespace and explicit
labels by SHA-256, so streams for fitting, cheap/expensive batches, references
and validation are independent of one another and of every policy's own
persistent RNG. A policy's own seeds come only from (namespace, bundle, arm,
seat) labels, never from hands, world or layout identities.
"""

from __future__ import annotations

import ctypes
import hashlib
import random

import numpy as np

STREAM_SCHEMA = "tuppi.research.stream.v1"
NAMESPACES = frozenset({"deal", "score", "agent", "fit", "plan", "screen", "confirm", "cheap", "expensive",
                        "reference", "validation", "fixture", "test"})
#: Whole label tokens that would name evaluator-only data (a layout's identity
#: must never seed a policy or an experimental stream).
_FORBIDDEN_TOKENS = frozenset({"world", "worlds", "layout", "layouts", "hands", "hidden", "truth"})


def _check(namespace: str, labels: tuple) -> None:
    import re

    if namespace not in NAMESPACES:
        raise ValueError(f"unknown stream namespace {namespace!r}")
    for lab in labels:
        tokens = set(re.split(r"[^a-z0-9]+", str(lab).lower()))
        if tokens & _FORBIDDEN_TOKENS:
            raise ValueError(f"stream label {lab!r} names evaluator-only data")


def stream_seed(namespace: str, *labels) -> int:
    """A 64-bit seed for (namespace, labels); distinct inputs give independent seeds."""
    _check(namespace, labels)
    text = "|".join([STREAM_SCHEMA, namespace, *map(str, labels)])
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


def scalar_stream(namespace: str, *labels) -> ctypes.c_uint64:
    """A native SplitMix state (the type every tc_sample_* call advances)."""
    return ctypes.c_uint64(stream_seed(namespace, *labels))


def numpy_stream(namespace: str, *labels) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(stream_seed(namespace, *labels)))


def python_stream(namespace: str, *labels) -> random.Random:
    return random.Random(stream_seed(namespace, *labels))


def shuffled_deck(namespace: str, *labels):
    """An engine deck (tuple of four 13-card hands) from a named stream."""
    from tuppi_rules.cards import FULL_DECK

    cards = list(FULL_DECK)
    python_stream(namespace, *labels).shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


def legacy_deck(seed: str, index: int):
    """tuppi_ai.evaluate's deck law (`random.Random(f"{seed}|deal|{index}")`), for continuity only."""
    from tuppi_rules.cards import FULL_DECK

    cards = list(FULL_DECK)
    random.Random(f"{seed}|deal|{index}").shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))


def legacy_match_deck(seed: str, pair: int, deal: int):
    """tuppi_ai.match_eval's deck law, for continuity only."""
    from tuppi_rules.cards import FULL_DECK

    cards = list(FULL_DECK)
    random.Random(f"{seed}|pair|{pair}|deal|{deal}").shuffle(cards)
    return tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
