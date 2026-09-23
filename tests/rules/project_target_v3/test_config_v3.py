"""project_target_v3 config: valid under its strict schema; v2 plus locked bids only."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tuppi_rules import LOCKED_BID_RULESETS, SOOLI_RULESETS, RulesetId

ROOT = Path(__file__).resolve().parents[3]


def test_config_valid_and_identity():
    cfg = json.loads((ROOT / "configs/rules/project_target_v3.json").read_text())
    schema = json.loads((ROOT / "schemas/ruleset.v3.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(cfg)
    assert cfg["ruleset_id"] == RulesetId.PROJECT_TARGET_V3.value
    assert cfg["locked_bids"]["bid_visibility"] == "locked_until_resolution"
    assert RulesetId.PROJECT_TARGET_V3 in LOCKED_BID_RULESETS and RulesetId.PROJECT_TARGET_V3 in SOOLI_RULESETS
    assert LOCKED_BID_RULESETS == {RulesetId.PROJECT_TARGET_V3}


def test_v3_differs_from_v2_only_by_identity_and_locked_bids():
    v2 = json.loads((ROOT / "configs/rules/project_target_v2.json").read_text())
    v3 = json.loads((ROOT / "configs/rules/project_target_v3.json").read_text())
    for key in v2:
        if key in ("schema_version", "ruleset_id", "ruleset_version", "provenance"):
            continue
        assert v3[key] == v2[key], key
    assert set(v3) - set(v2) == {"locked_bids"}
