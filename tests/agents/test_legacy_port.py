from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tuppi_agents import (
    Provenance,
    construct_agent,
    phase4_specifications_by_profile_key,
    require_profile,
    rules_for_profile,
)
from tuppi_agents.legacy_formulas import (
    expected_value_nolo,
    expected_value_rami,
    nolo_hand_index,
    rami_strength,
)
from tuppi_engine import (
    ExplicitDeal,
    PlayCardAction,
    ShowAction,
    action_from_data,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_legacy.heuristic_oracle import (
    TARGET_EQUIVALENT_BANNED_RANKS,
    legacy_play_choice,
    legacy_show_choice,
)
from tuppi_rules import ELIGIBLE_SHOW_RANKS, MatchScore, card_from_code, card_to_code

from .conftest import cards


ROOT = Path(__file__).resolve().parents[2]
AGENTS_SOURCE = ROOT / "src" / "tuppi_agents"
FIXTURE_PATH = ROOT / "examples" / "agents" / "legacy_port_compatibility.json"


@pytest.fixture(scope="module")
def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _start(deal: dict):
    hands = tuple(
        tuple(card_from_code(code) for code in hand) for hand in deal["hands"]
    )
    state = create_match(
        initial_score=MatchScore(*deal["starting_score"]),
        initial_dealer=deal["dealer"],
        match_ref="compat-replay",
    )
    return begin_explicit_deal(state, ExplicitDeal(dealer=deal["dealer"], hands=hands))


def _replay(deal: dict, prefix_length: int):
    state = _start(deal)
    for entry in deal["action_sequence"][:prefix_length]:
        state = apply_match_action(state, action_from_data(entry))
    return state


def _walk(deal: dict):
    """Yield ``(position, state)`` once per decision, replaying each deal once."""

    state = _start(deal)
    by_prefix = {item["action_prefix_length"]: item for item in deal["positions"]}
    for index, entry in enumerate(deal["action_sequence"]):
        position = by_prefix.get(index)
        if position is not None:
            yield position, state
        state = apply_match_action(state, action_from_data(entry))


# ------------------------------------------------- runtime isolation guarantees


def test_no_module_in_tuppi_agents_imports_the_legacy_package() -> None:
    for path in sorted(AGENTS_SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        roots = {name.split(".", 1)[0] for name in names}
        assert "tuppi_legacy" not in roots, path
        assert not roots.intersection(
            {"random", "secrets", "numpy", "torch", "tensorflow"}
        ), path


def test_constructing_and_running_the_port_loads_no_legacy_module() -> None:
    """Play a whole deal with the port in a clean interpreter and prove that
    neither ``tuppi_legacy`` nor the frozen module was ever imported.

    This runs in a subprocess on purpose: inside the shared test session the
    characterization fixtures load the Archive deliberately, which would mask
    exactly the property this guards.
    """

    program = """
import sys
from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import ExplicitDeal, begin_explicit_deal, create_match, play_active_deal
from tuppi_rules import FULL_DECK, MatchScore

specification = phase4_specifications_by_profile_key()["legacy_heuristic_port_v1"]
agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
hands = tuple(tuple(FULL_DECK[seat::4]) for seat in range(4))
state = create_match(initial_score=MatchScore(), initial_dealer=0, match_ref="isolation")
state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
state = play_active_deal(state, agents)
assert sum(state.completed_deals[-1].public_result.team_tricks) == 13
leaked = sorted(
    name
    for name in sys.modules
    if name.startswith("tuppi_legacy") or name.startswith("_tuppi_frozen_legacy")
)
print("LEAKED:" + ",".join(leaked))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    assert "LEAKED:\n" in completed.stdout or completed.stdout.strip() == "LEAKED:", (
        f"the port imported legacy code: {completed.stdout!r}"
    )


def _executable_identifiers(path: Path) -> set[str]:
    """Return every identifier a module actually executes, ignoring prose."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(alias.name for alias in node.names)
    return found


# Modules that never participate in a decision: specification builders, the
# Phase 3 arena harness, the CLI, and the performance measurement. They may
# legitimately mention Phase 3 vocabulary such as ``FIXED_SAMPLE`` or
# ``rollout_budget=None``.
HARNESS_MODULES = frozenset(
    {
        "__init__.py",
        "benchmark.py",
        "controls.py",
        "evaluation.py",
        "factory.py",
        "registry.py",
        "runner.py",
    }
)

# Tokens that would betray a search or a hidden-hand sampler anywhere in the
# package, harness included.
GLOBALLY_FORBIDDEN = (
    "montecarlo",
    "pimc",
    "ismcts",
    "playout",
    "determinize",
    "determinization",
    "shuffle",
    "randint",
    "randrange",
    "estimate_value",
    "simulate",
)

# Additional tokens forbidden in the policy layer, where any appearance of
# sampling vocabulary would be a genuine violation.
POLICY_FORBIDDEN = ("rollout", "sample", "choice", "belief", "particle")


def test_the_port_contains_no_monte_carlo_or_rollout_code() -> None:
    for path in sorted(AGENTS_SOURCE.glob("*.py")):
        identifiers = {name.lower() for name in _executable_identifiers(path)}
        for token in GLOBALLY_FORBIDDEN:
            assert not any(token in name for name in identifiers), (
                f"{path.name} executes an identifier containing {token!r}"
            )
        if path.name in HARNESS_MODULES:
            continue
        for token in POLICY_FORBIDDEN:
            assert not any(token in name for name in identifiers), (
                f"policy module {path.name} executes an identifier "
                f"containing {token!r}"
            )


def test_the_port_specification_declares_no_search_and_no_seed() -> None:
    specification = phase4_specifications_by_profile_key()["legacy_heuristic_port_v1"]
    assert specification.search_budget is None
    assert specification.seed_policy.value == "none"
    assert specification.determinism.value == "deterministic"
    with pytest.raises(Exception):
        construct_agent(specification, seat=0, seed="anything")


# ------------------------------------------------------ compatibility fixtures


def test_fixture_metadata_pins_the_frozen_artifact(fixture: dict) -> None:
    from tuppi_legacy.constants import ARTIFACT_ID, EMULATOR_SHA256

    assert fixture["schema_version"] == "tuppi.agents.legacy_compatibility_fixture.v1"
    assert fixture["legacy_artifact_id"] == ARTIFACT_ID
    assert fixture["legacy_emulator_sha256"] == EMULATOR_SHA256
    assert fixture["legacy_show_banned_ranks"] == list(TARGET_EQUIVALENT_BANNED_RANKS)
    assert "not claimed" in fixture["equivalence_claim"]
    assert fixture["position_count"] >= 100
    assert fixture["compatible_position_count"] >= 100


def test_the_port_reproduces_every_curated_fixture_action(fixture: dict) -> None:
    from tuppi_engine import action_to_data

    specification = phase4_specifications_by_profile_key()["legacy_heuristic_port_v1"]
    checked = 0
    for deal in fixture["deals"]:
        for position, state in _walk(deal):
            actor = state.current_actor
            assert actor == position["acting_seat"]
            assert state.phase.value == position["phase"]
            observation = match_observation_for(state, actor)
            agent = construct_agent(specification, seat=actor)
            action = agent.choose_action(observation)
            assert action_to_data(action) == position["expected_action"]
            checked += 1
    assert checked == fixture["position_count"]


def test_the_frozen_archive_agrees_on_every_compatible_position(fixture: dict) -> None:
    """The Archive is the historical oracle for these curated positions only."""

    agreed = 0
    for deal in fixture["deals"]:
        for position, state in _walk(deal):
            if not position["compatible"]:
                continue
            actor = state.current_actor
            observation = match_observation_for(state, actor)
            expected = position["expected_action"]
            if expected["type"] == "show":
                choice = legacy_show_choice(observation)
                assert choice.contract.value == expected["declared_contract"]
                assert choice.verbal is False
                assert card_to_code(choice.card) == expected["shown_card"]
            else:
                assert card_to_code(legacy_play_choice(observation)) == expected["card"]
            agreed += 1
    assert agreed == fixture["compatible_position_count"]


def test_documented_deviations_are_demonstrated_by_real_positions(fixture: dict) -> None:
    deviations = {item["deviation"]: item for item in fixture["deviation_positions"]}
    assert set(deviations) == {
        "legacy_cardless_verbal_declaration",
        "legacy_show_rank_set_is_wider",
    }

    verbal = deviations["legacy_cardless_verbal_declaration"]
    assert verbal["legacy_verbal"] is True
    assert verbal["legacy_card"] is None
    assert verbal["port_action"]["type"] == "show"
    assert verbal["legacy_contract"] == verbal["port_action"]["declared_contract"]
    shown = card_from_code(verbal["port_action"]["shown_card"])
    assert shown.rank in ELIGIBLE_SHOW_RANKS

    wider = deviations["legacy_show_rank_set_is_wider"]
    assert wider["legacy_card"] is not None
    legacy_card = card_from_code(wider["legacy_card"])
    assert legacy_card.rank not in ELIGIBLE_SHOW_RANKS
    assert wider["port_action"]["shown_card"] != wider["legacy_card"]


def test_port_showing_always_respects_target_eligibility(fixture: dict) -> None:
    from tuppi_rules import (
        Contract,
        card_color,
        contract_color,
        valid_show_cards,
    )

    for deal in fixture["deals"]:
        hands = tuple(
            tuple(card_from_code(code) for code in hand) for hand in deal["hands"]
        )
        for entry in deal["action_sequence"]:
            if entry["type"] != "show":
                continue
            seat = entry["seat"]
            contract = Contract(entry["declared_contract"])
            shown = card_from_code(entry["shown_card"])
            allowed = valid_show_cards(hands[seat], contract)
            assert shown in allowed
            eligible_matching = [
                item
                for item in hands[seat]
                if item.rank in ELIGIBLE_SHOW_RANKS
                and card_color(item) is contract_color(contract)
            ]
            if eligible_matching:
                # The port shows the lowest eligible rank of the wanted colour.
                assert shown.rank.value == min(
                    item.rank.value for item in eligible_matching
                )


# ------------------------------------------------------------- ported formulas


def test_ported_formulas_match_the_frozen_implementations() -> None:
    from tuppi_legacy.legacy_loader import load_legacy_module
    from tuppi_legacy.heuristic_oracle import to_legacy_card

    legacy = load_legacy_module()
    hands = [
        cards(["HA", "HK", "HQ", "HJ", "H10", "H2", "DA", "DK", "D10", "D2", "C3", "C4", "S5"]),
        cards(["H3", "H4", "H5", "D3", "D4", "C3", "C4", "C5", "S3", "S4", "S5", "S6", "S7"]),
        cards(["HA", "DA", "CA", "SA", "HK", "DK", "CK", "SK", "HQ", "DQ", "CQ", "SQ", "HJ"]),
    ]
    for hand in hands:
        legacy_hand = [to_legacy_card(item) for item in hand]
        assert rami_strength(hand) == legacy.rami_strength_RS(legacy_hand)
        assert nolo_hand_index(hand) == legacy.nolo_hand_index_NHI(legacy_hand)
        assert expected_value_rami(rami_strength(hand)) == (
            legacy.approx_EV_rami_from_RS(legacy.rami_strength_RS(legacy_hand))
        )
        assert expected_value_nolo(nolo_hand_index(hand)) == (
            legacy.approx_EV_nolo_from_NHI(legacy.nolo_hand_index_NHI(legacy_hand))
        )


def test_ported_liability_table_matches_the_frozen_weights() -> None:
    from tuppi_agents.legacy_formulas import nolo_discard_liability

    expected = {"A": 4.0, "K": 3.0, "Q": 2.0, "J": 1.0, "10": 0.5, "9": 0.25, "8": 0.0}
    for rank, weight in expected.items():
        assert nolo_discard_liability(card_from_code(f"{rank}H")) == weight


def test_every_port_rule_is_legacy_or_mechanical_and_never_expert() -> None:
    profile = require_profile("legacy_heuristic_port_v1")
    rules = rules_for_profile(profile.profile_key)
    assert rules
    for rule in rules:
        assert rule.provenance in (Provenance.LEGACY_PORT, Provenance.MECHANICAL)
        assert rule.provenance is not Provenance.EXPERT_VALIDATED
    assert any(rule.provenance is Provenance.LEGACY_PORT for rule in rules)


def test_the_port_never_returns_an_illegal_action(fixture: dict) -> None:
    specification = phase4_specifications_by_profile_key()["legacy_heuristic_port_v1"]
    for deal in fixture["deals"][:2]:
        for position in deal["positions"]:
            state = _replay(deal, position["action_prefix_length"])
            actor = state.current_actor
            observation = match_observation_for(state, actor)
            action = construct_agent(specification, seat=actor).choose_action(observation)
            assert action in observation.legal_actions
            assert isinstance(action, (ShowAction, PlayCardAction))
