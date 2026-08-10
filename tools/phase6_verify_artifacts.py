"""Read-only verification of the preserved Phase 6 research artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tuppi_agents import phase4_specifications_by_profile_key
from tuppi_engine import strict_json_load_file
from tuppi_learning.checkpoints import load_checkpoint, weight_digest
from tuppi_learning.datasets import build_dataset_manifest, read_examples_jsonl
from tuppi_learning.evaluation import (
    evaluate_learned_against_phase4,
    learned_agent_id,
)
from tuppi_learning.imitation import evaluate_imitation
from tuppi_match import pair_inference, secondary_metrics
from tuppi_match.executor import _pair_from_data


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _json_normalize(value: object) -> object:
    return json.loads(json.dumps(value, sort_keys=True))


def verify(artifact_root: Path, *, replay_first_pair: bool) -> dict[str, object]:
    dataset_root = artifact_root / "imitation-v1"
    corrected_root = artifact_root / "bc-v2-corrected"
    manifest = strict_json_load_file(dataset_root / "manifest.json")

    split_streams: dict[str, tuple[str, ...]] = {}
    split_counts: dict[str, int] = {}
    heldout = ()
    for split in ("train", "validation", "heldout"):
        examples = read_examples_jsonl(dataset_root / f"{split}.jsonl")
        _require(all(item.split == split for item in examples), f"{split} labels disagree")
        _require(
            all(item.target_action in item.observation.legal_actions for item in examples),
            f"{split} contains an illegal target action",
        )
        split_streams[split] = tuple(sorted({item.stream_id for item in examples}))
        split_counts[split] = len(examples)
        if split == "heldout":
            heldout = examples

    all_streams = tuple(
        stream_id
        for split in ("train", "validation", "heldout")
        for stream_id in split_streams[split]
    )
    _require(len(all_streams) == len(set(all_streams)), "dataset splits overlap")
    rebuilt_manifest = build_dataset_manifest(
        root_seed=manifest["root_seed"],
        target_agent_id=manifest["target_agent_id"],
        split_streams=split_streams,
        split_counts=split_counts,
        profile_schedule=tuple(tuple(row) for row in manifest["profile_schedule"]),
        score_schedule=tuple(tuple(row) for row in manifest["score_schedule"]),
        safety_cap=manifest["safety_cap"],
    )
    _require(
        _json_normalize(rebuilt_manifest.to_data()) == manifest,
        "dataset manifest does not rebuild from corpus content",
    )

    checkpoint_path = corrected_root / "bc_best.pt"
    actor, checkpoint = load_checkpoint(checkpoint_path, device="cpu")
    checkpoint_sidecar = strict_json_load_file(checkpoint_path.with_suffix(".pt.json"))
    training_report = strict_json_load_file(corrected_root / "bc_report.json")
    _require(
        checkpoint.to_data() == checkpoint_sidecar == training_report["checkpoint"],
        "checkpoint metadata and training report disagree",
    )
    _require(
        weight_digest(actor) == checkpoint.weight_sha256,
        "loaded actor weight digest disagrees with checkpoint",
    )
    heldout_metrics = evaluate_imitation(actor, heldout, device="cpu").to_data()
    _require(
        heldout_metrics == training_report["heldout"],
        "fresh held-out metrics disagree with training report",
    )

    strength = strict_json_load_file(corrected_root / "strength-32.json")
    pairs = tuple(_pair_from_data(item) for item in strength["pairs"])
    _require(len(pairs) == strength["pair_count"], "stored pair count disagrees")
    _require(
        all(pair.comparison_id == strength["comparison_id"] for pair in pairs),
        "stored pairs mix comparison identities",
    )
    inference = pair_inference(
        pairs,
        confidence_level=strength["inference"]["confidence_level"],
        analysis_seed=strength["inference"]["analysis_seed"],
        bootstrap_replicates=2_000,
        sign_flip_replicates=2_000,
    )
    _require(inference == strength["inference"], "paired inference does not rebuild")
    _require(
        secondary_metrics(pairs) == strength["secondary"],
        "secondary metrics do not rebuild",
    )

    candidate_id = learned_agent_id(
        checkpoint_id=checkpoint.checkpoint_id,
        weight_sha256=checkpoint.weight_sha256,
        configuration_id=actor.configuration.configuration_id,
    )
    opponent_id = phase4_specifications_by_profile_key()["partner_aware_v1"].agent_id
    _require(candidate_id == strength["candidate_agent_id"], "candidate identity disagrees")
    _require(opponent_id == strength["opponent_agent_id"], "opponent identity disagrees")

    replayed_pair_id = None
    if replay_first_pair:
        replay = evaluate_learned_against_phase4(
            actor,
            checkpoint,
            root_seed=strength["root_seed"],
            pair_count=1,
            analysis_seed=strength["inference"]["analysis_seed"],
        )
        _require(
            replay.pairs[0].semantic_data() == pairs[0].semantic_data(),
            "fresh first-pair replay disagrees with stored evaluation",
        )
        replayed_pair_id = replay.pairs[0].pair_record_id

    return {
        "candidate_agent_id": candidate_id,
        "checkpoint_id": checkpoint.checkpoint_id,
        "dataset_id": rebuilt_manifest.dataset_id,
        "heldout_agreement": heldout_metrics["agreement"],
        "pair_outcomes": inference["pair_outcomes"],
        "pairs_revalidated": len(pairs),
        "replayed_pair_id": replayed_pair_id,
        "split_counts": split_counts,
        "split_stream_counts": {
            split: len(streams) for split, streams in split_streams.items()
        },
        "status": "pass",
        "weight_sha256": checkpoint.weight_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--replay-first-pair", action="store_true")
    args = parser.parse_args()
    summary = verify(args.artifact_root, replay_first_pair=args.replay_first_pair)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
