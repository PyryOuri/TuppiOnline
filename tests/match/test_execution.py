from __future__ import annotations

import os
from pathlib import Path

import pytest

from tuppi_match import (
    MatchManifest,
    PairStatus,
    default_worker_count,
    run,
    run_experiment,
    work_units,
)
from tuppi_match.errors import IntegrityConflictError, SealedBankError
from tuppi_match.executor import parallel_available

from .conftest import bank, comparison


def small_manifest(*, pairs: int = 2, comparisons: int = 1, **overrides) -> MatchManifest:
    built = (
        comparison(candidate="reactive_contract_v1", opponent="legacy_heuristic_port_v1"),
        comparison(candidate="public_counting_v1", opponent="reactive_contract_v1"),
    )[:comparisons]
    values = {
        "name": "execution-test",
        "bank": bank(streams=max(pairs, 2), seed="execution-test-bank"),
        "comparisons": built,
        "pair_count": pairs,
        "engine_identity": "tuppi_engine:v1",
        "agents_version": "0.4.0",
        "bootstrap_replicates": 100,
        "sign_flip_replicates": 100,
    }
    values.update(overrides)
    return MatchManifest.build(**values)


def test_work_units_cover_every_comparison_and_ordinal() -> None:
    manifest = small_manifest(pairs=3, comparisons=2)
    units = work_units(manifest)
    assert len(units) == 6
    assert {(item.comparison_index, item.pair_ordinal) for item in units} == {
        (index, ordinal) for index in range(2) for ordinal in range(3)
    }


def test_the_worker_count_cannot_change_any_result() -> None:
    """Determinism under parallelism is a protocol requirement, not a hope."""

    manifest = small_manifest(pairs=2)
    serial = run_experiment(manifest, workers=1)
    parallel = run_experiment(manifest, workers=4)
    for key, records in serial.items():
        assert [item.pair_record_id for item in records] == [
            item.pair_record_id for item in parallel[key]
        ]
        assert [item.d_match for item in records] == [
            item.d_match for item in parallel[key]
        ]
        assert [item.semantic_data() for item in records] == [
            item.semantic_data() for item in parallel[key]
        ]


def test_results_are_returned_in_canonical_ordinal_order() -> None:
    manifest = small_manifest(pairs=3)
    for workers in (1, 3):
        records = run_experiment(manifest, workers=workers)
        for values in records.values():
            expected = [
                manifest.bank.stream(ordinal).stream_id
                for ordinal in range(manifest.pair_count)
            ]
            assert [item.stream_id for item in values] == expected


def test_default_worker_count_leaves_two_cores_of_headroom(monkeypatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert default_worker_count() == 14


def test_a_resumed_run_matches_a_run_that_never_stopped() -> None:
    manifest = small_manifest(pairs=2)
    complete = run_experiment(manifest, workers=1)
    key = manifest.comparisons[0].comparison_id
    partial = {key: {0: complete[key][0]}}
    resumed = run_experiment(manifest, workers=1, existing=partial)
    assert [item.pair_record_id for item in resumed[key]] == [
        item.pair_record_id for item in complete[key]
    ]


def test_the_output_path_cannot_change_a_result(tmp_path: Path) -> None:
    manifest = small_manifest(pairs=2)
    left = run(manifest, output_directory=tmp_path / "left", workers=1)
    right = run(manifest, output_directory=tmp_path / "a" / "deeper" / "right", workers=1)
    assert left.report["report_digest"] == right.report["report_digest"]
    assert left.manifest.manifest_id == right.manifest.manifest_id


def test_a_rerun_reproduces_the_same_semantic_result(tmp_path: Path) -> None:
    manifest = small_manifest(pairs=2)
    first = run(manifest, output_directory=tmp_path / "run", workers=1)
    second = run(manifest, output_directory=tmp_path / "run", workers=1)
    assert first.report["report_digest"] == second.report["report_digest"]
    for key, records in first.pairs.items():
        assert [item.pair_record_id for item in records] == [
            item.pair_record_id for item in second.pairs[key]
        ]


def test_a_tampered_stored_pair_raises_an_integrity_conflict(tmp_path: Path) -> None:
    from tuppi_engine import atomic_write_canonical_json, strict_json_load_file

    manifest = small_manifest(pairs=2)
    run(manifest, output_directory=tmp_path / "run", workers=1)
    stored = sorted((tmp_path / "run" / "pairs").glob("*.json"))[0]
    payload = strict_json_load_file(stored)
    payload["pairs"][0]["leg_even"]["resets"] += 1
    atomic_write_canonical_json(stored, payload)
    with pytest.raises(Exception):
        run(manifest, output_directory=tmp_path / "run", workers=1)


def test_an_experiment_stores_everything_needed_to_reproduce_it(
    tmp_path: Path,
) -> None:
    manifest = small_manifest(pairs=2)
    result = run(manifest, output_directory=tmp_path / "run", workers=1)
    directory = tmp_path / "run"
    for name in ("manifest.json", "frozen_agents.json", "inventory.json", "report.json"):
        assert (directory / name).exists(), name
    assert sorted((directory / "pairs").glob("*.json"))

    from tuppi_engine import strict_json_load_file

    inventory = strict_json_load_file(directory / "inventory.json")
    entry = inventory["comparisons"][0]
    assert entry["trusted_count"] + entry["quarantined_count"] == manifest.pair_count
    stored_manifest = strict_json_load_file(directory / "manifest.json")
    assert stored_manifest["manifest_id"] == manifest.manifest_id
    assert stored_manifest["bank_commitment"] == manifest.bank_commitment
    report = strict_json_load_file(directory / "report.json")
    assert report["report_digest"] == result.report["report_digest"]
    assert report["safety_cap"] == manifest.safety_cap


def test_a_sealed_manifest_refuses_to_run_without_an_explicit_opening(
    tmp_path: Path,
) -> None:
    from tuppi_match import BankRole

    sealed = small_manifest(
        pairs=2, bank=bank(role=BankRole.PROMOTION_SEALED, streams=2, name="sealed")
    )
    assert sealed.supports_promotion is True
    with pytest.raises(SealedBankError, match="allow_sealed"):
        run(sealed, output_directory=tmp_path / "sealed", workers=1)


def test_the_report_separates_trusted_and_quarantined_work(tmp_path: Path) -> None:
    manifest = small_manifest(pairs=2, safety_cap=1)
    result = run(manifest, output_directory=tmp_path / "run", workers=1)
    comparison_report = result.report["comparisons"][0]
    inference = comparison_report["primary_match_inference"]
    records = result.pairs[manifest.comparisons[0].comparison_id]
    censored = sum(
        1 for item in records if item.status is PairStatus.INCOMPLETE_CENSORED
    )
    assert inference["censored_pair_count"] == censored
    assert inference["complete_pair_count"] + censored == len(records)
    assert "never a draw" in result.report["interpretation"]["censoring_policy"]


def test_the_default_worker_count_leaves_headroom() -> None:
    import os

    assert 1 <= default_worker_count() <= max(1, (os.cpu_count() or 1))
    assert isinstance(parallel_available(), bool)
