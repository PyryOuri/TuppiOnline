from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_match import (
    DEFAULT_SAFETY_CAP,
    BankRole,
    MatchManifest,
    StreamBank,
    calibrate_safety_cap,
    calibration_bank,
    development_bank,
    open_sealed_bank,
    require_not_sealed,
    require_role,
    sealed_commitment,
    write_sealed_seed,
)
from tuppi_match.errors import BankRoleError, ManifestError, SealedBankError

from .conftest import bank, comparison


# ----------------------------------------------------------------- bank roles


def test_only_the_sealed_role_supports_promotion() -> None:
    assert development_bank(stream_count=4).supports_promotion is False
    assert calibration_bank(stream_count=4).supports_promotion is False
    sealed = bank(role=BankRole.PROMOTION_SEALED, name="sealed")
    assert sealed.supports_promotion is True


def test_role_enforcement_is_not_merely_documentation() -> None:
    development = development_bank(stream_count=4)
    assert require_role(development, BankRole.DEVELOPMENT) is development
    with pytest.raises(BankRoleError, match="not 'calibration'"):
        require_role(development, BankRole.CALIBRATION)
    sealed = bank(role=BankRole.PROMOTION_SEALED, name="sealed")
    with pytest.raises(SealedBankError, match="not permitted"):
        require_not_sealed(sealed, action="debugging")
    assert require_not_sealed(development, action="debugging") is development


def test_bank_identity_is_semantic_and_streams_are_addressable() -> None:
    left = bank(streams=6)
    right = bank(streams=6)
    assert left.bank_id == right.bank_id
    assert bank(streams=7).bank_id != left.bank_id
    assert bank(seed="other").bank_id != left.bank_id
    assert left.stream(0).stream_id != left.stream(1).stream_id
    assert len(left.streams()) == 6
    with pytest.raises(BankRoleError):
        left.stream(6)
    with pytest.raises(BankRoleError):
        left.stream(-1)


def test_a_bank_commitment_is_stable_and_detects_a_changed_bank() -> None:
    left = bank(streams=4)
    assert left.commitment(streams=2) == bank(streams=4).commitment(streams=2)
    assert left.commitment(streams=2) != left.commitment(streams=3)
    assert left.commitment(streams=2) != bank(streams=4, seed="x").commitment(streams=2)


# --------------------------------------------------------------- sealed banks


def test_sealed_seed_material_may_not_live_inside_the_repository() -> None:
    repository = Path(__file__).resolve().parents[2]
    with pytest.raises(SealedBankError, match="must not be written inside"):
        write_sealed_seed(repository / "sealed_seed.json", seed="x" * 32)
    assert not (repository / "sealed_seed.json").exists()


def test_the_repository_guard_does_not_depend_on_where_the_module_lives(
    tmp_path: Path,
) -> None:
    """Regression: the guard once inferred the repository from its own path.

    That works from a source checkout and silently stops working once the
    package is installed to site-packages - exactly when a stray seed file
    would be easiest to commit by accident. The guard must key off the *target*
    path instead.
    """

    from tuppi_match.banks import _inside_repository

    worktree = tmp_path / "some_other_repo"
    (worktree / ".git").mkdir(parents=True)
    (worktree / "nested" / "deeper").mkdir(parents=True)
    assert _inside_repository(worktree / "seed.json") is True
    assert _inside_repository(worktree / "nested" / "deeper" / "seed.json") is True

    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    assert _inside_repository(outside / "seed.json") is False

    with pytest.raises(SealedBankError, match="must not be written inside"):
        write_sealed_seed(worktree / "nested" / "seed.json", seed="y" * 32)
    assert not (worktree / "nested" / "seed.json").exists()
    written = write_sealed_seed(outside / "seed.json", seed="y" * 32)
    assert Path(written["path"]).exists()


def test_opening_refuses_seed_material_inside_a_repository(tmp_path: Path) -> None:
    worktree = tmp_path / "repo"
    (worktree / ".git").mkdir(parents=True)
    planted = worktree / "seed.json"
    planted.write_text('{"seed": "planted-seed-value-here"}', encoding="utf-8")
    with pytest.raises(SealedBankError, match="must live outside the repository"):
        open_sealed_bank(
            name="sealed_test",
            stream_count=2,
            initial_dealer=0,
            purpose="Sealed test bank.",
            reason="Attempting to open from inside a working tree.",
            seed_path=planted,
        )


def test_a_sealed_commitment_carries_no_seed(tmp_path: Path) -> None:
    sealed = StreamBank.build(
        name="sealed_test",
        role=BankRole.PROMOTION_SEALED,
        root_seed="a-secret-seed-value-32-characters",
        initial_dealer=0,
        stream_count=8,
        purpose="Sealed test bank.",
    )
    commitment = sealed_commitment(sealed, streams=2)
    text = repr(commitment)
    assert "a-secret-seed-value" not in text
    assert commitment["bank_commitment"].startswith("sha256:")
    assert commitment["role"] == "promotion_sealed"
    assert "explicit recorded act" in commitment["usage_rule"]
    with pytest.raises(BankRoleError):
        sealed_commitment(development_bank(stream_count=2))


def test_opening_a_sealed_bank_requires_a_reason_and_produces_a_record(
    tmp_path: Path,
) -> None:
    seed_file = tmp_path / "outside" / "seed.json"
    written = write_sealed_seed(seed_file, seed="sealed-seed-for-the-test-suite")
    assert written["seed_digest"].startswith("sha256:")

    with pytest.raises(SealedBankError, match="explicit reason"):
        open_sealed_bank(
            name="sealed_test",
            stream_count=4,
            initial_dealer=0,
            purpose="Sealed test bank.",
            reason="x",
            seed_path=seed_file,
        )
    opened, record = open_sealed_bank(
        name="sealed_test",
        stream_count=4,
        initial_dealer=0,
        purpose="Sealed test bank.",
        reason="Phase 5A acceptance test of the sealed opening path.",
        seed_path=seed_file,
    )
    assert opened.role is BankRole.PROMOTION_SEALED
    assert record["reason"].startswith("Phase 5A")
    assert record["seed_digest"] == written["seed_digest"]
    assert "seed" not in record
    assert record["bank_commitment"] == opened.commitment()


def test_opening_without_seed_material_fails_loudly(monkeypatch) -> None:
    monkeypatch.delenv("TUPPI_SEALED_SEED_FILE", raising=False)
    with pytest.raises(SealedBankError, match="no sealed seed available"):
        open_sealed_bank(
            name="sealed_test",
            stream_count=4,
            initial_dealer=0,
            purpose="Sealed test bank.",
            reason="An attempt with no seed material at all.",
        )


# ------------------------------------------------------------------ manifests


def _manifest(**overrides) -> MatchManifest:
    values = {
        "name": "test",
        "bank": bank(streams=4),
        "comparisons": (comparison(),),
        "pair_count": 2,
        "engine_identity": "tuppi_engine:v1",
        "agents_version": "0.4.0",
    }
    values.update(overrides)
    return MatchManifest.build(**values)


def test_a_manifest_records_the_safety_cap_and_its_reason() -> None:
    manifest = _manifest()
    assert manifest.safety_cap == DEFAULT_SAFETY_CAP
    assert len(manifest.safety_cap_reason) >= 20
    data = manifest.to_data()
    assert data["safety_cap"] == DEFAULT_SAFETY_CAP
    assert "censoring is exceptional" in data["safety_cap_reason"]
    assert data["bank_role"] == "development"
    assert data["supports_promotion"] is False


def test_a_manifest_rejects_a_reasonless_cap_and_an_oversized_request() -> None:
    with pytest.raises(ManifestError, match="explicit reason"):
        _manifest(safety_cap_reason="short")
    with pytest.raises(ManifestError, match="requests"):
        _manifest(pair_count=99)
    with pytest.raises(ManifestError, match="positive integer"):
        _manifest(safety_cap=0)


def test_comparison_identity_excludes_the_pair_count_so_banks_stay_extensible() -> None:
    small = _manifest(pair_count=2)
    large = _manifest(pair_count=4)
    assert small.comparisons[0].comparison_id == large.comparisons[0].comparison_id
    assert small.manifest_id != large.manifest_id


def test_a_comparison_refuses_a_self_match_and_a_terminal_score() -> None:
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    with pytest.raises(ManifestError, match="two distinct agents"):
        comparison(candidate="match_aware_v1", opponent="match_aware_v1")
    with pytest.raises(ManifestError, match="terminal score"):
        comparison(starting_score=(52, 0))
    assert specifications["match_aware_v1"].agent_id.startswith("agent:sha256:")


def test_manifest_identity_ignores_everything_operational() -> None:
    left = _manifest()
    right = _manifest()
    assert left.manifest_id == right.manifest_id
    assert set(left.identity_data()).isdisjoint(
        {"output_directory", "workers", "timestamp", "hostname"}
    )
    different = _manifest(safety_cap=256)
    assert different.manifest_id != left.manifest_id


# ------------------------------------------------------- safety-cap calibration


def test_the_safety_cap_is_calibrated_from_observed_lengths() -> None:
    result = calibrate_safety_cap([5, 12, 30, 61, 125])
    assert result["longest_observed"] == 125
    assert result["proposed_safety_cap"] >= 125 * 3
    assert result["proposed_safety_cap"] % 64 == 0
    assert result["observed_over_proposed_cap"] == 0
    assert "median" in result["rationale"]
    assert result["distribution"]["maximum"] == 125


def test_the_calibrated_cap_never_sits_near_the_median() -> None:
    """The Phase 4 failure was a cap at the median; that must be impossible."""

    lengths = [5, 12, 30, 61, 125]
    result = calibrate_safety_cap(lengths)
    assert result["proposed_safety_cap"] > result["distribution"]["median"] * 10
    assert result["proposed_safety_cap"] >= 256


def test_calibration_requires_data() -> None:
    from tuppi_match.errors import MatchValidationError

    with pytest.raises(MatchValidationError):
        calibrate_safety_cap([])
    with pytest.raises(MatchValidationError):
        calibrate_safety_cap([10], headroom=0.5)
