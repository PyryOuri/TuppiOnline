"""Write models/vrpo3_final.lite.npz: the anchor actor's weights for the PyTorch-free lite bot.

    python tools/export_lite_model.py [--check]

--check only verifies that the existing file equals a fresh export.
"""
from __future__ import annotations

import argparse
import hashlib
import io
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def export() -> bytes:
    import numpy as np
    from tuppi_ai import model, native
    from tuppi_ai.best import ANCHOR
    net = model.load(ANCHOR, "cpu")
    cfg = net.config
    buffer = io.BytesIO()
    np.savez(buffer, weights=native.flat_weights(net),
             shape=np.array([cfg["width"], cfg["blocks"], cfg.get("encoder", 1)], dtype=np.int64))
    return buffer.getvalue()


def main() -> None:
    p = argparse.ArgumentParser(); p.add_argument("--check", action="store_true"); a = p.parse_args()
    from tuppi_ai.lite import MODEL
    data = export()
    if a.check:  # zip timestamps differ between exports; compare the arrays bitwise
        import numpy as np
        with np.load(MODEL, allow_pickle=False) as old, np.load(io.BytesIO(data), allow_pickle=False) as new:
            if set(old) != set(new) or any(old[k].dtype != new[k].dtype or old[k].tobytes() != new[k].tobytes() for k in new):
                raise SystemExit("lite model differs from a fresh export")
        data = MODEL.read_bytes()
    else:
        MODEL.write_bytes(data)
    print(MODEL.name, hashlib.sha256(data).hexdigest(), len(data))


if __name__ == "__main__":
    main()
