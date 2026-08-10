"""Run the bounded direct BC-versus-reference complete-match gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tuppi_learning.checkpoints import load_checkpoint
from tuppi_learning.evaluation import evaluate_learned_against_phase4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=32)
    parser.add_argument("--root-seed", default="phase6-bc-strength-v1")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    actor, metadata = load_checkpoint(args.checkpoint, device="cpu")
    result = evaluate_learned_against_phase4(
        actor,
        metadata,
        root_seed=args.root_seed,
        pair_count=args.pairs,
        analysis_seed="phase6-bc-strength-v1",
    )
    args.output.write_text(json.dumps(result.to_data(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result.inference, indent=2, sort_keys=True))
    print(json.dumps(result.secondary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
