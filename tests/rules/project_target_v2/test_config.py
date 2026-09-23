"""project_target_v2 config: valid under its strict schema and consistent with the code."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tuppi_rules import Card, Rank, RulesetId, Suit
from tuppi_rules.sooli import SOOLI_POINTS, sooli_offer_order, sooli_rank_value

ROOT = Path(__file__).resolve().parents[3]


def test_config_valid_and_matches_code():
    cfg = json.loads((ROOT / "configs/rules/project_target_v2.json").read_text())
    schema = json.loads((ROOT / "schemas/ruleset.v2.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(cfg)
    assert cfg["ruleset_id"] == RulesetId.PROJECT_TARGET_V2.value
    sooli = cfg["sooli"]
    assert sooli["points"] == SOOLI_POINTS
    order = [sooli_rank_value(Card(Suit.HEARTS, Rank(r))) for r in sooli["rank_order_low_to_high"]]
    assert order == sorted(order) and len(set(order)) == 13
    for declarer in range(4):
        expected = tuple((declarer + o["offset"]) % o["modulus"] for o in sooli["offer_order"])
        assert sooli_offer_order(declarer) == expected


def test_v2_differs_from_v1_only_by_identity_and_sooli():
    v1 = json.loads((ROOT / "configs/rules/project_target_v1.json").read_text())
    v2 = json.loads((ROOT / "configs/rules/project_target_v2.json").read_text())
    for key in v1:
        if key in ("schema_version", "ruleset_id", "ruleset_version", "provenance"):
            continue
        assert v2[key] == v1[key], key
    assert set(v2) - set(v1) == {"sooli"}
