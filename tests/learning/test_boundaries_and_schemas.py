from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tuppi_engine import MatchState, action_from_data, action_to_data
from tuppi_learning.checkpoints import load_checkpoint, save_checkpoint
from tuppi_learning.datasets import build_dataset_manifest, generate_imitation_examples
from tuppi_learning.errors import (
    CheckpointError,
    LearningConfigurationError,
    ObservationBoundaryError,
)
from tuppi_learning.evaluation import evaluate_learned_against_phase4
from tuppi_learning.models import ActorConfiguration, CentralizedCritic, ObservationOnlyActor, SeatRelativeActor


ROOT = Path(__file__).resolve().parents[2]


def test_learning_schemas_are_strict_objects() -> None:
    for path in (ROOT / "schemas" / "learning").glob("*.schema.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["type"] == "object"
        assert payload["additionalProperties"] is False


def test_phase6_package_version_is_incremented() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "0.11.0"' in pyproject


def test_stream_manifest_has_disjoint_split_identity() -> None:
    manifest = build_dataset_manifest(
        root_seed="phase6-schema",
        target_agent_id="agent:sha256:" + "a" * 64,
        split_streams={
            "train": ("stream:a",),
            "validation": ("stream:b",),
            "heldout": ("stream:c",),
        },
        split_counts={"train": 1, "validation": 1, "heldout": 1},
    )
    assert manifest.safety_cap == 20
    assert not (set(manifest.split_streams["train"]) & set(manifest.split_streams["heldout"]))
    with pytest.raises(LearningConfigurationError, match="disjoint"):
        build_dataset_manifest(
            root_seed="phase6-overlap",
            target_agent_id="agent:sha256:" + "a" * 64,
            split_streams={
                "train": ("stream:shared",),
                "validation": ("stream:validation",),
                "heldout": ("stream:shared",),
            },
            split_counts={"train": 1, "validation": 1, "heldout": 1},
        )
    with pytest.raises(LearningConfigurationError, match="dataset_id"):
        replace(manifest, dataset_id="dataset:sha256:" + "0" * 64)


def test_actor_configuration_rejects_unsupported_encoder_identity() -> None:
    with pytest.raises(LearningConfigurationError, match="encoder_version"):
        ActorConfiguration(encoder_version="seat_relative_observation_encoder_unversioned")


def test_actor_logits_are_invariant_to_nonsemantic_match_identifiers() -> None:
    pytest.importorskip("torch")
    examples = generate_imitation_examples(
        root_seed="phase6-invariance",
        split="train",
        stream_indices=(0,),
        max_examples=1,
        safety_cap=2,
    )
    observation = examples[0].observation
    changed = replace(observation, match_ref="learn-tr-999999", deal_ref="learn-tr-999999/deal:0")
    actor = SeatRelativeActor(ActorConfiguration())
    actor.eval()
    deployed = ObservationOnlyActor(actor)
    assert deployed.choose_action(observation) == deployed.choose_action(changed)


def test_action_encoding_round_trips_every_legal_action() -> None:
    examples = generate_imitation_examples(
        root_seed="phase6-action-roundtrip",
        split="train",
        stream_indices=(0,),
        max_examples=16,
        safety_cap=2,
    )
    for example in examples:
        for action in example.observation.legal_actions:
            assert action_from_data(action_to_data(action)) == action


def test_critic_is_separate_from_deployment_actor() -> None:
    torch = pytest.importorskip("torch")
    critic = CentralizedCritic(input_dim=8)
    value = critic(torch.zeros((2, 8)))
    assert tuple(value.shape) == (2,)
    actor = SeatRelativeActor()
    assert not hasattr(actor, "critic")
    deployment = ObservationOnlyActor(actor)
    with pytest.raises(ObservationBoundaryError):
        deployment.choose_action(MatchState)  # type: ignore[arg-type]


def test_checkpoint_digest_validation(tmp_path) -> None:
    torch = pytest.importorskip("torch")
    actor = SeatRelativeActor()
    metadata = save_checkpoint(
        tmp_path / "actor.pt",
        actor,
        training_configuration={"test": True},
        training_seed=1,
        training_steps=0,
    )
    loaded, loaded_metadata = load_checkpoint(tmp_path / "actor.pt")
    assert loaded_metadata.weight_sha256 == metadata.weight_sha256
    assert ObservationOnlyActor(loaded).identity == actor.configuration.configuration_id
    with pytest.raises(CheckpointError):
        load_checkpoint(tmp_path / "actor.pt", expected_weight_sha256="0" * 64)

    different_actor = SeatRelativeActor()
    with torch.no_grad():
        next(different_actor.parameters()).add_(1.0)
    with pytest.raises(LearningConfigurationError, match="weights"):
        evaluate_learned_against_phase4(
            different_actor,
            metadata,
            root_seed="phase6-mismatched-checkpoint",
            pair_count=1,
        )

    metadata_path = tmp_path / "actor.pt.json"
    tampered = json.loads(metadata_path.read_text(encoding="utf-8"))
    tampered["training_steps"] = 1
    metadata_path.write_text(
        json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with pytest.raises(CheckpointError, match="checkpoint_id"):
        load_checkpoint(tmp_path / "actor.pt")
