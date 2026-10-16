"""Source, artifact, entrypoint and runtime identities (task C0.01, tests A01/A02/A12).

Everything here only reads. The baseline manifest is written once per output
directory and never rewritten; later checks recompute the same fields and
report differences instead of repairing them.

Private rooms and human records (`~/Library/Application Support/Tuppi`) are
never listed or read. Run banks under `TuppiAI/runs/` are protected by stat
metadata only (size, mtime), so their contents are never opened.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = AI_ROOT.parent
CHECKOUTS = {
    "AI": AI_ROOT,
    "ENGINE": WORKSPACE / "TuppiProject-current",
    "RESEARCH": WORKSPACE / "TuppiProject",
    "CLIENT": WORKSPACE / "TuppiClient-current",
}
#: HEADs recorded by the static audit (IMPLEMENTATION_SPEC.md section 0.1).
AUDIT_HEADS = {
    "AI": "4220f249e351905deb3a3754de812a01acf152d7",
    "ENGINE": "1347153f7d6e7bed95edddce9d35d28a3df91750",
    "RESEARCH": "622d5599318e4f1b2a82ef53bfc141970edc24de",
    "CLIENT": "7ba8ca283f01794170d105ba08c5a799f7bd7909",
}
INSTALLED_DYLIB = AI_ROOT / "native" / "libtuppi.dylib"
ASSETS = {
    "rollout_model": (AI_ROOT / "models" / "rollout_clone_small.pt",
                      "38737c9042695a4c960157fb77a8d17f308c5773899c2ec0c65b0d20546324f1"),
    "equity": (AI_ROOT / "models" / "equity_incumbent.json",
               "1496f77104f411c5cb55e2cef4573a10aead59acbd643261b755886bfeb60b91"),
    "installed_dylib": (INSTALLED_DYLIB,
                        "02d9b4fad98ebb342e12cd9ecb4723aaee1406c6c6b539a1dc4a5b2b002c1ab8"),
}
#: Owner-approved changes made after this programme (2026-09-29 onwards). The
#: audit values above stay exactly as recorded. The identity checks accept the
#: audit value, a checkout whose HEAD descends from its audited HEAD (history
#: extended, never rewritten), or an installed library registered here with
#: its reason. Register each later library installation the same way.
POST_AUDIT_UPGRADES = {
    "installed_dylib": {
        "3d07008f5353608e441f5320a29a2a7e838b737ae2d70b5146680d0cd762365a":
            "2026-09-29 exact search speed-ups E0-E5 (TuppiAI 7388c36, docs/EFFICIENCY_PLAN.md); "
            "every move and searched value identical to 02d9b4fa...; installed at the owner's request",
        "088c2f11a3734e2d091848b9d102300ae78797f796d063f89b2c022f7b481c29":
            "2026-09-30 merge of sp/selfplay (TuppiAI 54bd105): self-play, VRPO and own-team rollout support; "
            "with the new switches off, moves identical to 3d07008f... (profile_search fingerprint, 617 decisions); "
            "best_agents now uses SP1 own-team rollouts (docs/SELFPLAY_PLAN.md, owner-assigned item 1)",
        "285d186ebc08521bc83bbaecc4a3962c1dc07f83444704e0d6efa95e6f0ca5da":
            "2026-10-01 TuppiAI 450726c: NOLO extra solver-tail switch (off) and the B0-S1 sampler fix "
            "switched on by best_agents (W=128 screen non-inferior); best_agents(team_rollout=False) keeps "
            "the original sampler and clone rollouts",
    },
}


def accepted_asset(key: str, sha256: str, audit: str) -> bool:
    """True if an asset hash is the audited one or a registered post-audit upgrade."""
    return sha256 == audit or sha256 in POST_AUDIT_UPGRADES.get(key, {})


def head_descends_from_audit(alias: str, head: str) -> bool:
    """True if `head` is the audited HEAD or a descendant of it in that checkout."""
    audit = AUDIT_HEADS[alias]
    if head == audit:
        return True
    return subprocess.run(["git", "-C", str(CHECKOUTS[alias]), "merge-base", "--is-ancestor", audit, head],
                          capture_output=True).returncode == 0


AUDIT_DIR = WORKSPACE / "audit_deliverables" / "tuppi_design_20260925_184608"
PLAN_DIR = WORKSPACE / "audit_deliverables" / "tuppi_implementation_plan"
OUTPUT_DIR = WORKSPACE / "audit_deliverables" / "tuppi_implementation_output"
PRIVATE_EXCLUDED = (Path.home() / "Library" / "Application Support" / "Tuppi",)
PROTECTED_STAT_ONLY = (AI_ROOT / "runs",)
#: This programme's own additions to the AI checkout (new, untracked paths).
RESEARCH_ADDITIONS = ("tuppi_ai/research/", "native/research/", "tests/research/", "tests/conftest.py")


def is_research_addition(rel: str) -> bool:
    return rel.startswith(RESEARCH_ADDITIONS)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value) -> str:
    return sha256_bytes(canonical(value))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout


def git_identity(alias: str) -> dict:
    """HEAD, branch and every dirty/untracked path with its content hash.

    Hashes identify other authors' uncommitted files so a later check can prove
    they were not overwritten; nothing is modified.
    """
    repo = CHECKOUTS[alias]
    head = _git(repo, "rev-parse", "HEAD").strip()
    branch = _git(repo, "branch", "--show-current").strip()
    dirty = []
    for line in _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"):
        if not line:
            continue
        code, rel = line[:2], line[3:]
        if alias == "AI" and is_research_addition(rel):
            continue  # this programme's own files; identified by the output manifests instead
        if "__pycache__/" in rel:
            continue
        path = repo / rel
        entry = {"status": code, "path": rel}
        if path.is_file():
            entry["sha256"] = sha256_file(path)
        dirty.append(entry)
    return {"alias": alias, "path": str(repo), "head": head, "branch": branch,
            "audit_head": AUDIT_HEADS[alias], "head_matches_audit": head == AUDIT_HEADS[alias],
            "dirty": sorted(dirty, key=lambda e: e["path"])}


def tracked_hashes(alias: str) -> dict[str, str]:
    """Content hash of every tracked file in one checkout (working-tree bytes)."""
    repo = CHECKOUTS[alias]
    out = {}
    for rel in _git(repo, "ls-files", "-z").split("\0"):
        if rel and (repo / rel).is_file():
            out[rel] = sha256_file(repo / rel)
    return out


def source_drift(evidence_path: Path = AUDIT_DIR / "evidence.json") -> dict:
    """Compare every audited evidence file to its recorded hash (no reset)."""
    evidence = json.loads(evidence_path.read_text())
    rows = []
    for item in evidence:
        path = CHECKOUTS[item["repo"]] / item["path"]
        now = sha256_file(path) if path.exists() else None
        rows.append({"evidence_id": item["evidence_id"], "repo": item["repo"], "path": item["path"],
                     "audit_sha256": item["sha256"], "current_sha256": now,
                     "state": "missing" if now is None else ("same" if now == item["sha256"] else "changed")})
    changed = [r for r in rows if r["state"] != "same"]
    return {"schema_version": "tuppi.research.source_drift.v1", "evidence_file": str(evidence_path),
            "evidence_sha256": sha256_file(evidence_path), "files": rows,
            "changed_or_missing": [r["evidence_id"] for r in changed],
            "review_required": bool(changed)}


def stat_tree(root: Path) -> dict[str, list[int]]:
    """Size and mtime of every file under root; contents are never read."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = Path(dirpath) / name
            st = p.stat()
            out[str(p.relative_to(root))] = [st.st_size, st.st_mtime_ns]
    return out


def package_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256_file(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != ".DS_Store"}


# ------------------------------------------------------------------ runtime


def loaded_images() -> list[str]:
    """Paths of every Mach-O image mapped into this process (dyld's list)."""
    libc = ctypes.CDLL(None)
    libc._dyld_image_count.restype = ctypes.c_uint32
    libc._dyld_get_image_name.restype = ctypes.c_char_p
    libc._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    return [libc._dyld_get_image_name(i).decode() for i in range(libc._dyld_image_count())]


def loaded_tuppi_libraries() -> list[str]:
    return sorted(p for p in loaded_images() if "libtuppi" in os.path.basename(p))


def import_identity() -> dict:
    """Where the engine packages resolved, and whether RESEARCH code leaked in.

    Only modules already imported are inspected; this never imports RESEARCH.
    """
    import tuppi_engine
    import tuppi_rules

    engine_src = (CHECKOUTS["ENGINE"] / "src").resolve()
    research_src = (CHECKOUTS["RESEARCH"] / "src").resolve()
    engine_file = Path(tuppi_engine.__file__).resolve()
    rules_file = Path(tuppi_rules.__file__).resolve()
    foreign = sorted(name for name, mod in list(sys.modules.items())
                     if getattr(mod, "__file__", None)
                     and Path(mod.__file__).resolve().is_relative_to(research_src))
    return {
        "python": sys.version, "executable": sys.executable, "prefix": sys.prefix,
        "tuppi_engine": str(engine_file), "tuppi_rules": str(rules_file),
        "engine_resolves_to_v3_checkout": engine_file.is_relative_to(engine_src)
        and rules_file.is_relative_to(engine_src),
        "research_modules_loaded": foreign,
    }


def native_identity(lib=None) -> dict:
    """Identity of the library `tuppi_ai.native` actually loaded in this process."""
    from .. import native

    lib = lib or native.lib
    path = Path(lib._name).resolve()
    sizes = (ctypes.c_int * 2)()
    lib.tc_struct_sizes(sizes)
    return {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
            "struct_sizes": {"TcDeal": sizes[0], "TcObs": sizes[1]},
            "ctypes_sizes": {"TcDeal": ctypes.sizeof(native.TcDeal), "TcObs": ctypes.sizeof(native.TcObs)},
            "feature_dim": {"v1": lib.tc_feature_dim_v(1), "v2": lib.tc_feature_dim_v(2)},
            "num_actions": native.NUM_ACTIONS, "num_actions_v2": native.NUM_ACTIONS_V2,
            "mapped_tuppi_images": loaded_tuppi_libraries()}


def model_identity(path: Path = ASSETS["rollout_model"][0]) -> dict:
    from .. import model as qmodel
    from .. import native

    net = qmodel.load(path, "cpu")
    params = b"".join(v.detach().cpu().numpy().tobytes() for _k, v in sorted(net.state_dict().items()))
    return {"path": str(path), "sha256": sha256_file(path), "config": dict(net.config),
            "input_width": native.feature_dim(net.encoder), "outputs": native.NUM_ACTIONS,
            "parameter_bytes_sha256": sha256_bytes(params)}


def equity_identity(path: Path = ASSETS["equity"][0]) -> dict:
    import numpy as np

    from ..equity import Equity

    eq = Equity.load(path)
    table = np.ascontiguousarray(eq.table, dtype=np.float64)
    return {"path": str(path), "sha256": sha256_file(path), "dealer_win": eq.model.dealer_win,
            "table_shape": list(table.shape), "table_float64_sha256": sha256_bytes(table.tobytes()),
            "note": "Equity.load recomputes the table from the stored DealModel"}


def entrypoint_identity(seed: int = 0) -> dict:
    """The current best factory's effective construction, without constructing it."""
    from .. import best, search

    seats = {}
    for s in range(4):
        searcher_seed = seed + s + s  # best_agents adds the seat; SearchAgent adds it again
        seats[str(s)] = {"best_agents_seed_arg": seed + s, "searcher_seed": searcher_seed,
                         "env_seed": searcher_seed,
                         "scalar_rng_initial": (searcher_seed * 2654435761 + 1) % (1 << 64),
                         "numpy_default_rng_seed": searcher_seed}
    return {"entrypoint": "tuppi_ai.best.best_agents", "worlds": best.WORLDS, "dd_left": best.SOLVER_TAIL,
            "search_showing": 1, "show_searcher": None, "sooli_defaults": dict(search.SOOLI_DEFAULTS),
            "seat_seed_map": seats, "rollout_chunk_default": 32,
            "retained_v3_issue": "SearchAgent.choose_action sets rollout sooli options only for ruleset 2 "
                                 "(owner decision 2026-09-24: left unchanged; part of the as-is comparator)",
            "sources": {"best.py": sha256_file(Path(best.__file__)), "search.py": sha256_file(Path(search.__file__))}}


def protected_snapshot() -> dict:
    """Everything the research work must leave untouched (A12)."""
    return {
        "assets": {k: sha256_file(p) for k, (p, _h) in ASSETS.items()},
        "ai_tracked": tracked_hashes("AI"),
        "checkouts": {alias: git_identity(alias) for alias in CHECKOUTS},
        "input_packages": {"plan": package_hashes(PLAN_DIR), "audit": package_hashes(AUDIT_DIR)},
        "stat_only": {str(root): stat_tree(root) for root in PROTECTED_STAT_ONLY if root.exists()},
        "private_excluded_not_read": [str(p) for p in PRIVATE_EXCLUDED],
    }


def compare_protected(before: dict, after: dict) -> list[str]:
    """Differences between two snapshots, as readable strings (empty = unchanged).

    The research package's own new files are expected additions to the AI
    checkout's untracked set and are reported separately by the caller.
    """
    problems = []
    for key in ("assets", "ai_tracked", "input_packages", "stat_only"):
        if before[key] != after[key]:
            problems.append(f"{key} changed: {_diff_keys(before[key], after[key])}")
    for alias, ident in before["checkouts"].items():
        now = after["checkouts"][alias]
        if ident["head"] != now["head"] or ident["branch"] != now["branch"]:
            problems.append(f"{alias} HEAD/branch changed")
        old = {d["path"]: d.get("sha256") for d in ident["dirty"]}
        new = {d["path"]: d.get("sha256") for d in now["dirty"]}
        for path, h in old.items():
            if new.get(path) != h:
                problems.append(f"{alias} dirty file changed or vanished: {path}")
        added = sorted(set(new) - set(old))
        if added:
            problems.append(f"{alias} gained untracked/dirty files outside the research additions: {added[:5]}")
    return problems


def _diff_keys(a, b, prefix="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                out.extend(_diff_keys(a.get(k), b.get(k), f"{prefix}/{k}"))
        return out[:10]
    return [prefix or "/"]


def baseline_manifest(seed: int = 0) -> dict:
    """The immutable C0.01 baseline: separate AI/ENGINE/RESEARCH/CLIENT identities."""
    return {
        "schema_version": "tuppi.research.baseline_manifest.v1",
        "comparator_ids": {
            "B0-installed": "installed native/libtuppi.dylib + unmodified tuppi_ai.best entrypoint",
            "B0-source": "separately built unmodified-source library (see builds/)",
            "R0-parity": "research overlay build with every research switch disabled (see builds/)",
        },
        "checkouts": {alias: git_identity(alias) for alias in CHECKOUTS},
        "assets": {k: {"path": str(p), "audit_sha256": h, "sha256": sha256_file(p),
                       "matches_audit": sha256_file(p) == h} for k, (p, h) in ASSETS.items()},
        "imports": import_identity(),
        "native_installed": native_identity(),
        "model": model_identity(),
        "equity": equity_identity(),
        "entrypoint": entrypoint_identity(seed),
        "installed_source_correspondence": "UNPROVEN until the B0-installed vs B0-source parity boundary "
                                           "is tested (builds/parity_report.json)",
        "private_paths_excluded": [str(p) for p in PRIVATE_EXCLUDED],
    }


def write_once(path: Path, value: dict) -> str:
    """Write JSON once; an existing file must hold identical content."""
    data = json.dumps(value, indent=1, sort_keys=True).encode()
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"{path} exists with different content; baselines are immutable")
        return sha256_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.rename(path)
    return sha256_bytes(data)
