from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_agents import (
    LADDER_PROFILE_KEYS,
    RULE_CATALOGUE,
    STRATEGIC_PROFILE_KEYS,
    phase4_specifications_by_profile_key,
    registered_profiles,
)


ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "agents"
REQUIRED_DOCS = (
    "architecture.md",
    "baseline_profiles.md",
    "legacy_port.md",
    "phase4_evaluation.md",
    "public_inference.md",
    "strategy_rule_catalogue.md",
)


def _text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_every_required_document_exists_and_is_substantial() -> None:
    present = sorted(path.name for path in DOCS.glob("*.md"))
    assert present == sorted(REQUIRED_DOCS)
    for name in REQUIRED_DOCS:
        assert len(_text(name)) > 1500, name


def test_the_catalogue_document_covers_every_rule() -> None:
    text = _text("strategy_rule_catalogue.md")
    for rule in RULE_CATALOGUE:
        assert f"`{rule.rule_id}`" in text, rule.rule_id
        assert f"`{rule.provenance.value}`" in text
    assert "No Phase 4 rule carries this label" in text


def test_the_profile_document_lists_every_registered_profile() -> None:
    text = _text("baseline_profiles.md")
    specifications = phase4_specifications_by_profile_key()
    profiles = registered_profiles()
    for key in STRATEGIC_PROFILE_KEYS:
        assert f"`{key}`" in text, key
        assert specifications[key].agent_id[:29] in text, key
        assert profiles[key].profile_id[:31] in text, key


def test_the_documentation_states_the_observation_only_boundary() -> None:
    text = _text("architecture.md")
    for phrase in (
        "observation-only",
        "PlayerObservation",
        "information-set",
        "tie-break",
        "diagnostics",
    ):
        assert phrase.lower() in text.lower(), phrase


def test_the_documentation_separates_hard_inference_from_belief() -> None:
    text = _text("public_inference.md")
    assert "is not a belief model" in text
    assert "precursor" in text
    assert "no probabilities" in text.lower()
    assert "pigeonhole" in text.lower()


def test_the_documentation_explains_why_no_agent_is_expert() -> None:
    profiles = _text("baseline_profiles.md")
    assert "Why no agent here is described as an expert" in profiles
    assert "expert_validated" in profiles
    assert "no expert validation has happened" in profiles.lower()
    catalogue = _text("strategy_rule_catalogue.md")
    assert "no expert validation has taken place" in catalogue.lower()


def test_the_documentation_describes_each_rung_capability() -> None:
    text = _text("baseline_profiles.md")
    for key in LADDER_PROFILE_KEYS:
        assert f"`{key}`" in text
    assert "capability" in text.lower()
    assert "ladder is ordered by" in text.lower()


def test_the_documentation_states_the_bank_reuse_restriction() -> None:
    text = _text("phase4_evaluation.md")
    assert "development bank" in text.lower()
    assert "sealed" in text.lower()
    assert "not" in text.lower()
    assert "censored" in text.lower()


def test_the_documentation_explains_future_search_and_learning_use() -> None:
    text = _text("architecture.md")
    assert "rollout polic" in text.lower()
    assert "opponent model" in text.lower()
    assert "belief model" in text.lower()
    assert "deliberately does not provide" in text.lower()


def test_the_legacy_document_lists_every_documented_deviation() -> None:
    text = _text("legacy_port.md")
    for phrase in (
        "Show-rank eligibility is narrower",
        "There is no cardless verbal declaration",
        "The flat-scoring branch is unreachable",
        "A dead threshold was dropped",
        "The score state has a different shape",
        "No partnership awareness",
    ):
        assert phrase in text, phrase
    assert "is **not** claimed" in text


def test_the_root_readme_documents_phase_four() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "tuppi_agents" in readme
    assert "tuppi_agents.runner" in readme
    for key in LADDER_PROFILE_KEYS:
        assert key in readme, key
    assert "docs/agents/" in readme


def test_the_examples_readme_shows_every_required_demonstration() -> None:
    text = (ROOT / "examples" / "agents" / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "Obtaining an action from each strategic agent",
        "Viewing structured diagnostics",
        "Running a fixed deal",
        "Running a heterogeneous partnership",
        "Running baseline cross-play",
    ):
        assert phrase in text, phrase
