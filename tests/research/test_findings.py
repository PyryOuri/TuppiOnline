"""The findings index must stay valid, honest and in sync.

This index exists because four times in one sequence, work was started that a
file already in this repository would have redirected — and every one of those
four was an over-generalisation of a correctly scoped negative result. So the
tests here enforce two disciplines rather than merely checking a schema:

* a negative verdict without explicit scope limits is a validation failure;
* an evidence path that no longer exists is a validation failure.

The second is what stops the index rotting into a list of assertions nobody can
check.
"""

from __future__ import annotations

import json

import pytest

from tuppi_research.errors import LedgerError
from tuppi_research.findings import (
    FINDINGS_SCHEMA_VERSION,
    INDEX_PATH,
    NEGATIVE,
    REPO_ROOT,
    Verdict,
    load,
    render,
    search,
    stale_evidence,
)


@pytest.fixture(scope="module")
def rows():
    return load()


def test_the_index_loads_and_validates(rows):
    assert len(rows) >= 20
    assert len({r.finding_id for r in rows}) == len(rows)


def test_every_negative_verdict_records_its_scope_limits(rows):
    """The discipline. Every mistake this index prevents was a scope error."""
    for row in rows:
        if row.verdict in NEGATIVE:
            assert row.does_not_establish, (
                f"{row.finding_id} is {row.verdict.value} with no limits")


def test_no_evidence_path_has_rotted(rows):
    assert stale_evidence(rows) == ()


def test_every_row_is_tagged_and_dated(rows):
    for row in rows:
        assert row.tags
        assert len(row.date) == 10 and row.date[4] == "-"


def test_supersession_links_resolve(rows):
    ids = {r.finding_id for r in rows}
    for row in rows:
        for other in (*row.supersedes, *row.superseded_by):
            assert other in ids
    # and the relation is declared from both ends
    by_id = {r.finding_id: r for r in rows}
    for row in rows:
        for other in row.superseded_by:
            assert row.finding_id in by_id[other].supersedes, (
                f"{other} does not declare that it supersedes {row.finding_id}")


def test_the_generated_view_is_in_sync(rows):
    """`--render` output must match the committed README, or the doc is stale."""
    committed = (REPO_ROOT / "docs" / "findings" / "README.md").read_text(
        encoding="utf-8")
    assert render(rows) == committed, (
        "docs/findings/README.md is stale; run "
        "`python -m tuppi_research.findings --render`")


def test_a_negative_row_without_limits_is_refused(tmp_path):
    payload = {
        "schema": FINDINGS_SCHEMA_VERSION,
        "findings": [{
            "finding_id": "bad-row", "date": "2026-01-01",
            "question": "q", "verdict": "killed", "scope": "s",
            "does_not_establish": [], "tags": ["t"],
        }],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(LedgerError, match="records no scope limits"):
        load(path)


def test_an_unknown_verdict_is_refused(tmp_path):
    payload = {
        "schema": FINDINGS_SCHEMA_VERSION,
        "findings": [{
            "finding_id": "bad", "date": "2026-01-01", "question": "q",
            "verdict": "probably_fine", "scope": "s", "tags": ["t"],
        }],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(LedgerError, match="unknown verdict"):
        load(path)


def test_a_foreign_schema_is_refused(tmp_path):
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"schema": "other.v9", "findings": []}))
    with pytest.raises(LedgerError, match="declares schema"):
        load(path)


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("showing", "s1b-showing-kill"),
        ("pimc", "pimc-small-rejected"),
        ("world-count", "c3-world-count"),
        ("ablation", "t2-rule-ablation-closed"),
        ("latency", "trusted-transitions-policy-prohibition"),
    ],
)
def test_retrieval_finds_the_finding_that_would_have_redirected_the_work(
    rows, term, expected
):
    assert expected in {r.finding_id for r in search(term, rows)}


def test_the_four_detours_are_all_retrievable(rows):
    """Each of the four misses that motivated this index must be one query away."""
    for term, must_include in (
        ("showing", "s1b-showing-kill"),
        ("rules", "t2-rule-ablation-closed"),
        ("search", "pimc-small-rejected"),
        ("policy-boundary", "trusted-transitions-policy-prohibition"),
    ):
        hits = {r.finding_id for r in search(term, rows)}
        assert must_include in hits, f"{term!r} did not retrieve {must_include}"


def test_scope_limits_name_the_successor_where_one_exists(rows):
    """A superseded finding should point forward, so a reader cannot stop early."""
    by_id = {r.finding_id: r for r in rows}
    assert by_id["s1-showing-headroom"].superseded_by == ("s1b-showing-kill",)
    assert by_id["c1-opening-lead-headroom"].superseded_by == ("c3-world-count",)


def test_the_index_covers_both_negative_and_positive_verdicts(rows):
    verdicts = {r.verdict for r in rows}
    assert NEGATIVE & verdicts, "an index of only positives would be useless here"
    assert Verdict.MEASURED in verdicts
    assert Verdict.CONSTRAINT in verdicts
