"""Training on Linux/CUDA machines (Google Colab): see training/README.md.

Importing this package points `tuppi_ai.native` at the training build of the
native library (training/build_train.sh) and puts `ai/` and `engine/src` on the
path. It never touches the hosted library or the files the image is built from.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ.get("TUPPI_BUILD_DIR", REPO / "training" / "build"))
TRAIN_LIBRARY = BUILD / "libtuppi_train.so"
STOCK_LIBRARY = BUILD / "libtuppi_stock.so"
MODELS = REPO / "ai" / "models"

os.environ.setdefault("TUPPI_NATIVE_LIBRARY", str(TRAIN_LIBRARY))
# OpenBLAS reads this when it loads; tc_train_init also sets it at run time.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
for _p in (REPO / "ai", REPO / "engine" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
