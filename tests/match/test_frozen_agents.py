from __future__ import annotations

import json
from pathlib import Path

import pytest

from tuppi_match import (
    PHASE4_IMPLEMENTATION_COMMIT,
    behaviour_digest,
    build_snapshot,
    frozen_agent,
    verify_snapshot,
)
from tuppi_match.errors import MatchValidationError


ROOT = Path(__file__).resolve().parents[2]
COMMITTED_SNAPSHOT = ROOT / "reports" / "phase5a" / "phase4_frozen_agents.json"


def test_the_snapshot_records_everything_phase_4_froze() -> None:
    snapshot = build_snapshot()
    assert snapshot["implementation_commit"] == PHASE4_IMPLEMENTATION_COMMIT
    assert snapshot["ruleset_id"] == "project_target_v1"
    assert "is a promoted champion" in snapshot["promotion_status"]
    assert snapshot["promotion_status"].startswith("None of these agents")
    assert len(snapshot["agents"]) == 8
    for agent in snapshot["agents"]:
        assert agent["agent_id"].startswith("agent:sha256:")
        assert agent["profile_id"].startswith("profile:sha256:")
        assert agent["configuration_digest"].startswith("sha256:")
        assert agent["behaviour_digest"].startswith("sha256:")
        assert agent["ruleset_compatibility"] == ["project_target_v1"]
        assert agent["observation_schema_compatibility"] == [
            "tuppi.engine.player_observation.v1"
        ]
        for field in (
            "search",
            "belief_model",
            "endgame_solver",
            "hidden_hand_sampling",
            "learning",
            "rollout_budget",
        ):
            assert agent[field] is None, field
        assert agent["determinism"] == "deterministic"
        assert agent["seed_policy"] == "none"
        assert "not expert-validated" in agent["provenance"].lower()


def test_the_snapshot_is_stable_across_rebuilds() -> None:
    first = build_snapshot()
    second = build_snapshot()
    assert first["snapshot_digest"] == second["snapshot_digest"]
    assert verify_snapshot(first) == []


#: ``match_aware_no_match_features_v1`` is the match-aware family with every
#: rising-score rule switched off, which Phase 4 proved chooses exactly the same
#: actions as ``partner_aware_v1``. That is the one legitimate behavioural
#: duplicate; every other pair of frozen agents must differ.
EXPECTED_BEHAVIOURAL_DUPLICATES = frozenset(
    {frozenset({"partner_aware_v1", "match_aware_no_match_features_v1"})}
)


def test_the_behaviour_digest_is_content_based_not_name_based() -> None:
    """Two agents that decide identically must share a digest, not hide behind
    their names."""

    from tuppi_agents import STRATEGIC_PROFILE_KEYS
    from tuppi_match import behaviour_actions

    actions = {key: behaviour_actions(key) for key in STRATEGIC_PROFILE_KEYS}
    digests = {key: behaviour_digest(key) for key in STRATEGIC_PROFILE_KEYS}
    assert all(len(value) > 500 for value in actions.values())

    observed_duplicates = set()
    keys = sorted(STRATEGIC_PROFILE_KEYS)
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            same_actions = actions[left] == actions[right]
            assert same_actions is (digests[left] == digests[right]), (
                f"{left} and {right} disagree between actions and digest"
            )
            if same_actions:
                observed_duplicates.add(frozenset({left, right}))
    assert observed_duplicates == EXPECTED_BEHAVIOURAL_DUPLICATES

    # The ladder rungs themselves are all behaviourally distinct.
    from tuppi_agents import LADDER_PROFILE_KEYS

    ladder = {digests[key] for key in LADDER_PROFILE_KEYS}
    assert len(ladder) == len(LADDER_PROFILE_KEYS)


def test_a_behaviour_digest_is_stable() -> None:
    from tuppi_agents import STRATEGIC_PROFILE_KEYS

    for key in STRATEGIC_PROFILE_KEYS:
        assert behaviour_digest(key) == behaviour_digest(key)


def test_the_committed_snapshot_matches_the_current_agents() -> None:
    """Phase 5A must not have moved a single Phase 4 decision."""

    assert COMMITTED_SNAPSHOT.exists(), (
        "the Phase 4 baseline snapshot must be committed before Phase 5A can "
        "claim the agents are frozen"
    )
    committed = json.loads(COMMITTED_SNAPSHOT.read_text(encoding="utf-8"))
    problems = verify_snapshot(committed)
    assert problems == [], f"frozen Phase 4 agents drifted: {problems}"
    assert committed["snapshot_digest"] == build_snapshot()["snapshot_digest"]


def test_the_committed_snapshot_pins_the_phase_four_identities() -> None:
    committed = json.loads(COMMITTED_SNAPSHOT.read_text(encoding="utf-8"))
    recorded = {item["profile_key"]: item["agent_id"] for item in committed["agents"]}
    # The exact identities reported at the end of Phase 4.
    assert recorded["legacy_heuristic_port_v1"] == (
        "agent:sha256:2bfd7d7a6f8b84813f271252065ed5d3bf97727339c4b38794fd200351563e89"
    )
    assert recorded["reactive_contract_v1"] == (
        "agent:sha256:87e47923e5fbf0507490cfc97962093fb9f53463bc6e0e2dae71ceb7250182b9"
    )
    assert recorded["public_counting_v1"] == (
        "agent:sha256:87855eb185110bb48adc6785b466bd19a0bd0dabf6a1beb1d308ea0dd8a0fa17"
    )
    assert recorded["partner_aware_v1"] == (
        "agent:sha256:d8b426f1263c7ce32bdef82e4971dc2e494950f155e15db9b69fc6334a2ac929"
    )
    assert recorded["match_aware_v1"] == (
        "agent:sha256:ff888a9b055a7836bac53b4b95d6bd5e315a8eae8ef9bf4983910609332e1bcf"
    )


def test_drift_detection_actually_detects_drift() -> None:
    snapshot = build_snapshot()
    tampered = json.loads(json.dumps(snapshot))
    tampered["agents"][0]["behaviour_digest"] = "sha256:" + "0" * 64
    problems = verify_snapshot(tampered)
    assert problems and "behaviour_digest changed" in problems[0]

    removed = json.loads(json.dumps(snapshot))
    removed["agents"] = removed["agents"][1:]
    assert any("agent set changed" in item for item in verify_snapshot(removed))


def test_verify_rejects_a_foreign_document() -> None:
    with pytest.raises(MatchValidationError):
        verify_snapshot({"schema_version": "something.else"})
    with pytest.raises(MatchValidationError):
        verify_snapshot([])  # type: ignore[arg-type]


def test_an_unknown_profile_cannot_be_frozen() -> None:
    with pytest.raises(MatchValidationError, match="unknown Phase 4 profile"):
        frozen_agent("no_such_profile_v1")


def test_phase_5a_adds_no_search_to_any_frozen_agent() -> None:
    from tuppi_agents import phase4_agent_specifications

    for specification in phase4_agent_specifications():
        assert specification.search_budget is None
        assert specification.model_checkpoint_id is None
        configuration = specification.configuration
        for field in ("search", "belief_model", "endgame_solver", "learning"):
            assert configuration[field] is None
