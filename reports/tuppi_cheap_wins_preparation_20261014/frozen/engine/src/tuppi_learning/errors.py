"""Errors raised by the optional Phase 6 learning layer."""

from __future__ import annotations


class LearningError(Exception):
    """Base class for learning-layer failures."""


class LearningDependencyError(LearningError):
    """Raised when an operation requires an optional ML dependency."""


class ObservationBoundaryError(LearningError):
    """Raised when private engine state crosses the actor boundary."""


class LearningConfigurationError(LearningError):
    """Raised for malformed or internally inconsistent configurations."""


class CheckpointError(LearningError):
    """Raised when a checkpoint cannot be safely loaded or validated."""
