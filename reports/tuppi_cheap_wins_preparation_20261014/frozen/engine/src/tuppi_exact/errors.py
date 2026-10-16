"""Typed errors for the Phase 5B exact layer.

Every failure here is explicit. Nothing in this package normalizes an invalid
input, substitutes a fallback, or downgrades an exact answer to an approximate
one: a computation that cannot be completed exactly raises instead.
"""

from __future__ import annotations


class ExactError(Exception):
    """Base class for every Phase 5B exact-layer error."""


class ConstraintError(ExactError):
    """The hard public constraint model is malformed or infeasible."""


class CountingError(ExactError):
    """An exact counting request is malformed."""


class SamplingError(ExactError):
    """A uniform feasible sampling request is malformed or impossible."""


class ContinuationError(ExactError):
    """A hypothetical continuation state cannot be constructed."""


class SolverError(ExactError):
    """The exact solver was asked for something it cannot answer exactly."""


class SolverBudgetError(SolverError):
    """The position exceeds the configured exact-solving budget.

    This is deliberately a hard error and never a heuristic estimate. The
    caller either raises the budget or accepts that the position is out of
    exact range.
    """


class IntegrityError(ExactError):
    """A frozen-baseline integrity check could not be performed."""


class DiagnosisError(ExactError):
    """A rule-diagnosis request is malformed."""
