from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_agents import (
    LADDER_PROFILE_KEYS,
    STRATEGIC_PROFILE_KEYS,
    construct_agent,
    control_specification,
    phase4_specifications_by_profile_key,
)
from tuppi_eval.arena import run_evaluation
from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_eval.schedules import EvaluationMode
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    play_active_deal,
)
from tuppi_rules import MatchScore

from .conftest import partition_deck, start_deal
from .support import phase4_bank, phase4_comparison, team


SPECIFICATIONS = phase4_specifications_by_profile_key()
PROBE_SEED = 555


def _probe_bank(count: int = 8):
    return generate_deal_bank(
        count=count,
        root_seed=PROBE_SEED,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "phase4_integration"},
    )


def _play(profile_key: str, base, *, score: MatchScore | None = None):
    agents = tuple(
        construct_agent(SPECIFICATIONS[profile_key], seat=seat) for seat in range(4)
    )
    state = create_match(
        initial_score=score or base.starting_score,
        initial_dealer=base.dealer,
        match_ref="integration",
    )
    state = begin_explicit_deal(
        state, ExplicitDeal(dealer=base.dealer, hands=base.hands)
    )
    return play_active_deal(state, agents)


# ----------------------------------------------------------- homogeneous teams


@pytest.mark.parametrize("profile_key", STRATEGIC_PROFILE_KEYS)
def test_homogeneous_teams_complete_a_fixed_deal(profile_key: str) -> None:
    base = _probe_bank(1).base_deals[0]
    state = _play(profile_key, base)
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
    result = state.completed_deals[-1].public_result
    assert sum(result.team_tricks) == 13
    assert result.deal_score.points > 0


@pytest.mark.parametrize("profile_key", LADDER_PROFILE_KEYS)
def test_a_fixed_deal_replays_byte_identically(profile_key: str) -> None:
    from tuppi_engine import canonical_json_bytes, deal_result_to_data

    base = _probe_bank(1).base_deals[0]
    first = _play(profile_key, base).completed_deals[-1].public_result
    second = _play(profile_key, base).completed_deals[-1].public_result
    assert canonical_json_bytes(deal_result_to_data(first)) == canonical_json_bytes(
        deal_result_to_data(second)
    )


def test_the_ladder_produces_all_three_contract_outcomes() -> None:
    bank = _probe_bank(8)
    outcomes = set()
    for base in bank.base_deals:
        result = _play("match_aware_v1", base).completed_deals[-1].public_result
        if result.contract.value == "NOLO":
            outcomes.add("nolo")
        elif result.deal_score.stolen_rami:
            outcomes.add("stolen_rami")
        else:
            outcomes.add("successful_rami")
    assert outcomes == {"nolo", "successful_rami", "stolen_rami"}


def test_a_successful_rami_and_a_stolen_rami_are_scored_correctly() -> None:
    bank = _probe_bank(8)
    made = _play("match_aware_v1", bank.base_deals[0]).completed_deals[-1].public_result
    assert made.contract.value == "RAMI"
    assert made.deal_score.stolen_rami is False
    declaring = made.deal_score.declaring_team
    assert declaring is not None
    assert made.team_tricks[declaring.value] >= 7
    assert made.deal_score.points == 4 * (made.team_tricks[declaring.value] - 6)

    stolen = _play("match_aware_v1", bank.base_deals[2]).completed_deals[-1].public_result
    assert stolen.contract.value == "RAMI"
    assert stolen.deal_score.stolen_rami is True
    declaring = stolen.deal_score.declaring_team
    assert declaring is not None
    assert stolen.team_tricks[declaring.value] < 7
    winner = stolen.deal_score.winner_team
    assert stolen.deal_score.points == 8 * (stolen.team_tricks[winner.value] - 6)


def test_an_all_nolo_deal_reaches_the_documented_scoring_formula() -> None:
    bank = _probe_bank(8)
    result = _play("match_aware_v1", bank.base_deals[6]).completed_deals[-1].public_result
    assert result.contract.value == "NOLO"
    assert result.declarer is None
    winner = result.deal_score.winner_team
    assert result.deal_score.points == 4 * (7 - result.team_tricks[winner.value])


@pytest.mark.parametrize(
    "score", [MatchScore(), MatchScore(40, 0), MatchScore(0, 40), MatchScore(48, 0)]
)
def test_every_score_state_completes_for_the_top_rung(score: MatchScore) -> None:
    base = _probe_bank(1).base_deals[0]
    state = _play("match_aware_v1", base, score=score)
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)


# --------------------------------------------------- heterogeneous and control


@pytest.mark.parametrize("profile_key", LADDER_PROFILE_KEYS)
@pytest.mark.parametrize(
    "control_family", ["first_legal", "lowest_legal_card", "highest_legal_card"]
)
def test_each_strategic_agent_plays_a_full_deal_against_controls(
    profile_key: str, control_family: str
) -> None:
    from tuppi_agents import construct_control_agent

    control = control_specification(control_family)
    hands = partition_deck({})
    agents = (
        construct_agent(SPECIFICATIONS[profile_key], seat=0),
        construct_control_agent(control, seat=1, seed=None),
        construct_agent(SPECIFICATIONS[profile_key], seat=2),
        construct_control_agent(control, seat=3, seed=None),
    )
    state = play_active_deal(start_deal(hands), agents)
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
    assert sum(state.completed_deals[-1].public_result.team_tricks) == 13


def test_a_seeded_random_control_partners_a_strategic_agent() -> None:
    from tuppi_agents import construct_control_agent

    control = control_specification("seeded_random_legal")
    hands = partition_deck({})
    agents = (
        construct_agent(SPECIFICATIONS["match_aware_v1"], seat=0),
        construct_control_agent(control, seat=1, seed="fixed-seed-a"),
        construct_control_agent(control, seat=2, seed="fixed-seed-b"),
        construct_agent(SPECIFICATIONS["match_aware_v1"], seat=3),
    )
    state = play_active_deal(start_deal(hands), agents)
    assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)


def test_a_heterogeneous_strategic_partnership_completes_a_match() -> None:
    bank = _probe_bank(6)
    agents = (
        construct_agent(SPECIFICATIONS["match_aware_v1"], seat=0),
        construct_agent(SPECIFICATIONS["reactive_contract_v1"], seat=1),
        construct_agent(SPECIFICATIONS["partner_aware_v1"], seat=2),
        construct_agent(SPECIFICATIONS["legacy_heuristic_port_v1"], seat=3),
    )
    state = create_match(
        initial_score=MatchScore(), initial_dealer=0, match_ref="hetero-match"
    )
    played = 0
    for base in bank.base_deals:
        if state.terminal:
            break
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=base.dealer, hands=base.hands)
        )
        state = play_active_deal(state, agents)
        played += 1
    assert played >= 1
    assert len(state.completed_deals) == played


# --------------------------------------------------------------- arena records


def test_the_arena_records_canonical_phase4_agent_identities(tmp_path: Path) -> None:
    from tuppi_engine import strict_json_load_file

    bank = phase4_bank(count=1)
    team_a = team("match_aware_v1_clone")
    team_b = team("reactive_contract_v1_clone")
    schedule, config = phase4_comparison(bank=bank, team_a=team_a, team_b=team_b)
    run = run_evaluation(config, bank, schedule, output_directory=tmp_path / "run")
    assert run.executed_game_count == 8
    assert run.result.summary["execution_metrics"]["failed_games"] == 0

    match_aware = SPECIFICATIONS["match_aware_v1"].agent_id
    reactive = SPECIFICATIONS["reactive_contract_v1"].agent_id
    files = sorted((tmp_path / "run" / "games").glob("*.json"))
    assert len(files) == 8
    for path in files:
        record = strict_json_load_file(path)
        assert record["execution_status"] == "success"
        assert set(record["seat_agent_ids"]) == {match_aware, reactive}
        assert record["agent_seeds"] == [None, None, None, None]
        assert record["ruleset_id"] == "project_target_v1"


def test_an_identical_configuration_reproduces_identical_results(
    tmp_path: Path,
) -> None:
    """Everything except the wall-clock measurements must be byte-identical."""

    from tuppi_engine import canonical_json_bytes, strict_json_load_file

    bank = phase4_bank(count=1)
    team_a = team("partner_aware_v1_clone")
    team_b = team("control_first_legal_clone")
    schedule, config = phase4_comparison(bank=bank, team_a=team_a, team_b=team_b)
    first = run_evaluation(config, bank, schedule, output_directory=tmp_path / "one")
    second = run_evaluation(config, bank, schedule, output_directory=tmp_path / "two")
    assert first.result.result_id == second.result.result_id

    left = sorted((tmp_path / "one" / "games").glob("*.json"))
    right = sorted((tmp_path / "two" / "games").glob("*.json"))
    assert [path.name for path in left] == [path.name for path in right]
    measured = {"action_durations_seconds", "duration_seconds"}
    for a, b in zip(left, right, strict=True):
        one = strict_json_load_file(a)
        two = strict_json_load_file(b)
        assert one["record_id"] == two["record_id"]
        assert one["raw_result_digest"] == two["raw_result_digest"]
        assert canonical_json_bytes(
            {key: value for key, value in one.items() if key not in measured}
        ) == canonical_json_bytes(
            {key: value for key, value in two.items() if key not in measured}
        )
    for name in ("evaluation_config.json", "deal_bank.json", "schedule.json"):
        assert (tmp_path / "one" / name).read_bytes() == (
            tmp_path / "two" / name
        ).read_bytes()
    raw_left = sorted((tmp_path / "one" / "raw").glob("*.json"))
    raw_right = sorted((tmp_path / "two" / "raw").glob("*.json"))
    assert [path.name for path in raw_left] == [path.name for path in raw_right]
    for a, b in zip(raw_left, raw_right, strict=True):
        assert a.read_bytes() == b.read_bytes()


def test_a_heterogeneous_team_runs_through_the_arena(tmp_path: Path) -> None:
    bank = phase4_bank(count=1)
    schedule, config = phase4_comparison(
        bank=bank,
        team_a=team("heterogeneous_match_aware_with_reactive"),
        team_b=team("public_counting_v1_clone"),
    )
    run = run_evaluation(config, bank, schedule, output_directory=tmp_path / "run")
    assert run.result.summary["execution_metrics"]["failed_games"] == 0
    assert run.result.summary["primary_inference"]["independent_base_deals"] == 1


def test_a_complete_match_from_zero_zero_runs_through_the_arena(
    tmp_path: Path,
) -> None:
    bank = phase4_bank(count=24, root_seed="phase4-match-test")
    schedule, config = phase4_comparison(
        bank=bank,
        team_a=team("match_aware_v1_clone"),
        team_b=team("control_first_legal_clone"),
        mode=EvaluationMode.MATCH,
        match_sequence_length=24,
    )
    run = run_evaluation(config, bank, schedule, output_directory=tmp_path / "match")
    summary = run.result.summary
    assert run.executed_game_count == 8
    assert summary["evaluation_mode"] == "match"
    successful = summary["execution_metrics"]["successful_games"]
    failed = summary["execution_metrics"]["failed_games"]
    assert successful + failed == 8
    if successful:
        assert summary["outcome_metrics"]["match_win_rate_team_a"] is not None


def test_zero_illegal_actions_across_every_ladder_pairing() -> None:
    hands = partition_deck({})
    for left in LADDER_PROFILE_KEYS:
        for right in LADDER_PROFILE_KEYS:
            agents = (
                construct_agent(SPECIFICATIONS[left], seat=0),
                construct_agent(SPECIFICATIONS[right], seat=1),
                construct_agent(SPECIFICATIONS[left], seat=2),
                construct_agent(SPECIFICATIONS[right], seat=3),
            )
            state = start_deal(hands)
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                actor = state.current_actor
                assert actor is not None
                observation = match_observation_for(state, actor)
                action = agents[actor].choose_action(observation)
                assert action in observation.legal_actions
                state = apply_match_action(state, action)
            assert state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE)
