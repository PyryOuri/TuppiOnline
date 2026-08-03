"""The match-aware rule diagnosis: its instruments, and their honesty conditions."""

from __future__ import annotations

import pytest

from tuppi_exact.diagnosis import (
    CENSUS_ROOT_SEED,
    CENSUS_SCORE_STATES,
    DIAGNOSIS_SCHEMA_VERSION,
    ExactVerdict,
    _classify,
    _classify_utility,
    _match_role,
    ablation_bank,
    census_bank,
    diagnose,
    rule_activation_census,
    rule_ablation_comparisons,
    run_rule_ablation,
    show_rule_census,
    summarize_census,
)
from tuppi_exact.errors import DiagnosisError
from tuppi_exact.variants import MATCH_PLAY_RULES, MATCH_RULES, MATCH_SHOW_RULES
from tuppi_match.calibration import (
    CALIBRATION_ROOT_SEED,
    DEVELOPMENT_ROOT_SEED,
    DIAGNOSTIC_ROOT_SEED,
)


#: A reduced score-state grid for the tests that do not need the whole grid.
#: Every state here has a rising score, which is where the match rules can fire.
SMALL_STATES = ((48, 0), (0, 48), (16, 0))


def test_phase5b_banks_do_not_reuse_a_phase5a_seed():
    """A bank that was inspected while interpreting the null cannot be reused."""

    phase5a = {CALIBRATION_ROOT_SEED, DEVELOPMENT_ROOT_SEED, DIAGNOSTIC_ROOT_SEED}
    census = census_bank(stream_count=4)
    ablation = ablation_bank(stream_count=4)
    assert census.root_seed not in phase5a
    assert ablation.root_seed not in phase5a
    assert census.root_seed != ablation.root_seed
    assert census.bank_id != ablation.bank_id
    assert CENSUS_ROOT_SEED == census.root_seed


def test_the_banks_are_development_and_never_sealed():
    for bank in (census_bank(stream_count=4), ablation_bank(stream_count=4)):
        assert bank.role.value == "development"
        assert bank.supports_promotion is False


def test_match_role_is_derived_from_the_score_and_seat():
    assert _match_role((0, 0), 0) == "table"
    assert _match_role((48, 0), 0) == "up"
    assert _match_role((48, 0), 1) == "down"
    assert _match_role((0, 48), 3) == "up"
    assert _match_role((0, 48), 2) == "down"


def test_classification_helpers_agree_with_their_documented_direction():
    assert _classify(0, 0) == "neutral"
    assert _classify(0, 4) == "rule_helps"
    assert _classify(4, 0) == "rule_hurts"
    assert _classify_utility((1, 0), (1, 0)) == "neutral"
    assert _classify_utility((1, 0), (0, 8)) == "rule_helps"
    assert _classify_utility((0, 8), (1, 0)) == "rule_hurts"


def test_the_census_covers_every_score_state_and_both_phases():
    result = rule_activation_census(deals=1, samples_per_decision=1)
    assert result.deals_played == len(CENSUS_SCORE_STATES)
    assert result.decisions_by_phase["SHOWING"] > 0
    assert result.decisions_by_phase["TRICK_PLAY"] > 0
    summary = summarize_census(result)
    assert summary["schema_version"] == DIAGNOSIS_SCHEMA_VERSION
    assert set(summary["per_rule"]) == set(MATCH_RULES)
    for rule_id in MATCH_SHOW_RULES:
        assert summary["per_rule"][rule_id]["phase"] == "SHOWING"
    for rule_id in MATCH_PLAY_RULES:
        assert summary["per_rule"][rule_id]["phase"] == "TRICK_PLAY"
    assert "trajectory_caveat" in summary


def test_the_precondition_census_separates_inert_from_redundant():
    """A decision-change count of zero has two very different explanations."""

    from tuppi_exact.diagnosis import _rule_status

    assert _rule_status(0, 0) == "inert"
    assert _rule_status(7, 0) == "redundant"
    assert _rule_status(7, 3) == "active"
    assert _rule_status(0, 3) == "active"
    assert _rule_status(None, 0) == "not_measured"

    result = rule_activation_census(
        deals=2, samples_per_decision=0, score_states=SMALL_STATES
    )
    assert set(result.precondition_holds) == set(MATCH_PLAY_RULES)
    summary = summarize_census(result)
    for rule_id in MATCH_PLAY_RULES:
        entry = summary["per_rule"][rule_id]
        assert entry["precondition_held"] == result.precondition_holds[rule_id]
        assert entry["status"] in ("inert", "redundant", "active")
    for rule_id in MATCH_SHOW_RULES:
        assert summary["per_rule"][rule_id]["status"] == "not_measured"


def test_play_rule_preconditions_are_evaluated_rule_free():
    """The precondition must be read from the features, not from the rule switch."""

    from tuppi_agents import build_features
    from tuppi_engine import EnginePhase
    from tuppi_exact.diagnosis import play_rule_preconditions

    from .conftest import walk_deal

    seen = set()
    for position in walk_deal(profile_key="match_aware_v1", score=(48, 0)):
        if position.observation.phase is not EnginePhase.TRICK_PLAY:
            continue
        features = build_features(position.observation, include_inference=True)
        holds = play_rule_preconditions(features)
        assert set(holds) == set(MATCH_PLAY_RULES)
        assert all(isinstance(value, bool) for value in holds.values())
        seen |= {rule for rule, value in holds.items() if value}
    assert seen, "no play-rule precondition ever held on this deal"


def test_a_show_rule_never_produces_a_play_verdict():
    result = rule_activation_census(
        deals=2, samples_per_decision=0, score_states=SMALL_STATES
    )
    for verdict in result.exact_verdicts:
        assert verdict.rule_id in MATCH_PLAY_RULES
    for divergence in result.divergences:
        if divergence.rule_id in MATCH_SHOW_RULES:
            assert divergence.phase == "SHOWING"


def test_coasting_is_exactly_match_neutral_wherever_it_fires():
    """The rule's own precondition says the remaining margin is worthless.

    If that is true, then under perfect information every legal card reaches the
    same match state, so the exact verdict must be neutral. A non-neutral verdict
    would mean either the precondition or the utility model is wrong.
    """

    result = rule_activation_census(
        deals=6, samples_per_decision=0, score_states=SMALL_STATES
    )
    coasting = [
        item
        for item in result.exact_verdicts
        if item.rule_id == "match.play.coast_when_margin_worthless.v1"
    ]
    assert coasting, "the census produced no coasting verdicts to check"
    assert all(item.verdict == "neutral" for item in coasting)
    assert any(
        item.deal_point_verdict != "neutral" for item in coasting
    ), "coasting is expected to spend deal points while costing no match value"


def test_exact_verdicts_are_recorded_in_both_currencies():
    result = rule_activation_census(
        deals=3, samples_per_decision=0, score_states=SMALL_STATES
    )
    assert result.exact_verdicts
    for verdict in result.exact_verdicts:
        data = verdict.to_data()
        assert data["verdict"] in ("neutral", "rule_helps", "rule_hurts")
        assert data["deal_point_verdict"] in ("neutral", "rule_helps", "rule_hurts")
        assert len(data["base_match_utility"]) == 2
        assert data["base_regret_points"] >= 0
        assert data["variant_regret_points"] >= 0


def test_sampled_verdicts_state_the_measure_and_its_caveat():
    result = rule_activation_census(
        deals=3, samples_per_decision=4, score_states=SMALL_STATES
    )
    informative = [
        item for item in result.sampled_verdicts if item.get("samples_solved")
    ]
    assert informative
    for item in informative:
        assert item["measure"] == "uniform_over_feasible_assignments"
        assert "not a posterior" in item["measure_caveat"]
        assert item["feasible_assignment_count"] >= 1
        # The verdict must be decided in match utility per world, never by the
        # deal-point tie-break: a rule that spends a worthless margin would
        # otherwise be scored down for spending it.
        assert item["verdict_basis"] == "match_utility_per_sampled_world"
        assert item["worlds_base_better"] + item["worlds_variant_better"] <= (
            item["samples_solved"]
        )


def test_the_census_is_reproducible():
    def run():
        return summarize_census(
            rule_activation_census(
                deals=2, samples_per_decision=2, score_states=SMALL_STATES
            )
        )

    assert run() == run()


def test_the_census_rejects_malformed_arguments():
    with pytest.raises(DiagnosisError):
        rule_activation_census(deals=0)
    with pytest.raises(DiagnosisError):
        rule_activation_census(deals=1, samples_per_decision=-1)
    with pytest.raises(DiagnosisError):
        rule_activation_census(deals=1, variants=())


def test_the_show_census_reaches_many_more_showing_decisions():
    cheap = show_rule_census(deals=8)
    assert cheap["decisions"] > 0
    # Every variant whose changed rule is a showing rule takes part, including the
    # protect-distance sweep: moving that threshold is a showing change.
    expected = {f"off_{rule_id}" for rule_id in MATCH_SHOW_RULES} | {
        "protect_distance_0",
        "protect_distance_2",
        "protect_distance_6",
        "protect_distance_8",
    }
    assert set(cheap["per_variant"]) == expected
    for summary in cheap["per_variant"].values():
        assert summary["changed_rule_id"] in MATCH_SHOW_RULES
        assert summary["contract_flips"] >= 0
        assert summary["eligible_decisions"] >= 0
    assert "contract flip" in cheap["interpretation"]
    assert cheap["threshold_margin"]["count"] > 0


def test_the_show_census_is_reproducible():
    assert show_rule_census(deals=4) == show_rule_census(deals=4)


def test_the_show_census_requires_a_showing_variant():
    from tuppi_exact.variants import single_rule_off_variants

    play_only = tuple(
        item
        for item in single_rule_off_variants()
        if item.changed_rule_id in MATCH_PLAY_RULES
    )
    with pytest.raises(DiagnosisError):
        show_rule_census(deals=2, variants=play_only)


def test_ablation_comparisons_keep_the_phase5a_sign_convention():
    comparisons = rule_ablation_comparisons()
    assert comparisons
    for comparison, variant in comparisons:
        assert comparison.candidate_profile_key == "match_aware_v1"
        assert comparison.opponent_agent_id == variant.specification.agent_id
        assert comparison.result_class == "ablation"
        assert comparison.candidate_agent_id != comparison.opponent_agent_id
        assert comparison.starting_score == (0, 0)


def test_a_tiny_ablation_runs_the_frozen_protocol():
    from tuppi_exact.variants import single_rule_off_variants

    variants = single_rule_off_variants()[:1]
    report = run_rule_ablation(pairs=1, variants=variants, safety_cap=704)
    assert report["pair_count"] == 1
    assert report["schema_version"] == "tuppi.exact.rule_ablation_report.v1"
    assert "p_win above 0.5 means the changed rule helps" in report["sign_convention"]
    assert "wall-clock" in report["worker_independence"]
    comparison = report["comparisons"][0]
    inference = comparison["primary_match_inference"]
    assert inference["complete_pair_count"] + inference["censored_pair_count"] == 1
    assert comparison["variant"]["changed_rule_id"] in MATCH_RULES


def test_the_ablation_rejects_a_nonpositive_pair_count():
    with pytest.raises(DiagnosisError):
        run_rule_ablation(pairs=0)


def test_diagnose_composes_the_exact_instruments_without_the_expensive_one():
    report = diagnose(census_deals=1, samples_per_decision=2, ablation_pairs=None)
    assert report["schema_version"] == DIAGNOSIS_SCHEMA_VERSION
    assert report["monotonicity_certificate"]["holds"] is True
    assert report["variant_composition_check"]["behaviour_matches_frozen_ablation"]
    assert report["structural_verdict"]["holds"] is True
    assert set(report["structural_verdict"]["rules_covered"]) == set(MATCH_PLAY_RULES)
    assert "rule_ablation" not in report
    assert "Perfect information" in report["structural_verdict"]["scope"]


def test_exact_verdict_data_round_trips_its_fields():
    verdict = ExactVerdict(
        rule_id="match.play.coast_when_margin_worthless.v1",
        score_state=(48, 0),
        contract="RAMI",
        tricks_remaining=3,
        base_card="5H",
        variant_card="AH",
        base_regret_points=4,
        variant_regret_points=0,
        base_match_utility=(1, 0),
        variant_match_utility=(1, 0),
        verdict="neutral",
        deal_point_verdict="rule_hurts",
    )
    data = verdict.to_data()
    assert data["score_state"] == [48, 0]
    assert data["verdict"] == "neutral"
    assert data["deal_point_verdict"] == "rule_hurts"
