#!/usr/bin/env python3
"""Export the selected product assets without a browser Python dependency."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ai", type=Path, default=Path(__file__).resolve().parents[2] / "TuppiAI-hosted")
args = parser.parse_args()
sys.path.insert(0, str(args.ai.resolve()))
import numpy as np
import torch
torch.set_num_threads(1)
from tuppi_ai import model, native
from tuppi_ai.equity import Equity

out = Path(__file__).resolve().parents[1] / "web/assets"
out.mkdir(parents=True, exist_ok=True)
records = []
for role, name in enumerate(("vrpo1_actor_0504.pt", "vrpo3_final.pt")):
    source = args.ai / "models" / name
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
    filename = name.replace(".pt", ".f32")
    blob = flat.tobytes()
    (out / filename).write_bytes(blob)
    assert before == hashlib.sha256(source.read_bytes()).hexdigest(), "Model changed during export"
    records.append({"role": role, "file": filename, "config": net.config,
                    "in_dim": native.feature_dim(net.encoder), "out_dim": 156,
                    "count": len(flat), "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                    "source_file": name, "source_sha256": before})
equity_source = args.ai / "models/equity_incumbent.json"
equity = np.asarray(Equity.load(equity_source).table, dtype="<f8")
assert equity.shape == (25, 2) and np.isfinite(equity).all()
blob = equity.tobytes()
(out / "equity.f64").write_bytes(blob)
manifest = {"schema": "tuppi.browser.assets.v1", "api_version": 1, "ruleset": "project_target_v3",
            "models": records, "equity": {"file": "equity.f64", "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(), "source_sha256": hashlib.sha256(equity_source.read_bytes()).hexdigest()},
            "controller": {"reference_worlds": 1024, "dd_left": 6, "keep": 0.003, "keep_show": 0.03,
                           "adaptive": {"batch": 128, "z": 2.5, "delta": 0.005}, "showing_fix": True,
                           "sooli_belief": 17, "sooli_lambda": 0.3, "sooli_offer_margin": 0.02},
            "qualification": "Prototype; device performance and decision parity require separate results."}
(out / "models.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"output": str(out), "model_bytes": sum(r["bytes"] for r in records), "models": len(records)}))
