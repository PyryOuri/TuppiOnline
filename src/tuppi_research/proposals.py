"""Proposal cards that enforce three disciplines, and nothing else.

From `HYPOTHESIS_GENERATOR_REPORT.md`, the three cheapest parts of its design —
the ones that need no operator inventory, no lane machinery and no behavioural
fingerprinting to work:

1. **Executable sketch before persuasive narrative.** A card must carry decision
   pseudocode. This is the discipline that would have caught E5: its hypothesis
   arrived as a story ("winning is a liability when no safe lead remains") which
   had at least two codings, and the one chosen collapsed into the endgame and
   matched only one of the three positions that motivated it. Pseudocode makes
   the ambiguity visible before any compute is spent.

2. **An escape clause for every revisit.** "The earlier result applied under X;
   this candidate changes X through Y; the cheapest observation distinguishing
   the two explanations is Z." A card that revisits a recorded finding must state
   all three. A new narrative alone is not Y.

3. **Plausibility is a recorded prediction, never a veto.** The field exists and
   :func:`admit` provably ignores it — the operator's own three pre-registered
   predictions in this programme were all wrong, so plausibility here has
   demonstrated negative value as a filter. Rejection needs a reason code naming
   a real constraint.

Deliberately absent: transformation operators, allocation lanes, structural
signatures. Those wait until this discipline has admitted or refused a real
candidate, because the measured economics here are that experiments cost 6-20
minutes and process costs more.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path

from .errors import CycleError
from .findings import REPO_ROOT, load as load_findings

PROPOSALS_SCHEMA_VERSION = "tuppi.research.proposal.v1"
PROPOSALS_DIR = REPO_ROOT / "docs" / "proposals"


class RejectionCode(StrEnum):
    """Reasons a proposal may be refused. None of them is 'it sounds wrong'."""

    DUPLICATE = "duplicate"
    CONTRADICTED_IN_SCOPE = "contradicted_in_scope"
    ILLEGAL = "illegal"
    INFORMATION_UNAVAILABLE = "information_unavailable"
    UNDEFINED_EXECUTION = "undefined_execution"
    RESOURCE_INFEASIBLE = "resource_infeasible"


class Plausibility(StrEnum):
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class EscapeClause:
    applied_under: str              # X
    changed_by: str                 # Y
    distinguishing_observation: str  # Z


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    date: str
    mechanism: str
    structural_family: str
    executable_sketch: str
    observable_inputs: tuple[str, ...]
    predicted_sign: str
    falsifier: str
    plausibility: Plausibility
    plausibility_rationale: str
    resources: dict[str, object]
    revisits: tuple[str, ...] = ()
    escape_clause: EscapeClause | None = None
    negates_assumptions: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Admission:
    proposal_id: str
    status: str                     # "admitted" | "rejected"
    reason_code: RejectionCode | None
    detail: str
    is_revisit: bool


def _require(value: object, label: str, proposal_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CycleError(f"proposal {proposal_id!r} needs a nonempty {label}")
    return value


def parse(raw: dict) -> Proposal:
    pid = raw.get("proposal_id") or "?"
    for field in ("proposal_id", "date", "mechanism", "structural_family",
                  "predicted_sign", "falsifier", "plausibility_rationale"):
        _require(raw.get(field), field, pid)
    sketch = _require(raw.get("executable_sketch"), "executable_sketch", pid)
    if len([line for line in sketch.splitlines() if line.strip()]) < 2:
        raise CycleError(
            f"proposal {pid!r} has a one-line executable_sketch. A sketch must be "
            "decision pseudocode, not a restatement of the idea: a story with two "
            "possible codings is how E5 was operationalised wrongly."
        )
    inputs = tuple(raw.get("observable_inputs") or ())
    if not inputs:
        raise CycleError(f"proposal {pid!r} must declare its observable inputs")
    try:
        plausibility = Plausibility(raw["plausibility"])
    except (KeyError, ValueError) as exc:
        raise CycleError(
            f"proposal {pid!r} needs a plausibility from "
            f"{sorted(p.value for p in Plausibility)} — recorded, never a gate"
        ) from exc
    revisits = tuple(raw.get("revisits") or ())
    clause_raw = raw.get("escape_clause")
    clause = None
    if clause_raw is not None:
        clause = EscapeClause(
            applied_under=_require(clause_raw.get("applied_under"),
                                   "escape_clause.applied_under", pid),
            changed_by=_require(clause_raw.get("changed_by"),
                                "escape_clause.changed_by", pid),
            distinguishing_observation=_require(
                clause_raw.get("distinguishing_observation"),
                "escape_clause.distinguishing_observation", pid),
        )
    if revisits and clause is None:
        raise CycleError(
            f"proposal {pid!r} revisits {list(revisits)} without an escape clause. "
            "State what the earlier result applied under, what this changes, and "
            "the cheapest observation that distinguishes them. A new narrative "
            "alone is not a change."
        )
    return Proposal(
        proposal_id=raw["proposal_id"], date=raw["date"],
        mechanism=raw["mechanism"], structural_family=raw["structural_family"],
        executable_sketch=sketch, observable_inputs=inputs,
        predicted_sign=raw["predicted_sign"], falsifier=raw["falsifier"],
        plausibility=plausibility,
        plausibility_rationale=raw["plausibility_rationale"],
        resources=dict(raw.get("resources") or {}),
        revisits=revisits, escape_clause=clause,
        negates_assumptions=tuple(raw.get("negates_assumptions") or ()),
        notes=raw.get("notes", ""),
    )


def admit(proposal: Proposal) -> Admission:
    """Decide admission. Reads every field except ``plausibility``.

    The omission is the point and it is tested: three pre-registered plausibility
    predictions in this programme were all wrong, so the operator's prior has
    demonstrated negative value as a filter.
    """

    known_findings = {row.finding_id for row in load_findings()}
    for finding in proposal.revisits:
        if finding not in known_findings:
            return Admission(
                proposal.proposal_id, "rejected", RejectionCode.DUPLICATE,
                f"revisits unknown finding {finding!r}; if the earlier result is "
                "not in the index, add it before revisiting it", True)
    if proposal.negates_assumptions:
        from .assumptions import NegationStatus, register

        by_id = {a.assumption_id: a for a in register()}
        for name in proposal.negates_assumptions:
            row = by_id.get(name)
            if row is None:
                return Admission(
                    proposal.proposal_id, "rejected",
                    RejectionCode.UNDEFINED_EXECUTION,
                    f"unknown assumption {name!r}", bool(proposal.revisits))
            if row.negation is NegationStatus.BLOCKED_NO_FALLBACK:
                return Admission(
                    proposal.proposal_id, "rejected",
                    RejectionCode.UNDEFINED_EXECUTION,
                    f"assumption {name!r} has no ablation switch: no documented "
                    "downstream legal fallback exists, so the candidate has no "
                    "defined execution. Defining one is a governance question",
                    bool(proposal.revisits))
    return Admission(
        proposal.proposal_id, "admitted", None,
        "executable sketch present; escape clause present where required; "
        "plausibility recorded and not consulted",
        bool(proposal.revisits))


def load_all(directory: Path | str | None = None) -> tuple[Proposal, ...]:
    target = Path(directory) if directory is not None else PROPOSALS_DIR
    rows = []
    for path in sorted(target.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != PROPOSALS_SCHEMA_VERSION:
            raise CycleError(
                f"{path} declares schema {payload.get('schema')!r}, "
                f"this build reads {PROPOSALS_SCHEMA_VERSION!r}")
        rows.append(parse(payload["proposal"]))
    return tuple(rows)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    rows = load_all()
    print(f"{len(rows)} proposal card(s)\n")
    for proposal in rows:
        decision = admit(proposal)
        print(f"[{decision.status.upper()}] {proposal.proposal_id}"
              f"{'  (revisit)' if decision.is_revisit else ''}")
        print(f"  mechanism: {proposal.mechanism}")
        print(f"  family: {proposal.structural_family}")
        print(f"  plausibility (recorded, not consulted): "
              f"{proposal.plausibility.value}")
        if proposal.escape_clause:
            c = proposal.escape_clause
            print(f"  escape clause:")
            print(f"    applied under : {c.applied_under}")
            print(f"    changed by    : {c.changed_by}")
            print(f"    distinguished : {c.distinguishing_observation}")
        print(f"  falsifier: {proposal.falsifier}")
        if decision.reason_code:
            print(f"  reason: {decision.reason_code.value} — {decision.detail}")
        print()
    return 0


__all__ = [
    "PROPOSALS_SCHEMA_VERSION", "Admission", "EscapeClause", "Plausibility",
    "Proposal", "RejectionCode", "admit", "load_all", "parse",
]


if __name__ == "__main__":
    raise SystemExit(main())
