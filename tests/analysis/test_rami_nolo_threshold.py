from __future__ import annotations

import inspect

import pytest

from tuppi_agents import (
    construct_registered_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_analysis import rami_nolo_threshold as experiment
from tuppi_analysis.rami_nolo_threshold import (
    ExperimentConfig,
    apply_forced_choice,
    collect_corpus,
    current_production_rule,
    evaluate_source_deal,
    forced_action_for_contract,
    threshold_choice,
    threshold_sweep,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    ShowAction,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.deals import DealerPolicy, generate_base_deal
from tuppi_rules import (
    Contract,
    MatchScore,
    score_nolo,
    score_rami_for_declarer,
)


def _initial_state(*, seed: str = "rami-nolo-test-state"):
    deal = generate_base_deal(
        root_seed=seed,
        index=0,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
    )
    return begin_explicit_deal(
        create_match(
            initial_score=MatchScore(),
            initial_dealer=deal.dealer,
            match_ref="rami-nolo-test",
        ),
        deal.explicit_deal(),
    )


def _scored_showing(state):
    actor = state.current_actor
    assert actor is not None
    observation = match_observation_for(state, actor)
    specification = phase4_specifications_by_profile_key()["partner_aware_v1"]
    agent = construct_registered_agent(specification, seat=actor)
    return observation, agent.decide(observation, diagnostics=False).scored


def test_production_rule_is_recovered_from_the_registered_profile() -> None:
    rule = current_production_rule()
    assert rule["profile_key"] == "partner_aware_v1"
    assert rule["rami_score"]["threshold"] == 15.0
    assert rule["nolo_score"]["veto_threshold"] == 2.0
    assert rule["match_score_affects_decision"] is False
    assert "HCP + 0.5*aces" in rule["rami_score"]["formula"]
    assert "1.5*low_card_count" in rule["nolo_score"]["formula"]


def test_forced_actions_are_engine_legal_and_use_the_policy_card_ranking() -> None:
    state = _initial_state()
    observation, scored = _scored_showing(state)
    for contract in (Contract.RAMI, Contract.NOLO):
        action = forced_action_for_contract(scored, contract)
        assert isinstance(action, ShowAction)
        assert action.declared_contract is contract
        assert action in observation.legal_actions
        conditional = [
            candidate
            for candidate in scored.candidates
            if isinstance(candidate.action, ShowAction)
            and candidate.action.declared_contract is contract
        ]
        assert action == max(conditional, key=lambda item: item.selection_key).action


def test_rami_stops_showing_and_nolo_allows_it_to_continue() -> None:
    state = _initial_state(seed="rami-nolo-show-transition")
    rami_state, rami_action = apply_forced_choice(state, Contract.RAMI)
    nolo_state, nolo_action = apply_forced_choice(state, Contract.NOLO)

    assert rami_action.declared_contract is Contract.RAMI
    assert rami_state.phase is EnginePhase.TRICK_PLAY
    assert len(rami_state.active_deal.show_actions) == 1

    assert nolo_action.declared_contract is Contract.NOLO
    assert nolo_state.phase is EnginePhase.SHOWING
    assert len(nolo_state.active_deal.show_actions) == 1
    assert nolo_state.current_actor == (state.current_actor + 1) % 4

    # Frozen MatchState/DealState inputs are unchanged by either branch.
    assert state.phase is EnginePhase.SHOWING
    assert state.active_deal.show_actions == ()


def test_both_counterfactuals_start_from_the_identical_full_state() -> None:
    record = evaluate_source_deal(
        split="test",
        root_seed="rami-nolo-identical-state",
        source_deal_index=0,
    )[0]
    digest = record["pre_state_digest"]
    assert record["forced_actions"]["RAMI"]["pre_state_digest"] == digest
    assert record["forced_actions"]["NOLO"]["pre_state_digest"] == digest
    assert record["forced_actions"]["RAMI"]["seat"] == record["seat"]
    assert record["forced_actions"]["NOLO"]["seat"] == record["seat"]


def test_every_serialized_score_is_exactly_the_production_engine_score() -> None:
    records = evaluate_source_deal(
        split="test",
        root_seed="rami-nolo-score-check",
        source_deal_index=0,
    )
    for record in records:
        for outcome in record["counterfactuals"].values():
            totals = tuple(outcome["team_tricks"])
            if outcome["final_contract"] == Contract.NOLO.value:
                expected = score_nolo(*totals)
            else:
                expected = score_rami_for_declarer(outcome["declarer"], *totals)
            assert outcome["deal_points"] == expected.points
            assert outcome["final_deal_winner"] == expected.winner_team.value
            assert outcome["stolen_rami"] == (
                None
                if expected.contract is Contract.NOLO
                else expected.stolen_rami
            )


def test_stolen_rami_uses_the_eight_point_multiplier_in_a_full_branch() -> None:
    # This deterministic deal's fourth production-reachable decision gives the
    # declaring partnership 6 tricks and the defenders 7 after forced RAMI.
    records = evaluate_source_deal(
        split="test",
        root_seed="test-rn-stolen",
        source_deal_index=1,
    )
    stolen = [
        record["counterfactuals"]["RAMI"]
        for record in records
        if record["counterfactuals"]["RAMI"]["stolen_rami"]
    ]
    assert stolen
    exact_boundary = next(
        outcome for outcome in stolen if outcome["opponent_team_tricks"] == 7
    )
    assert exact_boundary["acting_team_tricks"] == 6
    assert exact_boundary["deal_points"] == 8
    assert exact_boundary["partnership_utility"] == -8
    for outcome in stolen:
        assert outcome["deal_points"] == 8 * (outcome["opponent_team_tricks"] - 6)


def test_threshold_application_is_inclusive_vetoed_and_deterministic() -> None:
    calls = [
        threshold_choice(
            rami_score=15.0,
            nolo_score=2.0,
            threshold=15.0,
            nolo_veto_threshold=2.0,
        )
        for _ in range(10)
    ]
    assert calls == [Contract.RAMI] * 10
    assert threshold_choice(
        rami_score=14.75,
        nolo_score=2.0,
        threshold=15.0,
        nolo_veto_threshold=2.0,
    ) is Contract.NOLO
    assert threshold_choice(
        rami_score=30.0,
        nolo_score=2.5,
        threshold=15.0,
        nolo_veto_threshold=2.0,
    ) is Contract.NOLO


def test_partner_aware_showing_sequence_is_invariant_to_match_score() -> None:
    generated = generate_base_deal(
        root_seed="rami-nolo-match-score-invariance",
        index=0,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
    )
    explicit = ExplicitDeal(dealer=generated.dealer, hands=generated.hands)
    specification = phase4_specifications_by_profile_key()["partner_aware_v1"]

    def showing_sequence(score: MatchScore):
        state = begin_explicit_deal(
            create_match(
                initial_score=score,
                initial_dealer=generated.dealer,
                match_ref=f"score-{score.team0}-{score.team1}",
            ),
            explicit,
        )
        actions = []
        while state.phase is EnginePhase.SHOWING:
            actor = state.current_actor
            assert actor is not None
            observation = match_observation_for(state, actor)
            agent = construct_registered_agent(specification, seat=actor)
            action = agent.choose_action(observation)
            actions.append(action)
            state = apply_match_action(state, action)
        return tuple(actions)

    baseline = showing_sequence(MatchScore())
    assert showing_sequence(MatchScore(44, 0)) == baseline
    assert showing_sequence(MatchScore(0, 44)) == baseline


def test_dense_sweep_includes_current_and_both_legal_controls() -> None:
    records, _manifest = collect_corpus(
        split="test",
        root_seed="rami-nolo-sweep-test",
        target_decisions=3,
        workers=1,
    )
    sweep = threshold_sweep(
        records,
        production_threshold=15.0,
        nolo_veto_threshold=2.0,
    )
    numeric = [row for row in sweep if row["threshold"] is not None]
    assert any(row["threshold"] == 15.0 and row["is_current"] for row in numeric)
    assert all(
        round((right["threshold"] - left["threshold"]) * 4) == 1
        for left, right in zip(numeric, numeric[1:], strict=False)
    )
    assert {row["control"] for row in sweep if row["control"]} == {
        "always_rami",
        "always_nolo",
    }


def test_direct_seeded_corpus_is_reproducible() -> None:
    kwargs = {
        "split": "test",
        "root_seed": "rami-nolo-reproducibility",
        "target_decisions": 2,
        "workers": 1,
    }
    first_records, first_manifest = collect_corpus(**kwargs)
    second_records, second_manifest = collect_corpus(**kwargs)
    assert first_records == second_records
    assert first_manifest == second_manifest
    config = ExperimentConfig(tuning_decisions=2, validation_decisions=2)
    assert config.to_data() == config.to_data()


def test_experiment_never_calls_or_imports_the_sealed_bank_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tuppi_match.banks as banks

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sealed bank opener was called")

    monkeypatch.setattr(banks, "open_sealed_bank", forbidden)
    records, manifest = collect_corpus(
        split="test",
        root_seed="rami-nolo-unsealed-boundary",
        target_decisions=1,
        workers=1,
    )
    assert records
    assert manifest["source_kind"] == "direct_deterministic_unsealed_generation"
    assert manifest["sealed_bank_opened"] is False
    source = inspect.getsource(experiment)
    assert "open_sealed_bank(" not in source
    assert "load_deal_bank(" not in source
