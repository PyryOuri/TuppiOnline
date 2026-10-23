"""Write a network's weights for the PyTorch-free lite bot (default models/vrpo3_final.lite.npz).

    python tools/export_lite_model.py [--check]
    python tools/export_lite_model.py --model models/vrpo4_final.pt --out models/vrpo4_final.lite.npz [--check]

Without --model the product anchor is exported to tuppi_ai.lite.MODEL, as before.
--model and --out go together (Heidi 1.2: the .pt beside its .lite.npz).
--check only verifies that the existing file equals a fresh export.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def export(path=None) -> bytes:
    """The lite .npz bytes of checkpoint `path` (default: the product anchor)."""
    import numpy as np
    from tuppi_ai import model, native
    if path is None:
        from tuppi_ai.best import ANCHOR
        path = ANCHOR
    net = model.load(path, "cpu")
    cfg = net.config
    buffer = io.BytesIO()
    np.savez(buffer, weights=native.flat_weights(net),
             shape=np.array([cfg["width"], cfg["blocks"], cfg.get("encoder", 1)], dtype=np.int64))
    return buffer.getvalue()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--model", default=None, help="export this checkpoint instead of the product anchor")
    p.add_argument("--out", default=None, help="the .lite.npz to write or check (required with --model)")
    a = p.parse_args()
    if (a.model is None) != (a.out is None):
        p.error("--model and --out go together")
    from tuppi_ai.lite import MODEL
    target = MODEL if a.out is None else Path(a.out)
    data = export(a.model)
    if a.check:  # zip timestamps differ between exports; compare the arrays bitwise
        import numpy as np
        with np.load(target, allow_pickle=False) as old, np.load(io.BytesIO(data), allow_pickle=False) as new:
            if set(old) != set(new) or any(old[k].dtype != new[k].dtype or old[k].tobytes() != new[k].tobytes() for k in new):
                raise SystemExit(f"{target.name} differs from a fresh export")
        data = target.read_bytes()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if a.model is not None:  # as tools/export_lite_model.py of research/base-network-20261022
            print(json.dumps({"model": a.model, "out": str(target), "sha256": hashlib.sha256(data).hexdigest()}))
            return
    print(target.name, hashlib.sha256(data).hexdigest(), len(data))


if __name__ == "__main__":
    main()
