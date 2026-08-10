from __future__ import annotations

import pytest

from tuppi_learning.datasets import generate_imitation_examples
from tuppi_learning.errors import LearningConfigurationError
from tuppi_learning.imitation import TrainingConfiguration, evaluate_imitation, train_behavior_clone


def test_dataset_stream_splits_are_explicit_and_labels_are_legal() -> None:
    examples = generate_imitation_examples(
        root_seed="phase6-dataset-tests",
        split="train",
        stream_indices=(0,),
        max_examples=32,
        safety_cap=4,
    )
    assert examples
    assert all(item.split == "train" for item in examples)
    assert all(item.target_action in item.observation.legal_actions for item in examples)
    assert len({item.stream_id for item in examples}) == 1


def test_dataset_generation_rejects_repeated_stream_identity() -> None:
    with pytest.raises(LearningConfigurationError, match="unique"):
        generate_imitation_examples(
            root_seed="phase6-duplicate-stream",
            split="train",
            stream_indices=(0, 0),
            max_examples=1,
            safety_cap=2,
        )


def test_tiny_dataset_overfit_gate() -> None:
    pytest.importorskip("torch")
    examples = generate_imitation_examples(
        root_seed="phase6-overfit",
        split="train",
        stream_indices=(0, 1),
        max_examples=128,
        safety_cap=4,
    )
    run = train_behavior_clone(
        examples,
        examples,
        training_configuration=TrainingConfiguration(
            epochs=20,
            batch_size=64,
            learning_rate=3e-3,
            seed=17,
        ),
    )
    assert run.best_validation.agreement >= 0.99
