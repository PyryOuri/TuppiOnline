"""Supplied claims, deliberate false certificates and exhaustive N01 comparison."""

from collections import Counter
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from tuppi_engine import PlayCardAction, apply_action, observation_for
from tuppi_exact import continuation as replay_module
from tuppi_exact.continuation import hypothetical_continuation
from tuppi_nolo import certificates as verifier
from tuppi_nolo.certificates import (
    OBJECTIVE, Certificate, CheckStatus, ClaimType, CompletenessProvenance,
    ControlModel, PlanEntry, TerminalOutcome, all_action_bounds,
    complete_support_digest, verify_certificate,
)
from tuppi_nolo.fixtures import load_fixtures
from tuppi_nolo.support import SupportBudget, SupportStatus, build_support, semantic_observation_key
from tuppi_rules import MatchScore, card_from_code, score_nolo, transition_rising_score

from evidence_reference import engine_worlds, terminal_counts

PACKET = Path(__file__).resolve().parents[2] / "docs/nolo/tasks"
EXPECTED = {r["id"]: r["expected"] for r in json.loads((PACKET / "fixtures.json").read_text())["fixtures"]}


def observation(state):
    return observation_for(state, state.current_actor)


def action(obs, card):
    return PlayCardAction(obs.observing_seat, card_from_code(card))


@pytest.fixture(scope="module")
def cases():
    cases = {}
    for f in load_fixtures(PACKET / "fixtures.json"):
        state = f.replay()
        obs = observation(state)
        cases[f.id] = obs, build_support(obs, SupportBudget())
    return cases


def certificate(cases, name, card, bound, *, next_card=None, control=ControlModel.ALL_ACTIONS,
                universal_over=None):
    obs, sup = cases[name]
    plan = ()
    if next_card is not None:
        after = apply_action(sup.research_worlds[0].continuation.state, action(obs, card))
        own = observation(after)
        assert own.observing_seat == obs.observing_seat
        plan = (PlanEntry(semantic_observation_key(own), action(own, next_card)),)
    return Certificate(semantic_observation_key(obs), obs.observing_seat, action(obs, card),
        OBJECTIVE, control, complete_support_digest(sup), plan, bound,
        CompletenessProvenance(SupportStatus.EXACT_COMPLETE, sup.world_count,
                               SupportBudget(), sup.engine_transitions),
        ClaimType.UNIVERSAL if universal_over else ClaimType.UNCLASSIFIED,
        action(obs, universal_over) if universal_over else None)


def replay_witness(obs, witness):
    assert witness is not None
    state = hypothetical_continuation(obs, witness.assignment).state
    for played in witness.actions:
        assert played in observation(state).legal_actions
        state = apply_action(state, played)
    if witness.outcome is not None:
        assert state.complete and len(state.completed_tricks) == 13
        assert witness.outcome == TerminalOutcome(state.team_tricks[obs.observing_seat % 2],
                                                  state.ending_score.as_tuple())
    else:
        assert semantic_observation_key(observation(state)) == witness.information_key
    return state


# Run the deliberate false claim tests before the positive certificates.
def test_wrong_b_line_is_disproved_with_legal_six_trick_path(cases):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 4, next_card="3H", control=ControlModel.SINGLE_SEAT)
    result = verify_certificate(obs, cert, SupportBudget())
    assert result.status is CheckStatus.DISPROVED_BOUND
    assert result.claim_type is ClaimType.UNCLASSIFIED
    assert result.terminal_totals == {6} and result.terminal_paths == 8
    assert replay_witness(obs, result.counterexample).team_tricks[0] == 6


@pytest.mark.parametrize("fault", ["missing_branch", "illegal_action", "conflict", "world_key", "root_conflict"])
def test_invalid_plan_never_passes(cases, fault):
    obs, sup = cases["B"]
    cert = certificate(cases, "B", "9C", 13, next_card="3C", control=ControlModel.SINGLE_SEAT)
    entry = cert.plan[0]
    if fault == "missing_branch":
        cert = replace(cert, plan=())
    elif fault == "illegal_action":
        cert = replace(cert, plan=(replace(entry, action=action(obs, "9C")),))
    elif fault == "conflict":
        cert = replace(cert, plan=cert.plan + (replace(entry, action=action(obs, "3H")),))
    elif fault == "world_key":
        cert = replace(cert, plan=cert.plan + (replace(entry, information_key=str(sup.research_worlds[0].content_key)),))
    else:
        cert = replace(cert, plan=cert.plan + (PlanEntry(cert.source_information_key, action(obs, "3C")),))
    result = verify_certificate(obs, cert, SupportBudget())
    assert result.status is CheckStatus.ILLEGAL_PLAN
    assert not result.outcomes and result.bounds is None
    if fault in ("missing_branch", "illegal_action"):
        state = replay_witness(obs, result.counterexample)
        assert state.current_actor == 0 and len(observation(state).legal_actions) == 2


@pytest.mark.parametrize("forged_count", [1, 2])
def test_omitting_one_world_cannot_forge_complete_support(cases, forged_count):
    obs, sup = cases["B"]
    cert = certificate(cases, "B", "9C", 4, next_card="3C", control=ControlModel.SINGLE_SEAT)
    partial = replace(sup, world_count=1, counted_candidates=1, research_worlds=sup.research_worlds[:1])
    cert = replace(cert, complete_support_digest=complete_support_digest(partial),
                   provenance=replace(cert.provenance, world_count=forged_count))
    result = verify_certificate(obs, cert, SupportBudget())
    assert result.status is CheckStatus.INCOMPLETE_SUPPORT
    assert not result.outcomes
    assert result.world_count == 2  # Independently rebuilt, never the asserted 1.


@pytest.fixture(scope="module")
def a_verified(cases):
    obs, _ = cases["A"]
    cert = certificate(cases, "A", "8S", 7, universal_over="QD")
    return verify_certificate(obs, cert, SupportBudget())


def test_a_is_universal_without_future_own_restrictions(cases, a_verified):
    obs, _ = cases["A"]
    result = a_verified
    assert result.status is CheckStatus.EXACT_COMPLETE
    assert result.claim_type is ClaimType.UNIVERSAL
    assert result.control_model is ControlModel.ALL_ACTIONS and result.plan == ()
    assert result.world_count == 20
    assert result.bounds == (7, 7) and result.terminal_totals == {obs.team_tricks[0]}
    assert result.score_states == {(0, 4)} and result.terminal_paths == 1680
    assert result.baseline_bounds == (7, 9)
    assert replay_witness(obs, result.comparison_path).team_tricks[0] == 9
    print(f"A universal verification: transitions={result.engine_transitions}, paths={result.terminal_paths}")


def test_b_correct_line_is_safe_but_not_universal(cases):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 4, next_card="3C", control=ControlModel.SINGLE_SEAT)
    result = verify_certificate(obs, cert, SupportBudget())
    assert result.status is CheckStatus.EXACT_COMPLETE
    assert result.claim_type is ClaimType.UNCLASSIFIED  # Bound verified; no security search here.
    assert result.world_count == 2 and result.bounds == (4, 4)
    assert result.terminal_paths == 16 and result.score_states == {(12, 0)}
    universal = verify_certificate(obs, replace(cert, claim_type=ClaimType.UNIVERSAL,
                                                baseline_action=action(obs, "3C")), SupportBudget())
    assert universal.status is CheckStatus.DISPROVED_UNIVERSAL
    assert universal.claim_type is ClaimType.UNCLASSIFIED
    assert universal.baseline_bounds == (3, 5)
    assert replay_witness(obs, universal.counterexample).team_tricks[0] == 4
    assert replay_witness(obs, universal.comparison_path).team_tricks[0] == 3
    print(f"B bound verification: transitions={result.engine_transitions}; "
          f"rejected universal comparison: transitions={universal.engine_transitions}")


def test_c_universal_claim_is_rejected_with_same_layout_counterexample(cases):
    obs, _ = cases["C"]
    cert = certificate(cases, "C", "10D", 6, universal_over="KC")
    result = verify_certificate(obs, cert, SupportBudget())
    assert result.status is CheckStatus.DISPROVED_UNIVERSAL
    assert result.claim_type is ClaimType.UNCLASSIFIED
    assert result.bounds == result.baseline_bounds == (4, 6)
    assert result.counterexample.assignment.content_key() == result.comparison_path.assignment.content_key()
    a = replay_witness(obs, result.counterexample)
    b = replay_witness(obs, result.comparison_path)
    assert a.team_tricks[0] > b.team_tricks[0]
    print(f"C rejected universal claim: transitions={result.engine_transitions}; "
          f"same-world totals={a.team_tricks[0]}/{b.team_tricks[0]}")


@pytest.fixture(scope="module")
def independent_worlds(cases):
    # Separate independent replay allowance: 2,000 partitions, 100,000 calls/case.
    worlds = {}
    for name, (obs, _) in cases.items():
        calls = 0
        real = replay_module.apply_action
        def step(state, action):
            nonlocal calls
            assert calls < 100_000
            calls += 1
            return real(state, action)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(replay_module, "apply_action", step)
            attempted, accepted = engine_worlds(obs)
        assert attempted == EXPECTED[name]["unconstrained_partition_count"] <= 2000
        print(f"{name} independent support: partitions={attempted}, calls={calls}")
        worlds[name] = accepted
    return worlds


@pytest.mark.parametrize("name,card", [("A", "8S"), ("A", "QD"), ("A", "3H"),
    ("B", "9C"), ("B", "3C"), ("C", "KC"), ("C", "2D"), ("C", "10D")])
def test_all_terminal_sets_match_n01_independent_enumerator(cases, independent_worlds, monkeypatch, name, card):
    obs, _ = cases[name]
    chosen = action(obs, card)
    result = all_action_bounds(obs, chosen, SupportBudget())
    counts = Counter()
    # A separate allowance for each root's independent all-path enumeration.
    import evidence_reference
    calls = 0
    real = evidence_reference.apply_action
    def step(state, played):
        nonlocal calls
        assert calls < 100_000
        calls += 1
        return real(state, played)
    with monkeypatch.context() as patch:
        patch.setattr(evidence_reference, "apply_action", step)
        for world in independent_worlds[name].values():
            counts.update(terminal_counts(step(world, chosen), obs.observing_seat % 2))
    expected = {int(k): v for k, v in EXPECTED[name]["all_legal_terminal_path_counts"][card].items()}
    assert counts == expected
    assert result.status is CheckStatus.EXACT_COMPLETE
    assert result.terminal_totals == set(counts)
    assert result.terminal_paths == sum(counts.values())
    expected_outcomes = frozenset(TerminalOutcome(total,
        transition_rising_score(obs.match_score, score_nolo(total, 13-total)).as_tuple())
        for total in counts)
    assert result.outcomes == expected_outcomes
    for witness in result.research_paths:
        replay_witness(obs, witness)
    print(f"{name} {card}: support+traversal={result.engine_transitions}; "
          f"independent traversal={calls}, totals={sorted(counts)}, paths={result.terminal_paths}")


@pytest.mark.parametrize("fault", ["source", "objective", "control", "bound", "observation", "private_input"])
def test_invalid_input_has_distinct_status(cases, fault):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 6)
    if fault == "source":
        cert = replace(cert, source_information_key="wrong")
    elif fault == "objective":
        cert = replace(cert, objective="unapproved equity")
    elif fault == "control":
        cert = replace(cert, control_model="omniscient partnership")
    elif fault == "bound":
        cert = replace(cert, claimed_terminal_bound=-1)
    elif fault == "observation":
        obs = replace(obs, team_tricks=(2, 8))
        cert = replace(cert, source_information_key=semantic_observation_key(obs))
    else:
        obs = {"private": "fixture"}
    result = verify_certificate(obs, cert, SupportBudget())
    assert result.status is CheckStatus.INVALID_INPUT
    assert not result.outcomes


@pytest.mark.parametrize("fault", ["incomplete", "generation_budget", "undercounted_replay"])
def test_false_completeness_provenance_cannot_pass(cases, fault):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 6)
    if fault == "incomplete":
        provenance = replace(cert.provenance, support_status=SupportStatus.SUPPORT_BUDGET)
    elif fault == "generation_budget":
        provenance = replace(cert.provenance, generation_budget=SupportBudget(max_worlds=1))
    else:
        provenance = replace(cert.provenance, generation_engine_transitions=0)
    result = verify_certificate(obs, replace(cert, provenance=provenance), SupportBudget())
    assert result.status is CheckStatus.INCOMPLETE_SUPPORT


def test_budget_counts_replay_traversal_and_comparator(cases, monkeypatch):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 4, next_card="3C", control=ControlModel.SINGLE_SEAT,
                       universal_over="3C")
    actual = 0
    original = apply_action
    def measured(state, action):
        nonlocal actual
        actual += 1
        return original(state, action)
    monkeypatch.setattr(replay_module, "apply_action", measured)
    monkeypatch.setattr(verifier, "apply_action", measured)
    full = verify_certificate(obs, cert, SupportBudget())
    assert full.status is CheckStatus.DISPROVED_UNIVERSAL
    assert actual == full.engine_transitions
    full_calls = actual
    for limit in (0, 1, 94, full_calls-1, full_calls):
        actual = 0
        result = verify_certificate(obs, cert, SupportBudget(max_engine_transitions=limit))
        assert result.engine_transitions == actual == limit
        if limit < full_calls:
            assert result.status is CheckStatus.SEARCH_BUDGET
            assert not result.outcomes and result.bounds is None
            assert result.claim_type is ClaimType.UNCLASSIFIED
        else:
            assert result.status is CheckStatus.DISPROVED_UNIVERSAL
    actual = 0
    limited = verify_certificate(obs, cert, SupportBudget(max_worlds=1))
    assert limited.status is CheckStatus.SUPPORT_BUDGET and actual == 0


def test_all_action_bounds_budget_never_promotes_partial_leaves(cases):
    obs, _ = cases["B"]
    chosen = action(obs, "3C")
    full = all_action_bounds(obs, chosen, SupportBudget())
    short = all_action_bounds(obs, chosen, SupportBudget(max_engine_transitions=full.engine_transitions-1))
    assert short.status is CheckStatus.SEARCH_BUDGET
    assert not short.outcomes and short.terminal_paths == 0


def test_reference_renaming_does_not_change_certificate_or_result(cases):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 4, next_card="3C", control=ControlModel.SINGLE_SEAT)
    original = verify_certificate(obs, cert, SupportBudget())
    renamed = replace(obs, match_ref="renamed-match", deal_ref="renamed-match/deal:2")
    other = verify_certificate(renamed, cert, SupportBudget())
    assert other.diagnostics() == original.diagnostics()
    assert other.outcomes == original.outcomes


def test_immutable_certificate_and_private_witness_boundary(cases):
    obs, _ = cases["B"]
    cert = certificate(cases, "B", "9C", 4, next_card="3H", control=ControlModel.SINGLE_SEAT)
    with pytest.raises(FrozenInstanceError):
        cert.claimed_terminal_bound = 13
    with pytest.raises(TypeError):
        replace(cert, plan=list(cert.plan))
    result = verify_certificate(obs, cert, SupportBudget())
    data = json.dumps(result.diagnostics())
    assert result.counterexample is not None
    for forbidden in ("assignment", "hands", "sample_index", "match_ref", "deal_ref"):
        assert forbidden not in data
        assert forbidden not in repr(result)
