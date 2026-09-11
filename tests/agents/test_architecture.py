from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tuppi_agents import (
    RULE_CATALOGUE,
    STRATEGIC_PROFILE_KEYS,
    Provenance,
    disableable_rule_ids,
    phase4_agent_specifications,
    registered_profiles,
    rule_catalogue_to_data,
    rules_for_profile,
)


ROOT = Path(__file__).resolve().parents[2]
AGENTS_SOURCE = ROOT / "src" / "tuppi_agents"
EVAL_SOURCE = ROOT / "src" / "tuppi_eval"

FORBIDDEN_ROOTS = frozenset(
    {
        "random",
        "secrets",
        "numpy",
        "torch",
        "tensorflow",
        "jax",
        "sklearn",
        "scipy",
        "tuppi_legacy",
    }
)

# The package has two layers and they are held to different rules. A *policy*
# module may be reached by a running agent, so it may not touch engine-private
# state, the evaluation package, or anything that resembles sampling. A
# *harness* module never participates in a decision: it builds specifications,
# runs the Phase 3 arena, or measures performance. Splitting them keeps the
# guards strict where strictness means something instead of blanket-banning
# words.
HARNESS_MODULES = frozenset(
    {
        "__init__.py",
        "benchmark.py",
        "controls.py",
        "evaluation.py",
        "factory.py",
        "improved_registry.py",
        "registry.py",
        # Declares research candidates and their identities; never participates
        # in a decision. Their runtime behaviour is in research_overrides.py,
        # which stays in the policy layer.
        "research_candidates.py",
        "runner.py",
    }
)


def _module_paths() -> list[Path]:
    return sorted(AGENTS_SOURCE.glob("*.py"))


def _policy_paths() -> list[Path]:
    return [path for path in _module_paths() if path.name not in HARNESS_MODULES]


def test_the_module_layers_are_exactly_as_declared() -> None:
    names = {path.name for path in _module_paths()}
    assert HARNESS_MODULES.issubset(names), sorted(HARNESS_MODULES - names)
    assert _policy_paths(), "the policy layer must not be empty"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return {name.split(".", 1)[0] for name in names}


def test_the_agents_package_imports_no_randomness_or_learning_stack() -> None:
    for path in _module_paths():
        assert not _imports(path).intersection(FORBIDDEN_ROOTS), path


def test_no_policy_module_touches_private_engine_state() -> None:
    forbidden_attributes = {
        "initial_hands",
        "hands",
        "active_deal",
        "completed_deals",
        "deal_id",
        "research_result",
    }
    for path in _policy_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
                raise AssertionError(f"{path.name} reads engine-private {node.attr!r}")
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in (
                    "tuppi_engine.state",
                    "tuppi_engine.match",
                    # A policy must never elide the engine's own invariants:
                    # tuppi_engine.trusted is a generation device, and a policy
                    # that entered it would silently disarm every state check
                    # for whatever ran inside its decision.
                    "tuppi_engine.trusted",
                )


def test_only_harness_modules_reach_into_the_evaluation_package() -> None:
    for path in _module_paths():
        if "tuppi_eval" in _imports(path):
            assert path.name in HARNESS_MODULES, path


def test_the_evaluation_package_reaches_strategic_agents_only_lazily() -> None:
    """``tuppi_eval`` must keep no module-level dependency on ``tuppi_agents``."""

    for path in sorted(EVAL_SOURCE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith("tuppi_agents") for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("tuppi_agents"), path


def test_no_policy_declares_a_search_budget_or_a_checkpoint() -> None:
    for specification in phase4_agent_specifications():
        assert specification.search_budget is None
        assert specification.model_checkpoint_id is None
        assert specification.determinism.value == "deterministic"


def test_no_phase4_rule_claims_expert_or_simulation_validation() -> None:
    assert RULE_CATALOGUE
    for rule in RULE_CATALOGUE:
        assert rule.provenance is not Provenance.EXPERT_VALIDATED
        assert rule.provenance is not Provenance.SIMULATION_VALIDATED
    data = rule_catalogue_to_data()
    assert data["no_expert_validated_rules"] is True
    assert all(
        item["provenance"] != "expert_validated" for item in data["rules"]
    )


def test_every_rule_is_catalogued_with_a_stable_versioned_identifier() -> None:
    identifiers = [rule.rule_id for rule in RULE_CATALOGUE]
    assert identifiers == sorted(identifiers)
    assert len(set(identifiers)) == len(identifiers)
    for rule in RULE_CATALOGUE:
        assert rule.rule_id.endswith(".v1")
        assert rule.implementing_profiles
        assert rule.condition and rule.action_preference
        assert rule.rationale and rule.limitations


def test_every_profile_implements_at_least_one_catalogued_rule() -> None:
    for key in STRATEGIC_PROFILE_KEYS:
        rules = rules_for_profile(key)
        assert rules, key
        profile = registered_profiles()[key]
        assert set(profile.enabled_rule_ids) | set(profile.disabled_rule_ids) == {
            rule.rule_id for rule in rules
        }


def test_convention_like_rules_are_independently_disableable() -> None:
    convention_like = [
        rule
        for rule in RULE_CATALOGUE
        if rule.rule_id.startswith("partner.legacy.")
        or rule.rule_id.startswith("match.")
    ]
    assert convention_like
    for rule in convention_like:
        assert rule.independently_disableable, rule.rule_id
    assert disableable_rule_ids("partner_aware_legacy_convention_v1")


def test_no_description_claims_expert_strength() -> None:
    banned = ("expert", "optimal", "strongest", "world-class", "grandmaster")
    for specification in phase4_agent_specifications():
        text = specification.description.lower()
        for token in banned:
            assert token not in text or "not an expert" in text, specification.agent_id
    for rule in RULE_CATALOGUE:
        assert "expert" not in rule.rationale.lower() or "not" in rule.rationale.lower()


def test_every_module_carries_a_docstring_explaining_its_boundary() -> None:
    for path in _module_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        docstring = ast.get_docstring(tree)
        assert docstring, path
        assert len(docstring) > 40, path


def test_the_counting_nolo_rules_are_ablatable_and_fall_back_to_the_rung_below() -> None:
    """T0-T3 found 12 of 16 unvalidated strategic rules could not be ablated at
    all — no documented legal fallback, so `HeuristicProfile` refused them. That
    was the binding constraint on the whole discovery route, and it was blocked
    on a design decision rather than on compute.

    These two are unblocked because their fallback is structural rather than
    invented: each adds one named component above the reactive base, so disabling
    it simply does not insert the component and the mode falls back to the layout
    of `reactive_contract_v1` — a real profile that is measured and shipped.
    """

    from tuppi_agents.counting import (
        NOLO_SHED_WINNER_RULE,
        NOLO_UNACCOUNTED_RULE,
        counting_layout,
    )
    from tuppi_agents.profiles import HeuristicProfile
    from tuppi_agents.reactive import PlayMode, layout_for

    key = "public_counting_v1"
    assert set(disableable_rule_ids(key)) >= {
        NOLO_UNACCOUNTED_RULE,
        NOLO_SHED_WINNER_RULE,
    }
    control = registered_profiles()[key]
    for rule, modes in (
        (NOLO_UNACCOUNTED_RULE, (PlayMode.NOLO_LEAD,)),
        (
            NOLO_SHED_WINNER_RULE,
            (PlayMode.NOLO_FOLLOW, PlayMode.NOLO_DISCARD, PlayMode.NOLO_CONCEDED),
        ),
    ):
        variant = HeuristicProfile.build(
            profile_key=key,
            family=control.family,
            showing_policy=control.showing_policy,
            parameters=dict(control.parameters),
            disabled_rule_ids=(rule,),
            description="ablation",
        )
        assert variant.profile_id != control.profile_id
        for mode in modes:
            reactive = layout_for(
                PlayMode.NOLO_DISCARD if mode is PlayMode.NOLO_CONCEDED else mode
            )
            # Disabled: exactly the rung below. Enabled: one component more.
            assert counting_layout(mode, variant) == reactive
            assert len(counting_layout(mode, control)) == len(reactive) + 1


def test_ablating_a_counting_rule_leaves_a_policy_that_still_plays_legally() -> None:
    """A fallback that is not exercised is not a fallback. The score vector must
    also stay the same length as the layout, which is what makes this more than a
    flag flip."""

    from tuppi_agents.counting import NOLO_SHED_WINNER_RULE, PublicCountingPolicy
    from tuppi_agents.profiles import HeuristicProfile
    from tuppi_engine import EnginePhase

    from tests.search.conftest import walk_deal

    control = registered_profiles()["public_counting_v1"]
    variant = HeuristicProfile.build(
        profile_key="public_counting_v1",
        family=control.family,
        showing_policy=control.showing_policy,
        parameters=dict(control.parameters),
        disabled_rule_ids=(NOLO_SHED_WINNER_RULE,),
        description="ablation",
    )
    policy = PublicCountingPolicy(agent_id="ablation", profile=variant)
    checked = 0
    for stream in range(6):
        for position in walk_deal(stream_index=stream):
            observation = position.observation
            if observation.phase is not EnginePhase.TRICK_PLAY:
                continue
            if observation.contract is None or observation.contract.value != "NOLO":
                continue
            assert policy.choose_action(observation) in observation.legal_actions
            checked += 1
    assert checked >= 20, "no NOLO trick-play decision was exercised"
