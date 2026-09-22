#!/bin/sh
# One expert-iteration round after data generation.
#   tools/xi_round.sh <round> <init_big> <init_small> <data dirs...>
set -e
R=$1; BIG=$2; SMALL=$3; shift 3
PY=~/.venvs/tuppi-ai/bin/python
$PY -m tuppi_ai.distill --data "$@" --init $BIG --out runs/xi$R.pt --bc-data runs/bc/v1 --bc-share 0.2 --epochs 3 2>&1 | grep -E "rows|final|saved"
$PY -m tuppi_ai.distill --data "$@" --init $SMALL --out runs/xi${R}_small.pt --bc-data runs/bc/v1 --bc-share 0.2 --epochs 3 --lr 1e-3 2>&1 | grep -E "final|saved"
for c in runs/xi$R.pt runs/xi${R}_small.pt; do
  $PY -m tuppi_ai.evaluate --checkpoint $c --deals 1024 --workers 13 --out runs/eval_$(basename $c .pt)_v1.json > /dev/null 2>&1
done
$PY -m tuppi_ai.evaluate --checkpoint "search:runs/xi${R}_small.pt:w=64:dd=6:show=1" --deals 128 --seed tuppi-ai-eval-v3 --workers 13 --out runs/cmp_xi${R}_w64.json > /dev/null 2>&1
$PY - <<PYEOF
import json, numpy as np
for c in ("xi$R", "xi${R}_small"):
    r = json.load(open(f"runs/eval_{c}_v1.json")); print(f"{c} (no search): {r['equity_per_deal']:+.5f} [{r['ci95'][0]:+.5f}, {r['ci95'][1]:+.5f}] won {r['won']:.3f}")
old = np.array(json.load(open("runs/cmp_w64.json"))["values"])
r = json.load(open("runs/cmp_xi${R}_w64.json")); v = np.array(r["values"]); d = v - old
print(f"search(xi${R}_small, W=64): {v.mean():+.5f} vs search(bc_small, W=64) paired {d.mean():+.5f} +- {1.96*d.std(ddof=1)/np.sqrt(len(d)):.5f}")
PYEOF
