"""Errors raised by the Phase 7 corpus layer."""

from __future__ import annotations


class CorpusError(Exception):
    """Base class for every corpus failure."""


class CorpusConfigurationError(CorpusError):
    """A manifest, stratum mixture, or stream range is invalid."""


class CorpusFormatError(CorpusError):
    """A record, shard, or catalogue entry could not be encoded or decoded."""


class CorpusIntegrityError(CorpusError):
    """Stored bytes disagree with their recorded digest, or a rebuild diverged."""


class CorpusProvenanceError(CorpusError):
    """A pinned source digest has changed, so regeneration cannot be trusted."""


__all__ = [
    "CorpusConfigurationError",
    "CorpusError",
    "CorpusFormatError",
    "CorpusIntegrityError",
    "CorpusProvenanceError",
]
