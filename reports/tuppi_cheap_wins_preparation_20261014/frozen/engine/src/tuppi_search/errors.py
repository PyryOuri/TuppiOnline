"""Typed errors for the Phase 5C search layer.

Every failure here is explicit. A PIMC decision that cannot be completed exactly
as configured raises; it never falls back to a partial average over whichever
worlds happened to succeed. Discarding failed worlds would silently reweight the
sample, and if the failures correlate with the position - which is exactly what a
constraint or engine defect would produce - the surviving average is biased in an
unknown direction.
"""

from __future__ import annotations


class SearchError(Exception):
    """Base class for every Phase 5C search-layer error."""


class SearchConfigurationError(SearchError):
    """A PIMC configuration is malformed or internally inconsistent."""


class SeedError(SearchError):
    """A seed-derivation request is malformed."""


class UtilityError(SearchError):
    """A utility adapter was given something it cannot score."""


class WorldSetError(SearchError):
    """A sampled-world set is malformed or could not be constructed."""


class RolloutError(SearchError):
    """A rollout could not be completed."""


class IllegalRolloutActionError(RolloutError):
    """A rollout policy returned an action the engine rejected.

    This is never repaired by substituting a legal action. A policy that proposes
    an illegal action in a hypothetical world is either broken or was handed
    information it should not have, and both are defects worth surfacing.
    """


class ExactTailError(SearchError):
    """The exact-tail continuation failed under a strict failure policy."""


class PimcDecisionError(SearchError):
    """The PIMC decision as a whole is invalid and must not be used."""


class RootInfoUctDecisionError(SearchError):
    """A root-information UCT decision failed and must not be used."""

    def __init__(self, message: str, *, failure_kind: str | None = None) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


class RootInfoUctInvariantError(RootInfoUctDecisionError):
    """The information-set tree violated a correctness invariant."""


class MultiObserverDecisionError(SearchError):
    """A multi-observer re-determinizing search decision failed."""

    def __init__(self, message: str, *, failure_kind: str | None = None) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind


class MultiObserverInvariantError(MultiObserverDecisionError):
    """The multi-observer tree or privacy contract was violated."""


class SearchDiagnosticsError(SearchError):
    """A diagnostics record is malformed or would leak hidden state."""


class OracleError(SearchError):
    """A restricted perfect-information diagnostic was misused."""
