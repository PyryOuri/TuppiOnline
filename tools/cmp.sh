#!/bin/sh
# Paired comparison on the seed-v3 128 deals against a reference result file.
#   tools/cmp.sh <name> <spec> [reference=runs/cmp_w64.json] [deals=128] [seed=tuppi-ai-eval-v3]
NAME=$1; SPEC=$2; REF=${3:-runs/cmp_w64.json}; DEALS=${4:-128}; SEED=${5:-tuppi-ai-eval-v3}
PY=~/.venvs/tuppi-ai/bin/python
$PY -m tuppi_ai.evaluate --checkpoint "$SPEC" --deals $DEALS --seed $SEED --workers 13 ${OPP:+--opponent $OPP} --out runs/cmp_$NAME.json > /dev/null 2>&1
$PY - "$NAME" "$REF" <<'PYEOF'
import json, sys, numpy as np
name, ref = sys.argv[1], sys.argv[2]
old = np.array(json.load(open(ref))["values"]); r = json.load(open(f"runs/cmp_{name}.json")); v = np.array(r["values"])
d = v - old[:len(v)]
print(f"{name}: {v.mean():+.5f} paired vs {ref.split('/')[-1]} {d.mean():+.5f} +- {1.96*d.std(ddof=1)/np.sqrt(len(d)):.5f}  won {r['won']:.3f} rami {r['rami']:.3f} cand_decl {r['cand_declared']:.3f} ({r['seconds']}s)")
PYEOF
