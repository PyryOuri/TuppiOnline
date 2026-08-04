"""Phase 5C architecture and boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_exact.integrity import DISCLAIMED_CAPABILITY_FIELDS, sealed_bank_containment

from tuppi_search.errors import SearchError
from tuppi_search.validation import (
    EARLIER_PACKAGES,
    EXCLUDED_TECHNIQUE_PATTERNS,
    boundary_report,
    dependency_direction_problems,
    development_reference_problems,
    excluded_technique_problems,
    frozen_agent_problems,
    legacy_import_problems,
    match_aware_not_retuned,
    require_no_full_state,
    search_package_root,
)


ROOT = Path(__file__).resolve().parents[2]


def test_the_boundary_report_holds():
    report = boundary_report()
    assert report["holds"] is True, report
    for key, value in report.items():
        if key.endswith("problems"):
            assert value == [], (key, value)


def test_no_earlier_package_imports_the_search_layer():
    """Phase 4 agents must not be able to reach PIMC, or their results change meaning."""

    assert dependency_direction_problems() == []
    for package in EARLIER_PACKAGES:
        directory = ROOT / "src" / package
        for module in sorted(directory.glob("*.py")):
            assert "tuppi_search" not in module.read_text(encoding="utf-8"), module


def test_frozen_phase4_agents_still_disclaim_search():
    assert frozen_agent_problems() == []
    from tuppi_match.freeze import build_snapshot

    for agent in build_snapshot()["agents"]:
        for field_name in DISCLAIMED_CAPABILITY_FIELDS:
            assert agent[field_name] is None, (agent["profile_key"], field_name)


def test_match_aware_is_not_retuned():
    """Phase 5B concluded its rising-score rules stay frozen. Phase 5C honours that."""

    assert match_aware_not_retuned() == []


def test_the_development_reference_is_still_the_committed_agent():
    assert development_reference_problems() == []
    from tuppi_agents import phase4_specifications_by_profile_key
    from tuppi_engine import strict_json_load_file

    from tuppi_search.config import DEVELOPMENT_REFERENCE_POLICY

    assert DEVELOPMENT_REFERENCE_POLICY == "partner_aware_v1"
    recorded = strict_json_load_file(
        str(ROOT / "reports" / "phase5a" / "phase4_frozen_agents.json")
    )
    by_key = {item["profile_key"]: item for item in recorded["agents"]}
    current = phase4_specifications_by_profile_key()[DEVELOPMENT_REFERENCE_POLICY]
    assert current.agent_id == by_key[DEVELOPMENT_REFERENCE_POLICY]["agent_id"]


def test_no_excluded_technique_family_is_present():
    """A source scan for the families Phase 5C is not allowed to add."""

    assert excluded_technique_problems() == []
    assert len(EXCLUDED_TECHNIQUE_PATTERNS) >= 8
    labels = {label for label, _ in EXCLUDED_TECHNIQUE_PATTERNS}
    for expected in ("ismcts", "pomcp", "cfr", "particle_filter", "neural_network"):
        assert expected in labels


def test_the_search_layer_never_imports_frozen_legacy_code():
    assert legacy_import_problems() == []


def test_the_sealed_promotion_bank_remains_unopened():
    assert sealed_bank_containment(ROOT) == []
    opened = sorted(
        path.name
        for path in (ROOT / "reports").rglob("*.json")
        if "sealed_open" in path.name
    )
    assert opened == []


def test_no_search_internals_reach_a_public_serializer():
    """Public and network serializers must not accept sampled worlds or PIMC objects."""

    from tuppi_engine import serialization

    text = Path(serialization.__file__).read_text(encoding="utf-8")
    for token in (
        "SampledWorld",
        "PimcDecision",
        "HypotheticalContinuation",
        "tuppi_search",
    ):
        assert token not in text, token


def test_a_public_event_log_never_carries_a_search_field(mid_position, smoke_config):
    """A PIMC decision must leave the public record untouched."""

    from tuppi_engine import public_event_log_to_data

    from tuppi_search.pimc import decide

    match_ref = mid_position.deal_state.match_ref
    before = public_event_log_to_data(
        mid_position.deal_state.events, match_ref=match_ref
    )
    decide(mid_position.observation, configuration=smoke_config, decision_seed="a")
    after = public_event_log_to_data(
        mid_position.deal_state.events, match_ref=match_ref
    )
    assert before == after
    serialized = repr(after)
    for token in ("world", "pimc", "sampled", "solver"):
        assert token not in serialized.lower()


def test_the_exact_solver_is_reached_only_through_hypothetical_states():
    """No module may solve a *real* deal state on the search path."""

    directory = search_package_root()
    for module in sorted(directory.glob("*.py")):
        if module.name in ("exact_tail.py", "oracle.py", "__init__.py"):
            continue
        text = module.read_text(encoding="utf-8")
        assert "solve_late_game" not in text, module
    # The tail solves hypothetical continuations; the oracle is a restricted
    # diagnostic that is allowed to read the real state and is not an agent.
    tail = (directory / "exact_tail.py").read_text(encoding="utf-8")
    assert "solve_late_game" in tail


def test_require_no_full_state_guards_the_entry_points(mid_position):
    with pytest.raises(SearchError):
        require_no_full_state(mid_position.deal_state)
    require_no_full_state(mid_position.observation)
    require_no_full_state(None)


def test_bulk_outputs_are_not_written_into_the_repository():
    """Committed Phase 5C artifacts must be compact summaries only."""

    reports = ROOT / "reports" / "phase5c"
    if not reports.exists():
        pytest.skip("Phase 5C reports have not been written yet")
    for path in sorted(reports.rglob("*")):
        if path.is_file():
            assert path.stat().st_size < 512_000, path


def test_no_committed_artifact_contains_a_hypothetical_world():
    """Sampled worlds must never be serialized into a committed artifact."""

    reports = ROOT / "reports" / "phase5c"
    if not reports.exists():
        pytest.skip("Phase 5C reports have not been written yet")
    for path in sorted(reports.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert "hidden_hands" not in text, path
        assert "initial_hands" not in text, path
        assert "sampled_hands" not in text, path


def test_the_search_package_declares_its_exclusions():
    """The package docstring must name what Phase 5C deliberately omits."""

    import tuppi_search

    doc = (tuppi_search.__doc__ or "").lower()
    for phrase in (
        "not an equilibrium solver",
        "strategy fusion",
        "no persistent search tree",
        "no learned",
        "one-way",
    ):
        assert phrase in doc, phrase
