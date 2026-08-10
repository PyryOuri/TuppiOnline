"""Behaviour cloning from the frozen ``partner_aware_v1`` labels."""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any, Iterable

from tuppi_engine import EnginePhase

from .datasets import ImitationExample
from .errors import LearningConfigurationError, LearningDependencyError
from .models import ActorConfiguration, SeatRelativeActor
from .encoding import batch_from_observations


def _torch():
    try:
        import torch
        import torch.nn.functional as functional
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("imitation training requires PyTorch") from exc
    return torch, functional


@dataclass(frozen=True, slots=True)
class TrainingConfiguration:
    epochs: int = 8
    batch_size: int = 256
    learning_rate: float = 1e-3
    weight_decay: float = 1e-5
    seed: int = 6
    device: str = "cpu"
    phase_aware_showing_weight: float = 2.0

    def __post_init__(self) -> None:
        if self.epochs <= 0 or self.batch_size <= 0:
            raise LearningConfigurationError("training epochs and batch size must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise LearningConfigurationError("optimizer settings are invalid")
        if self.phase_aware_showing_weight <= 0:
            raise LearningConfigurationError("showing loss weight must be positive")

    def to_data(self) -> dict[str, object]:
        return {
            "batch_size": self.batch_size,
            "device": self.device,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "phase_aware_showing_weight": self.phase_aware_showing_weight,
            "seed": self.seed,
            "weight_decay": self.weight_decay,
        }


@dataclass(frozen=True, slots=True)
class ImitationMetrics:
    examples: int
    correct: int
    cross_entropy: float
    showing_examples: int
    showing_correct: int
    trick_examples: int
    trick_correct: int
    rami_examples: int
    rami_correct: int
    nolo_examples: int
    nolo_correct: int
    declarer_examples: int
    declarer_correct: int
    defender_examples: int
    defender_correct: int

    @property
    def agreement(self) -> float:
        return self.correct / self.examples if self.examples else 0.0

    @staticmethod
    def _rate(correct: int, examples: int) -> float:
        return correct / examples if examples else float("nan")

    @property
    def showing_agreement(self) -> float:
        return self._rate(self.showing_correct, self.showing_examples)

    @property
    def trick_agreement(self) -> float:
        return self._rate(self.trick_correct, self.trick_examples)

    def to_data(self) -> dict[str, object]:
        return {
            "agreement": self.agreement,
            "correct": self.correct,
            "cross_entropy": self.cross_entropy,
            "declarer_agreement": self._rate(self.declarer_correct, self.declarer_examples),
            "declarer_correct": self.declarer_correct,
            "declarer_examples": self.declarer_examples,
            "defender_agreement": self._rate(self.defender_correct, self.defender_examples),
            "defender_correct": self.defender_correct,
            "defender_examples": self.defender_examples,
            "examples": self.examples,
            "nolo_agreement": self._rate(self.nolo_correct, self.nolo_examples),
            "nolo_correct": self.nolo_correct,
            "nolo_examples": self.nolo_examples,
            "rami_agreement": self._rate(self.rami_correct, self.rami_examples),
            "rami_correct": self.rami_correct,
            "rami_examples": self.rami_examples,
            "showing_agreement": self.showing_agreement,
            "showing_correct": self.showing_correct,
            "showing_examples": self.showing_examples,
            "trick_agreement": self.trick_agreement,
            "trick_correct": self.trick_correct,
            "trick_examples": self.trick_examples,
        }


@dataclass(frozen=True, slots=True)
class ImitationRun:
    actor: Any
    configuration: ActorConfiguration
    training_configuration: TrainingConfiguration
    history: tuple[dict[str, object], ...]
    best_epoch: int
    best_validation: ImitationMetrics


def _seed_everything(seed: int) -> None:
    torch, _ = _torch()
    random.seed(seed)
    torch.manual_seed(seed)


def _batch_loss(actor, examples: tuple[ImitationExample, ...], indices: list[int], config: TrainingConfiguration):
    torch, functional = _torch()
    observations = tuple(examples[index].observation for index in indices)
    batch = batch_from_observations(observations, device=config.device)
    targets = torch.tensor([examples[index].target_index for index in indices], dtype=torch.long, device=config.device)
    logits = actor(batch)
    losses = functional.cross_entropy(logits, targets, reduction="none")
    weights = torch.tensor(
        [config.phase_aware_showing_weight if examples[index].observation.phase is EnginePhase.SHOWING else 1.0 for index in indices],
        dtype=losses.dtype,
        device=config.device,
    )
    return (losses * weights).mean(), logits, targets


def evaluate_imitation(actor, examples: Iterable[ImitationExample], *, device: str = "cpu") -> ImitationMetrics:
    torch, functional = _torch()
    items = tuple(examples)
    if not items:
        raise LearningConfigurationError("cannot evaluate an empty imitation split")
    actor.eval()
    correct = showing_correct = trick_correct = 0
    showing_examples = trick_examples = 0
    rami_examples = rami_correct = nolo_examples = nolo_correct = 0
    declarer_examples = declarer_correct = defender_examples = defender_correct = 0
    total_loss = 0.0
    with torch.no_grad():
        for start in range(0, len(items), 512):
            chunk = items[start : start + 512]
            batch = batch_from_observations((item.observation for item in chunk), device=device)
            targets = torch.tensor([item.target_index for item in chunk], dtype=torch.long, device=device)
            logits = actor(batch)
            total_loss += float(functional.cross_entropy(logits, targets, reduction="sum").item())
            predictions = logits.argmax(dim=-1).tolist()
            for item, prediction in zip(chunk, predictions):
                is_correct = prediction == item.target_index
                correct += int(is_correct)
                if item.observation.phase is EnginePhase.SHOWING:
                    showing_examples += 1
                    showing_correct += int(is_correct)
                else:
                    trick_examples += 1
                    trick_correct += int(is_correct)
                    if item.observation.contract is not None and item.observation.contract.value == "RAMI":
                        rami_examples += 1
                        rami_correct += int(is_correct)
                    elif item.observation.contract is not None:
                        nolo_examples += 1
                        nolo_correct += int(is_correct)
                    if item.observation.declarer is not None:
                        if item.observation.declarer == item.observation.observing_seat:
                            declarer_examples += 1
                            declarer_correct += int(is_correct)
                        else:
                            defender_examples += 1
                            defender_correct += int(is_correct)
    return ImitationMetrics(
        examples=len(items),
        correct=correct,
        cross_entropy=total_loss / len(items),
        showing_examples=showing_examples,
        showing_correct=showing_correct,
        trick_examples=trick_examples,
        trick_correct=trick_correct,
        rami_examples=rami_examples,
        rami_correct=rami_correct,
        nolo_examples=nolo_examples,
        nolo_correct=nolo_correct,
        declarer_examples=declarer_examples,
        declarer_correct=declarer_correct,
        defender_examples=defender_examples,
        defender_correct=defender_correct,
    )


def train_behavior_clone(
    train_examples: Iterable[ImitationExample],
    validation_examples: Iterable[ImitationExample],
    *,
    actor_configuration: ActorConfiguration | None = None,
    training_configuration: TrainingConfiguration | None = None,
) -> ImitationRun:
    torch, _ = _torch()
    train = tuple(train_examples)
    validation = tuple(validation_examples)
    if not train or not validation:
        raise LearningConfigurationError("training and validation splits must be nonempty")
    config = training_configuration or TrainingConfiguration()
    architecture = actor_configuration or ActorConfiguration()
    _seed_everything(config.seed)
    actor = SeatRelativeActor(architecture)
    actor.to(config.device)
    optimizer = torch.optim.AdamW(actor.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    history: list[dict[str, object]] = []
    best_epoch = 0
    best_validation: ImitationMetrics | None = None
    best_state = None
    rng = random.Random(config.seed)
    for epoch in range(config.epochs):
        actor.train()
        indices = list(range(len(train)))
        rng.shuffle(indices)
        loss_sum = 0.0
        batch_count = 0
        for start in range(0, len(indices), config.batch_size):
            batch_indices = indices[start : start + config.batch_size]
            optimizer.zero_grad(set_to_none=True)
            loss, _logits, _targets = _batch_loss(actor, train, batch_indices, config)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(actor.parameters(), 1.0)
            optimizer.step()
            loss_sum += float(loss.detach().item())
            batch_count += 1
        validation_metrics = evaluate_imitation(actor, validation, device=config.device)
        history.append({
            "epoch": epoch + 1,
            "train_loss": loss_sum / max(batch_count, 1),
            "validation": validation_metrics.to_data(),
        })
        if best_validation is None or (
            validation_metrics.agreement > best_validation.agreement
            or (
                validation_metrics.agreement == best_validation.agreement
                and validation_metrics.cross_entropy < best_validation.cross_entropy
            )
        ):
            best_epoch = epoch + 1
            best_validation = validation_metrics
            best_state = {name: value.detach().cpu().clone() for name, value in actor.state_dict().items()}
    if best_validation is None or best_state is None:  # pragma: no cover
        raise LearningConfigurationError("training produced no validation checkpoint")
    actor.load_state_dict(best_state)
    actor.to(config.device)
    return ImitationRun(
        actor=actor,
        configuration=architecture,
        training_configuration=config,
        history=tuple(history),
        best_epoch=best_epoch,
        best_validation=best_validation,
    )
