#!/bin/sh
# XI-PIB: distil the search with play inference into the lite bot's network,
# then test the result without search against the lite bot (VRPO3).
# Resumable: rerun after any interruption; finished stages are skipped.
#   HOURS=20 WORKERS=7 sh tools/xi_pib_job.sh
# Task and analysis: docs/XI_PIB_TASK.md.
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH=$PWD TUPPI_AI_SERIAL=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
PY=${PY:-.venv/bin/python}
OUT=runs/xi_pib
HOURS=${HOURS:-20}
WORKERS=${WORKERS:-7}
mkdir -p $OUT
if [ ! -f $OUT/gen.done ]; then
  $PY -B tools/gen_xi_pib.py --out $OUT/data --hours "$HOURS" --workers "$WORKERS" >> $OUT/gen.log 2>&1
  touch $OUT/gen.done
fi
if [ ! -f $OUT/xi_pib.pt ]; then
  $PY -B -m tuppi_ai.distill --data $OUT/data --init models/vrpo3_final.pt --out $OUT/xi_pib.pt \
    --epochs 3 --lr 1e-4 > $OUT/distill.log 2>&1
fi
for scores in zero uniform; do
  [ -f $OUT/eval_$scores.json ] && continue
  $PY -B -m tuppi_ai.evaluate --checkpoint $OUT/xi_pib.pt --opponent models/vrpo3_final.pt --ruleset v3 \
    --deals 4096 --scores $scores --seed xi-pib-eval-v1 --workers "$WORKERS" --out $OUT/eval_$scores.json \
    > $OUT/eval_$scores.log 2>&1
done
$PY -B - <<'PY'
import json, glob, numpy as np
out = "runs/xi_pib"
rows = [json.loads(l) for l in open(f"{out}/data/progress.jsonl") if '"rows"' in l]
summary = {"shards": len(rows), "rows": sum(r["rows"] for r in rows),
           "teacher_differs_from_lite": float(np.average([r["differs"] for r in rows], weights=[r["rows"] for r in rows])),
           "distill": [l.strip() for l in open(f"{out}/distill.log") if "agreement" in l][-1]}
for s in ("zero", "uniform"):
    r = json.load(open(f"{out}/eval_{s}.json"))
    summary[f"eval_{s}"] = {k: r[k] for k in ("equity_per_deal", "ci95", "base_deals", "won", "rami", "seconds")}
json.dump(summary, open(f"{out}/SUMMARY.json", "w"), indent=1)
print(json.dumps(summary, indent=1))
PY
