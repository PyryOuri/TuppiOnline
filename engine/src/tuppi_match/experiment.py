"""Running a resolved manifest, storing it, and rebuilding it byte-identically.

Storage layout under one experiment directory::

    manifest.json          the resolved immutable manifest
    frozen_agents.json     the Phase 4 baseline snapshot used
    pairs/<comparison>.json  every pair record, complete or not
    inventory.json         trusted and quarantined work units
    report.json            the aggregate report

The rule that matters for reproducibility: rerunning an existing semantic work
unit must reproduce the same semantic result or raise
:class:`~tuppi_match.errors.IntegrityConflictError`. Wall-clock durations are
excluded from semantic identity, so a slower machine is not a conflict; a
different action is.

Large outputs belong outside a cloud-synced directory. See
``docs/match/complete_match_protocol.md`` for the recommended scratch path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tuppi_engine import atomic_write_canonical_json, strict_json_load_file
from tuppi_eval.serialization import content_digest

from .errors import IntegrityConflictError, ManifestError, SealedBankError
from .executor import _pair_from_data, run_experiment
from .freeze import build_snapshot, verify_snapshot
from .manifest import MatchManifest
from .records import PairRecord, PairStatus
from .statistics import pair_inference, secondary_metrics


EXPERIMENT_SCHEMA_VERSION = "tuppi.match.experiment_result.v1"
INVENTORY_SCHEMA_VERSION = "tuppi.match.inventory.v1"


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    manifest: MatchManifest
    pairs: dict[str, tuple[PairRecord, ...]]
    report: dict[str, object]


def _comparison_file(comparison_id: str) -> str:
    return f"{comparison_id.split(':')[-1][:24]}.json"


def load_pairs(directory: Path, manifest: MatchManifest) -> dict[str, tuple[PairRecord, ...]]:
    """Load previously stored pairs, revalidating every record."""

    collected: dict[str, tuple[PairRecord, ...]] = {}
    for comparison in manifest.comparisons:
        path = directory / "pairs" / _comparison_file(comparison.comparison_id)
        if not path.exists():
            continue
        payload = strict_json_load_file(path)
        if type(payload) is not dict or payload.get("comparison_id") != (
            comparison.comparison_id
        ):
            raise IntegrityConflictError(
                f"stored pairs do not belong to comparison {comparison.name!r}"
            )
        collected[comparison.comparison_id] = tuple(
            _pair_from_data(item) for item in payload["pairs"]
        )
    return collected


def run(
    manifest: MatchManifest,
    *,
    output_directory: str | Path,
    workers: int | None = None,
    progress=None,
    allow_sealed: bool = False,
    reuse_existing: bool = True,
) -> ExperimentResult:
    """Execute a manifest, storing every artifact it needs to be reproducible."""

    if manifest.supports_promotion and not allow_sealed:
        raise SealedBankError(
            "this manifest targets the promotion-sealed bank; pass allow_sealed "
            "explicitly and record the opening"
        )
    directory = Path(output_directory)
    (directory / "pairs").mkdir(parents=True, exist_ok=True)

    snapshot = build_snapshot()
    drift = verify_snapshot(snapshot)
    if drift:  # pragma: no cover - guarded by tests/match
        raise IntegrityConflictError(f"frozen Phase 4 agents drifted: {drift}")

    stored_pairs = load_pairs(directory, manifest) if reuse_existing else {}
    by_ordinal: dict[str, dict[int, PairRecord]] = {}
    for comparison in manifest.comparisons:
        records = stored_pairs.get(comparison.comparison_id, ())
        by_ordinal[comparison.comparison_id] = {
            ordinal: record for ordinal, record in enumerate(records)
        }

    checkpoint = _Checkpoint(directory=directory, manifest=manifest, known=by_ordinal)
    pairs = run_experiment(
        manifest,
        workers=workers,
        progress=progress,
        existing=by_ordinal,
        on_unit=checkpoint.record,
    )
    for comparison in manifest.comparisons:
        previous = stored_pairs.get(comparison.comparison_id)
        if previous:
            _require_same_semantics(
                previous, pairs[comparison.comparison_id], comparison.name
            )
        _write_pairs(directory, comparison, pairs[comparison.comparison_id])

    report = build_report(manifest, pairs, snapshot)
    atomic_write_canonical_json(directory / "manifest.json", manifest.to_data())
    atomic_write_canonical_json(directory / "frozen_agents.json", snapshot)
    atomic_write_canonical_json(directory / "inventory.json", _inventory(manifest, pairs))
    atomic_write_canonical_json(directory / "report.json", report)
    return ExperimentResult(manifest=manifest, pairs=pairs, report=report)


def _write_pairs(directory: Path, comparison, records: tuple[PairRecord, ...]) -> None:
    atomic_write_canonical_json(
        directory / "pairs" / _comparison_file(comparison.comparison_id),
        {
            "comparison_id": comparison.comparison_id,
            "comparison_name": comparison.name,
            "pairs": [item.to_data() for item in records],
            "schema_version": "tuppi.match.pair_collection.v1",
        },
    )


class _Checkpoint:
    """Persist completed pairs during a long run so progress survives a crash.

    Records are only ever written as a contiguous prefix of ordinals, because
    that is what :func:`load_pairs` can resume from. A unit finished out of
    order simply waits for its predecessors.
    """

    def __init__(self, *, directory: Path, manifest: MatchManifest, known) -> None:
        self._directory = directory
        self._manifest = manifest
        self._known = known
        self._by_id = {
            item.comparison_id: item for item in manifest.comparisons
        }

    def record(self, comparison_id: str, ordinal: int, value: PairRecord) -> None:
        bucket = self._known.setdefault(comparison_id, {})
        bucket[ordinal] = value
        prefix: list[PairRecord] = []
        index = 0
        while index in bucket:
            prefix.append(bucket[index])
            index += 1
        if prefix:
            _write_pairs(self._directory, self._by_id[comparison_id], tuple(prefix))


def _require_same_semantics(
    previous: tuple[PairRecord, ...], current: tuple[PairRecord, ...], name: str
) -> None:
    before = [item.pair_record_id for item in previous]
    after = [item.pair_record_id for item in current]
    if before[: len(after)] != after[: len(before)]:
        raise IntegrityConflictError(
            f"rerunning {name!r} produced a different semantic result; "
            "the manifest, the agents, or the stream generator changed"
        )


def _inventory(
    manifest: MatchManifest, pairs: dict[str, tuple[PairRecord, ...]]
) -> dict[str, object]:
    entries = []
    for comparison in manifest.comparisons:
        records = pairs.get(comparison.comparison_id, ())
        trusted = [
            item.pair_record_id for item in records if item.status is PairStatus.COMPLETE
        ]
        quarantined = [
            {
                "pair_record_id": item.pair_record_id,
                "reason": item.status.value,
                "stream_id": item.stream_id,
            }
            for item in records
            if item.status is not PairStatus.COMPLETE
        ]
        entries.append(
            {
                "comparison_id": comparison.comparison_id,
                "comparison_name": comparison.name,
                "quarantined": quarantined,
                "quarantined_count": len(quarantined),
                "trusted_count": len(trusted),
                "trusted_pair_record_ids": trusted,
            }
        )
    return {
        "comparisons": entries,
        "manifest_id": manifest.manifest_id,
        "schema_version": INVENTORY_SCHEMA_VERSION,
    }


def build_report(
    manifest: MatchManifest,
    pairs: dict[str, tuple[PairRecord, ...]],
    snapshot: dict[str, object],
) -> dict[str, object]:
    """Aggregate a complete-match experiment into its committed report."""

    comparisons = []
    for comparison in manifest.comparisons:
        records = pairs.get(comparison.comparison_id, ())
        inference = pair_inference(
            records,
            confidence_level=manifest.confidence_level,
            analysis_seed=manifest.analysis_seed,
            bootstrap_replicates=manifest.bootstrap_replicates,
            sign_flip_replicates=manifest.sign_flip_replicates,
        )
        comparisons.append(
            {
                "candidate_profile_key": comparison.candidate_profile_key,
                "comparison_id": comparison.comparison_id,
                "hypothesis": comparison.hypothesis,
                "name": comparison.name,
                "opponent_profile_key": comparison.opponent_profile_key,
                "primary_match_inference": inference,
                "result_class": comparison.result_class,
                "secondary_metrics": secondary_metrics(records),
                "starting_score": list(comparison.starting_score),
            }
        )
    report = {
        "bank": manifest.bank.to_data(),
        "bank_commitment": manifest.bank_commitment,
        "comparisons": comparisons,
        "frozen_agents_digest": snapshot["snapshot_digest"],
        "interpretation": {
            "bank_role": (
                f"This experiment ran on a {manifest.role.value} bank. "
                + (
                    "Sealed-bank results may support a promotion claim."
                    if manifest.supports_promotion
                    else "Its results cannot support a promotion claim."
                )
            ),
            "censoring_policy": (
                "A leg that reaches the infrastructure safety cap is "
                "censored_infrastructure. It is never a draw, never a policy "
                "win, and never a policy loss; its pair is excluded from the "
                "primary analysis entirely."
            ),
            "primary_endpoint": (
                "Candidate orientation-averaged match win probability, "
                "(1 + mean(D_match)) / 2, estimated over complete complementary "
                "pairs. The pair is the only independent unit."
            ),
            "secondary_status": (
                "Secondary metrics may explain a result but cannot override the "
                "primary match outcome."
            ),
        },
        "manifest_id": manifest.manifest_id,
        "match_protocol_version": manifest.identity_data()["match_protocol_version"],
        "pair_count_requested": manifest.pair_count,
        "safety_cap": manifest.safety_cap,
        "safety_cap_reason": manifest.safety_cap_reason,
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
    }
    report["report_digest"] = content_digest(report)
    return report


def load_report(path: str | Path) -> dict[str, object]:
    payload = strict_json_load_file(path)
    if type(payload) is not dict or payload.get("schema_version") != (
        EXPERIMENT_SCHEMA_VERSION
    ):
        raise ManifestError("not a complete-match experiment report")
    return payload
