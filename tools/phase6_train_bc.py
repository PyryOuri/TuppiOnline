"""Train and freeze the single Phase 6 behaviour-cloning checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tuppi_learning.checkpoints import save_checkpoint
from tuppi_learning.datasets import read_examples_jsonl
from tuppi_learning.imitation import (
    TrainingConfiguration,
    evaluate_imitation,
    train_behavior_clone,
)
from tuppi_learning.models import ActorConfiguration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=6)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    train = read_examples_jsonl(args.dataset / "train.jsonl")
    validation = read_examples_jsonl(args.dataset / "validation.jsonl")
    heldout = read_examples_jsonl(args.dataset / "heldout.jsonl")
    training = TrainingConfiguration(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        seed=args.seed,
        device="cpu",
    )
    run = train_behavior_clone(
        train,
        validation,
        actor_configuration=ActorConfiguration(),
        training_configuration=training,
    )
    heldout_metrics = evaluate_imitation(run.actor, heldout)
    metadata = save_checkpoint(
        args.output / "bc_best.pt",
        run.actor,
        training_configuration=training.to_data(),
        training_seed=args.seed,
        training_steps=len(train) * run.best_epoch,
    )
    report = {
        "best_epoch": run.best_epoch,
        "best_validation": run.best_validation.to_data(),
        "checkpoint": metadata.to_data(),
        "heldout": heldout_metrics.to_data(),
        "history": list(run.history),
        "train_examples": len(train),
        "validation_examples": len(validation),
        "heldout_examples": len(heldout),
    }
    (args.output / "bc_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
