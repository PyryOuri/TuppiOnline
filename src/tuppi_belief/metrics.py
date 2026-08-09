"""Offline probabilistic metrics for hidden-card owner beliefs."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from tuppi_rules import Card, card_to_code

from .posterior import WeightedBelief


@dataclass(frozen=True, slots=True)
class OwnerMetrics:
    card_count: int
    nll: float
    brier: float
    top_owner_accuracy: float
    mean_true_owner_probability: float
    entropy: float

    def to_data(self) -> dict[str, object]:
        return {
            "brier": self.brier,
            "card_count": self.card_count,
            "entropy": self.entropy,
            "mean_true_owner_probability": self.mean_true_owner_probability,
            "nll": self.nll,
            "top_owner_accuracy": self.top_owner_accuracy,
        }


def owner_metrics(
    belief: WeightedBelief,
    true_current_hands: tuple[tuple[Card, ...], ...],
) -> OwnerMetrics:
    """Evaluate labels offline; true hands never enter deployable diagnostics."""

    marginals = belief.owner_marginals()
    true_owner: dict[str, int] = {
        card_to_code(card): seat
        for seat, hand in enumerate(true_current_hands)
        for card in hand
    }
    selected = [
        (code, probabilities, true_owner[code])
        for code, probabilities in marginals.items()
        if code in true_owner
    ]
    if not selected:
        raise ValueError("no unknown-card labels overlap the belief")
    nll = 0.0
    brier = 0.0
    correct = 0
    true_probability = 0.0
    entropy = 0.0
    for _code, probabilities, owner in selected:
        probability = max(probabilities.get(owner, 0.0), 1e-300)
        nll -= math.log(probability)
        brier += sum((probabilities.get(seat, 0.0) - (1.0 if seat == owner else 0.0)) ** 2 for seat in range(4))
        top = max(probabilities, key=lambda seat: (probabilities[seat], -seat))
        correct += int(top == owner)
        true_probability += probability
        entropy += -sum(value * math.log(value) for value in probabilities.values() if value > 0.0)
    count = len(selected)
    return OwnerMetrics(
        card_count=count,
        nll=nll / count,
        brier=brier / count,
        top_owner_accuracy=correct / count,
        mean_true_owner_probability=true_probability / count,
        entropy=entropy / count,
    )


def reliability_bins(
    records: Iterable[tuple[float, bool]], *, bins: int = 10
) -> tuple[dict[str, float], ...]:
    """Return simple reliability bins for owner probabilities."""

    if type(bins) is not int or bins <= 0:
        raise ValueError("bins must be positive")
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for probability, correct in records:
        if not 0.0 <= probability <= 1.0:
            raise ValueError("reliability probabilities must lie in [0,1]")
        index = min(int(probability * bins), bins - 1)
        buckets[index].append((probability, correct))
    output: list[dict[str, float]] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        output.append(
            {
                "count": float(len(bucket)),
                "mean_predicted": sum(item[0] for item in bucket) / len(bucket),
                "empirical_frequency": sum(float(item[1]) for item in bucket) / len(bucket),
                "bin_lower": index / bins,
                "bin_upper": (index + 1) / bins,
            }
        )
    return tuple(output)


def marginal_total_variation(
    left: Mapping[str, Mapping[int, float]],
    right: Mapping[str, Mapping[int, float]],
) -> float:
    cards = set(left) | set(right)
    if not cards:
        return 0.0
    values = []
    for card in cards:
        values.append(
            0.5
            * sum(abs(left.get(card, {}).get(seat, 0.0) - right.get(card, {}).get(seat, 0.0)) for seat in range(4))
        )
    return sum(values) / len(values)
