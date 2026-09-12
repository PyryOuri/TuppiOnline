"""The coverage module's own falsifier, and the concentration it reports.

`coverage.py` claims to find where the record is empty. Its one hand-written
input is `DIMENSIONS`, and a dimension nobody named stays invisible — so the
load-bearing test here is `test_every_finding_lands_in_some_dimension`, which
fails when a finding exists in a region the list does not name.
"""

from __future__ import annotations

import pytest

from tuppi_research.coverage import (
    DIMENSIONS,
    coverage,
    summary,
    unclaimed_findings,
    unexplored,
)


def test_every_finding_lands_in_some_dimension():
    """The module's falsifier. A finding matching no dimension is proof that
    `DIMENSIONS` has a hole, which is the blindness it claims to reduce."""

    stray = unclaimed_findings()
    assert stray == (), (
        "these findings match no dimension, so DIMENSIONS is incomplete: "
        f"{list(stray)}"
    )


def test_every_dimension_is_fully_declared():
    for dimension in DIMENSIONS:
        assert dimension.dimension_id.replace("_", "").isalnum()
        assert dimension.question.endswith("?")
        assert dimension.patterns
        assert dimension.why_it_matters.strip()
    ids = [d.dimension_id for d in DIMENSIONS]
    assert len(set(ids)) == len(ids)


def test_coverage_is_ordered_shallowest_first():
    depths = [item.depth for item in coverage()]
    assert depths == sorted(depths)


def test_the_record_is_concentrated_not_uniform():
    """The claim that motivated this module. If coverage were even, ranking
    dimensions by depth would be pointless."""

    depths = sorted(item.depth for item in coverage())
    assert depths[0] < depths[-1] / 3, (
        f"coverage looks uniform: shallowest {depths[0]}, deepest {depths[-1]}"
    )


def test_unexplored_reports_agent_axes_only():
    """`instrument` is the measuring apparatus. Proposing 'more instrument work'
    is not a structurally novel change to the agent."""

    assert "instrument" not in {c.dimension.dimension_id for c in unexplored(99)}
    assert "instrument" in {c.dimension.dimension_id for c in coverage()}


def test_unexplored_returns_the_shallowest_axes():
    ranked = [c for c in coverage() if c.dimension.dimension_id != "instrument"]
    assert [c.dimension.dimension_id for c in unexplored(3)] == [
        c.dimension.dimension_id for c in ranked[:3]
    ]


@pytest.mark.parametrize("dimension_id", ["adaptation", "score_state"])
def test_the_known_empty_axes_are_still_empty(dimension_id):
    """Pinned deliberately. When one of these finally gets explored this test
    fails, and that failure is the signal to re-read the ranking rather than a
    defect."""

    depth = summary()["depth_by_dimension"][dimension_id]
    assert depth <= 1, (
        f"{dimension_id} now has depth {depth}; the coverage ranking has moved "
        "and docs/audit/hypothesis_coverage.md should be re-read"
    )


def test_summary_is_reportable():
    payload = summary()
    assert payload["findings_indexed"] >= 29
    assert payload["dimensions"] == len(DIMENSIONS)
    assert set(payload["depth_by_dimension"]) == {
        d.dimension_id for d in DIMENSIONS
    }
