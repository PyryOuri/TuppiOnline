"""A queryable index of concluded findings, with their scope limits.

Why this exists, from measured experience rather than principle. Four times in
one research sequence, work was started that a file already in this repository
would have redirected:

* an experiment licensed showing as a target after ``docs/showing/results_s1b.md``
  had already killed it under a pre-registered gate;
* three experiments tested rule neighbours after ``docs/audit/results_t0_t3.md``
  had already found three of the four ablatable rules inert;
* a world-sampling selector was described as unexpressible while
  ``tuppi_search`` contained a built, registered and rejected implementation;
* a performance remedy was proposed that ``tuppi_engine.trusted``'s own module
  docstring forbids to policies, while naming the sanctioned alternative that
  already existed.

None of those needed an experiment. They needed a lookup, and there was nowhere
to look: the record is spread across 115 documents in seventeen package
directories, phase reports, registry constants and commit messages.

Every one of those four was also an **over-generalisation of a correctly scoped
negative result**. That is why ``does_not_establish`` is a required field for any
negative verdict and why the validator refuses a row without it. A finding that
records only its verdict is the shape of mistake this index exists to prevent.

The index is data, not prose: ``docs/findings/index.json`` is the source of
truth, this module validates and queries it, and ``docs/findings/README.md`` is
generated from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from enum import StrEnum
import json
from pathlib import Path

from .errors import LedgerError

FINDINGS_SCHEMA_VERSION = "tuppi.research.findings.v1"

#: Repository root, resolved from this file's location.
REPO_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = REPO_ROOT / "docs" / "findings" / "index.json"

#: Prefixes that mark an evidence entry as a repository path, which must exist.
_PATH_PREFIXES = ("docs/", "src/", "work/", "reports/", "tests/", "manifests/")


class Verdict(StrEnum):
    """Controlled vocabulary. Anything else is a validation failure."""

    KILLED = "killed"                # a pre-registered kill gate fired
    REJECTED = "rejected"            # measured worse than its comparator
    REFUTED = "refuted"              # the stated hypothesis did not hold
    INCONCLUSIVE = "inconclusive"    # ran, could not place the effect
    VOID = "void"                    # instrument or estimator defect
    CONFIRMED = "confirmed"          # a pre-registered prediction held
    MEASURED = "measured"            # a quantity established, no hypothesis
    CONSTRAINT = "constraint"        # an architectural fact, not an experiment


#: Verdicts whose rows MUST carry explicit scope limits.
NEGATIVE = frozenset({
    Verdict.KILLED, Verdict.REJECTED, Verdict.REFUTED,
    Verdict.INCONCLUSIVE, Verdict.VOID,
})


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    date: str
    question: str
    verdict: Verdict
    scope: str
    does_not_establish: tuple[str, ...]
    numbers: dict[str, object]
    evidence: tuple[str, ...]
    tags: tuple[str, ...]
    supersedes: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()

    def matches(self, term: str) -> bool:
        needle = term.lower().strip()
        if not needle:
            return True
        haystack = " ".join(
            (self.finding_id, self.question, self.scope, self.verdict.value,
             " ".join(self.tags), " ".join(self.does_not_establish))
        ).lower()
        return needle in haystack


def _row(raw: dict) -> Finding:
    try:
        verdict = Verdict(raw["verdict"])
    except (KeyError, ValueError) as exc:
        raise LedgerError(
            f"finding {raw.get('finding_id', '?')!r} has an unknown verdict "
            f"{raw.get('verdict')!r}; the vocabulary is "
            f"{sorted(v.value for v in Verdict)}"
        ) from exc
    for field in ("finding_id", "date", "question", "scope"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise LedgerError(
                f"finding {raw.get('finding_id', '?')!r} needs a nonempty {field}")
    try:
        _date.fromisoformat(raw["date"])
    except ValueError as exc:
        raise LedgerError(f"finding {raw['finding_id']!r} has an invalid date") from exc
    limits = tuple(raw.get("does_not_establish") or ())
    if verdict in NEGATIVE and not limits:
        raise LedgerError(
            f"finding {raw['finding_id']!r} is {verdict.value} and records no "
            "scope limits. Every over-generalisation this index exists to "
            "prevent was a negative result read beyond its scope, so "
            "does_not_establish is required here."
        )
    tags = tuple(raw.get("tags") or ())
    if not tags:
        raise LedgerError(f"finding {raw['finding_id']!r} must carry at least one tag")
    return Finding(
        finding_id=raw["finding_id"], date=raw["date"], question=raw["question"],
        verdict=verdict, scope=raw["scope"], does_not_establish=limits,
        numbers=dict(raw.get("numbers") or {}),
        evidence=tuple(raw.get("evidence") or ()), tags=tags,
        supersedes=tuple(raw.get("supersedes") or ()),
        superseded_by=tuple(raw.get("superseded_by") or ()),
    )


def load(path: Path | str | None = None) -> tuple[Finding, ...]:
    """Load and validate the index. Raises rather than returning bad rows."""

    target = Path(path) if path is not None else INDEX_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != FINDINGS_SCHEMA_VERSION:
        raise LedgerError(
            f"{target} declares schema {payload.get('schema')!r}, "
            f"this build reads {FINDINGS_SCHEMA_VERSION!r}")
    rows = tuple(_row(item) for item in payload.get("findings", ()))
    if not rows:
        raise LedgerError(f"{target} contains no findings")
    seen: set[str] = set()
    for row in rows:
        if row.finding_id in seen:
            raise LedgerError(f"duplicate finding id {row.finding_id!r}")
        seen.add(row.finding_id)
    for row in rows:
        for other in (*row.supersedes, *row.superseded_by):
            if other not in seen:
                raise LedgerError(
                    f"finding {row.finding_id!r} references unknown id {other!r}")
    return rows


def stale_evidence(rows: tuple[Finding, ...],
                   root: Path | str = REPO_ROOT) -> tuple[str, ...]:
    """Evidence paths that no longer exist. The anti-rot check.

    Evidence may also be a commit sha or a registry constant, which are not
    checkable here; only entries that look like repository paths are verified.
    """

    base = Path(root)
    missing: list[str] = []
    for row in rows:
        for item in row.evidence:
            if item.startswith(_PATH_PREFIXES) and not (base / item).exists():
                missing.append(f"{row.finding_id}: {item}")
    return tuple(missing)


def search(term: str, rows: tuple[Finding, ...] | None = None) -> tuple[Finding, ...]:
    """Findings whose id, question, scope, verdict, tags or limits mention *term*."""

    return tuple(r for r in (rows if rows is not None else load()) if r.matches(term))


def render(rows: tuple[Finding, ...]) -> str:
    """The human-readable view. Generated; do not hand-edit the output file."""

    lines = [
        "# Concluded findings",
        "",
        "**Generated from `index.json` by `tuppi_research.findings`. Do not edit "
        "by hand.**",
        "",
        "Check this before proposing a hypothesis. Every negative row carries "
        "its scope limits, because every mistake this index exists to prevent "
        "was a correctly scoped negative result read too broadly.",
        "",
        f"Query: `python -m tuppi_research.findings <term>` — {len(rows)} findings.",
        "",
        "| date | id | verdict | question |",
        "|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: (r.date, r.finding_id)):
        lines.append(f"| {row.date} | `{row.finding_id}` | **{row.verdict.value}** "
                     f"| {row.question} |")
    lines.append("")
    for row in sorted(rows, key=lambda r: (r.date, r.finding_id)):
        lines += [f"## `{row.finding_id}` — {row.verdict.value}", "",
                  f"*{row.date}* · tags: {', '.join(f'`{t}`' for t in row.tags)}", "",
                  f"**Question.** {row.question}", "",
                  f"**Scope.** {row.scope}", ""]
        if row.numbers:
            lines.append("**Numbers.** " + "; ".join(
                f"{k} = {v}" for k, v in row.numbers.items()) + "\n")
        if row.does_not_establish:
            lines.append("**Does not establish.**")
            lines += [f"- {item}" for item in row.does_not_establish]
            lines.append("")
        if row.superseded_by:
            lines.append("**Superseded by.** "
                         + ", ".join(f"`{s}`" for s in row.superseded_by) + "\n")
        if row.supersedes:
            lines.append("**Supersedes.** "
                         + ", ".join(f"`{s}`" for s in row.supersedes) + "\n")
        if row.evidence:
            lines.append("**Evidence.** "
                         + ", ".join(f"`{e}`" for e in row.evidence) + "\n")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    rows = load()
    if args and args[0] == "--render":
        target = REPO_ROOT / "docs" / "findings" / "README.md"
        target.write_text(render(rows), encoding="utf-8")
        print(f"wrote {target.relative_to(REPO_ROOT)} ({len(rows)} findings)")
        return 0
    if args and args[0] == "--check":
        stale = stale_evidence(rows)
        for item in stale:
            print(f"STALE {item}")
        print(f"{len(rows)} findings, {len(stale)} stale evidence paths")
        return 1 if stale else 0
    term = " ".join(args)
    hits = search(term, rows)
    if not hits:
        print(f"no findings match {term!r} (of {len(rows)})")
        return 0
    print(f"{len(hits)} of {len(rows)} findings match {term!r}\n")
    for row in sorted(hits, key=lambda r: r.date):
        print(f"[{row.verdict.value.upper()}] {row.finding_id}  ({row.date})")
        print(f"  Q: {row.question}")
        print(f"  scope: {row.scope}")
        for item in row.does_not_establish:
            print(f"  ! does not establish: {item}")
        if row.evidence:
            print(f"  evidence: {', '.join(row.evidence)}")
        print()
    return 0


__all__ = [
    "FINDINGS_SCHEMA_VERSION", "INDEX_PATH", "NEGATIVE", "Finding", "Verdict",
    "load", "render", "search", "stale_evidence",
]


if __name__ == "__main__":
    raise SystemExit(main())
