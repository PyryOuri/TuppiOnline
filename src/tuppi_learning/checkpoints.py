"""Digest-checked learned-policy checkpoint metadata."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import pickle
from typing import Any

from .errors import CheckpointError, LearningConfigurationError, LearningDependencyError
from .models import ActorConfiguration, SeatRelativeActor


CHECKPOINT_SCHEMA_VERSION = "tuppi.learning.actor_checkpoint.v1"
_METADATA_KEYS = frozenset(
    {
        "actor_configuration",
        "checkpoint_id",
        "path_name",
        "schema_version",
        "training_configuration",
        "training_seed",
        "training_steps",
        "weight_sha256",
    }
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _checkpoint_id(
    *,
    actor_configuration: dict[str, object],
    training_configuration: dict[str, object],
    training_seed: int | None,
    training_steps: int,
    weight_sha256: str,
) -> str:
    payload = {
        "actor_configuration": actor_configuration,
        "training_configuration": training_configuration,
        "training_seed": training_seed,
        "training_steps": training_steps,
        "weight_sha256": weight_sha256,
    }
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise CheckpointError("checkpoint metadata is not canonical JSON") from exc
    return "checkpoint:sha256:" + hashlib.sha256(canonical).hexdigest()


def _torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("checkpoint operations require PyTorch") from exc
    return torch


@dataclass(frozen=True, slots=True)
class CheckpointMetadata:
    checkpoint_id: str
    path_name: str
    weight_sha256: str
    actor_configuration: dict[str, object]
    training_configuration: dict[str, object]
    training_seed: int | None
    training_steps: int
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise CheckpointError("unsupported checkpoint metadata schema")
        if (
            not isinstance(self.path_name, str)
            or not self.path_name
            or Path(self.path_name).name != self.path_name
        ):
            raise CheckpointError("checkpoint path_name must be one file name")
        if not _is_sha256(self.weight_sha256):
            raise CheckpointError("checkpoint weight digest is not canonical")
        if (
            type(self.actor_configuration) is not dict
            or type(self.training_configuration) is not dict
        ):
            raise CheckpointError("checkpoint configurations must be objects")
        if self.training_seed is not None and type(self.training_seed) is not int:
            raise CheckpointError("checkpoint training seed must be an integer or null")
        if type(self.training_steps) is not int or self.training_steps < 0:
            raise CheckpointError("checkpoint training steps must be a nonnegative integer")
        expected = _checkpoint_id(
            actor_configuration=self.actor_configuration,
            training_configuration=self.training_configuration,
            training_seed=self.training_seed,
            training_steps=self.training_steps,
            weight_sha256=self.weight_sha256,
        )
        if self.checkpoint_id != expected:
            raise CheckpointError("checkpoint_id disagrees with checkpoint metadata")

    def to_data(self) -> dict[str, object]:
        return {
            "actor_configuration": self.actor_configuration,
            "checkpoint_id": self.checkpoint_id,
            "path_name": self.path_name,
            "schema_version": self.schema_version,
            "training_configuration": self.training_configuration,
            "training_seed": self.training_seed,
            "training_steps": self.training_steps,
            "weight_sha256": self.weight_sha256,
        }


def weight_digest(actor: Any) -> str:
    torch = _torch()
    hasher = hashlib.sha256()
    for name, tensor in sorted(actor.state_dict().items()):
        hasher.update(name.encode())
        hasher.update(str(tuple(tensor.shape)).encode())
        hasher.update(str(tensor.dtype).encode())
        hasher.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return hasher.hexdigest()


def save_checkpoint(
    path: str | Path,
    actor: Any,
    *,
    training_configuration: dict[str, object],
    training_seed: int | None,
    training_steps: int,
) -> CheckpointMetadata:
    torch = _torch()
    if not hasattr(actor, "configuration") or not hasattr(actor.configuration, "to_data"):
        raise CheckpointError("actor does not expose a versioned configuration")
    target = Path(path)
    actor_configuration = actor.configuration.to_data()
    digest = weight_digest(actor)
    checkpoint_id = _checkpoint_id(
        actor_configuration=actor_configuration,
        training_configuration=training_configuration,
        training_seed=training_seed,
        training_steps=training_steps,
        weight_sha256=digest,
    )
    metadata = CheckpointMetadata(
        checkpoint_id=checkpoint_id,
        path_name=target.name,
        weight_sha256=digest,
        actor_configuration=actor_configuration,
        training_configuration=dict(training_configuration),
        training_seed=training_seed,
        training_steps=training_steps,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "actor_configuration": actor_configuration,
        "state_dict": actor.state_dict(),
    }
    torch.save(payload, target)
    target.with_suffix(target.suffix + ".json").write_text(
        json.dumps(metadata.to_data(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def load_checkpoint(
    path: str | Path,
    *,
    expected_weight_sha256: str | None = None,
    device: str = "cpu",
) -> tuple[Any, CheckpointMetadata]:
    torch = _torch()
    target = Path(path)
    try:
        metadata_data = json.loads(target.with_suffix(target.suffix + ".json").read_text(encoding="utf-8"))
        if type(metadata_data) is not dict or set(metadata_data) != _METADATA_KEYS:
            raise CheckpointError("checkpoint metadata fields are invalid")
        metadata = CheckpointMetadata(
            checkpoint_id=metadata_data["checkpoint_id"],
            path_name=metadata_data["path_name"],
            weight_sha256=metadata_data["weight_sha256"],
            actor_configuration=metadata_data["actor_configuration"],
            training_configuration=metadata_data["training_configuration"],
            training_seed=metadata_data["training_seed"],
            training_steps=metadata_data["training_steps"],
            schema_version=metadata_data["schema_version"],
        )
        if metadata.path_name != target.name:
            raise CheckpointError(
                "checkpoint metadata path_name disagrees with loaded file"
            )
        payload = torch.load(target, map_location=device, weights_only=True)
        if type(payload) is not dict or set(payload) != {"actor_configuration", "state_dict"}:
            raise CheckpointError("checkpoint payload fields are invalid")
        if payload["actor_configuration"] != metadata.actor_configuration:
            raise CheckpointError("checkpoint payload and metadata configurations disagree")
        configuration = ActorConfiguration(**metadata.actor_configuration)
        actor = SeatRelativeActor(configuration)
        actor.load_state_dict(payload["state_dict"], strict=True)
        actor.to(device)
    except CheckpointError:
        raise
    except (
        OSError,
        ValueError,
        RuntimeError,
        TypeError,
        KeyError,
        pickle.UnpicklingError,
        LearningConfigurationError,
    ) as exc:
        raise CheckpointError(f"cannot load checkpoint {target}") from exc
    actual = weight_digest(actor)
    expected = expected_weight_sha256 or metadata.weight_sha256
    if actual != expected or actual != metadata.weight_sha256:
        raise CheckpointError("checkpoint weight digest mismatch")
    return actor, metadata
