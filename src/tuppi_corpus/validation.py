"""The one-way boundary gate for the corpus layer.

Every research layer in this repository owns a check that nothing earlier
references it, because the earlier layers' results are quoted against
specifications that record no corpus, no learning and no sampling.  If an engine
or agent module could import this package, every Phase 4, 5 and 6 result would
become retroactively corpus-assisted.

Written as a scan rather than a paragraph, for the same reason the exact and
search layers scan: it catches an accident, which is what actually happens.

Note the trap this module is careful about, and which the corpus layer walked
into once already: those scans read raw module *text*, so naming an outer
package in a comment inside an earlier one reports a dependency that does not
exist.  This scan matches an ``import`` statement, not a mention.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Every package that must not reach the corpus layer.
EARLIER_PACKAGES: tuple[str, ...] = (
    "tuppi_rules",
    "tuppi_engine",
    "tuppi_eval",
    "tuppi_agents",
    "tuppi_match",
    "tuppi_exact",
    "tuppi_search",
)


def repository_root(root: str | Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def dependency_direction_problems(root: str | Path | None = None) -> list[str]:
    """Drift descriptions for the one-way rule.  Empty means the boundary holds."""

    resolved = repository_root(root)
    problems: list[str] = []
    for package in EARLIER_PACKAGES:
        directory = resolved / "src" / package
        if not directory.is_dir():
            problems.append(f"src/{package} is missing")
            continue
        for module in sorted(directory.glob("*.py")):
            if any(name.startswith("tuppi_corpus") for name in _imports(module)):
                problems.append(
                    f"src/{package}/{module.name} imports tuppi_corpus; the corpus "
                    "layer must stay one-directional"
                )
    return problems


def excluded_technique_problems(root: str | Path | None = None) -> list[str]:
    """The corpus generates and stores play; it does not learn from it.

    Model fitting, gradient descent and search integration belong to the layers
    that consume a corpus, not to the one that writes it.  Keeping them out is
    what lets a generation run be a pure function of its manifest.
    """

    resolved = repository_root(root)
    directory = resolved / "src" / "tuppi_corpus"
    forbidden = ("torch", "tensorflow", "jax", "sklearn", "numpy", "random", "secrets")
    problems: list[str] = []
    for module in sorted(directory.glob("*.py")):
        imported = _imports(module)
        for name in forbidden:
            if any(item == name or item.startswith(f"{name}.") for item in imported):
                problems.append(
                    f"src/tuppi_corpus/{module.name} imports {name}; generation must "
                    "stay deterministic and dependency-free"
                )
    return problems


__all__ = [
    "EARLIER_PACKAGES",
    "dependency_direction_problems",
    "excluded_technique_problems",
    "repository_root",
]
