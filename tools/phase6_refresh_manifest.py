"""Add the frozen corpus safety-cap field without regenerating its examples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tuppi_learning.datasets import build_dataset_manifest, write_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--safety-cap", type=int, default=20)
    args = parser.parse_args()
    old = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = build_dataset_manifest(
        root_seed=old["root_seed"],
        target_agent_id=old["target_agent_id"],
        split_streams={key: tuple(value) for key, value in old["split_streams"].items()},
        split_counts={key: int(value) for key, value in old["split_counts"].items()},
        safety_cap=args.safety_cap,
    )
    write_manifest(args.manifest, manifest)
    print(manifest.dataset_id)


if __name__ == "__main__":
    main()
