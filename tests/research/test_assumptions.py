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


def test_the_counts_track_t0_t3_plus_what_has_since_been_unblocked():
    """docs/audit/results_t0_t3.md §2.1 measured 24 implemented, 8 mechanical,
    16 strategic-and-unvalidated, of those **4 ablatable and 12 with no switch**.

    The 24/8/16 split is a property of the catalogue and must not drift. The
    4/12 split is a property of the *switch surface* and is expected to move as
    fallbacks are defined: `docs/audit/ablation_fallbacks.md` unblocked both
    `counting.nolo` rules, so it is now 6/10. This test pins the total and
    records the movement rather than deleting the original figures.
    """

    rows = [a for a in register() if a.kind == "catalogued_rule"]
    assert len(rows) == 24
    mechanical = [a for a in rows if a.negation is NegationStatus.NOT_AN_ASSUMPTION]
    assert len(mechanical) == 8
    unvalidated = [a for a in rows if a.negation is not NegationStatus.NOT_AN_ASSUMPTION]
    assert len(unvalidated) == 16

    ablatable = [a for a in unvalidated if a.negation is NegationStatus.ABLATABLE]
    stuck = [a for a in unvalidated
             if a.negation is NegationStatus.BLOCKED_NO_FALLBACK]
    assert len(ablatable) + len(stuck) == 16
    # T0-T3's 4, plus the two counting.nolo rules unblocked since.
    assert len(ablatable) == 6
    assert len(stuck) == 10
    assert {a.assumption_id for a in ablatable} >= {
        "counting.nolo.avoid_retaining_certain_winner.v1",
        "counting.nolo.lead_suit_with_most_unaccounted_higher.v1",
    }


def test_mechanical_rules_are_not_treated_as_assumptions():
    for row in register():
        if row.provenance == "mechanical":
            assert row.negation is NegationStatus.NOT_AN_ASSUMPTION


def test_most_of_the_untested_surface_still_cannot_be_negated():
    """T0-T3's binding constraint, and how far it has moved.

    It was 12 of 16 — three quarters. Defining the structural fallback for the
    two `counting.nolo` rules brought it to 10 of 16. Still the dominant
    constraint on any assumption-negation operator, and still a governance
    question rather than a compute one for the seven Class B rules.
    """

    untested = [a for a in register()
                if a.negation is not NegationStatus.NOT_AN_ASSUMPTION
                and a.kind == "catalogued_rule"]
    stuck = [a for a in blocked() if a.kind == "catalogued_rule"]
    assert len(stuck) == 10
    assert 0.5 < len(stuck) / len(untested) < 0.75


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
    assert payload["by_status"]["blocked_no_fallback"] == 10
    assert len(payload["negatable_now"]) == 8
