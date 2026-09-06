"""N02 correctness, support completeness, visibility and deterministic budgets."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tuppi_engine import (EnginePhase, ExplicitDeal, PlayCardAction, apply_action,
                          create_deal_state, observation_for)
from tuppi_exact import continuation as replay_module
from tuppi_exact.constraints import HardConstraintModel, derive_show_exclusions
from tuppi_exact.continuation import hypothetical_continuation
from tuppi_nolo import support
from tuppi_nolo.fixtures import load_fixtures
from tuppi_nolo.support import (INDEPENDENT_PARTITION_LIMIT, ResearchWorld,
    SupportBudget, SupportInvariantError, SupportStatus, build_support,
    semantic_observation_key)
from tuppi_rules import (Color, Contract, FULL_DECK, MatchScore, card_from_code,
                        card_to_index)
from tuppi_exact.constraints import ELIGIBLE_SHOW_CARDS, ELIGIBLE_SHOW_CARDS_BY_COLOR
from tuppi_valuation.corpus import forced_show_action

from evidence_reference import assignment_key, engine_worlds

PACKET = Path(__file__).resolve().parents[2] / "docs/nolo/tasks"


@pytest.fixture(scope="module")
def positions():
    return {f.id: f.replay() for f in load_fixtures(PACKET / "fixtures.json")}


def obs_for(state, seat=None):
    return observation_for(state, state.current_actor if seat is None else seat)


def contents(result):
    return tuple(w.content_key for w in result.research_worlds)


@pytest.fixture(scope="module")
def supports(positions):
    return {name: build_support(obs_for(s), SupportBudget()) for name, s in positions.items()}


def reference_with_budget(obs, monkeypatch):
    """Independent verification budget, separate from each build_support call."""
    calls = 0
    original = replay_module.apply_action

    def measured(state, action):
        nonlocal calls
        assert calls < 100_000, "independent verification transition budget"
        calls += 1
        return original(state, action)

    # Check the fixed unconstrained partition ceiling before enumerating.
    from math import factorial
    played = [p for t in obs.completed_tricks for p in t.plays] + list(obs.current_trick)
    sizes = [13-sum(p.seat == s for p in played) for s in range(4) if s != obs.observing_seat]
    partitions = factorial(sum(sizes))
    for size in sizes:
        partitions //= factorial(size)
    assert partitions <= INDEPENDENT_PARTITION_LIMIT
    with monkeypatch.context() as patch:
        patch.setattr(replay_module, "apply_action", measured)
        attempted, worlds = engine_worlds(obs)
    assert attempted == partitions
    return attempted, worlds, calls


@pytest.mark.parametrize("name,count,partitions,calls", [
    ("A", 20, 560, 900), ("B", 2, 90, 94), ("C", 24, 90, 1128),
])
def test_complete_support_matches_independent_engine_set(
    positions, supports, monkeypatch, name, count, partitions, calls
):
    state, result = positions[name], supports[name]
    attempted, accepted, verification_calls = reference_with_budget(obs_for(state), monkeypatch)
    assert result.status is SupportStatus.EXACT_COMPLETE
    assert result.world_count == result.counted_candidates == count
    assert result.assignments_attempted == count
    assert result.engine_transitions == calls
    assert len(set(contents(result))) == count
    assert set(contents(result)) == set(accepted)
    assert assignment_key(state.hands) in accepted
    assert attempted == partitions
    assert verification_calls > 0
    print(f"{name}: independent attempts={attempted}, accepted={len(accepted)}, "
          f"verification_calls={verification_calls}; support_calls={result.engine_transitions}")
    obs = obs_for(state)
    model = HardConstraintModel.build(obs)
    for world in result.research_worlds:
        assert world.continuation.is_hypothetical
        assert world.assignment.hands[obs.observing_seat] == obs.own_hand
        assert semantic_observation_key(obs_for(world.continuation.state)) == result.decision_key
        for seat in range(4):
            assert model.known_held[seat] <= set(world.assignment.hands[seat])
            assert not model.show_exclusions[seat] & set(world.assignment.hands[seat])
            assert all(c.suit not in model.void_suits[seat] for c in world.assignment.hands[seat])


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_hidden_layout_and_reference_renaming_preserve_semantics(positions, supports, name):
    original = supports[name]
    # Distinct hidden worlds, identical observing seat's own/public information.
    first, last = original.research_worlds[0], original.research_worlds[-1]
    assert first.content_key != last.content_key
    for world in (first, last):
        obs = obs_for(world.continuation.state)
        renamed = replace(obs, match_ref="renamed-match", deal_ref="renamed-match/deal:4")
        assert semantic_observation_key(renamed) == original.decision_key
        changed_sample = replace(world.assignment, sample_index=98765)
        rebuilt = hypothetical_continuation(renamed, changed_sample, match_ref="hypothetical:renamed")
        assert ResearchWorld(changed_sample, rebuilt).content_key == world.content_key
        result = build_support(obs_for(rebuilt.state), SupportBudget())
        assert result.diagnostics() == original.diagnostics()
        assert contents(result) == contents(original)
    again = build_support(obs_for(positions[name]), SupportBudget())
    assert contents(again) == contents(original)
    assert again.diagnostics() == original.diagnostics()


def test_key_retains_own_order_actions_and_score(positions):
    obs = obs_for(positions["A"])
    key = semantic_observation_key(obs)
    assert key != semantic_observation_key(replace(obs, own_hand=obs.own_hand[::-1],
                                                    legal_actions=obs.legal_actions[::-1]))
    assert key != semantic_observation_key(replace(obs, match_score=MatchScore(0, 40)))
    assert key != semantic_observation_key(obs_for(positions["A"], 0))


@pytest.mark.parametrize("name", ["A", "B", "C"])
@pytest.mark.parametrize("limit", [0, 1])
def test_world_limit_counts_before_replay(positions, monkeypatch, name, limit):
    def forbidden(*args, **kwargs):
        pytest.fail("over-budget support must not enumerate assignments")
    monkeypatch.setattr(support, "_assignments", forbidden)
    result = build_support(obs_for(positions[name]), SupportBudget(max_worlds=limit))
    assert result.status is SupportStatus.SUPPORT_BUDGET
    assert result.counted_candidates == {"A": 20, "B": 2, "C": 24}[name]
    assert result.world_count is None and result.research_worlds == ()
    assert result.engine_transitions == result.assignments_attempted == 0


@pytest.mark.parametrize("limit", [0, 1, 45, 899, 900])
def test_actual_replay_calls_obey_budget_without_global_mutation(positions, monkeypatch, limit):
    calls = 0
    real = replay_module.apply_action

    def measured(state, action):
        nonlocal calls
        calls += 1
        return real(state, action)

    monkeypatch.setattr(replay_module, "apply_action", measured)
    result = build_support(obs_for(positions["A"]), SupportBudget(max_engine_transitions=limit))
    assert replay_module.apply_action is measured
    assert calls == result.engine_transitions == limit
    if limit == 900:
        assert result.status is SupportStatus.EXACT_COMPLETE
        assert result.world_count == 20
    else:
        assert result.status is SupportStatus.SEARCH_BUDGET
        assert result.world_count is None and not result.research_worlds
        assert result.counted_candidates == 20
    # Independent repeated operation gets a fresh meter even with a warm counter cache.
    again = build_support(obs_for(positions["A"]), SupportBudget(max_engine_transitions=limit))
    assert again.diagnostics() == result.diagnostics()
    assert calls == 2 * limit


def test_avoidable_win_keeps_lower_card_possible_for_opponent(positions, monkeypatch):
    state = apply_action(positions["B"], PlayCardAction(0, card_from_code("9C")))
    obs = obs_for(state, 1)  # Seat 0's remaining cards are hidden from this opponent.
    assert card_from_code("3C") not in obs.own_hand
    result = build_support(obs, SupportBudget())
    assert result.status is SupportStatus.EXACT_COMPLETE
    assert assignment_key(state.hands) in contents(result)
    assert any(card_from_code("3C") in w.assignment.hands[0] for w in result.research_worlds)
    _, independent, calls = reference_with_budget(obs, monkeypatch)
    assert set(contents(result)) == set(independent)
    print(f"B after 9C, observer 1: worlds={result.world_count}, "
          f"support_calls={result.engine_transitions}, verification_calls={calls}")


@pytest.mark.parametrize("level", [2, 3])
def test_showing_fallback_exclusions_through_support(level, monkeypatch):
    codes = ("2C 10C JC QC KC AC 2S 10S JS QS KS AS 5H" if level == 2 else
             "2H 10H JH QH KH AH 2D 10D JD QD KD AD 2C")
    own = tuple(map(card_from_code, codes.split()))
    rest = sorted(set(FULL_DECK) - set(own), key=card_to_index)
    hands = (own,) + tuple(tuple(rest[i:i+13]) for i in range(0, 39, 13))
    state = create_deal_state(ExplicitDeal(dealer=3, hands=hands),
        starting_score=MatchScore(0, 0), match_ref="fallback", deal_ref="fallback/deal:0",
        deal_number=0, event_start_index=0)
    while state.phase is EnginePhase.SHOWING:
        state = apply_action(state, forced_show_action(obs_for(state), Contract.NOLO))
    assert state.show_actions[0].verbal_required
    while len(state.completed_tricks) < 12:
        state = apply_action(state, obs_for(state).legal_actions[0])
    obs = obs_for(state, 1)
    exclusion = derive_show_exclusions(obs)[0]
    assert exclusion == (ELIGIBLE_SHOW_CARDS_BY_COLOR[Color.BLACK] if level == 2 else ELIGIBLE_SHOW_CARDS)
    result = build_support(obs, SupportBudget())
    assert result.status is SupportStatus.EXACT_COMPLETE
    assert assignment_key(state.hands) in contents(result)
    assert all(not exclusion & set(w.assignment.hands[0]) for w in result.research_worlds)
    _, accepted, _ = reference_with_budget(obs, monkeypatch)
    assert set(contents(result)) == set(accepted)


@pytest.mark.parametrize("corruption", ["shown_owner", "fallback", "played_show_owner", "winner", "legal", "own_duplicate"])
def test_contradictory_evidence_is_invalid(positions, corruption):
    obs = obs_for(positions["A"])
    if corruption in ("shown_owner", "fallback"):
        shows = list(obs.show_actions)
        if corruption == "shown_owner":
            # Valid priority-3 show in isolation, but seat 1 is publicly heart-void.
            codes = "2H 10H JH QH KH AH 2D 10D JD QD KD AD 2C"
            shown = "2H"
        else:
            # Valid priority-2 fallback in isolation, contradicted by seat 1's
            # already-played eligible black cards.
            codes = "2H 3H 4H 5H 6H 7H 8H 9H 10H JH QH KH AH"
            shown = "5H"
        shows[1] = type(shows[1])(
            seat=1, hand=tuple(map(card_from_code, codes.split())),
            shown_card=card_from_code(shown), declared_contract=Contract.NOLO)
        obs = replace(obs, show_actions=tuple(shows),
                      publicly_shown_cards=tuple((s.seat, s.shown_card) for s in shows))
    elif corruption == "played_show_owner":
        # The existing model ignores shown ownership once a card is played.
        # The entry boundary must still reject ownership inconsistent with history.
        shows = list(obs.show_actions)
        shown = card_from_code("7C")  # Publicly played by seat 1, not seat 0.
        hand = (shown,) + tuple(c for c in FULL_DECK if c != shown)[:12]
        shows[0] = type(shows[0])(seat=0, hand=hand, shown_card=shown,
                                 declared_contract=Contract.NOLO)
        obs = replace(obs, show_actions=tuple(shows),
                      publicly_shown_cards=tuple((s.seat, s.shown_card) for s in shows))
    elif corruption == "winner":
        obs = replace(obs, team_tricks=(6, 4))
    elif corruption == "legal":
        obs = replace(obs, legal_actions=obs.legal_actions[:1])
    else:
        obs = replace(obs, own_hand=(obs.own_hand[0],)*3)
    result = build_support(obs, SupportBudget())
    assert result.status is SupportStatus.INVALID_INPUT
    assert result.world_count is None and not result.research_worlds
    assert result.engine_transitions == 0


def test_rejects_private_or_wrong_input_types(positions):
    for obj in (positions["A"], json.loads((PACKET / "fixtures.json").read_text()), object()):
        with pytest.raises(TypeError, match="PlayerObservation"):
            build_support(obj, SupportBudget())
        with pytest.raises(TypeError, match="PlayerObservation"):
            semantic_observation_key(obj)
    with pytest.raises(TypeError, match="SupportBudget"):
        build_support(obs_for(positions["A"]), 100)


@pytest.mark.parametrize("field,value", [("max_worlds", -1), ("max_worlds", True),
    ("max_worlds", 101), ("max_remaining_tricks", 4), ("max_engine_transitions", 100001)])
def test_budget_cannot_silently_expand_frozen_scope(field, value):
    with pytest.raises(ValueError):
        SupportBudget(**{field: value})


def test_out_of_scope_returns_no_claim(positions):
    obs = obs_for(positions["A"])
    for observation, budget in ((obs, SupportBudget(max_remaining_tricks=2)),
                               (replace(obs, contract=Contract.RAMI), SupportBudget()),
                               (replace(obs, contract=None), SupportBudget())):
        result = build_support(observation, budget)
        assert result.status is SupportStatus.OUT_OF_SCOPE
        assert result.world_count is None and result.research_worlds == ()
        assert result.engine_transitions == 0


@pytest.mark.parametrize("fault", ["missing", "duplicate", "illegal"])
def test_enumerator_errors_never_shrink_exact_support(positions, monkeypatch, fault):
    obs = obs_for(positions["B"])
    candidates = list(support._assignments(HardConstraintModel.build(obs), obs))
    if fault == "missing":
        candidates.pop()
    elif fault == "duplicate":
        candidates.append(candidates[0])
    else:
        hands = [list(h) for h in candidates[0].hands]
        # Force the publicly shown 7C out of seat 1's hand.
        card = card_from_code("7C")
        other = hands[2][0]
        hands[1].remove(card)
        hands[1].append(other)
        hands[2].remove(other)
        hands[2].append(card)
        candidates[0] = replace(candidates[0], hands=tuple(tuple(h) for h in hands))
    monkeypatch.setattr(support, "_assignments", lambda *args: iter(candidates))
    with pytest.raises(SupportInvariantError):
        build_support(obs, SupportBudget())


def test_unexpected_errors_propagate(positions, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("programming fault")
    monkeypatch.setattr(support, "feasible_assignment_count", broken)
    with pytest.raises(RuntimeError, match="programming fault"):
        build_support(obs_for(positions["A"]), SupportBudget())


def test_diagnostics_do_not_contain_private_worlds(supports):
    for result in supports.values():
        data = result.diagnostics()
        assert "research_worlds" not in repr(result)
        assert data["claim_type"] == "UNCLASSIFIED"
        assert not any(token in json.dumps(data) for token in
                       ("hands", "owner", "sample_index", "match_ref", "deal_ref", "weight", "probability"))


def test_nonacting_observer_with_empty_hand_is_not_falsely_excluded(positions, monkeypatch):
    state = positions["A"]
    while len(state.completed_tricks) < 12:
        state = apply_action(state, obs_for(state).legal_actions[0])
    observer = state.current_actor
    state = apply_action(state, obs_for(state).legal_actions[0])
    obs = obs_for(state, observer)
    assert obs.own_hand == obs.legal_actions == ()
    result = build_support(obs, SupportBudget())
    assert result.status is SupportStatus.EXACT_COMPLETE
    assert assignment_key(state.hands) in contents(result)
    _, accepted, _ = reference_with_budget(obs, monkeypatch)
    assert set(contents(result)) == set(accepted)
