from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVALUATION_SOURCE = ROOT / "src" / "tuppi_eval"


def test_evaluation_package_does_not_import_legacy_or_strategic_systems() -> None:
    forbidden_imports = {
        "tuppi_legacy",
        "torch",
        "tensorflow",
        "networkx",
    }
    for path in EVALUATION_SOURCE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not {
            name.split(".", 1)[0] for name in imports
        }.intersection(forbidden_imports), path


def test_runtime_agent_construction_receives_no_hidden_hands_or_engine_state() -> None:
    tree = ast.parse(
        (EVALUATION_SOURCE / "arena.py").read_text(encoding="utf-8")
    )
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "construct_agent"
    ]
    assert calls
    for call in calls:
        assert {keyword.arg for keyword in call.keywords} == {
            "seed",
            "seat",
            "scripted_actions",
        }


def test_baseline_agents_choose_only_from_player_observation_legal_actions() -> None:
    source = (EVALUATION_SOURCE / "agents.py").read_text(encoding="utf-8")
    assert "observation.legal_actions" in source
    assert "observation.hand" not in source
    assert "initial_hands" not in source
