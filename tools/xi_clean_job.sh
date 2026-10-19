#!/bin/sh
# XI-CLEAN: distil the W=1024 search with play inference into the lite bot,
# with statistically filtered labels. Stages run in order; each later stage
# starts only when the previous gate passes. A failed gate ends the job with a
# summary; that is a valid result.
#   A consistency -> gate A -> B labels -> C fit -> gate C_d -> D evaluation
#   -> gate D -> E more labels, refit, fresh evaluation -> gate E -> stop.
# Resumable: rerun the same command after any interruption; finished stages
# are skipped. Task and analysis: docs/XI_CLEAN_TASK.md.
#   WORKERS=7 HOURS_B=24 HOURS_E=24 nohup sh tools/xi_clean_job.sh > runs/xi_clean.out 2>&1 &
#   SMOKE=1 WORKERS=2 sh tools/xi_clean_job.sh    # pipeline check, minutes, no strength meaning
set -eu
cd "$(dirname "$0")/.."
export PYTHONPATH=$PWD TUPPI_AI_SERIAL=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
PY=${PY:-.venv/bin/python}
WORKERS=${WORKERS:-7}
HOURS_B=${HOURS_B:-24}
HOURS_E=${HOURS_E:-24}
SMOKE=${SMOKE:-0}
if [ "$SMOKE" = 1 ]; then
  OUT=runs/xi_clean_smoke; FLAG=--smoke; DEALS=8
else
  OUT=runs/xi_clean; FLAG=; DEALS=4096
fi
mkdir -p $OUT
X="$PY -B tools/xi_clean.py --out $OUT $FLAG"

say() { echo "$(date '+%F %T') $*" | tee -a $OUT/job.log; }
finish() { $X summary > /dev/null; say "finished; see $OUT/SUMMARY.json"; exit 0; }
gate() {
  if $X gate "$1" >> $OUT/job.log 2>&1; then
    say "gate $1: pass"
  elif [ "$SMOKE" = 1 ]; then
    say "gate $1: fail (smoke run: continuing to exercise the pipeline)"
  else
    say "gate $1: fail; stopping here"
    finish
  fi
}
evaluate() {  # $1 = stage (d/e), $2 = seed
  for scores in zero uniform; do
    [ -f $OUT/eval_$1_$scores.json ] && continue
    say "evaluate $1 $scores"
    $PY -B -m tuppi_ai.evaluate --checkpoint $OUT/student_$1.pt --opponent models/vrpo3_final.pt --ruleset v3 \
      --deals $DEALS --scores $scores --seed "$2" --workers "$WORKERS" --out $OUT/eval_$1_$scores.json \
      > $OUT/eval_$1_$scores.log 2>&1
  done
}

if [ ! -f $OUT/A.json ]; then
  say "A: teacher consistency"
  $X consistency --workers "$WORKERS" >> $OUT/A.log 2>&1
fi
gate A

if [ ! -f $OUT/B.done ]; then
  say "B: label bank ($HOURS_B h)"
  $X labels --stage B --hours "$HOURS_B" --workers "$WORKERS" >> $OUT/B.log 2>&1
  touch $OUT/B.done
fi
if [ ! -f $OUT/fit_d.json ]; then
  say "C: fit"
  $X fit --stage d > $OUT/fit_d.log 2>&1
fi
gate C_d
if [ -f $OUT/student_d.pt ]; then evaluate d xi-clean-eval-v1; fi
[ -f $OUT/eval_d_uniform.json ] || { say "no student to evaluate"; finish; }
gate D

if [ ! -f $OUT/E.done ]; then
  say "E: more labels ($HOURS_E h)"
  $X labels --stage E --hours "$HOURS_E" --workers "$WORKERS" >> $OUT/E.log 2>&1
  touch $OUT/E.done
fi
if [ ! -f $OUT/fit_e.json ]; then
  say "E: refit on all labels"
  $X fit --stage e > $OUT/fit_e.log 2>&1
fi
gate C_e
if [ -f $OUT/student_e.pt ]; then evaluate e xi-clean-eval-v2; fi
[ -f $OUT/eval_e_uniform.json ] && gate E
finish
