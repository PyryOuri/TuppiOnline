"""Proposal cards must enforce three disciplines — and ignore plausibility.

The third test here is the load-bearing one. Three pre-registered plausibility
predictions in this programme were all wrong, so the operator's prior has
demonstrated negative value as an admission filter. `admit` must therefore be
provably indifferent to it.
"""

from __future__ import annotations

import copy
import json

import pytest

from tuppi_research.errors import CycleError
from tuppi_research.proposals import (
    PROPOSALS_DIR,
    PROPOSALS_SCHEMA_VERSION,
    Plausibility,
    RejectionCode,
    admit,
    load_all,
    parse,
)

VALID = {
    "proposal_id": "test-card",
    "date": "2026-09-10",
    "mechanism": "m",
    "structural_family": "f",
    "executable_sketch": "decide(observation):\n    return incumbent(observation)",
    "observable_inputs": ["the acting seat's observation"],
    "predicted_sign": "positive",
    "falsifier": "an interval upper bound below delta",
    "plausibility": "moderate",
    "plausibility_rationale": "recorded only",
}


def test_the_committed_pimc_card_loads_and_is_admitted():
    rows = load_all()
    assert rows, "the worked example card should be committed"
    card = next(r for r in rows if r.proposal_id == "pimc-opening-lead-w64")
    decision = admit(card)
    assert decision.status == "admitted"
    assert decision.is_revisit
    assert card.revisits == ("pimc-small-rejected",)


def test_the_escape_clause_on_the_worked_card_names_all_three_parts():
    card = next(r for r in load_all() if r.proposal_id == "pimc-opening-lead-w64")
    clause = card.escape_clause
    assert clause is not None
    # X names the rejected configuration's actual world count
    assert "world_count=4" in clause.applied_under
    # Y names the change and its measured reason
    assert "64" in clause.changed_by and "c3-world-count" in clause.changed_by
    # Z names an observation, not a story
    assert "latency" in clause.distinguishing_observation


def test_plausibility_does_not_affect_admission():
    """The load-bearing test. Vary only the rating; the decision must not move."""
    decisions = {}
    for rating in Plausibility:
        raw = copy.deepcopy(VALID)
        raw["plausibility"] = rating.value
        decisions[rating] = admit(parse(raw)).status
    assert set(decisions.values()) == {"admitted"}, decisions


def test_a_revisit_without_an_escape_clause_is_refused():
    raw = copy.deepcopy(VALID)
    raw["revisits"] = ["s1b-showing-kill"]
    with pytest.raises(CycleError, match="without an escape clause"):
        parse(raw)


def test_a_one_line_sketch_is_refused():
    raw = copy.deepcopy(VALID)
    raw["executable_sketch"] = "hold the ace to promote the queens"
    with pytest.raises(CycleError, match="one-line executable_sketch"):
        parse(raw)


def test_an_incomplete_escape_clause_is_refused():
    raw = copy.deepcopy(VALID)
    raw["revisits"] = ["s1b-showing-kill"]
    raw["escape_clause"] = {"applied_under": "x", "changed_by": "y",
                            "distinguishing_observation": "  "}
    with pytest.raises(CycleError, match="distinguishing_observation"):
        parse(raw)


def test_revisiting_an_unrecorded_finding_is_refused():
    raw = copy.deepcopy(VALID)
    raw["revisits"] = ["no-such-finding"]
    raw["escape_clause"] = {"applied_under": "x", "changed_by": "y",
                            "distinguishing_observation": "z"}
    decision = admit(parse(raw))
    assert decision.status == "rejected"
    assert decision.reason_code is RejectionCode.DUPLICATE


def test_negating_an_assumption_with_no_ablation_switch_is_refused():
    """T0-T3's binding constraint, enforced at admission."""
    raw = copy.deepcopy(VALID)
    raw["negates_assumptions"] = ["reactive.nolo.prefer_safe_loss.v1"]
    decision = admit(parse(raw))
    assert decision.status == "rejected"
    assert decision.reason_code is RejectionCode.UNDEFINED_EXECUTION
    assert "no ablation switch" in decision.detail


def test_negating_an_ablatable_assumption_is_admitted():
    raw = copy.deepcopy(VALID)
    raw["negates_assumptions"] = ["reactive.rami.avoid_overtaking_partner.v1"]
    assert admit(parse(raw)).status == "admitted"


def test_no_rejection_code_is_a_plausibility_judgement():
    values = {code.value for code in RejectionCode}
    for forbidden in ("implausible", "low_plausibility", "unlikely",
                      "sounds_wrong", "unconvincing"):
        assert forbidden not in values


def test_a_card_must_declare_observable_inputs_and_a_falsifier():
    for field in ("observable_inputs", "falsifier"):
        raw = copy.deepcopy(VALID)
        raw[field] = [] if field == "observable_inputs" else ""
        with pytest.raises(CycleError):
            parse(raw)


def test_a_foreign_schema_is_refused(tmp_path):
    (tmp_path / "card.json").write_text(json.dumps(
        {"schema": "other.v9", "proposal": VALID}))
    with pytest.raises(CycleError, match="declares schema"):
        load_all(tmp_path)


def test_every_committed_card_is_valid_and_decidable():
    for card in load_all():
        decision = admit(card)
        assert decision.status in {"admitted", "rejected"}
        assert card.plausibility_rationale.strip()
        assert PROPOSALS_SCHEMA_VERSION
        assert PROPOSALS_DIR.exists()
