"""Deterministic indexed resampling for future search integration."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math

from tuppi_eval.serialization import content_digest


RESAMPLING_ALGORITHM_ID = "systematic_sha256_resampling_v1"


@dataclass(frozen=True, slots=True)
class DeterministicResample:
    source_indices: tuple[int, ...]
    multiplicities: tuple[int, ...]
    algorithm_id: str = field(default=RESAMPLING_ALGORITHM_ID, init=False)

    @property
    def unique_count(self) -> int:
        return sum(1 for count in self.multiplicities if count)

    def to_data(self) -> dict[str, object]:
        return {
            "algorithm_id": self.algorithm_id,
            "multiplicities": list(self.multiplicities),
            "sample_count": len(self.source_indices),
            "unique_count": self.unique_count,
        }


def systematic_resample(
    normalized_weights: tuple[float, ...] | list[float],
    *,
    count: int,
    seed: str,
    sample_index: int = 0,
) -> DeterministicResample:
    """Return deterministic systematic-resampling indices.

    The one random offset is a SHA-256 random-access draw; there is no mutable
    RNG and worker order cannot affect the output.
    """

    weights = tuple(normalized_weights)
    if not weights or any(weight < 0.0 or not math.isfinite(weight) for weight in weights):
        raise ValueError("weights must be finite and nonnegative")
    if not math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=1e-10):
        raise ValueError("weights must sum to one")
    if type(count) is not int or count <= 0:
        raise ValueError("resample count must be positive")
    if not isinstance(seed, str) or not seed:
        raise ValueError("resample seed must be nonempty")
    if type(sample_index) is not int or sample_index < 0:
        raise ValueError("sample_index must be nonnegative")
    digest = hashlib.sha256(
        f"{RESAMPLING_ALGORITHM_ID}|{seed}|{sample_index}".encode("utf-8")
    ).digest()
    offset = int.from_bytes(digest, "big") / float(1 << 256)
    step = 1.0 / count
    cumulative: list[float] = []
    running = 0.0
    for weight in weights:
        running += weight
        cumulative.append(running)
    cumulative[-1] = 1.0
    indices: list[int] = []
    pointer = 0
    for draw in range(count):
        target = (offset + draw) * step
        while pointer < len(cumulative) - 1 and target >= cumulative[pointer]:
            pointer += 1
        indices.append(pointer)
    multiplicities = tuple(indices.count(index) for index in range(len(weights)))
    return DeterministicResample(
        source_indices=tuple(indices),
        multiplicities=multiplicities,
    )


def resample_identity(result: DeterministicResample) -> str:
    return content_digest(result.to_data())
