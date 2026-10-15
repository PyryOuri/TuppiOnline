"""Optional Phase 6 learned-policy layer.

Importing this package does not import PyTorch.  The rules engine, frozen
agents, evaluator, and classical search therefore remain usable without the
optional learning dependency group.
"""

from .encoding import (
    ACTION_ENCODER_VERSION,
    ENCODER_VERSION,
    PREPROCESSING_VERSION,
    EncodedObservation,
    batch_from_observations,
    encode_observation,
    relative_seat,
)
from .errors import (
    CheckpointError,
    LearningConfigurationError,
    LearningDependencyError,
    LearningError,
    ObservationBoundaryError,
)
from .models import ActorConfiguration

LEARNING_LAYER_VERSION = "0.11.0"

__all__ = (
    "ACTION_ENCODER_VERSION",
    "ENCODER_VERSION",
    "PREPROCESSING_VERSION",
    "ActorConfiguration",
    "CheckpointError",
    "EncodedObservation",
    "LearningConfigurationError",
    "LearningDependencyError",
    "LearningError",
    "LEARNING_LAYER_VERSION",
    "ObservationBoundaryError",
    "batch_from_observations",
    "encode_observation",
    "relative_seat",
)
