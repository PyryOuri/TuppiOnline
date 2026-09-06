"""N07 harness checks: the screen must not be able to flatter its own answer.

Three properties are worth more here than coverage of the reporting code, and
each has a test that fails loudly if it stops holding:

* an unresolved position stays in the denominators rather than disappearing;
* the real layout never reaches the decision function, and never reaches the
  record the decision is read from;
* the gate is decided by the frozen rule, so soundness outranks any count.

The full screen is 256 deals and hours of search, so these run on the
development bank with the remaining-trick budget cut to two. That changes the
size of the positions, never the code path under test.
"""

from __future__ import annotations

import inspect
import json

import pytest

from tuppi_engine import EnginePhase, PlayCardAction, observation_for
from tuppi_nolo import runner
from tuppi_nolo.certificates import CheckStatus
from tuppi_nolo.outcomes import ClaimLabel
from tuppi_nolo.runner import (
    DEVELOPMENT_SEED,
    FEASIBILITY_THRESHOLD,
    contains_forbidden_key,
    deal_state,
    decision_role,
    is_eligible,
    run_coverage,
    screen_deal,
    summarise,
)
from tuppi_nolo.security import SecurityStatus, solve_security
from tuppi_nolo.support import SupportBudget, SupportStatus

SHALLOW = SupportBudget(2, 100, 100_000)
STARVED = SupportBudget(2, 100, 40)


@pytest.fixture(scope="module")
def screened():
    return screen_deal(DEVELOPMENT_SEED, 0, budget=SHALLOW, verification_budget=SHALLOW)


@pytest.fixture(scope="module")
def starved():
    return screen_deal(DEVELOPMENT_SEED, 0, budget=STARVED, verification_budget=STARVED)


def fake_deal(deal_id, records):
    return {"deal_index": 0, "deal_id": deal_id, "card_plays": 52,
            "records": records, "oracle": []}


def fake_record(**overrides):
    record = {
        "position_id": "d#0/10/1", "deal_id": "d#0", "role": "lead",
        "remaining_tricks": 2, "world_count": 4, "support_status": "EXACT_COMPLETE",
        "status": SecurityStatus.EXACT_COMPLETE.value, "deviation": False,
        "reverification_status": CheckStatus.EXACT_COMPLETE.value,
        "claim": "NO_DEVIATION", "score_relevant": False, "failures": [],
    }
    record.update(overrides)
    return record


# ------------------------------------------------------------- the bank


def test_the_bank_is_a_pure_function_of_seed_and_index():
    first = deal_state(DEVELOPMENT_SEED, 3)
    again = deal_state(DEVELOPMENT_SEED, 3)
    other = deal_state(DEVELOPMENT_SEED, 4)
    assert first.hands == again.hands and first.dealer == again.dealer
    assert first.hands != other.hands


def test_the_bank_starts_in_forced_nolo_trick_play_at_love():
    state = deal_state(DEVELOPMENT_SEED, 0)
    assert state.phase is EnginePhase.TRICK_PLAY
    assert state.contract.name == "NOLO"
    assert state.starting_score.as_tuple() == (0, 0)


def test_dealers_are_round_robin_from_seat_zero():
    assert [deal_state(DEVELOPMENT_SEED, i).dealer for i in range(5)] == [0, 1, 2, 3, 0]


# -------------------------------------------------------- the frozen rule


def test_eligibility_needs_a_real_choice_near_the_end():
    state = deal_state(DEVELOPMENT_SEED, 0)
    observation = observation_for(state, state.current_actor)
    assert 13 - len(observation.completed_tricks) == 13
    assert not is_eligible(observation, SHALLOW), "the first trick is out of scope"


def test_a_forced_position_is_never_eligible(screened):
    """A single legal action is not a decision, so it cannot be a deviation."""

    state = deal_state(DEVELOPMENT_SEED, 0)
    from tuppi_agents.void_lead import void_seeking_agents

    agents = void_seeking_agents()
    seen_forced = False
    while state.phase is EnginePhase.TRICK_PLAY:
        observation = observation_for(state, state.current_actor)
        if len(observation.legal_actions) == 1:
            seen_forced = True
            assert not is_eligible(observation, SHALLOW)
        state = runner.apply_action(state, agents[state.current_actor].choose_action(observation))
    assert seen_forced, "the deal should contain at least one forced play"


def test_the_role_is_read_from_the_legal_set_not_the_played_card():
    state = deal_state(DEVELOPMENT_SEED, 0)
    observation = observation_for(state, state.current_actor)
    assert decision_role(observation) == "lead"
    from tuppi_agents.void_lead import void_seeking_agents

    agents = void_seeking_agents()
    roles = set()
    while state.phase is EnginePhase.TRICK_PLAY:
        observation = observation_for(state, state.current_actor)
        role = decision_role(observation)
        roles.add(role)
        if role == "discard":
            led = observation.current_trick[0].card.suit
            assert all(a.card.suit is not led for a in observation.legal_actions)
        state = runner.apply_action(state, agents[state.current_actor].choose_action(observation))
    assert {"lead", "follow"} <= roles


# ------------------------------------------- unresolved stays in the count


def test_unresolved_positions_stay_in_the_denominators(starved):
    """The point of the check: a starved run must report eligible-and-unresolved,
    never a coverage rate computed over the easy positions alone."""

    report = summarise([starved], attempted=1, cap_reached=False)
    denominators = report["denominators"]
    assert denominators["eligible_choices"] > 0
    assert denominators["completed_searches"] == 0
    assert report["unresolved"]["eligible_but_unresolved"] == denominators["eligible_choices"]
    assert set(report["unresolved"]["by_status"]) <= {
        SecurityStatus.SUPPORT_BUDGET.value, SecurityStatus.SEARCH_BUDGET.value
    }


def test_an_unresolved_position_proposes_nothing_and_fails_nothing(starved):
    for record in starved["records"]:
        assert record["status"] != SecurityStatus.EXACT_COMPLETE.value
        assert record["proposed_action"] is None and record["deviation"] is False
        assert record["failures"] == []


def test_a_starved_bank_is_complete_and_sound_but_finds_nothing(starved):
    report = summarise([starved], attempted=1, cap_reached=False)
    assert report["soundness"]["passed"]
    assert report["outcome"] == "NO_USEFUL_SIGNAL"


# ------------------------------------------------------- the information wall


def test_the_decision_function_refuses_anything_but_an_observation():
    state = deal_state(DEVELOPMENT_SEED, 0)
    with pytest.raises(TypeError):
        solve_security(state, SHALLOW)


def test_no_record_carries_a_hidden_card(screened):
    assert contains_forbidden_key(screened["records"]) is None
    for record in screened["records"]:
        assert json.loads(json.dumps(record)) == record, "records must be plain JSON"


def test_the_real_layout_is_kept_in_the_oracle_file_only(screened):
    assert screened["oracle"] and len(screened["oracle"]) == len(screened["records"])
    ids = {entry["position_id"] for entry in screened["oracle"]}
    assert ids == {record["position_id"] for record in screened["records"]}
    for entry in screened["oracle"]:
        assert sum(len(hand) for hand in entry["hands"]) > 0


def test_the_true_layout_lies_inside_the_enumerated_support(screened):
    """The sharpest available soundness check: a certificate quantifies over a
    support asserted complete, so the deal actually being played must be in it."""

    resolved = [r for r in screened["records"]
                if r["status"] == SecurityStatus.EXACT_COMPLETE.value]
    assert resolved, "the shallow budget should still resolve something"
    for record in resolved:
        assert "truth_outside_support" not in record["failures"]


def test_the_screen_never_uses_the_failed_memo():
    """N06 did not meet its reduction target, so its task permits N07 to use it
    only if it had. The screen must therefore run the plain search."""

    source = inspect.getsource(runner)
    assert "SecurityCache" not in source and "cache=" not in source


# ----------------------------------------------------------- the records


def test_a_resolved_record_carries_everything_needed_to_reconstruct_it(screened):
    for record in screened["records"]:
        if record["status"] != SecurityStatus.EXACT_COMPLETE.value:
            continue
        assert record["world_count"] and record["world_count"] >= 1
        assert record["baseline_action"] and record["proposed_action"]
        assert record["claimed_bound"] is not None
        assert record["verified_bound"] is not None
        assert record["verification_status"] == CheckStatus.EXACT_COMPLETE.value
        assert record["verified_bound"] <= record["claimed_bound"]
        # Only a deviation is re-verified independently; that is what gets counted.
        assert (record["reverification_status"] is None) is not record["deviation"]
        assert record["search_engine_transitions"] > 0
        assert record["deal_id"] and record["position_id"]


def test_a_non_deviation_is_labelled_as_such_and_is_not_score_relevant(screened):
    for record in screened["records"]:
        if record["status"] == SecurityStatus.EXACT_COMPLETE.value and not record["deviation"]:
            assert record["claim"] == "NO_DEVIATION"
            assert record["score_relevant"] is False
            assert record["baseline_totals"] is None, "an unchanged action needs no comparator"


# ------------------------------------------------------------- the gate


def test_a_tie_is_never_counted_as_score_relevant():
    records = [fake_record(deal_id=f"d#{i}", deviation=True,
                           claim=ClaimLabel.TIE.value, score_relevant=False)
               for i in range(FEASIBILITY_THRESHOLD + 3)]
    report = summarise([fake_deal(r["deal_id"], [r]) for r in records],
                       attempted=len(records), cap_reached=False)
    assert report["denominators"]["verified_deviations"] == len(records)
    assert report["denominators"]["score_relevant_deviations"] == 0
    assert report["outcome"] == "NO_USEFUL_SIGNAL"


def test_enough_distinct_deals_reach_the_feasibility_gate():
    deals = [fake_deal(f"d#{i}", [fake_record(deal_id=f"d#{i}", deviation=True,
                                              claim=ClaimLabel.UNIVERSAL.value,
                                              score_relevant=True)])
             for i in range(FEASIBILITY_THRESHOLD)]
    report = summarise(deals, attempted=len(deals), cap_reached=False)
    assert report["outcome"] == "GO"
    assert report["denominators"]["distinct_deals_with_a_deviation"] == FEASIBILITY_THRESHOLD


def test_four_seats_of_one_deal_are_not_four_samples():
    seats = [fake_record(deal_id="d#0", position_id=f"d#0/10/{seat}", deviation=True,
                         claim=ClaimLabel.SECURITY_ONLY.value, score_relevant=True)
             for seat in range(4)]
    more = [fake_deal(f"d#{i}", [fake_record(deal_id=f"d#{i}", deviation=True,
                                             claim=ClaimLabel.SECURITY_ONLY.value,
                                             score_relevant=True)])
            for i in range(1, FEASIBILITY_THRESHOLD - 1)]
    report = summarise([fake_deal("d#0", seats), *more],
                       attempted=FEASIBILITY_THRESHOLD - 1, cap_reached=False)
    assert report["denominators"]["score_relevant_deviations"] == 4 + len(more)
    assert report["denominators"]["distinct_deals_with_a_deviation"] == 1 + len(more)
    assert report["outcome"] == "NO_USEFUL_SIGNAL", "deals are the unit, not seats"


def test_one_soundness_failure_outranks_every_count():
    deals = [fake_deal(f"d#{i}", [fake_record(deal_id=f"d#{i}", deviation=True,
                                              claim=ClaimLabel.UNIVERSAL.value,
                                              score_relevant=True)])
             for i in range(FEASIBILITY_THRESHOLD + 5)]
    deals[0]["records"][0]["failures"] = ["false_certificate"]
    report = summarise(deals, attempted=len(deals), cap_reached=False)
    assert report["outcome"] == "FAILED_CHECK"
    assert report["soundness"]["passed"] is False
    assert report["soundness"]["failures"]["false_certificate"] == 1


def test_the_cap_and_a_crash_both_report_inconclusive():
    deals = [fake_deal(f"d#{i}", [fake_record(deal_id=f"d#{i}", deviation=True,
                                              claim=ClaimLabel.UNIVERSAL.value,
                                              score_relevant=True)])
             for i in range(FEASIBILITY_THRESHOLD + 1)]
    capped = summarise(deals, attempted=len(deals), cap_reached=True)
    assert capped["outcome"] == "INCONCLUSIVE"
    short = summarise(deals, attempted=len(deals) + 3, cap_reached=False)
    assert short["outcome"] == "INCONCLUSIVE"
    crashed = [*deals, {"deal_index": 99, "deal_id": "d#99", "card_plays": 0,
                        "records": [], "oracle": [], "error": "RuntimeError()"}]
    broken = summarise(crashed, attempted=len(crashed), cap_reached=False)
    assert broken["outcome"] == "INCONCLUSIVE" and broken["errors"]


# ------------------------------------------------------------ end to end


def test_a_small_run_writes_records_oracle_and_a_report(tmp_path):
    report = run_coverage(seed=DEVELOPMENT_SEED, deals=2, workers=1, out_dir=tmp_path,
                          budget=SHALLOW, log=lambda message: None)
    records = [json.loads(line) for line in
               (tmp_path / "records.jsonl").read_text().splitlines()]
    oracle = [json.loads(line) for line in
              (tmp_path / "oracle.jsonl").read_text().splitlines()]
    stored = json.loads((tmp_path / "report.json").read_text())
    assert len(records) == report["denominators"]["eligible_choices"] == len(oracle)
    assert stored["denominators"] == report["denominators"]
    assert report["denominators"]["card_plays"] == 104
    assert report["denominators"]["deals_completed"] == 2
    assert report["run"]["cached_search"] is False
    assert contains_forbidden_key(records) is None


# ------------------------------------------- anchored against N05's table


PACKET_WITNESSES = {
    "A": {"baseline": "QD", "proposed": "8S", "claim": ClaimLabel.UNIVERSAL.value,
          "candidate": [7], "baseline_totals": [7, 8, 9]},
    "B": {"baseline": "3C", "proposed": "9C", "claim": ClaimLabel.SECURITY_ONLY.value,
          "candidate": [4], "baseline_totals": [3, 5]},
    "C": {"baseline": "KC", "proposed": "KC", "claim": "NO_DEVIATION",
          "candidate": [4, 5, 6], "baseline_totals": None},
}


@pytest.mark.parametrize("name", sorted(PACKET_WITNESSES))
def test_the_screen_reproduces_the_n05_labels_on_the_packet_witnesses(name):
    """The whole pipeline, on positions whose labels were derived separately.

    N05 classified these three by hand from the same primitives; if the harness
    around them shifted a seat, a baseline or an orientation, the labels here
    would move. Nothing in this file could produce them by accident.
    """

    from pathlib import Path

    from tuppi_agents.void_lead import void_seeking_agents
    from tuppi_nolo.fixtures import load_fixtures
    from tuppi_nolo.runner import evaluate_decision

    packet = Path(__file__).resolve().parents[2] / "docs/nolo/tasks/fixtures.json"
    state = {f.id: f.replay() for f in load_fixtures(packet)}[name]
    observation = observation_for(state, state.current_actor)
    baseline = void_seeking_agents()[state.current_actor].choose_action(observation)
    record = evaluate_decision(state, observation, baseline,
                              budget=SupportBudget(), verification_budget=SupportBudget())
    expected = PACKET_WITNESSES[name]

    assert record["status"] == SecurityStatus.EXACT_COMPLETE.value
    assert record["failures"] == []
    assert record["baseline_action"] == expected["baseline"]
    assert record["proposed_action"] == expected["proposed"]
    assert record["claim"] == expected["claim"]
    assert record["candidate_totals"] == expected["candidate"]
    assert record["baseline_totals"] == expected["baseline_totals"]
    assert record["score_relevant"] is (expected["claim"] in {
        ClaimLabel.UNIVERSAL.value, ClaimLabel.SECURITY_ONLY.value})
