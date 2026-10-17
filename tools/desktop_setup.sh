#!/bin/sh
# One-time setup of a Linux compute machine (written for Fedora; XI-PIB task,
# docs/XI_PIB_TASK.md). Run from the root of this checkout
# (branch ai/research/play-inference-20261016 of PyryOuri/TuppiOnline).
# Leaves: ../tuppi-engine (v3 rules engine worktree), .venv, native/libtuppi.so.
set -eu
cd "$(dirname "$0")/.."
if command -v dnf >/dev/null; then
  sudo dnf install -y gcc make python3 python3-devel openblas-devel git
fi
git fetch origin engine/rules/project-target-v3-locked-bids
[ -d ../tuppi-engine ] || git worktree add ../tuppi-engine FETCH_HEAD
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q numpy pytest
# CUDA 12.6 wheels still carry Pascal (GTX 10xx, sm_61) kernels. If CUDA is not
# usable below, training falls back to the CPU (slower, same result).
.venv/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cu126 || .venv/bin/pip install -q torch
.venv/bin/pip install -q -e ../tuppi-engine
# Fedora keeps cblas.h under /usr/include/openblas.
CPATH=/usr/include/openblas${CPATH:+:$CPATH} sh native/build.sh --blas
PYTHONPATH=$PWD .venv/bin/python - <<'PY'
import torch
ok = torch.cuda.is_available()
if ok:
    try:
        (torch.ones(8, device="cuda") * 2).sum().item()
    except Exception as e:  # no kernels for this GPU
        ok = False; print("CUDA present but unusable:", e)
print("torch", torch.__version__, "cuda usable:", ok, torch.cuda.get_device_name(0) if ok else "")
PY
PYTHONPATH=$PWD .venv/bin/python -m pytest -q tests/test_history.py tests/test_belief_search.py
echo "setup ok"
