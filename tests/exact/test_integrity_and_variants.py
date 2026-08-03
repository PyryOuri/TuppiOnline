"""The frozen-baseline gate, and the Phase 5B diagnostic identities.

The point of these tests is that Phase 5B adds a solver and a sampler to the
repository without letting either reach a frozen Phase 4 agent. That containment
is checked mechanically, not asserted in prose.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_agents import registered_profiles
from tuppi_exact.errors import DiagnosisError, IntegrityError
from tuppi_exact.integrity import (
    BASELINE_SCHEMA_VERSION,
    DISCLAIMED_CAPABILITY_FIELDS,
    EARLIER_PACKAGES,
    FROZEN_ARTIFACT_PATHS,
    archive_manifest_agreement,
    build_baseline,
    capability_containment,
    file_digest,
    integrity_report,
    repository_root,
    sealed_bank_containment,
    verify_baseline,
    working_tree_location,
)
from tuppi_exact.variants import (
    BASE_PROFILE_KEY,
    MATCH_PLAY_RULES,
    MATCH_RULES,
    MATCH_SHOW_RULES,
    all_match_rules_off_variant,
    base_profile,
    composition_check,
    diagnostic_variants,
    protect_distance_variants,
    single_rule_off_variants,
    variants_by_label,
)


# ------------------------------------------------------------------- integrity


def test_repository_root_is_located_and_validated():
    root = repository_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "manifests" / "legacy_v9.json").is_file()
    with pytest.raises(IntegrityError):
        repository_root(Path("/"))


def test_archive_hashes_still_match_their_own_manifest():
    assert archive_manifest_agreement(repository_root()) == []


def test_every_frozen_artifact_exists_and_digests():
    root = repository_root()
    for relative in FROZEN_ARTIFACT_PATHS:
        digest = file_digest(root / relative)
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64


def test_capability_containment_holds():
    """No frozen agent may claim a solver, a sampler, or a belief model."""

    assert capability_containment(repository_root()) == []


def test_no_earlier_package_references_the_exact_layer():
    root = repository_root()
    for package in EARLIER_PACKAGES:
        for module in sorted((root / "src" / package).glob("*.py")):
            assert "tuppi_exact" not in module.read_text(encoding="utf-8"), module


def test_the_frozen_agents_still_disclaim_every_phase5b_capability():
    from tuppi_match.freeze import build_snapshot

    for agent in build_snapshot()["agents"]:
        for field_name in DISCLAIMED_CAPABILITY_FIELDS:
            assert agent[field_name] is None, (agent["profile_key"], field_name)


def test_the_sealed_bank_is_still_sealed():
    assert sealed_bank_containment(repository_root()) == []


def test_a_baseline_verifies_against_itself():
    baseline = build_baseline()
    assert baseline["schema_version"] == BASELINE_SCHEMA_VERSION
    assert baseline["baseline_digest"].startswith("sha256:")
    assert verify_baseline(baseline) == []


def test_baseline_drift_is_detected():
    baseline = build_baseline()
    tampered = dict(baseline)
    tampered["ruleset_config_digest"] = "sha256:" + "0" * 64
    problems = verify_baseline(tampered)
    assert any("ruleset_config_digest" in item for item in problems)

    tampered = dict(baseline)
    tampered["phase4_behaviour_digests"] = [
        {"behaviour_digest": "sha256:" + "1" * 64, "profile_key": BASE_PROFILE_KEY}
    ]
    problems = verify_baseline(tampered)
    assert any(BASE_PROFILE_KEY in item for item in problems)

    tampered = dict(baseline)
    tampered["artifact_digests"] = [
        {"digest": "sha256:" + "2" * 64, "path": "Archive/tuppi_emulator_v9.py"}
    ]
    problems = verify_baseline(tampered)
    assert any("tuppi_emulator_v9" in item for item in problems)


def test_verify_baseline_rejects_an_unsupported_schema():
    with pytest.raises(IntegrityError):
        verify_baseline({"schema_version": "something.else"})
    with pytest.raises(IntegrityError):
        verify_baseline([])  # type: ignore[arg-type]


def test_integrity_report_holds_and_describes_the_working_tree():
    report = integrity_report()
    assert report["holds"] is True
    assert report["archive_manifest_problems"] == []
    assert report["capability_containment_problems"] == []
    assert report["sealed_bank_problems"] == []
    tree = report["working_tree"]
    assert isinstance(tree["is_probably_cloud_synced"], bool)
    assert tree["repository_root"] == repository_root().as_posix()


def test_working_tree_location_flags_a_cloud_synced_path():
    assert working_tree_location()["schema_version"] == (
        "tuppi.exact.working_tree_location.v1"
    )


# -------------------------------------------------------------------- variants


def test_the_rule_sets_are_the_four_match_rules():
    assert len(MATCH_RULES) == 4
    assert set(MATCH_RULES) == set(MATCH_SHOW_RULES) | set(MATCH_PLAY_RULES)
    profile = base_profile()
    for rule_id in MATCH_RULES:
        assert profile.rule_enabled(rule_id)


def test_every_variant_has_a_distinct_new_identity():
    variants = diagnostic_variants()
    assert len(variants) >= 8
    identities = {item.specification.agent_id for item in variants}
    assert len(identities) == len(variants)
    frozen_ids = {
        item.profile_id for item in registered_profiles().values()
    }
    for item in variants:
        assert item.profile.profile_id not in frozen_ids
    assert set(variants_by_label()) == {item.label for item in variants}


def test_single_rule_variants_disable_exactly_one_rule():
    for item in single_rule_off_variants():
        assert item.change_kind == "rule_disabled"
        assert item.changed_rule_id in MATCH_RULES
        assert set(item.profile.disabled_rule_ids) == {item.changed_rule_id}
        assert item.profile.match_state_enabled is True


def test_protect_distance_variants_move_only_that_parameter():
    base = base_profile()
    for item in protect_distance_variants():
        assert item.change_kind == "parameter_changed"
        assert item.profile.disabled_rule_ids == base.disabled_rule_ids
        changed = dict(item.changed_parameters)
        assert set(changed) == {"match_protect_distance"}
        assert changed["match_protect_distance"] != base.parameter(
            "match_protect_distance"
        )
        others = {
            key: value
            for key, value in item.profile.parameters.items()
            if key != "match_protect_distance"
        }
        assert others == {
            key: value
            for key, value in base.parameters.items()
            if key != "match_protect_distance"
        }


def test_protect_distance_respects_the_profile_validator():
    """The sweep may not exceed the pressure distance; the profile rejects that."""

    with pytest.raises(DiagnosisError):
        protect_distance_variants(distances=(40,))


def test_composing_all_four_rules_off_reproduces_the_frozen_ablation():
    """Validates the variant machinery against a frozen Phase 4 behaviour digest."""

    check = composition_check()
    assert check["behaviour_matches_frozen_ablation"] is True
    assert check["enabled_rules_match"] is True
    assert check["differs_from_base"] is True
    assert check["identity_differs_by_design"] is True
    assert (
        check["composed_behaviour_digest"]
        == check["frozen_ablation_behaviour_digest"]
    )


def test_the_frozen_ablation_digest_matches_the_committed_report():
    """The composed digest must equal the value committed in Phase 5A."""

    from tuppi_engine import strict_json_load_file

    recorded = strict_json_load_file(
        str(
            repository_root()
            / "reports"
            / "phase5a"
            / "phase4_frozen_agents.json"
        )
    )
    by_key = {item["profile_key"]: item for item in recorded["agents"]}
    check = composition_check()
    assert (
        check["composed_behaviour_digest"]
        == by_key["match_aware_no_match_features_v1"]["behaviour_digest"]
    )
    assert check["base_behaviour_digest"] == by_key[BASE_PROFILE_KEY][
        "behaviour_digest"
    ]


def test_a_variant_identical_to_the_base_is_rejected():
    from tuppi_exact.variants import DiagnosticVariant
    from tuppi_agents import specification_for_profile

    profile = base_profile()
    with pytest.raises(DiagnosisError):
        DiagnosticVariant(
            label="identical",
            profile=profile,
            specification=specification_for_profile(profile),
            change_kind="rule_disabled",
            changed_rule_id=None,
            changed_parameters=(),
            rationale="no change at all",
        )


def test_variant_data_is_canonical():
    for item in diagnostic_variants():
        data = item.to_data()
        assert data["agent_id"].startswith("agent:sha256:")
        assert data["profile_id"].startswith("profile:sha256:")
        assert data["schema_version"] == "tuppi.exact.diagnostic_variant.v1"
        assert data["rationale"]


def test_the_all_off_variant_is_not_part_of_the_default_sweep():
    """It is a machinery check, not one of the per-rule measurements."""

    labels = {item.label for item in diagnostic_variants()}
    assert all_match_rules_off_variant().label not in labels
