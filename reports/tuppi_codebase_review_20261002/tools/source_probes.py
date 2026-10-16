#!/usr/bin/env python3
"""Exercise selected real Python function bodies with dependency stubs.

No Tuppi module, NumPy, Torch, native library or game is imported. These probes
establish Python control-flow defects; they do not validate game semantics or
measure performance. Function bodies are AST-extracted unchanged from source.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from types import ModuleType, SimpleNamespace

WORKSPACE = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parents[1]


def extract(relative, name, class_name=None, globals_=None):
    path = WORKSPACE / relative
    source = path.read_bytes()
    tree = ast.parse(source)
    nodes = tree.body
    if class_name:
        nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == class_name).body
    node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    ns = {"__package__": "audit_stub", **(globals_ or {})}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    return ns[name], {"path": relative, "function": name, "line": node.lineno,
                       "sha256": hashlib.sha256(source).hexdigest()}


@contextmanager
def stubs():
    package = ModuleType("audit_stub")
    package.__path__ = []
    modules = {"audit_stub": package}
    for name in ("model", "native", "equity", "search"):
        module = ModuleType("audit_stub." + name)
        modules[module.__name__] = module
        setattr(package, name, module)
    package.model.load = lambda *a, **k: SimpleNamespace(encoder=2)
    package.native.showing_fix = False
    package.native.calls = []
    def set_showing_fix(on):
        package.native.showing_fix = on
        package.native.calls.append(on)
    package.native.set_showing_fix = set_showing_fix
    package.native.set_dd_extra_nolo = lambda extra: None
    package.equity.Equity = SimpleNamespace(load=lambda path: SimpleNamespace(table=[]))
    package.search.SearchAgent = lambda *a, **k: SimpleNamespace(**k)
    engine = ModuleType("tuppi_engine")
    for name in ("EnginePhase", "ExplicitDeal", "apply_match_action", "begin_explicit_deal", "create_match", "match_observation_for"):
        setattr(engine, name, lambda *a, **k: None)
    engine.EnginePhase = SimpleNamespace(SHOWING=0, TRICK_PLAY=1)
    engine.create_match = lambda **k: SimpleNamespace(terminal=False)
    modules[engine.__name__] = engine
    rules = ModuleType("tuppi_rules")
    rules.__path__ = []
    rules.MatchScore = lambda *args: args
    cards = ModuleType("tuppi_rules.cards")
    cards.FULL_DECK = ()
    modules.update({rules.__name__: rules, cards.__name__: cards})
    previous = {k: sys.modules.get(k) for k in modules}
    sys.modules.update(modules)
    try:
        yield package
    finally:
        for k, value in previous.items():
            if value is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = value


class Vector(list):
    def mean(self):
        return statistics.fmean(self)
    def std(self, ddof=1):
        assert ddof == 1
        return statistics.stdev(self)
    def __sub__(self, other):
        return Vector(a - b for a, b in zip(self, other))


class Matrix:
    def __init__(self, rows):
        self.rows = rows
    def __getitem__(self, key):
        row_slice, column = key
        return Vector(row[column] for row in self.rows[row_slice])


def run():
    findings = []
    with stubs() as package:
        best, src = extract("TuppiAI/tuppi_ai/best.py", "best_agents", globals_={
            "WORLDS": 128, "ROLLOUT": "clone", "TEAM_ROLLOUT": "team", "ANCHOR": "anchor",
            "EQUITY": "equity", "SOLVER_TAIL": 6, "KEEP": .003, "RAMI_MARGIN": 0.0,
            "ADAPTIVE_BIDS": {"batch": 128, "z": 2.5, "delta": .005}})
        best(seats=(0,), showing_fix=True)
        best(seats=(0,), team_rollout=False, showing_fix=False)
        assert package.native.showing_fix is True and package.native.calls == [True]
        findings.append({"id": "F01", "source": src, "probe": "best_agents(True) then pinned B0 factory(False)",
                         "observed": {"setter_calls": package.native.calls, "final_showing_fix": True},
                         "expected_contract": "False request must not silently retain True"})
        package.native.showing_fix = False
        package.native.calls = []
        factory, src = extract("TuppiAI/tuppi_ai/evaluate.py", "_make_candidate", globals_={
            "_W": {"equity": SimpleNamespace(table=[])}})
        factory("search:clone:w=1:sf=1")
        factory("search:clone:w=1:sf=0")
        assert package.native.showing_fix is True and package.native.calls == [True]
        findings.append({"id": "F02", "source": src, "probe": "search sf=1 side then sf=0 side in one worker",
                         "observed": {"setter_calls": package.native.calls, "effective_fix_for_both": True},
                         "expected_contract": "Reject incompatible process-global settings before constructing sides"})
        leg, src = extract("TuppiAI/tuppi_ai/match_eval.py", "_leg", globals_={
            "_W": {"candidate": {}, "opponent": {}, "ruleset": "v1"}})
        censored = leg(0, "stub", 0, 0)
        assert censored == {"result": .5, "deals": 0, "censored": True}
        findings.append({"id": "F03", "source": src, "probe": "nonterminal leg at cap with no game actions",
                         "observed": censored, "expected_contract": "Unknown result, with bounds in aggregation"})
    draws = []
    def search_values(env, mlp, obs, actions, batch, *args):
        draws.append(batch)
        # Alternating differences retain a wide CI; delta=0 prevents early stopping.
        return Matrix([[0.0, 1.0 if i % 2 else -1.0] for i in range(batch)])
    fake_np = SimpleNamespace(concatenate=lambda cols: Vector(v for col in cols for v in col),
                              sqrt=math.sqrt, array=lambda x: x)
    adaptive, src = extract("TuppiAI/tuppi_ai/search.py", "adaptive_values", "Searcher", {
        "native": SimpleNamespace(search_world_values=search_values, TcObs=object), "np": fake_np})
    searcher = SimpleNamespace(worlds=200, env=None, mlp=None, dd_left=6, rng=None)
    values, leader, drawn = adaptive(searcher, None, [0, 1], 128, 2.5, 0.0)
    assert drawn == 256 and draws == [128, 128]
    findings.append({"id": "F04", "source": src, "probe": "200-world cap, batch 128, unresolved equal means",
                     "observed": {"draws": draws, "drawn": drawn, "cap": searcher.worlds, "values": values},
                     "expected_contract": "Final batch is at most remaining worlds; validate positive batch/cap"})
    return {"scope": "AST-extracted real Python functions, dependency stubs only; no Tuppi game execution",
            "successful": True, "findings": findings}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="SOURCE_PROBES_CURRENT.json")
    args = parser.parse_args()
    destination = OUTPUT / args.out
    if destination.parent != OUTPUT or destination.exists():
        raise SystemExit("Use a new simple filename inside the review directory.")
    result = run()
    with destination.open("x") as handle:
        handle.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
