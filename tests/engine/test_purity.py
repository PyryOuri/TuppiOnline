from __future__ import annotations

import ast
import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE_MODULES = (
    "actions.py",
    "deal.py",
    "event_builder.py",
    "identity.py",
    "events.py",
    "match.py",
    "observations.py",
    "results.py",
    "state.py",
    "transitions.py",
    "validation.py",
)


def test_transition_core_has_no_rng_io_gui_network_or_legacy_imports() -> None:
    forbidden_imports = {
        "random",
        "secrets",
        "socket",
        "tkinter",
        "tuppi_legacy",
        "urllib",
    }
    forbidden_calls = {"input", "print", "open"}
    for filename in CORE_MODULES:
        path = ROOT / "src/tuppi_engine" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] not in forbidden_imports
                    for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports, path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, path


def test_no_clean_engine_module_imports_legacy() -> None:
    for path in (ROOT / "src/tuppi_engine").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    alias.name.split(".")[0] != "tuppi_legacy"
                    for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] != "tuppi_legacy", path


def test_transition_modules_expose_no_mutable_global_constants() -> None:
    for module_name in (
        "tuppi_engine",
        "tuppi_engine.actions",
        "tuppi_engine.deal",
        "tuppi_engine.events",
        "tuppi_engine.event_builder",
        "tuppi_engine.identity",
        "tuppi_engine.match",
        "tuppi_engine.observations",
        "tuppi_engine.results",
        "tuppi_engine.state",
        "tuppi_engine.transitions",
        "tuppi_engine.validation",
    ):
        module = importlib.import_module(module_name)
        for name, value in vars(module).items():
            if name.isupper() or name == "__all__":
                assert not isinstance(value, (list, dict, set, bytearray)), (
                    module_name,
                    name,
                )
