#!/usr/bin/env python3
"""Create a new, hash-verified snapshot without editing any source checkout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
FROZEN = OUT / "frozen"
RUNTIME = OUT / "runtime"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory():
    items = []
    for component, folder, suffixes in (
        ("ai", "TuppiAI/tuppi_ai", {".py"}),
        ("ai", "TuppiAI/native", {".c", ".h"}),
        ("engine", "TuppiProject-current/src", {".py", ".json", ".yaml", ".toml"}),
        ("engine", "TuppiProject-current/configs/rules", {".json"}),
    ):
        base = ROOT / folder
        source_root = ROOT / ("TuppiAI" if component == "ai" else "TuppiProject-current")
        for source in sorted(base.rglob("*")):
            if source.is_file() and source.suffix in suffixes and "__pycache__" not in source.parts:
                if component == "ai" and source.is_relative_to(ROOT / "TuppiAI/native/research"):
                    continue  # unrelated immutable research overlay
                items.append((source, FROZEN / component / source.relative_to(source_root)))
    for relative in ("native/libtuppi.dylib", "models/vrpo1_actor_0504.pt", "models/vrpo3_final.pt",
                     "models/rollout_clone_small.pt", "models/equity_incumbent.json"):
        items.append((ROOT / "TuppiAI" / relative, FROZEN / "ai" / relative))
    for relative in ("docs/rules/project_target_v3.md", "pyproject.toml"):
        items.append((ROOT / "TuppiProject-current" / relative, FROZEN / "engine" / relative))
    return items


def main():
    if FROZEN.exists() or RUNTIME.exists():
        raise SystemExit("Snapshot destination already exists; verify it instead of overwriting.")
    items = inventory()
    hashes = {str(source.relative_to(ROOT)): digest(source) for source, _ in items}
    for source, target in items:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert digest(target) == hashes[str(source.relative_to(ROOT))]
    assert hashes == {str(source.relative_to(ROOT)): digest(source) for source, _ in items}, "Source changed during capture"
    # Runtime differs only by a deliberate library selector and optional shared
    # immutable MLP injection. The original comparator remains under frozen/.
    shutil.copytree(FROZEN / "ai", RUNTIME)
    source = RUNTIME / "tuppi_ai/native.py"
    text = source.read_text()
    needle = '_LIB_PATH = Path(__file__).resolve().parents[1] / "native" / "libtuppi.dylib"'
    assert text.count(needle) == 1
    text = text.replace(needle, 'import os as _cw_os\n' + needle + '\n_LIB_PATH = Path(_cw_os.environ.get("TUPPI_CHEAP_WINS_LIBRARY", str(_LIB_PATH)))')
    source.write_text(text)
    source = RUNTIME / "tuppi_ai/search.py"
    text = source.read_text()
    needle = 'opp_temp: float = 0.0, native_loop: bool = True):'
    assert text.count(needle) == 1
    text = text.replace(needle, 'opp_temp: float = 0.0, native_loop: bool = True, shared_mlp=None):')
    needle = 'self.mlp = native.Mlp(net) if self.native_loop else None'
    assert text.count(needle) == 1
    text = text.replace(needle, 'self.mlp = (shared_mlp if shared_mlp is not None else native.Mlp(net)) if self.native_loop else None')
    source.write_text(text)
    identities = {}
    for name in ("TuppiAI", "TuppiProject-current", "TuppiAI-prior"):
        identities[name] = {"head": subprocess.check_output(["git", "-C", str(ROOT / name), "rev-parse", "HEAD"], text=True).strip(),
                            "status": subprocess.check_output(["git", "-C", str(ROOT / name), "status", "--short"], text=True).splitlines()}
    manifest = {"schema": "tuppi.cheap_wins.frozen.v1", "source_hashes": hashes,
                "frozen_hashes": {str(target.relative_to(OUT)): digest(target) for _, target in items},
                "runtime_base_hashes": {str(p.relative_to(OUT)): digest(p) for p in RUNTIME.rglob("*") if p.is_file()},
                "repositories": identities, "scope": "Current source bytes, including the uncommitted lazy native buffers; no runtime user state or historical runs."}
    (OUT / "FROZEN.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"frozen_files": len(items), "source_bytes": sum(p.stat().st_size for p, _ in items), "source_unchanged": True}))


if __name__ == "__main__":
    main()
