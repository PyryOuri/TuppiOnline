from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_match import (
    DIAGNOSTIC_SCORES,
    MatchManifest,
    build_report,
    build_snapshot,
    load_report,
    run,
    score_state_comparisons,
    summarize_score_states,
)
from tuppi_match.diagnostics import validate_diagnostic_scores
from tuppi_match.errors import ManifestError, MatchValidationError
from tuppi_rules import MATCH_TARGET

from .conftest import bank, comparison, synthetic_pair


def diagnostic_comparisons():
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    return score_state_comparisons(
        candidate_profile_key="match_aware_v1",
        opponent_profile_key="match_aware_no_match_features_v1",
        candidate_agent_id=specifications["match_aware_v1"].agent_id,
        opponent_agent_id=specifications["match_aware_no_match_features_v1"].agent_id,
    )


# ----------------------------------------------------------- score-state set


def test_the_required_score_states_are_covered_in_both_orientations() -> None:
    assert validate_diagnostic_scores() == DIAGNOSTIC_SCORES
    assert (0, 0) in DIAGNOSTIC_SCORES
    for value in (16, 32, 44, 48):
        assert (value, 0) in DIAGNOSTIC_SCORES, value
        assert (0, value) in DIAGNOSTIC_SCORES, value
    for score in DIAGNOSTIC_SCORES:
        assert max(score) < MATCH_TARGET
        assert not (score[0] > 0 and score[1] > 0)


def test_every_diagnostic_score_yields_its_own_comparison() -> None:
    comparisons = diagnostic_comparisons()
    assert len(comparisons) == len(DIAGNOSTIC_SCORES)
    scores = {tuple(item.starting_score) for item in comparisons}
    assert scores == set(DIAGNOSTIC_SCORES)
    assert len({item.comparison_id for item in comparisons}) == len(comparisons)
    for item in comparisons:
        assert item.result_class == "ablation"
        assert item.name.startswith("diag_")
        assert "natural termination" in item.hypothesis


def test_the_starting_score_is_part_of_comparison_identity() -> None:
    table = comparison(starting_score=(0, 0))
    up = comparison(starting_score=(48, 0))
    down = comparison(starting_score=(0, 48))
    assert len({table.comparison_id, up.comparison_id, down.comparison_id}) == 3


# ------------------------------------------------------- diagnostics run small


def test_a_diagnostic_leg_runs_to_natural_termination_from_a_high_score(
    tmp_path: Path,
) -> None:
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    comparisons = score_state_comparisons(
        candidate_profile_key="match_aware_v1",
        opponent_profile_key="match_aware_no_match_features_v1",
        candidate_agent_id=specifications["match_aware_v1"].agent_id,
        opponent_agent_id=specifications["match_aware_no_match_features_v1"].agent_id,
        scores=((48, 0), (0, 48)),
    )
    manifest = MatchManifest.build(
        name="diagnostic-test",
        bank=bank(streams=2, seed="diagnostic-test-bank"),
        comparisons=comparisons,
        pair_count=2,
        engine_identity="tuppi_engine:v1",
        agents_version="0.4.0",
        bootstrap_replicates=100,
        sign_flip_replicates=100,
    )
    result = run(manifest, output_directory=tmp_path / "diag", workers=1)
    assert len(result.report["comparisons"]) == 2
    for entry in result.report["comparisons"]:
        inference = entry["primary_match_inference"]
        assert inference["complete_pair_count"] == 2
        assert inference["censored_pair_count"] == 0
        assert inference["candidate_match_win_probability"] is not None
    for records in result.pairs.values():
        for pair in records:
            for leg in (pair.leg_even, pair.leg_odd):
                assert max(leg.final_score) >= MATCH_TARGET


def test_the_score_state_summary_separates_itself_from_the_primary(
    tmp_path: Path,
) -> None:
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    comparisons = score_state_comparisons(
        candidate_profile_key="match_aware_v1",
        opponent_profile_key="match_aware_no_match_features_v1",
        candidate_agent_id=specifications["match_aware_v1"].agent_id,
        opponent_agent_id=specifications["match_aware_no_match_features_v1"].agent_id,
        scores=((48, 0),),
    )
    manifest = MatchManifest.build(
        name="diagnostic-summary",
        bank=bank(streams=2, seed="diagnostic-summary-bank"),
        comparisons=comparisons,
        pair_count=2,
        engine_identity="tuppi_engine:v1",
        agents_version="0.4.0",
        bootstrap_replicates=100,
        sign_flip_replicates=100,
    )
    result = run(manifest, output_directory=tmp_path / "diag", workers=1)
    summary = summarize_score_states(result.report)
    assert summary["score_states"]
    assert "never replace the 0-0 primary endpoint" in summary["note"]
    row = summary["score_states"][0]
    assert row["starting_score"] == [48, 0]
    assert row["complete_pair_count"] == 2
    assert "immediate_completion_rate" in row


# ------------------------------------------------------------------ reporting


def test_a_report_labels_its_bank_role_and_promotion_status() -> None:
    manifest = MatchManifest.build(
        name="report-test",
        bank=bank(streams=2),
        comparisons=(comparison(),),
        pair_count=1,
        engine_identity="tuppi_engine:v1",
        agents_version="0.4.0",
    )
    pairs = {manifest.comparisons[0].comparison_id: (synthetic_pair(even_winner=0, odd_winner=1),)}
    report = build_report(manifest, pairs, build_snapshot())
    assert report["interpretation"]["bank_role"].startswith(
        "This experiment ran on a development bank"
    )
    assert "cannot support a promotion claim" in report["interpretation"]["bank_role"]
    assert "never a draw" in report["interpretation"]["censoring_policy"]
    assert "cannot override" in report["interpretation"]["secondary_status"]
    assert "(1 + mean(D_match)) / 2" in report["interpretation"]["primary_endpoint"]
    assert report["safety_cap"] == manifest.safety_cap
    assert report["report_digest"].startswith("sha256:")


def test_a_sealed_bank_report_says_so() -> None:
    from tuppi_match import BankRole

    manifest = MatchManifest.build(
        name="sealed-report",
        bank=bank(role=BankRole.PROMOTION_SEALED, streams=2, name="sealed"),
        comparisons=(comparison(),),
        pair_count=1,
        engine_identity="tuppi_engine:v1",
        agents_version="0.4.0",
    )
    pairs = {manifest.comparisons[0].comparison_id: (synthetic_pair(even_winner=0, odd_winner=1),)}
    report = build_report(manifest, pairs, build_snapshot())
    assert "may support a promotion claim" in report["interpretation"]["bank_role"]


def test_the_report_digest_is_stable_and_content_bound() -> None:
    manifest = MatchManifest.build(
        name="digest-test",
        bank=bank(streams=2),
        comparisons=(comparison(),),
        pair_count=1,
        engine_identity="tuppi_engine:v1",
        agents_version="0.4.0",
    )
    key = manifest.comparisons[0].comparison_id
    snapshot = build_snapshot()
    first = build_report(manifest, {key: (synthetic_pair(even_winner=0, odd_winner=1),)}, snapshot)
    second = build_report(manifest, {key: (synthetic_pair(even_winner=0, odd_winner=1),)}, snapshot)
    third = build_report(manifest, {key: (synthetic_pair(even_winner=1, odd_winner=0),)}, snapshot)
    assert first["report_digest"] == second["report_digest"]
    assert first["report_digest"] != third["report_digest"]


def test_loading_a_foreign_document_as_a_report_fails(tmp_path: Path) -> None:
    from tuppi_engine import atomic_write_canonical_json

    path = tmp_path / "not-a-report.json"
    atomic_write_canonical_json(path, {"schema_version": "something.else"})
    with pytest.raises(ManifestError):
        load_report(path)


def test_diagnostic_scores_reject_a_terminal_or_impossible_state() -> None:
    import tuppi_match.diagnostics as module

    original = module.DIAGNOSTIC_SCORES
    try:
        module.DIAGNOSTIC_SCORES = ((52, 0),)
        with pytest.raises(MatchValidationError, match="nonterminal"):
            module.validate_diagnostic_scores()
        module.DIAGNOSTIC_SCORES = ((10, 10),)
        with pytest.raises(MatchValidationError, match="only one partnership"):
            module.validate_diagnostic_scores()
    finally:
        module.DIAGNOSTIC_SCORES = original
