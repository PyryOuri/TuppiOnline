from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from tuppi_rules import (
    CARD_ENCODING_ID,
    CARDS_PER_HAND,
    CARDS_PER_TRICK,
    DECK_SIZE,
    ELIGIBLE_SHOW_RANKS,
    FULL_DECK,
    MATCH_TARGET,
    PLAYER_COUNT,
    RANK_ORDER,
    RULESET_ID,
    RULESET_VERSION,
    SUIT_ORDER,
    TRICKS_PER_DEAL,
    Color,
    Card,
    Contract,
    MatchScore,
    PlayedCard,
    Rank,
    RulesetId,
    Suit,
    Team,
    card_color,
    contract_color,
    first_leader,
    forehand,
    is_match_terminal,
    legal_cards,
    resolve_showing,
    rotate_dealer,
    score_nolo,
    score_rami,
    team_for_seat,
    transition_rising_score,
    trick_winner,
    valid_show_cards,
    validate_show_action,
)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "configs/rules/project_target_v1.json"
SCHEMA_PATH = ROOT / "schemas/ruleset.schema.json"


def load_documents():
    return (
        json.loads(CONFIG_PATH.read_text(encoding="utf-8")),
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
    )


def test_schema_is_valid_and_project_configuration_validates() -> None:
    config, schema = load_documents()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(config)


@pytest.mark.parametrize("missing", ["provenance", "showing", "deal_scoring", "match"])
def test_missing_required_configuration_domains_fail(missing: str) -> None:
    config, schema = load_documents()
    del config[missing]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(config)


def test_unknown_root_or_nested_configuration_fields_fail() -> None:
    config, schema = load_documents()
    config["unknown"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(config)

    config, schema = load_documents()
    config["showing"]["unknown"] = True
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(config)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("ruleset_id",), "legacy_v9_unverified"),
        (("deck", "trump"), "spades"),
        (("deck", "card_serialization", "order"), "rank_major_then_suit"),
        (("showing", "eligible_ranks"), [3, 4, 5, 6, 7, 8, 9, 10]),
        (("showing", "shown_card_retained_in_hand"), False),
        (("contracts", "rami_declaring_team"), "caller_selected_team"),
        (("deal", "tricks_per_completed_deal"), 7),
        (("deal", "early_termination"), True),
        (("deal_scoring", "RAMI", "stolen", "formula", "factor"), 4),
        (("match", "target_score"), 51),
        (("match", "terminal_comparison"), "equal"),
        (("match", "down_team_reset_awards_points"), True),
    ],
)
def test_contradictory_configuration_values_fail(path, value) -> None:
    config, schema = load_documents()
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(config)


def test_executable_constants_and_relations_agree_with_configuration() -> None:
    config, _ = load_documents()
    assert RULESET_ID is RulesetId.PROJECT_TARGET_V1
    assert RULESET_ID.value == config["ruleset_id"]
    assert RULESET_VERSION == config["ruleset_version"]
    assert PLAYER_COUNT == config["players"]["count"]
    assert DECK_SIZE == config["deck"]["card_count"]
    assert CARDS_PER_HAND == config["deck"]["cards_per_hand"]
    assert CARD_ENCODING_ID == config["deck"]["card_serialization"]["encoding_id"]
    assert len(FULL_DECK) == config["deck"]["card_count"]
    assert tuple(suit.value for suit in SUIT_ORDER) == tuple(
        config["deck"]["suit_serialization_order"]
    )
    assert tuple(rank.value for rank in RANK_ORDER) == tuple(
        config["deck"]["rank_order_low_to_high"]
    )
    assert {rank.value for rank in ELIGIBLE_SHOW_RANKS} == set(
        config["showing"]["eligible_ranks"]
    )
    for suit in SUIT_ORDER:
        assert card_color(next(card for card in FULL_DECK if card.suit is suit)).value == config[
            "deck"
        ]["suit_colors"][suit.value]
    for contract in Contract:
        assert contract_color(contract).value == config["showing"]["contract_colors"][
            contract.value
        ]
    assert [team_for_seat(seat).value for seat in range(4)] == [0, 1, 0, 1]
    assert [forehand(seat) for seat in range(4)] == [1, 2, 3, 0]
    assert [rotate_dealer(seat) for seat in range(4)] == [1, 2, 3, 0]
    assert CARDS_PER_TRICK == config["trick_play"]["cards_per_trick"]
    assert TRICKS_PER_DEAL == config["deal"]["tricks_per_completed_deal"]
    assert MATCH_TARGET == config["match"]["target_score"]
    assert config["players"]["partnerships"] == {
        "team_0": [seat for seat in range(4) if team_for_seat(seat) is Team.TEAM_0],
        "team_1": [seat for seat in range(4) if team_for_seat(seat) is Team.TEAM_1],
    }

    configured_deck = tuple(
        Card(Suit(suit), Rank(rank))
        for suit in config["deck"]["suit_serialization_order"]
        for rank in config["deck"]["rank_order_low_to_high"]
    )
    assert config["deck"]["card_serialization"]["order"] == (
        "suit_major_then_rank_low_to_high"
    )
    assert config["deck"]["card_serialization"]["index_min"] == 0
    assert config["deck"]["card_serialization"]["index_max"] == 51
    assert configured_deck == FULL_DECK


def test_machine_semantics_agree_with_executable_behavior() -> None:
    config, _ = load_documents()

    hierarchy = config["showing"]["fallback_hierarchy"]
    normal_hand = tuple(FULL_DECK[:13])
    normal_card = Card(Suit.HEARTS, Rank.THREE)
    normal = validate_show_action(
        seat=1,
        hand=normal_hand,
        shown_card=normal_card,
        declared_contract=Contract.RAMI,
    )
    assert normal.verbal_required is hierarchy[0]["verbal_required"]
    assert normal.shown_card in normal_hand
    assert config["showing"]["shown_card_retained_in_hand"] is True

    mismatch_hand = tuple(FULL_DECK[26:39])
    mismatch = validate_show_action(
        seat=1,
        hand=mismatch_hand,
        shown_card=Card(Suit.CLUBS, Rank.THREE),
        declared_contract=Contract.RAMI,
    )
    assert mismatch.verbal_required is hierarchy[1]["verbal_required"]

    ineligible = tuple(card for card in FULL_DECK if card.rank.value not in range(3, 10))[:13]
    fallback = validate_show_action(
        seat=1,
        hand=ineligible,
        shown_card=ineligible[0],
        declared_contract=Contract.RAMI,
    )
    assert fallback.verbal_required is hierarchy[2]["verbal_required"]
    assert valid_show_cards(ineligible, Contract.RAMI) == frozenset(ineligible)

    resolution = resolve_showing(dealer=0, actions=(normal,))
    assert resolution.contract is Contract.RAMI
    assert len(resolution.actions) == 1
    assert config["showing"]["termination"].startswith("immediately_after_first_rami")
    assert config["contracts"]["rami_declaring_team"] == (
        "partnership_containing_first_rami_declarer"
    )

    for dealer in range(4):
        assert first_leader(
            contract=Contract.NOLO, dealer=dealer, declarer=None
        ) == forehand(dealer)
        for declarer in range(4):
            assert first_leader(
                contract=Contract.RAMI, dealer=dealer, declarer=declarer
            ) == (declarer + config["contracts"]["first_leader"]["RAMI"]["offset"]) % 4

    hand = (
        Card(Suit.HEARTS, Rank.TWO),
        Card(Suit.CLUBS, Rank.ACE),
    )
    assert legal_cards(hand, Suit.HEARTS) == frozenset({hand[0]})
    plays = (
        PlayedCard(0, Card(Suit.HEARTS, Rank.TWO)),
        PlayedCard(1, Card(Suit.SPADES, Rank.ACE)),
        PlayedCard(2, Card(Suit.HEARTS, Rank.KING)),
        PlayedCard(3, Card(Suit.CLUBS, Rank.ACE)),
    )
    assert trick_winner(plays) == 2
    assert config["deck"]["trump"] is None
    assert config["trick_play"]["off_suit_cards_can_win"] is False
    assert config["deal"]["early_termination"] is False
    assert config["deal"]["scoring_timing"] == "after_all_13_tricks"

    nolo_formula = config["deal_scoring"]["NOLO"]["formula"]
    for winner_tricks in range(7):
        score = score_nolo(winner_tricks, 13 - winner_tricks)
        assert score.points == nolo_formula["factor"] * (
            nolo_formula["pivot"] - winner_tricks
        )
    rami = config["deal_scoring"]["RAMI"]
    for declaring_tricks in range(14):
        score = score_rami(Team.TEAM_0, declaring_tricks, 13 - declaring_tricks)
        formula = rami["normal"]["formula"] if declaring_tricks >= 7 else rami["stolen"]["formula"]
        operand = declaring_tricks if declaring_tricks >= 7 else 13 - declaring_tricks
        assert score.points == formula["factor"] * (operand - formula["pivot"])

    down_win = transition_rising_score(MatchScore(48, 0), score_nolo(8, 5))
    assert down_win == MatchScore(0, 0)
    assert config["match"]["down_team_reset_awards_points"] is False
    terminal = transition_rising_score(MatchScore(48, 0), score_nolo(6, 7))
    assert terminal == MatchScore(config["match"]["target_score"], 0)
    assert config["match"]["terminal_comparison"] == "greater_than_or_equal"
    assert is_match_terminal(terminal)


def test_rules_package_has_no_legacy_random_io_network_or_gui_capability() -> None:
    package_root = ROOT / "src/tuppi_rules"
    allowed_external_imports = {"__future__", "collections", "dataclasses", "enum"}
    forbidden_calls = {"print", "input", "open", "exec", "eval", "compile", "__import__"}
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] in allowed_external_imports
                    for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] in allowed_external_imports, path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, path


def test_normative_test_tree_never_imports_legacy() -> None:
    for path in (ROOT / "tests/rules/project_target_v1").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "tuppi_legacy" for alias in node.names), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "tuppi_legacy", path
