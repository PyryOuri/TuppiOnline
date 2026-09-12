"""Which dimensions of the agent has the record actually explored, and which not.

The findings index answers "has this been tried?". It cannot answer "what have we
never tried?", because an index only contains what happened. That gap is the one
the architecture review named when it said the attempts were "too narrow, too
similar to each other", and counting the record confirms it: 29 findings, and
card-play, opening-lead and headroom carry 6, 6 and 5 of them.

So this module does not generate hypotheses. It generates *regions* — the axes
along which an agent could differ, ranked by how little the record has touched
them — on the argument that a proposal drawn from an empty region is structurally
novel by construction, whatever its merit.

Why this rather than a generator that enumerates candidate changes: idea supply
is not the scarce resource here. The record already holds 8 negatable
assumptions, 10 blocked ones, 88 stated open questions and 2 admitted proposal
cards, against an experiment cost of minutes to hours. Raising the volume of
candidates pours into a funnel whose neck is elsewhere. Raising their *spread*
does not.

The honest weakness, stated where it cannot be missed
-----------------------------------------------------

`DIMENSIONS` is hand-written. It is the one input here that is not derived, and a
dimension nobody thought to name stays invisible to this module exactly as it
stayed invisible to the programme. That cannot be fixed by deriving it from the
record, because the record is what is suspected of being narrow.

What *can* be done is to detect the list failing: :func:`unclaimed_findings`
reports any finding that matches no dimension at all. A finding in a region the
list does not name is proof the list is incomplete, and
``tests/research/test_coverage.py`` fails on it. That converts an unfalsifiable
worry into a check.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .errors import CycleError
from .findings import REPO_ROOT

COVERAGE_SCHEMA_VERSION = "tuppi.research.coverage.v1"

#: A finding must match this many patterns of a dimension to count as touching it.
_MATCH_THRESHOLD = 1


@dataclass(frozen=True, slots=True)
class Dimension:
    """One axis along which the agent could be different."""

    dimension_id: str
    question: str
    patterns: tuple[str, ...]
    why_it_matters: str


#: The axes. Ordered as a decision travels: what is seen, how it is judged, how
#: hard it is thought about, when that effort is spent, what finishes the deal,
#: who is across the table, and what is counted at the end.
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        dimension_id="observation",
        question="What does the agent see?",
        patterns=("observation", "information set", "public inference", "belief",
                  "hidden hand", "privacy"),
        why_it_matters=(
            "Every policy here consumes the same frozen PlayerObservation. A "
            "change to what is observable is the one change that cannot be made "
            "by scoring differently."
        ),
    ),
    Dimension(
        dimension_id="scoring",
        question="How are legal actions ranked?",
        patterns=("rule", "ablation", "catalogue", "heuristic", "score", "layer",
                  "assumption"),
        why_it_matters=(
            "The incumbent is a lexicographic score over named components. Most "
            "of the programme has changed this and nothing else."
        ),
    ),
    Dimension(
        dimension_id="search",
        question="Does the agent think ahead, and how much?",
        patterns=("pimc", "search", "world-count", "world-sampling", "rollout",
                  "uct", "solver", "depth"),
        why_it_matters="Spending compute at a decision instead of judgement.",
    ),
    Dimension(
        dimension_id="decision_scope",
        question="At which decisions is extra effort spent?",
        patterns=("opening-lead", "scope", "leverage", "decision-classes",
                  "trick 12", "depth"),
        why_it_matters=(
            "A selector that fires everywhere and one that fires once a deal are "
            "different agents at the same budget."
        ),
    ),
    Dimension(
        dimension_id="continuation",
        question="What plays the rest of the deal, in simulation and in fact?",
        patterns=("continuation", "rollout policy", "delegate", "incumbent"),
        why_it_matters=(
            "A search is only as good as its model of what happens next, and the "
            "record priced every arm with one fixed continuation."
        ),
    ),
    Dimension(
        dimension_id="showing",
        question="How is the contract chosen?",
        patterns=("showing", "contract", "declare", "rami", "nolo suitability"),
        why_it_matters=(
            "Showing is upstream of every card decision and decides the scoring "
            "regime the whole deal is played under."
        ),
    ),
    Dimension(
        dimension_id="score_state",
        question="Does play change with the match score?",
        patterns=("score state", "score-state", "match score", "match-aware",
                  "match state", "rising score"),
        why_it_matters=(
            "A deal point is worth a different amount at 0-0 than near the "
            "target, and the rising score resets, so a real match spends most of "
            "its deals away from level."
        ),
    ),
    Dimension(
        dimension_id="opponent",
        question="Who is across the table?",
        patterns=("transfer", "crossplay", "cross-play", "opponent",
                  "self-play-overfitting", "ladder", "diversity"),
        why_it_matters=(
            "Everything measured in self-play is conditional on the opponent it "
            "was measured against."
        ),
    ),
    Dimension(
        dimension_id="adaptation",
        question="Does the agent change during a match, or across matches?",
        patterns=("learning", "training", "adapt", "opponent model", "imitation",
                  "checkpoint"),
        why_it_matters=(
            "Every policy here is frozen and memoryless across deals. Adaptation "
            "is a different kind of agent, not a better score."
        ),
    ),
    Dimension(
        dimension_id="partnership",
        question="What do partners communicate, and how?",
        patterns=("partner", "convention", "signal", "partnership"),
        why_it_matters=(
            "The legal channel between partners is the play itself, and a "
            "convention is a shared reading of it."
        ),
    ),
    Dimension(
        dimension_id="endpoint",
        question="What is counted as success?",
        patterns=("endpoint", "equity", "deal points", "match win", "promotion",
                  "headroom", "hindsight"),
        why_it_matters=(
            "A screening endpoint and a promotion endpoint disagree about what "
            "an improvement is."
        ),
    ),
    Dimension(
        dimension_id="instrument",
        question="Can the thing even be measured?",
        patterns=("instrument", "estimator-defect", "latency", "power",
                  "retrieval", "variance-pilot", "underpowered", "void"),
        why_it_matters=(
            "Not an axis of the agent, but the axis that has voided the most "
            "work here. Counted so that instrument findings are not mistaken for "
            "coverage of the agent."
        ),
    ),
)

#: `instrument` describes the measuring apparatus, not the agent. It is counted
#: for completeness and excluded when ranking where to propose next.
_NOT_AN_AGENT_AXIS = frozenset({"instrument"})


@dataclass(frozen=True, slots=True)
class DimensionCoverage:
    dimension: Dimension
    finding_ids: tuple[str, ...]

    @property
    def depth(self) -> int:
        return len(self.finding_ids)


def _index() -> list[dict]:
    path = REPO_ROOT / "docs" / "findings" / "index.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - the index is committed
        raise CycleError(f"no findings index at {path}") from exc
    rows = payload.get("findings")
    if not isinstance(rows, list):
        raise CycleError("the findings index has no 'findings' list")
    return rows


def _haystack(finding: dict) -> str:
    parts = [finding.get("question", ""), finding.get("scope", ""),
             finding.get("finding_id", "")]
    parts.extend(finding.get("tags", []))
    return " ".join(parts).lower()


def _touches(finding: dict, dimension: Dimension) -> bool:
    text = _haystack(finding)
    hits = sum(1 for pattern in dimension.patterns
               if re.search(re.escape(pattern), text))
    return hits >= _MATCH_THRESHOLD


def coverage() -> tuple[DimensionCoverage, ...]:
    """Every dimension with the findings that touch it, shallowest first."""

    rows = _index()
    out = [
        DimensionCoverage(
            dimension=dimension,
            finding_ids=tuple(
                f["finding_id"] for f in rows if _touches(f, dimension)),
        )
        for dimension in DIMENSIONS
    ]
    return tuple(sorted(out, key=lambda c: (c.depth, c.dimension.dimension_id)))


def unclaimed_findings() -> tuple[str, ...]:
    """Findings that match no dimension — proof `DIMENSIONS` is incomplete.

    This is the module's own falsifier. A finding sitting in a region the list
    does not name means the list has a hole, and a hole in the list is exactly
    the blindness this module claims to reduce.
    """

    rows = _index()
    return tuple(
        f["finding_id"] for f in rows
        if not any(_touches(f, dimension) for dimension in DIMENSIONS)
    )


def unexplored(limit: int = 3) -> tuple[DimensionCoverage, ...]:
    """The shallowest agent axes: where a proposal would be structurally novel."""

    return tuple(
        c for c in coverage()
        if c.dimension.dimension_id not in _NOT_AN_AGENT_AXIS
    )[:limit]


def summary() -> dict[str, object]:
    rows = coverage()
    return {
        "schema_version": COVERAGE_SCHEMA_VERSION,
        "findings_indexed": len(_index()),
        "dimensions": len(DIMENSIONS),
        "depth_by_dimension": {c.dimension.dimension_id: c.depth for c in rows},
        "unexplored_agent_axes": [c.dimension.dimension_id for c in unexplored()],
        "unclaimed_findings": list(unclaimed_findings()),
    }


def _render() -> str:
    lines = ["Coverage of the agent's dimensions by the findings record", ""]
    for item in coverage():
        mark = "   (measuring apparatus, not the agent)" if (
            item.dimension.dimension_id in _NOT_AN_AGENT_AXIS) else ""
        lines.append(f"{item.depth:>3}  {item.dimension.dimension_id}{mark}")
        lines.append(f"     {item.dimension.question}")
        if item.finding_ids:
            lines.append(f"     touched by: {', '.join(item.finding_ids[:4])}"
                         + (" ..." if len(item.finding_ids) > 4 else ""))
        else:
            lines.append("     touched by: NOTHING")
        lines.append("")
    lines.append("Where a proposal would be structurally novel:")
    for item in unexplored():
        lines.append(f"  * {item.dimension.dimension_id} "
                     f"(depth {item.depth}) — {item.dimension.question}")
        lines.append(f"      {item.dimension.why_it_matters}")
    stray = unclaimed_findings()
    if stray:
        lines.append("")
        lines.append("INCOMPLETE: these findings match no dimension, so the list "
                     "has a hole:")
        lines.extend(f"  - {fid}" for fid in stray)
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI
    print(_render())
