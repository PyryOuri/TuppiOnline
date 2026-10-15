"""The Phase 5C boundary gate.

Phase 5C adds a search agent to a repository whose earlier phases explicitly
disclaimed search. That is the situation in which the boundaries are easiest to
erode, so they are checked mechanically:

1. **One-way dependencies.** No earlier package may reference ``tuppi_search``.
2. **Frozen Phase 4 agents still disclaim search.** Every entry in the frozen
   snapshot keeps ``search``, ``belief_model``, ``endgame_solver``,
   ``hidden_hand_sampling``, ``learning``, and ``rollout_budget`` null.
3. **`match_aware_v1` is not retuned.** Its behaviour digest still matches the
   value committed in Phase 5A.
4. **`development_reference_v1` still resolves to the committed
   `partner_aware_v1`.**
5. **No excluded technique is present.** The source is scanned for the families
   Phase 5C is not allowed to add - ISMCTS, persistent trees, learned belief
   weighting, neural models, CFR, reinforcement learning, self-play training.
6. **The sealed bank is still sealed**, delegated to Phase 5B's check.
7. **No runtime import of frozen legacy code.**

Check 5 is a source scan, so it is a smoke alarm rather than a proof: it catches an
accidental import or a copied helper, not a determined re-implementation under
another name. It is worth having for exactly the accident it catches.
"""

from __future__ import annotations

from pathlib import Path
import re

from tuppi_exact.integrity import (
    DISCLAIMED_CAPABILITY_FIELDS,
    repository_root,
    sealed_bank_containment,
)

from .errors import SearchError


VALIDATION_SCHEMA_VERSION = "tuppi.search.boundary_report.v1"

#: Packages that existed before Phase 5C and must not depend on it.
EARLIER_PACKAGES: tuple[str, ...] = (
    "tuppi_rules",
    "tuppi_engine",
    "tuppi_eval",
    "tuppi_agents",
    "tuppi_legacy",
    "tuppi_match",
    "tuppi_exact",
)

#: Phase 5D-A additionally forbids solving policy mismatch by recursion. A nested
#: PIMC would multiply cost by the branching factor at every ply, and its semantics
#: do not terminate: the nested search would itself have to assume something about
#: *its* partner. These are the call shapes that would implement it.
RECURSIVE_SEARCH_PATTERNS: tuple[tuple[str, str], ...] = (
    ("nested_pimc", r"\bnested[-_ ]?pimc\b"),
    ("recursive_pimc", r"\brecursive[-_ ]?pimc\b"),
    ("pimc_inside_rollout", r"\bpimc_rollout_policy\b"),
)

#: The modules a rollout executes. Neither may construct a search agent, which is
#: the structural half of the no-recursion rule.
ROLLOUT_EXECUTED_MODULES: tuple[str, ...] = ("rollout.py", "exact_tail.py")

#: Technique families Phase 5C is explicitly not allowed to introduce. Matched
#: case-insensitively against the search package's own source.
EXCLUDED_TECHNIQUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("ismcts", r"\bis[-_ ]?mcts\b"),
    ("mo_ismcts", r"\bmo[-_ ]?is[-_ ]?mcts\b"),
    ("ris_mcts", r"\bris[-_ ]?mcts\b"),
    ("pomcp", r"\bpomcp\b"),
    ("cfr", r"\bcounterfactual regret\b"),
    ("particle_filter", r"\bparticle filter"),
    ("neural_network", r"\b(neural network|torch|tensorflow|keras)\b"),
    ("reinforcement_learning", r"\breinforcement learning\b"),
    ("self_play_training", r"\bself[-_ ]play training\b"),
    ("search_distillation", r"\bdistillation\b"),
)

#: Modules whose prose legitimately *names* a forbidden thing in order to forbid
#: it, or whose versioned algorithm name necessarily contains the family name.
#: This module holds the patterns themselves and the package docstring lists
#: what Phase 5C excludes, so both would otherwise trip their own checks. The
#: exemptions are narrow and explicit rather than hidden by fragmenting the
#: tokens, which would make the rules invisible to a reader grepping for them.
DOCUMENTED_EXCLUSION_MODULES: frozenset[str] = frozenset(
    {"validation.py", "__init__.py", "multi_observer.py"}
)


def search_package_root(root: str | Path | None = None) -> Path:
    return repository_root(root) / "src" / "tuppi_search"


def dependency_direction_problems(root: str | Path | None = None) -> list[str]:
    """Return drift descriptions for the one-way dependency rule."""

    resolved = repository_root(root)
    problems: list[str] = []
    for package in EARLIER_PACKAGES:
        directory = resolved / "src" / package
        if not directory.is_dir():
            problems.append(f"src/{package} is missing")
            continue
        for module in sorted(directory.glob("*.py")):
            if "tuppi_search" in module.read_text(encoding="utf-8"):
                problems.append(
                    f"src/{package}/{module.name} references tuppi_search; the "
                    "Phase 5C layer must stay one-directional"
                )
    return problems


def frozen_agent_problems() -> list[str]:
    """Return drift descriptions for the frozen Phase 4 population."""

    from tuppi_match.freeze import build_snapshot, verify_snapshot
    from tuppi_engine import strict_json_load_file

    problems: list[str] = []
    snapshot = build_snapshot()
    for agent in snapshot["agents"]:
        for field_name in DISCLAIMED_CAPABILITY_FIELDS:
            if agent.get(field_name) is not None:
                problems.append(
                    f"{agent['profile_key']}: {field_name} is no longer null, so a "
                    "Phase 5C capability has leaked into a frozen agent identity"
                )
    recorded_path = (
        repository_root() / "reports" / "phase5a" / "phase4_frozen_agents.json"
    )
    problems.extend(verify_snapshot(strict_json_load_file(str(recorded_path))))
    return problems


def match_aware_not_retuned() -> list[str]:
    """Confirm ``match_aware_v1`` still has its committed behaviour digest.

    Phase 5B measured its rising-score rules and concluded they should stay frozen
    rather than be retuned. Phase 5C touches neither, and says so checkably.
    """

    from tuppi_engine import strict_json_load_file
    from tuppi_match.freeze import behaviour_digest

    recorded = strict_json_load_file(
        str(repository_root() / "reports" / "phase5a" / "phase4_frozen_agents.json")
    )
    by_key = {item["profile_key"]: item for item in recorded["agents"]}
    problems: list[str] = []
    for key in ("match_aware_v1", "match_aware_no_match_features_v1"):
        current = behaviour_digest(key)
        if current != by_key[key]["behaviour_digest"]:
            problems.append(
                f"{key}: behaviour digest changed from "
                f"{by_key[key]['behaviour_digest']} to {current}"
            )
    return problems


def development_reference_problems() -> list[str]:
    """Confirm ``development_reference_v1`` is still the committed agent."""

    from tuppi_agents import phase4_specifications_by_profile_key
    from tuppi_engine import strict_json_load_file

    from .config import DEVELOPMENT_REFERENCE_POLICY

    recorded = strict_json_load_file(
        str(repository_root() / "reports" / "phase5a" / "phase4_frozen_agents.json")
    )
    by_key = {item["profile_key"]: item for item in recorded["agents"]}
    specifications = phase4_specifications_by_profile_key()
    current = specifications[DEVELOPMENT_REFERENCE_POLICY].agent_id
    expected = by_key[DEVELOPMENT_REFERENCE_POLICY]["agent_id"]
    if current != expected:
        return [
            f"development_reference_v1 ({DEVELOPMENT_REFERENCE_POLICY}) changed "
            f"identity from {expected} to {current}"
        ]
    return []


def excluded_technique_problems(root: str | Path | None = None) -> list[str]:
    """Scan the search package for technique families Phase 5C must not add."""

    directory = search_package_root(root)
    problems: list[str] = []
    for module in sorted(directory.glob("*.py")):
        text = module.read_text(encoding="utf-8").lower()
        for label, pattern in EXCLUDED_TECHNIQUE_PATTERNS:
            if re.search(pattern, text) is None:
                continue
            if module.name in DOCUMENTED_EXCLUSION_MODULES:
                continue
            problems.append(
                f"src/tuppi_search/{module.name} mentions the excluded technique "
                f"family {label!r}; Phase 5C adds classical root PIMC only"
            )
    return problems


def legacy_import_problems(root: str | Path | None = None) -> list[str]:
    """Confirm the search package never imports the frozen legacy archive."""

    directory = search_package_root(root)
    problems: list[str] = []
    for module in sorted(directory.glob("*.py")):
        if module.name in DOCUMENTED_EXCLUSION_MODULES:
            continue
        text = module.read_text(encoding="utf-8")
        if "tuppi_legacy" in text or "tuppi_emulator" in text:
            problems.append(
                f"src/tuppi_search/{module.name} references frozen legacy code"
            )
    return problems


def recursive_search_problems(root: str | Path | None = None) -> list[str]:
    """Confirm no rollout path can invoke a search.

    Two checks. The first is a name scan for the shapes a nested search would take.
    The second is structural and stronger: ``rollout.py`` and ``exact_tail.py`` are
    the modules a rollout executes, and neither may construct a PIMC agent or call
    :func:`tuppi_search.pimc.decide`. A rollout that could search would make the
    cost unbounded and the semantics circular.
    """

    directory = search_package_root(root)
    problems: list[str] = []
    for module in sorted(directory.glob("*.py")):
        text = module.read_text(encoding="utf-8")
        lowered = text.lower()
        if module.name not in DOCUMENTED_EXCLUSION_MODULES:
            for label, pattern in RECURSIVE_SEARCH_PATTERNS:
                if re.search(pattern, lowered) is not None:
                    problems.append(
                        f"src/tuppi_search/{module.name} mentions {label!r}; "
                        "Phase 5D-A forbids solving policy mismatch by recursion"
                    )
        if module.name in ROLLOUT_EXECUTED_MODULES:
            for token in (
                "UniformFeasiblePimcAgent",
                "PhaseGatedPimcAgent",
                "from .pimc import",
                "build_agent",
            ):
                if token in text:
                    problems.append(
                        f"src/tuppi_search/{module.name} references {token!r}; a "
                        "rollout must never be able to invoke a search"
                    )
    return problems


def boundary_report(root: str | Path | None = None) -> dict[str, object]:
    """Run every Phase 5C boundary check and report the result."""

    resolved = repository_root(root)
    dependency = dependency_direction_problems(resolved)
    frozen = frozen_agent_problems()
    retuned = match_aware_not_retuned()
    reference = development_reference_problems()
    excluded = excluded_technique_problems(resolved)
    legacy = legacy_import_problems(resolved)
    sealed = sealed_bank_containment(resolved)
    recursion = recursive_search_problems(resolved)
    return {
        "dependency_direction_problems": dependency,
        "recursive_search_problems": recursion,
        "development_reference_problems": reference,
        "excluded_technique_problems": excluded,
        "frozen_agent_problems": frozen,
        "holds": not (
            dependency
            or frozen
            or retuned
            or reference
            or excluded
            or legacy
            or sealed
            or recursion
        ),
        "legacy_import_problems": legacy,
        "match_aware_retuning_problems": retuned,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "sealed_bank_problems": sealed,
        "excluded_technique_families": [
            label for label, _ in EXCLUDED_TECHNIQUE_PATTERNS
        ],
        "scan_limitation": (
            "The excluded-technique check is a source scan. It catches an "
            "accidental import or a copied helper, not a determined "
            "re-implementation under a different name."
        ),
    }


def require_no_full_state(candidate: object) -> None:
    """Reject anything that looks like a real full engine state.

    Used at the search entry points as a defence in depth. The real protection is
    structural - the agent has no parameter for a state - but a stray positional
    argument in a future caller should fail loudly rather than be searched.
    """

    from tuppi_engine import DealState, MatchState

    if isinstance(candidate, (DealState, MatchState)):
        raise SearchError(
            "a search agent must never receive an engine state; it receives only "
            "a PlayerObservation"
        )
