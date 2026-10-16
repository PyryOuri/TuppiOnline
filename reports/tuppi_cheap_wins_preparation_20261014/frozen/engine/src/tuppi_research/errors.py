"""Typed failures for the research control layer."""


class ResearchError(Exception):
    """Base class for research-layer failures."""


class LedgerError(ResearchError, ValueError):
    """The metadata ledger was used inconsistently or holds invalid state."""


class CycleError(ResearchError, ValueError):
    """A control cycle cannot proceed as specified."""


class LegalityError(CycleError):
    """A candidate failed a correctness precondition before any measurement."""
