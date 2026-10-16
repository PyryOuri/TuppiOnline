"""Typed failures for deterministic Tuppi evaluation."""


class EvaluationError(Exception):
    """Base class for evaluation-layer failures."""


class EvaluationValidationError(EvaluationError, ValueError):
    """A strict evaluation input or immutable value is invalid."""


class ConfigurationError(EvaluationValidationError):
    """An evaluation configuration is invalid or inconsistent."""


class DealBankError(EvaluationValidationError):
    """A deterministic deal bank is invalid or mismatched."""


class TransformationError(EvaluationValidationError):
    """A deal, seat, suit, or script transformation is invalid."""


class ScheduleError(EvaluationValidationError):
    """A duplicate schedule is invalid or unbalanced."""


class RegistryError(EvaluationValidationError):
    """An agent registry or team specification is invalid."""


class IncompleteEvidenceError(EvaluationValidationError):
    """Results do not cover the planned manifest, so they cannot qualify."""


class EvaluationSerializationError(EvaluationValidationError):
    """Evaluation JSON could not be serialized or parsed strictly."""


class ArenaError(EvaluationError):
    """A finite arena run could not be completed as requested."""


class EvaluationTimeout(ArenaError):
    """A configured wall-time limit was exceeded."""


class InterruptedEvaluation(ArenaError):
    """A run stopped intentionally after writing resumable shards."""
