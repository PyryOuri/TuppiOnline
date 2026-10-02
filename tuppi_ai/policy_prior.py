"""Root-action scoring only; no engine, model, or hidden-state access.

Soft scores are Q + tau * log pi over the legal actions. Centered logits
give the same ranking without computing probabilities or exponentials.
All Q values and margins are in equity units, not RETURN_SCALE units.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _finite_vector(values: Sequence[float], name: str) -> list[float]:
    out = [float(v) for v in values]
    if not out or not all(math.isfinite(v) for v in out):
        raise ValueError(f"{name} must be a nonempty finite vector")
    return out


def soft_offsets(legal_logits: Sequence[float], strength: float) -> list[float]:
    """Offsets equivalent to tau log pi, with the largest offset set to zero."""
    if not math.isfinite(strength) or strength < 0:
        raise ValueError("policy-prior strength must be finite and nonnegative")
    logits = _finite_vector(legal_logits, "legal logits")
    if strength == 0:
        return [0.0] * len(logits)
    top = max(logits)
    return _finite_vector([strength * (v - top) for v in logits], "score offsets")


def hard_offsets(legal_logits: Sequence[float], margin: float) -> tuple[list[float], int]:
    """A fixed bonus for the actor's first maximum; ties must prefer that action."""
    if not math.isfinite(margin) or margin < 0:
        raise ValueError("anchor margin must be finite and nonnegative")
    logits = _finite_vector(legal_logits, "legal logits")
    preferred = max(range(len(logits)), key=logits.__getitem__)
    offsets = [0.0] * len(logits)
    offsets[preferred] = margin
    return offsets, preferred


def action_scores(values: Sequence[float], offsets: Sequence[float] | None = None) -> list[float]:
    scores = _finite_vector(values, "searched values")
    if offsets is not None:
        prior = _finite_vector(offsets, "score offsets")
        if len(prior) != len(scores):
            raise ValueError("score offsets must match the legal action count")
        scores = [v + p for v, p in zip(scores, prior)]
        if not all(math.isfinite(v) for v in scores):
            raise ValueError("combined scores must be finite")
    return scores


def select_action(values: Sequence[float], offsets: Sequence[float] | None = None,
                  preferred: int | None = None) -> int:
    """First maximum, except the fixed-margin anchor wins an exact score tie."""
    scores = action_scores(values, offsets)
    if preferred is not None and not 0 <= preferred < len(scores):
        raise ValueError("preferred action index is outside the legal action list")
    return max(range(len(scores)), key=lambda i: (scores[i], i == preferred, -i))
