"""Typed failures raised by the clean ``project_target_v1`` engine."""


class EngineError(Exception):
    """Base class for clean-engine failures."""


class EngineValidationError(EngineError, ValueError):
    """Input or action data failed explicit validation."""


class InvalidConstructionError(EngineValidationError):
    """A deal or match could not be constructed faithfully."""


class InvalidActionError(EngineValidationError):
    """An action is structurally or semantically illegal."""


class WrongActorError(InvalidActionError):
    """An action was returned for a seat other than the current actor."""


class WrongPhaseError(InvalidActionError):
    """An action does not belong to the current explicit phase."""


class TerminalStateError(InvalidActionError):
    """A transition was attempted after terminal state."""


class StateInvariantError(EngineError):
    """A supposedly internal engine state violates an invariant."""


class AgentProtocolError(EngineError):
    """An agent failed to return a valid engine action."""


class SerializationError(EngineValidationError):
    """Serialized input or output violates its versioned contract."""


class DealSequenceError(EngineValidationError):
    """An explicit deal sequence cannot be applied to the match."""


class RunnerConfigurationError(EngineValidationError):
    """Headless runner configuration is invalid."""
