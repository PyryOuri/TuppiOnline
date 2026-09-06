"""All N01 endpoints, including exhaustive tests (no optional slow exclusion)."""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tuppi_agents.void_lead import void_seeking_agents
from tuppi_engine import PlayerObservation, PlayCardAction, apply_action, observation_for
from tuppi_exact.constraints import HardConstraintModel
from tuppi_exact.counting import feasible_assignment_count
from tuppi_exact.solver import solve_late_game
from tuppi_nolo.fixtures import FixtureError, load_fixtures
from tuppi_rules import MatchScore, card_from_code, card_to_code, score_nolo, transition_rising_score

from evidence_reference import (
    assert_at_most, cooperative_value, engine_worlds, hard_assignment_set,
    terminal_counts,
)

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "docs/nolo/tasks"
DATA = json.loads((PACKET / "fixtures.json").read_text())
EXPECTED = {r["id"]: r["expected"] for r in DATA["fixtures"]}


@pytest.fixture(scope="module")
def fixtures():
    return {f.id: f for f in load_fixtures(PACKET / "fixtures.json")}


@pytest.fixture(scope="module")
def evidence_by_id(fixtures):
    cache = {}

    def get(name):
        if name not in cache:
            state = fixtures[name].replay()
            obs = observation_for(state, state.current_actor)
            attempted, worlds = engine_worlds(obs)
            cache[name] = name, state, obs, attempted, worlds
        return cache[name]

    return get


@pytest.fixture(scope="module", params=["A", "B", "C"])
def evidence(request, evidence_by_id):
    return evidence_by_id(request.param)


def oracle_values(state):
    return {card_to_code(a.card): a.team0_tricks_final
            for a in solve_late_game(state).actions}


def test_input_provenance():
    manifest = json.loads((PACKET / "source_manifest.json").read_text())
    drift = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
             for p, h in manifest["sha256"].items()
             if hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != h}
    assert not drift, f"source drift (do not update expected answers): {drift}"
    preparation = json.loads((PACKET / "preparation.json").read_text())
    assert hashlib.sha256((PACKET / "fixtures.json").read_bytes()).hexdigest() == preparation["fixture_sha256"]


def test_replay_observation_baseline_and_actual_oracle(evidence, fixtures):
    name, state, obs, _, _ = evidence
    expected = EXPECTED[name]
    assert isinstance(obs, PlayerObservation)
    assert obs.observing_seat == state.current_actor == expected["actor"]
    assert len(obs.completed_tricks) == expected["completed_tricks"]
    assert len(obs.current_trick) == expected["position"]
    assert list(state.team_tricks) == expected["team_tricks"]
    assert list(map(card_to_code, obs.own_hand)) == expected["own_hand"]
    assert [[card_to_code(c) for c in h] for h in fixtures[name].initial_hands] == next(
        r["initial_hands"] for r in DATA["fixtures"] if r["id"] == name)
    # The baseline receives only the acting observation; never state/fixture/world.
    action = void_seeking_agents()[obs.observing_seat].choose_action(obs)
    assert card_to_code(action.card) == expected["baseline_action"]
    assert oracle_values(state) == expected["actual_layout_minimax"]


def test_complete_support_assignment_sets(evidence):
    name, _, obs, attempted, worlds = evidence
    expected = EXPECTED[name]
    model = HardConstraintModel.build(obs)
    assert attempted == expected["unconstrained_partition_count"]
    assert len(worlds) == feasible_assignment_count(model) == expected["hard_support_count"]
    hard = hard_assignment_set(model)
    assert set(worlds) == hard
    for world in worlds.values():
        other = observation_for(world, obs.observing_seat)
        assert other.own_hand == obs.own_hand
        assert other.legal_actions == obs.legal_actions
        assert other.completed_tricks == obs.completed_tricks
        assert other.current_trick == obs.current_trick
        assert other.show_actions == obs.show_actions


def test_all_legal_terminal_paths(evidence):
    name, _, obs, _, worlds = evidence
    counts = {card_to_code(a.card): Counter() for a in obs.legal_actions}
    for world in worlds.values():
        for action in obs.legal_actions:
            counts[card_to_code(action.card)].update(
                terminal_counts(apply_action(world, action), obs.observing_seat % 2))
    expected = {card: Counter({int(k): v for k, v in values.items()})
                for card, values in EXPECTED[name]["all_legal_terminal_path_counts"].items()}
    assert counts == expected
    if name == "A":
        assert_at_most(counts["8S"], 7)
        with pytest.raises(AssertionError, match="at-most-7"):
            assert_at_most(counts["QD"], 7)
    if name == "C":
        assert all((min(c), max(c)) == (4, 6) for c in counts.values())


def test_b_correct_and_wrong_continuations(evidence_by_id):
    _, _, _, _, worlds = evidence_by_id("B")
    lines = {"3C": Counter(), "3H": Counter()}
    for world in worlds.values():
        after_win = apply_action(world, PlayCardAction(0, card_from_code("9C")))
        assert after_win.current_actor == 0
        next_obs = observation_for(after_win, 0)
        assert card_from_code("3C") in next_obs.own_hand  # Avoidable win counterexample.
        assert card_to_code(void_seeking_agents()[0].choose_action(next_obs).card) == "3H"
        for card in lines:
            after_lead = apply_action(after_win, PlayCardAction(0, card_from_code(card)))
            counts = terminal_counts(after_lead, 0)
            assert counts == ({4: 8} if card == "3C" else {6: 4})
            lines[card].update(counts)
    assert lines == {"3C": {4: 16}, "3H": {6: 8}}
    assert_at_most(lines["3C"], 4)
    with pytest.raises(AssertionError, match="at-most-4"):
        assert_at_most(lines["3H"], 4)


def test_c_minimax_reversals(evidence_by_id):
    _, _, obs, _, worlds = evidence_by_id("C")
    pairs = Counter()
    for world in worlds.values():
        independent = {card_to_code(a.card): cooperative_value(apply_action(world, a), 0)
                       for a in obs.legal_actions}
        assert independent == oracle_values(world)
        pairs[independent["KC"], independent["10D"]] += 1
    assert pairs == {(4, 6): 6, (4, 5): 6, (6, 5): 6, (6, 6): 3, (4, 4): 3}
    assert {str(k): v for k, v in pairs.items()} == EXPECTED["C"]["cooperative_minimax_pair_counts_KC_10D"]
    assert any(kc < diamond for kc, diamond in pairs)
    assert any(diamond < kc for kc, diamond in pairs)


@pytest.mark.parametrize("corruption,match", [
    ("schema", "schema"), ("duplicate", "52 unique"), ("missing", "13 cards"),
    ("dealer", "dealer"), ("boolean_dealer", "dealer"), ("illegal", "illegal prefix"),
    ("group", "final prefix group"), ("card", "card code"),
])
def test_corrupted_input_rejected(tmp_path, corruption, match):
    data = deepcopy(DATA)
    record = data["fixtures"][0]
    if corruption == "schema":
        data["schema_version"] = "unknown"
    elif corruption == "duplicate":
        record["initial_hands"][0][0] = record["initial_hands"][1][0]
    elif corruption == "missing":
        record["initial_hands"][0].pop()
    elif corruption == "dealer":
        record["dealer"] = 4
    elif corruption == "boolean_dealer":
        record["dealer"] = True
    elif corruption == "illegal":
        record["play_prefix"][0][0] = "AC"  # Not held by the opening actor.
    elif corruption == "group":
        record["play_prefix"][0].pop()
    elif corruption == "card":
        record["initial_hands"][0][0] = "XX"
    path = tmp_path / "corrupt.json"
    path.write_text(json.dumps(data))
    with pytest.raises(FixtureError, match=match):
        load_fixtures(path)


def test_scoring_corrections():
    eight, nine = score_nolo(8, 5), score_nolo(9, 4)
    assert (eight.points, nine.points) == (8, 12)
    assert transition_rising_score(MatchScore(0, 40), eight) == MatchScore(0, 48)
    assert transition_rising_score(MatchScore(0, 40), nine) == MatchScore(0, 52)
    for winning_total in range(7):
        assert transition_rising_score(MatchScore(0, 40), score_nolo(winning_total, 13-winning_total)) == MatchScore(0, 0)
    for losing_total in range(7, 14):
        assert transition_rising_score(MatchScore(40, 0), score_nolo(losing_total, 13-losing_total)) == MatchScore(0, 0)
