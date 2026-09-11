"""The register of untested strategic assumptions, derived rather than composed.

The generator report proposes an assumption register whose first transformation
operator is "assumption negation". That register is already half-written: every
catalogued strategy rule carries a ``provenance`` field saying whether it is a
deduction or a guess, plus its own ``condition``, ``rationale`` and
``limitations`` as declared by whoever added it.

So this module *derives* the register from ``tuppi_agents.RULE_CATALOGUE`` and
the improved-policy layer declarations instead of copying them into a second
document. Nothing here can drift out of date, because there is no duplicated
data to drift.

Two things it records that the catalogue alone does not make obvious:

* **Which assumptions can actually be negated.** ``docs/audit/results_t0_t3.md``
  found only 4 of the incumbent's 16 unvalidated strategic rules were ablatable;
  the other 12 carried ``independently_disableable = False`` because no
  documented downstream legal fallback existed, and ``HeuristicProfile`` refuses
  them. T0-T3 called this "the binding constraint on the whole discovery route"
  and noted the limit was the switch surface, not compute.
  ``docs/audit/ablation_fallbacks.md`` settled the fallback semantics and
  unblocked the two ``counting.nolo`` rules, so it is now 6 ablatable and 10
  blocked. An assumption-negation operator still emits ``UNDEFINED_EXECUTION``
  for most of this register, and the remainder is still a governance question
  rather than a grammar one — but it is a classified one now, not a wall.
* **What has already been tested jointly.** ``partner_aware_lead_v2``'s two lead
  layers were removed together as T2's V5 positive control, costing -0.00574
  equity per deal, so they are established as beneficial *as a pair* while
  remaining individually unvalidated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from tuppi_agents import RULE_CATALOGUE, rules_for_profile
from tuppi_agents.improved_registry import improved_policies

ASSUMPTIONS_SCHEMA_VERSION = "tuppi.research.assumptions.v1"

#: The production incumbent, and the Phase 4 profile its rules come from.
INCUMBENT_PROFILE = "partner_aware_lead_v2"
BASE_PROFILE = "partner_aware_v1"

#: Provenance values that make a rule a deduction rather than an assumption.
_SOUND = frozenset({"mechanical"})


class NegationStatus(StrEnum):
    """Can this assumption be removed and the policy still run?"""

    ABLATABLE = "ablatable"
    BLOCKED_NO_FALLBACK = "blocked_no_fallback"
    NOT_AN_ASSUMPTION = "not_an_assumption"


@dataclass(frozen=True, slots=True)
class Assumption:
    assumption_id: str
    kind: str                      # "catalogued_rule" | "policy_layer"
    provenance: str
    contracts: tuple[str, ...]
    phases: tuple[str, ...]
    claim: str                     # the rule's condition -> action preference
    declared_limitations: str
    negation: NegationStatus
    tested: str                    # what evidence exists, in words
    finding_ids: tuple[str, ...] = ()


def _rule_assumptions() -> tuple[Assumption, ...]:
    out: list[Assumption] = []
    for rule in rules_for_profile(BASE_PROFILE):
        provenance = rule.provenance.value
        if provenance in _SOUND:
            status = NegationStatus.NOT_AN_ASSUMPTION
            tested = ("Mechanical: a deduction from the public record, not a "
                      "strategic guess. Out of scope for negation.")
            findings = ("t1-hard-exclusions-sound",)
        elif rule.independently_disableable:
            status = NegationStatus.ABLATABLE
            tested = ("Ablatable. T2 disabled the four ablatable rules over 2000 "
                      "deals: three changed not one action, the fourth cost "
                      "-0.0002 at 5.2% action divergence.")
            findings = ("t2-rule-ablation-closed", "t0-ablation-surface")
        else:
            status = NegationStatus.BLOCKED_NO_FALLBACK
            tested = ("Never tested in isolation. HeuristicProfile refuses to "
                      "disable it because no documented downstream legal "
                      "fallback exists, so no ablation is possible at any budget.")
            findings = ("t0-ablation-surface",)
        out.append(Assumption(
            assumption_id=rule.rule_id, kind="catalogued_rule",
            provenance=provenance, contracts=tuple(rule.contracts),
            phases=tuple(rule.phases),
            claim=f"When {rule.condition.rstrip('.')}, prefer: {rule.action_preference}",
            declared_limitations=rule.limitations or "",
            negation=status, tested=tested, finding_ids=findings,
        ))
    return tuple(out)


def _layer_assumptions() -> tuple[Assumption, ...]:
    policy = improved_policies()[INCUMBENT_PROFILE]
    out: list[Assumption] = []
    for layer in policy.layers:
        parameters = ", ".join(f"{name}={value}" for name, value in layer.parameters)
        out.append(Assumption(
            assumption_id=layer.layer_id, kind="policy_layer",
            provenance="improved_policy_layer",
            contracts=("RAMI", "NOLO"), phases=("TRICK_PLAY",),
            claim=(f"Replaces {layer.supersedes}; introduces "
                   f"{', '.join(layer.introduces)}; parameters: {parameters}"),
            declared_limitations=(
                "Measured paired as part of the improved policy, not expert "
                "validated, and not a Phase 4 profile."),
            negation=NegationStatus.ABLATABLE,
            tested=("Tested JOINTLY, not individually: T2's V5 control removed "
                    "both lead layers together, costing -0.00574 equity per deal "
                    "on [-0.00652, -0.00498]. Beneficial as a pair; each layer's "
                    "own contribution is unmeasured."),
            finding_ids=("t2-rule-ablation-closed",),
        ))
    return tuple(out)


def register() -> tuple[Assumption, ...]:
    """The whole derived register, catalogued rules then policy layers."""

    return _rule_assumptions() + _layer_assumptions()


def negatable(rows: tuple[Assumption, ...] | None = None) -> tuple[Assumption, ...]:
    """Assumptions an assumption-negation job could actually produce a runnable
    candidate for."""

    return tuple(a for a in (rows or register())
                 if a.negation is NegationStatus.ABLATABLE)


def blocked(rows: tuple[Assumption, ...] | None = None) -> tuple[Assumption, ...]:
    """Untested assumptions with no ablation switch. The governance question."""

    return tuple(a for a in (rows or register())
                 if a.negation is NegationStatus.BLOCKED_NO_FALLBACK)


def summary() -> dict[str, object]:
    rows = register()
    return {
        "schema": ASSUMPTIONS_SCHEMA_VERSION,
        "incumbent": INCUMBENT_PROFILE,
        "catalogue_total": len(RULE_CATALOGUE),
        "assumptions": len(rows),
        "by_status": {
            status.value: sum(1 for a in rows if a.negation is status)
            for status in NegationStatus
        },
        "by_provenance": {
            provenance: sum(1 for a in rows if a.provenance == provenance)
            for provenance in sorted({a.provenance for a in rows})
        },
        "negatable_now": [a.assumption_id for a in negatable(rows)],
        "blocked_on_fallback_definition": [a.assumption_id for a in blocked(rows)],
    }


def main(argv: list[str] | None = None) -> int:
    import json
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    rows = register()
    if args and args[0] == "--summary":
        print(json.dumps(summary(), indent=2))
        return 0
    term = " ".join(args).lower()
    hits = [a for a in rows if not term or term in
            f"{a.assumption_id} {a.claim} {a.provenance} {a.negation.value}".lower()]
    print(f"{len(hits)} of {len(rows)} assumptions\n")
    for a in hits:
        print(f"[{a.negation.value.upper()}] {a.assumption_id}")
        print(f"  provenance: {a.provenance}  contracts: {','.join(a.contracts)}")
        print(f"  claim: {a.claim}")
        if a.declared_limitations:
            print(f"  declared limitation: {a.declared_limitations}")
        print(f"  tested: {a.tested}")
        print()
    return 0


__all__ = [
    "ASSUMPTIONS_SCHEMA_VERSION", "Assumption", "NegationStatus",
    "blocked", "negatable", "register", "summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
