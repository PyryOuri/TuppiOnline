"""Write the hosted compact controller's directory (tuppi_ai/compact.py).

    python tools/export_compact.py [--out models/compact] [--check]

Three networks, in role order: models/vrpo1_actor_0504.pt (0, rollouts),
models/vrpo3_final.pt (1, Heidi 1.0/1.1 anchor) and models/vrpo4_final.pt
(2, the Heidi 1.2 network), plus the match-equity table, as flat little-endian
files and models.json in the browser's asset schema (tuppi.browser.assets.v1,
byte for byte what the browser's tools/export_models.py writes).

The role 0 and 1 networks and the equity table are fixed for this release: an
existing file that differs from a fresh export stops the tool before anything
is written. Only vrpo4_final.f32 and models.json may change (new weights).
--check writes nothing and fails unless the directory equals a fresh export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCES = ("vrpo1_actor_0504.pt", "vrpo3_final.pt", "vrpo4_final.pt")
FIXED = ("vrpo1_actor_0504.f32", "vrpo3_final.f32", "equity.f64")


def export(models: Path) -> dict[str, bytes]:
    """{file name: bytes} of the whole directory, models.json last."""
    import numpy as np
    import torch
    torch.set_num_threads(1)
    from tuppi_ai import model, native
    from tuppi_ai.equity import Equity

    files, records = {}, []
    for role, name in enumerate(SOURCES):
        source = models / name
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        net = model.load(source, "cpu")
        state = {k: v.detach().cpu().float().numpy() for k, v in net.state_dict().items()}
        parts = [state["inp.weight"], state["inp.bias"]]
        for b in range(net.config["blocks"]):
            parts.extend(state[f"blocks.{b}.{field}"] for field in
                         ("norm.weight", "norm.bias", "fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"))
        parts.extend(state[key] for key in ("norm.weight", "norm.bias", "out.weight", "out.bias"))
        flat = np.concatenate([p.ravel() for p in parts]).astype("<f4")
        if not np.isfinite(flat).all():
            raise ValueError("Nonfinite model weights")
        if not np.array_equal(flat.view(np.uint32), native.flat_weights(net).view(np.uint32)):
            raise ValueError("flat layout differs from tc_mlp_new's")
        filename = name.replace(".pt", ".f32")
        blob = flat.tobytes()
        files[filename] = blob
        assert before == hashlib.sha256(source.read_bytes()).hexdigest(), "Model changed during export"
        records.append({"role": role, "file": filename, "config": net.config,
                        "in_dim": native.feature_dim(net.encoder), "out_dim": 156,
                        "count": len(flat), "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                        "source_file": name, "source_sha256": before})
    equity_source = models / "equity_incumbent.json"
    equity = np.asarray(Equity.load(equity_source).table, dtype="<f8")
    assert equity.shape == (25, 2) and np.isfinite(equity).all()
    blob = equity.tobytes()
    files["equity.f64"] = blob
    manifest = {"schema": "tuppi.browser.assets.v1", "api_version": 1, "ruleset": "project_target_v3",
                "models": records, "equity": {"file": "equity.f64", "bytes": len(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "source_sha256": hashlib.sha256(equity_source.read_bytes()).hexdigest()},
                "controller": {"reference_worlds": 1024, "dd_left": 6, "keep": 0.003, "keep_show": 0.03,
                               "adaptive": {"batch": 128, "z": 2.5, "delta": 0.005}, "showing_fix": True,
                               "sooli_belief": 17, "sooli_lambda": 0.3, "sooli_offer_margin": 0.02},
                "qualification": "Prototype; device performance and decision parity require separate results."}
    files["models.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=ROOT / "models/compact")
    p.add_argument("--models", type=Path, default=ROOT / "models", help="the .pt and equity sources")
    p.add_argument("--check", action="store_true", help="compare only; write nothing")
    a = p.parse_args()
    files = export(a.models)
    sha = {name: hashlib.sha256(blob).hexdigest() for name, blob in files.items()}
    changed = [name for name, blob in files.items()
               if not (a.out / name).exists() or (a.out / name).read_bytes() != blob]
    if a.check:
        if changed:
            raise SystemExit(f"differs from a fresh export: {', '.join(changed)}")
    else:
        moved = [name for name in FIXED if (a.out / name).exists() and name in changed]
        if moved:
            raise SystemExit(f"refusing to change fixed files: {', '.join(moved)}")
        a.out.mkdir(parents=True, exist_ok=True)
        for name in sorted(files, key=lambda n: n == "models.json"):  # the manifest last
            if name in changed:
                tmp = a.out / (name + ".tmp")
                tmp.write_bytes(files[name])
                tmp.replace(a.out / name)
    from tuppi_ai.compact import model_identity
    print(json.dumps({"output": str(a.out), "written": [] if a.check else changed, "sha256": sha,
                      "models_json_sha256": model_identity(a.out)["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
