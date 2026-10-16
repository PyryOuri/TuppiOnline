#!/bin/bash
# PLAN.md steps 3-5 for the selected arm L0, sequential.
set -e
export TUPPI_AI_SERIAL=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
PY=/Users/pyryouri/.venvs/tuppi-v2/bin/python
$PY -B lite_eval.py --candidate L0 --opponent live128 --seed 'lite-screen-v1|L0' --first 512 --deals 512 --out results/strength/primary_L0_vs_live128_512_1023.json > results/strength/primary_L0.log 2>&1
echo primary done
$PY -B lite_eval.py --candidate L0 --opponent profile:partner_aware_lead_v3 --seed 'panel-p1b|heur' --first 0 --deals 2048 --out results/strength/guard_L0_vs_heur.json > results/strength/guard_L0.log 2>&1
echo guard done
$PY -B lite_eval.py --candidate L0 --opponent live1024 --seed 'lite-confirm-v1' --first 0 --deals 512 --out results/strength/confirm_L0_vs_live1024.json > results/strength/confirm_L0.log 2>&1
echo confirm done
