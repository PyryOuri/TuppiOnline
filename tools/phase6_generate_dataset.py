"""Generate a stream-separated Phase 6 imitation corpus outside Git.

Example (the default output root is intentionally outside this repository):

    PYTHONPATH=src python tools/phase6_generate_dataset.py \
      --output /Users/pyryouri/Developer/TuppiRuns/phase6/imitation-v1 \
      --train-streams 0:31 --validation-streams 100:107 --heldout-streams 200:207
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tuppi_agents import phase4_specifications_by_profile_key
from tuppi_learning.datasets import (
    build_dataset_manifest,
    generate_imitation_examples,
    write_examples_jsonl,
    write_manifest,
)


def _range(value: str) -> tuple[int, ...]:
    try:
        start, stop = (int(item) for item in value.split(":", 1))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("stream range must be START:STOP") from exc
    if start < 0 or stop <= start:
        raise argparse.ArgumentTypeError("stream range must satisfy 0 <= START < STOP")
    return tuple(range(start, stop))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root-seed", default="phase6-imitation-v1")
    parser.add_argument("--train-streams", type=_range, default=tuple(range(0, 32)))
    parser.add_argument("--validation-streams", type=_range, default=tuple(range(100, 108)))
    parser.add_argument("--heldout-streams", type=_range, default=tuple(range(200, 208)))
    parser.add_argument("--safety-cap", type=int, default=20)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    target_id = phase4_specifications_by_profile_key()["partner_aware_v1"].agent_id
    split_ranges = {
        "train": args.train_streams,
        "validation": args.validation_streams,
        "heldout": args.heldout_streams,
    }
    all_stream_ids: dict[str, tuple[str, ...]] = {}
    counts: dict[str, int] = {}
    for split, indices in split_ranges.items():
        examples = generate_imitation_examples(
            root_seed=args.root_seed,
            split=split,
            stream_indices=indices,
            safety_cap=args.safety_cap,
        )
        write_examples_jsonl(output / f"{split}.jsonl", examples)
        all_stream_ids[split] = tuple(sorted({item.stream_id for item in examples}))
        counts[split] = len(examples)
        print(f"{split}: {len(examples)} examples from {len(indices)} streams", flush=True)
    manifest = build_dataset_manifest(
        root_seed=args.root_seed,
        target_agent_id=target_id,
        split_streams=all_stream_ids,
        split_counts=counts,
        safety_cap=args.safety_cap,
    )
    write_manifest(output / "manifest.json", manifest)
    print(f"dataset_id: {manifest.dataset_id}")


if __name__ == "__main__":
    main()
