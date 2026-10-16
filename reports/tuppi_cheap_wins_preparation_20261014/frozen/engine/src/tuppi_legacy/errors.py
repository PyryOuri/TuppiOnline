"""Errors with user-facing messages for the archival harness."""


class LegacyHarnessError(Exception):
    """Base class for expected validation or execution failures."""


class ConfigurationError(LegacyHarnessError):
    """The runner configuration is invalid."""


class DealValidationError(LegacyHarnessError):
    """A generated or loaded deal is invalid."""


class ArtifactIntegrityError(LegacyHarnessError):
    """A frozen artifact does not match its manifest."""


class LegacyExecutionError(LegacyHarnessError):
    """The unchanged legacy implementation could not be executed faithfully."""

