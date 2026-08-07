"""Phase 5D-A boundary tests: no recursion, nothing frozen moved."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuppi_exact.integrity import sealed_bank_containment

from tuppi_search.validation import (
    ROLLOUT_EXECUTED_MODULES,
    RECURSIVE_SEARCH_PATTERNS,
    boundary_report,
    recursive_search_problems,
    search_package_root,
)


ROOT = Path(__file__).resolve().parents[2]


def test_the_boundary_report_still_holds():
    report = boundary_report()
    assert report["holds"] is True, report
    for key, value in report.items():
        if key.endswith("problems"):
            assert value == [], (key, value)


def test_no_recursive_search_is_implemented():
    assert recursive_search_problems() == []
    labels = {label for label, _ in RECURSIVE_SEARCH_PATTERNS}
    assert {"nested_pimc", "recursive_pimc"} <= labels


def test_the_modules_a_rollout_executes_cannot_construct_a_search():
    """The structural half of the no-recursion rule, checked directly."""

    directory = search_package_root()
    assert ROLLOUT_EXECUTED_MODULES == ("rollout.py", "exact_tail.py")
    for name in ROLLOUT_EXECUTED_MODULES:
        text = (directory / name).read_text(encoding="utf-8")
        for token in (
            "UniformFeasiblePimcAgent",
            "PhaseGatedPimcAgent",
            "from .pimc import",
            "build_agent",
        ):
            assert token not in text, (name, token)


def test_a_planted_recursive_call_would_be_caught(tmp_path):
    """The check must actually fire, not merely pass on clean source."""

    from tuppi_search.validation import RECURSIVE_SEARCH_PATTERNS as patterns
    import re

    planted = "value = nested_pimc(observation)\n"
    hits = [
        label
        for label, pattern in patterns
        if re.search(pattern, planted.lower()) is not None
    ]
    assert "nested_pimc" in hits
    del tmp_path


def test_the_gated_agents_never_call_decide_from_a_rollout():
    """The gated agent's own module must route rollouts through the frozen policy."""

    text = (search_package_root() / "hybrid.py").read_text(encoding="utf-8")
    # It constructs a PIMC agent for the searched phase and a frozen Phase 4 agent
    # for the delegated one. It must not add a rollout policy of its own.
    assert "construct_agent(specification, seat=seat)" in text
    assert "rollout_policy_key=" not in text


def test_the_frozen_phase4_population_is_unchanged():
    from tuppi_match.freeze import build_snapshot, verify_snapshot
    from tuppi_engine import strict_json_load_file

    recorded = strict_json_load_file(
        str(ROOT / "reports" / "phase5a" / "phase4_frozen_agents.json")
    )
    assert verify_snapshot(recorded) == []
    del build_snapshot


def test_match_aware_is_still_not_retuned():
    from tuppi_search.validation import match_aware_not_retuned

    assert match_aware_not_retuned() == []


def test_the_phase5c_agents_are_unchanged():
    from tuppi_search.registry import phase5c_specifications, registry_snapshot

    committed = json.loads(
        (ROOT / "reports" / "phase5c" / "pimc_registry.json").read_text()
    )
    live = registry_snapshot()
    assert live["registry_digest"] == committed["registry_digest"]
    by_key = {item["profile_key"]: item["agent_id"] for item in committed["agents"]}
    for key, specification in phase5c_specifications().items():
        assert specification.agent_id == by_key[key], key


def test_the_phase5c_evaluation_report_is_untouched():
    """The negative result must not be rewritten after observing later variants."""

    report = json.loads(
        (ROOT / "reports" / "phase5c" / "phase5c_evaluation.json").read_text()
    )
    inference = report["primary_complete_match_comparison"][
        "primary_match_inference"
    ]
    assert inference["candidate_match_win_probability"] == 0.15625
    assert inference["pair_outcomes"] == {"loss": 22, "tie": 10, "win": 0}
    assert inference["complete_pair_count"] == 32


def test_the_sealed_promotion_bank_remains_unopened():
    assert sealed_bank_containment(ROOT) == []
    opened = sorted(
        path.name
        for path in (ROOT / "reports").rglob("*.json")
        if "sealed_open" in path.name
    )
    assert opened == []


def test_the_archive_hashes_are_unchanged():
    from tuppi_exact.integrity import archive_manifest_agreement

    assert archive_manifest_agreement(ROOT) == []


def test_every_phase5d_a_fixture_is_a_fresh_unsealed_development_bank():
    from tuppi_search.evaluation import (
        DEAL_ABLATION_ROOT_SEED,
        MATCH_COMPARISON_ROOT_SEED,
        phase5d_a_corpus_bank,
        phase5d_a_deal_bank,
        phase5d_a_hetero_bank,
        phase5d_a_match_bank,
    )

    phase5c_seeds = {MATCH_COMPARISON_ROOT_SEED, DEAL_ABLATION_ROOT_SEED}
    banks = [
        phase5d_a_match_bank(stream_count=4),
        phase5d_a_hetero_bank(stream_count=4),
        phase5d_a_deal_bank(stream_count=4),
        phase5d_a_corpus_bank(stream_count=4),
    ]
    seeds = {bank.root_seed for bank in banks}
    assert len(seeds) == len(banks), "Phase 5D-A banks must not share a seed"
    assert seeds.isdisjoint(phase5c_seeds)
    for bank in banks:
        assert bank.role.value == "development"
        assert bank.supports_promotion is False
    # Distinct banks must produce distinct identities, not just distinct names.
    assert len({bank.bank_id for bank in banks}) == len(banks)


def test_phase5d_a_bulk_output_is_not_written_into_the_repository():
    reports = ROOT / "reports" / "phase5d_a"
    if not reports.exists():
        pytest.skip("Phase 5D-A reports have not been written yet")
    for path in sorted(reports.rglob("*")):
        if path.is_file():
            assert path.stat().st_size < 512_000, path


def test_no_committed_phase5d_a_artifact_contains_a_hidden_hand():
    reports = ROOT / "reports" / "phase5d_a"
    if not reports.exists():
        pytest.skip("Phase 5D-A reports have not been written yet")
    for path in sorted(reports.rglob("*.json")):
        text = path.read_text(encoding="utf-8")
        for token in ("hidden_hands", "initial_hands", "sampled_hands", "true_hands"):
            assert token not in text, (path, token)
