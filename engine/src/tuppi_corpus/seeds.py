"""Domain-separated deterministic seed derivation for corpus generation.

The corpus contains randomised strata - epsilon branches and a softened
reference policy - and they must be reproducible from the manifest alone.  This
module derives every random quantity from a canonical JSON object over named
coordinates, the same shape ``tuppi_search.random`` uses, rather than from a
mutable stream.

Nothing here touches Python's module-global RNG, and nothing uses ``hash()``,
which is salted per process and would make a run irreproducible.
"""

from __future__ import annotations

import hashlib
import json

from .errors import CorpusConfigurationError


SEED_SCHEMA_VERSION = "tuppi.corpus.seed_derivation.v1"


def derive_seed(root_seed: str, **coordinates: object) -> int:
    """A 256-bit integer determined by *root_seed* and the named coordinates."""

    if not isinstance(root_seed, str) or not root_seed:
        raise CorpusConfigurationError("root_seed must be a nonempty string")
    payload = {
        "coordinates": coordinates,
        "root_seed": root_seed,
        "schema_version": SEED_SCHEMA_VERSION,
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")


def uniform_below(seed: int, bound: int, *, stride: int = 0) -> int:
    """An unbiased draw from ``range(bound)``, determined by *seed*.

    Rejection sampling on successive SHA-256 blocks rather than ``seed %
    bound``, which would bias the low indices.  ``stride`` draws a second,
    independent value from the same seed without re-deriving coordinates.
    """

    if type(bound) is not int or bound <= 0:
        raise CorpusConfigurationError("bound must be a positive integer")
    if bound == 1:
        return 0
    limit = (1 << 64) - ((1 << 64) % bound)
    material = seed.to_bytes(32, "big")
    counter = stride
    while True:
        block = hashlib.sha256(material + counter.to_bytes(8, "big")).digest()
        candidate = int.from_bytes(block[:8], "big")
        if candidate < limit:
            return candidate % bound
        counter += 1


def uniform_unit(seed: int, *, stride: int = 0) -> float:
    """A value in [0, 1) determined by *seed*, at 53-bit resolution."""

    return uniform_below(seed, 1 << 53, stride=stride) / float(1 << 53)


__all__ = ["SEED_SCHEMA_VERSION", "derive_seed", "uniform_below", "uniform_unit"]
