"""Typed failures for the Phase 5A complete-match protocol."""


class MatchProtocolError(Exception):
    """Base class for complete-match protocol failures."""


class MatchValidationError(MatchProtocolError, ValueError):
    """A strict immutable protocol input or value is invalid."""


class StreamError(MatchValidationError):
    """A deterministic match stream is invalid or was addressed illegally."""


class BankRoleError(MatchValidationError):
    """A fixture bank was used outside the role it was created for."""


class SealedBankError(BankRoleError):
    """A promotion-sealed bank was opened or used without an explicit record."""


class ManifestError(MatchValidationError):
    """A resolved match manifest is invalid or inconsistent."""


class RecordError(MatchValidationError):
    """A leg or pair record is invalid."""


class InferenceError(MatchValidationError):
    """A pair-level statistical input is invalid."""


class ExecutionError(MatchProtocolError):
    """A match leg could not be executed as requested."""


class IntegrityConflictError(MatchProtocolError):
    """A rerun produced a different semantic result for the same work unit."""
