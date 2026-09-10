"""The assumption register must be derived, not composed, and must agree with T0-T3.

The generator report proposes writing an assumption register. It is already
half-written in `RULE_CATALOGUE.provenance`, so this register derives from it and
these tests pin that it cannot drift: the counts must reproduce what
`docs/audit/results_t0_t3.md` measured independently.
"""

from __future__ import annotations

from tuppi_agents import rules_for_profile
from tuppi_research.assumptions import (
    BASE_PROFILE,
    NegationStatus,
    blocked,
    negatable,
    register,
    summary,
)


def test_the_register_covers_every_incumbent_rule_plus_its_layers():
    rows = register()
    catalogue = {r.rule_id for r in rules_for_profile(BASE_PROFILE)}
    derived = {a.assumption_id for a in rows if a.kind == "catalogued_rule"}
    assert derived == catalogue, "the register must derive, not select"
    layers = [a for a in rows if a.kind == "policy_layer"]
    assert len(layers) == 2, "partner_aware_lead_v2 declares two lead layers"


def test_the_counts_reproduce_the_t0_t3_measurement():
    """docs/audit/results_t0_t3.md §2.1: 24 implemented, 8 mechanical,
    16 strategic-and-unvalidated, of those 4 ablatable and 12 with no switch."""
    rows = [a for a in register() if a.kind == "catalogued_rule"]
    assert len(rows) == 24
    mechanical = [a for a in rows if a.negation is NegationStatus.NOT_AN_ASSUMPTION]
    assert len(mechanical) == 8
    unvalidated = [a for a in rows if a.negation is not NegationStatus.NOT_AN_ASSUMPTION]
    assert len(unvalidated) == 16
    assert len([a for a in unvalidated
                if a.negation is NegationStatus.ABLATABLE]) == 4
    assert len([a for a in unvalidated
                if a.negation is NegationStatus.BLOCKED_NO_FALLBACK]) == 12


def test_mechanical_rules_are_not_treated_as_assumptions():
    for row in register():
        if row.provenance == "mechanical":
            assert row.negation is NegationStatus.NOT_AN_ASSUMPTION


def test_three_quarters_of_the_untested_surface_cannot_be_negated():
    """The binding constraint on any assumption-negation operator."""
    untested = [a for a in register()
                if a.negation is not NegationStatus.NOT_AN_ASSUMPTION
                and a.kind == "catalogued_rule"]
    stuck = blocked()
    assert len(stuck) == 12
    assert len(stuck) / len(untested) == 0.75


def test_the_lead_layers_record_that_they_were_only_tested_jointly():
    layers = [a for a in register() if a.kind == "policy_layer"]
    for layer in layers:
        assert "JOINTLY" in layer.tested
        assert "-0.00574" in layer.tested
        assert layer.negation is NegationStatus.ABLATABLE


def test_every_assumption_carries_a_claim_and_its_evidence_state():
    for row in register():
        assert row.claim.strip()
        assert row.tested.strip()
        assert row.contracts and row.phases


def test_negatable_and_blocked_partition_the_assumptions():
    rows = register()
    assumptions = [a for a in rows
                   if a.negation is not NegationStatus.NOT_AN_ASSUMPTION]
    assert len(negatable(rows)) + len(blocked(rows)) == len(assumptions)


def test_summary_is_reportable():
    payload = summary()
    assert payload["catalogue_total"] == 38
    assert payload["by_status"]["blocked_no_fallback"] == 12
    assert len(payload["negatable_now"]) == 6
