"""The T0-T3 audit's own gates, as tests.

Three properties that a one-off script check would not keep true:

* the T4 review packet is **observation-only** - it may carry nothing the acting
  seat could not see, and the check must be non-vacuous;
* the frozen variant list in the runner still matches the eligible set the
  profile actually accepts, so the pre-registration and the code cannot drift
  apart silently;
* the rule-catalogue counts the pre-registration asserts are still true.

The sentinel's non-vacuity half needs the researcher-only artifact, which holds
true deals and therefore lives outside the repository. That half skips when the
file is absent rather than passing vacuously.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "audit"
PRIVATE = Path("/Users/pyryouri/Developer/TuppiRuns/phase7/audit")
CARD = re.compile(r'"((?:10|[2-9JQKA])[HDCS])"')

sys.path.insert(0, str(ROOT / "work" / "audit"))


def _load(name: str, base: Path = REPORTS):
    path = base / name
    if not path.exists():
        pytest.skip(f"{path} not generated; run the audit runners first")
    return json.loads(path.read_text(encoding="utf-8"))


def _visible(case: dict) -> set[str]:
    """Every card the acting seat can legitimately see in this case."""

    observation = case["observation"]
    visible = set(observation["own_hand"])
    visible |= {shown["card"] for shown in observation["publicly_shown_cards"]}
    for trick in observation["completed_tricks"]:
        visible |= {play["card"] for play in trick["plays"]}
    visible |= {play["card"] for play in observation["current_trick"]}
    visible |= {alt["action"]["card"] for alt in case["alternatives"]}
    return visible


def test_the_review_packet_names_no_unseeable_card() -> None:
    packet = _load("t4_review_packet.json")
    schema = json.loads(
        (ROOT / "schemas" / "engine" / "player_observation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    allowed = set(schema["properties"])
    assert packet["cases"], "the packet must not be empty"
    for case in packet["cases"]:
        extra_keys = set(case["observation"]) - allowed
        assert not extra_keys, f"{case['case_id']} adds fields outside the schema: {extra_keys}"
        mentioned = set(CARD.findall(json.dumps(case)))
        leaked = mentioned - _visible(case)
        assert not leaked, f"{case['case_id']} names cards the seat cannot see: {sorted(leaked)}"


def test_the_review_packet_carries_no_consequences() -> None:
    packet = _load("t4_review_packet.json")
    text = json.dumps(packet)
    for token in ("oracle", "true_hands", "initial_hands", "equity", "deal_index"):
        assert token not in text, f"the reviewable packet leaks {token!r}"
    for case in packet["cases"]:
        labels = [alt["label"] for alt in case["alternatives"]]
        assert labels == sorted(labels), "options must be in the engine's order"
        assert all(label.startswith("option ") for label in labels), (
            "options must be neutrally labelled, not ranked"
        )


def test_the_sentinel_is_not_vacuous() -> None:
    """Each case must have had a foreign card available to leak, and not leaked it."""

    packet = _load("t4_review_packet.json")
    secrets = _load("t4_researcher_only.json", PRIVATE)
    assert len(secrets["cases"]) == len(packet["cases"])
    for case, secret in zip(packet["cases"], secrets["cases"]):
        assert case["case_id"] == secret["case_id"]
        visible = _visible(case)
        foreign = {
            card
            for seat, hand in enumerate(secret["true_hands"])
            if seat != secret["acting_seat"]
            for card in hand
        } - visible
        assert foreign, f"{case['case_id']}: no foreign card left, sentinel is vacuous"
        mentioned = set(CARD.findall(json.dumps(case)))
        assert not (foreign & mentioned), f"{case['case_id']} names a foreign card"


def test_cases_come_from_distinct_deals() -> None:
    secrets = _load("t4_researcher_only.json", PRIVATE)
    deals = [case["deal_index"] for case in secrets["cases"]]
    assert len(set(deals)) == len(deals), "review cases must be independent deals"
    assert len(deals) <= 24, "the packet cap is 24 cases"


def test_the_frozen_variant_list_still_matches_what_the_profile_accepts() -> None:
    """Pre-registration §4 against the repository, so the two cannot drift."""

    from t2_t3_runner import COMPOUND_ABLATION, SINGLE_RULE_ABLATIONS

    from tuppi_agents import RULE_CATALOGUE, registered_profiles
    from tuppi_agents.profiles import HeuristicProfile

    control = registered_profiles()["partner_aware_v1"]
    accepted = set()
    for rule in RULE_CATALOGUE:
        if "partner_aware_v1" not in rule.implementing_profiles:
            continue
        try:
            HeuristicProfile.build(
                profile_key="partner_aware_v1",
                family=control.family,
                showing_policy=control.showing_policy,
                parameters=dict(control.parameters),
                disabled_rule_ids=(rule.rule_id,),
                description="drift check",
            )
        except Exception:  # noqa: BLE001 - refusal is the datum
            continue
        accepted.add(rule.rule_id)

    frozen = {rule for _variant, rule in SINGLE_RULE_ABLATIONS}
    assert frozen == accepted, (
        "the pre-registered single-rule ablation list no longer matches the set the "
        f"profile accepts. frozen={sorted(frozen)} accepted={sorted(accepted)}"
    )
    assert len(accepted) == 4, (
        "prereg_t0.md §2.1 records four eligible ablations; if this changed, the "
        "audit's central structural finding needs restating"
    )
    assert COMPOUND_ABLATION[0] == "V5"


def test_the_catalogue_counts_in_the_prereg_still_hold() -> None:
    catalogue = _load("t1_rule_catalogue.json")
    assert catalogue["catalogue_size"] == 38
    assert catalogue["rules_in_reference_profile"] == 24
    assert catalogue["mechanical"] == 8
    assert catalogue["strategic_unvalidated"] == 16
    assert catalogue["eligible_for_single_rule_ablation"] == 4
    for rule in catalogue["rules"]:
        if rule["is_strategic_heuristic"]:
            assert rule["validation_status"].startswith("UNVALIDATED"), rule["rule_id"]


def test_the_hard_exclusion_audit_found_no_violation() -> None:
    audit = _load("t1_certainty_audit.json")
    assert audit["hard_exclusion_checks"] > 100_000, "the audit must be substantial"
    assert audit["hard_exclusion_violations"] == 0, (
        "the reference acted on a false ownership certainty; that is a defect to "
        "report, not a test to relax"
    )
    assert audit["tracing_proof"]["identical"], "tracing perturbed play"
    # The behavioural deduction is expected to fail; pin it so a later change is noticed.
    assert audit["ducking_by_contract"]["NOLO"]["rate"] > 0.10
