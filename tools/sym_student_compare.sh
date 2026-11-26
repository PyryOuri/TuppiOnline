#!/bin/sh
# Compare the suit-symmetry student network (models/vrpo4sym_v1.pt, baked on Colab from
# sym24:vrpo4_final.pt; audit_deliverables/tuppi_sym_student_20261126) with the released bots.
# Every arm is the released bot with only its network swapped:
#
#   plain    the network alone, greedy (the lite bot without the safety net): student vs VRPO4
#   nelli    Nelli 1.1 = lite C1H on VRPO4  vs  the same lite C1H on the student
#   heidi    Heidi 1.2 = W1024 PIB8 search, VRPO4 anchor, VRPO3 likelihood, VRPO1 rollouts
#            vs  the same search with the student as anchor (anchor only, as Heidi 1.2 itself)
#
#   OUT=<dir> sh tools/sym_student_compare.sh <step|group> [...]
#   DRYRUN=1 OUT=<dir> sh tools/sym_student_compare.sh all
#
# Steps: plain0 plainu nelli_dup nelli_pairs heidi128 heidi1024 report
# Groups: plain (plain0 plainu), nelli (nelli_dup nelli_pairs), heidi (heidi128),
#         confirm (heidi1024), cheap (plain nelli), all (cheap heidi; NOT confirm).
# A step whose result JSON exists is skipped (resume = run the same command again). A failed
# step is appended to OUT/failures.jsonl and the driver continues.
#
# Instrument: tools/stage3_eval.py (Stage 3 of the base-network task, copied unchanged from
# research/base-network-20261022 a9efdab): tuppi_ai.evaluate's duplicate deals (4 rotations x
# 2 team assignments per base deal, dealer 0, incumbent equity table), searches reseeded from
# the information state (rs=1) so both arms meet the same opponent searches, and complete
# matches from 0-0 for `pairs`. On this tree it reproduces Stage 3's stored Nelli and Heidi
# games exactly (checks/replay_*.json in the audit directory).
#
# Environment: OUT (required); DRYRUN=1 (tiny sizes); WORKERS (12; W1024 uses
# WORKERS_1024, default 10); NICE_LEVEL (10); ENGINE_SRC (release engine source);
# sizes N_PLAIN (4096), N_NELLI (8192), NELLI_PAIRS (3500), N_H128 (1024), N_H1024 (256).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$HOME/.venvs/tuppi-ai/bin/python}"
: "${OUT:?set OUT to the output directory}"
ENGINE_SRC="${ENGINE_SRC:-/Users/pyryouri/Developer/TuppiProject-dan11-20261026/src}"
export PYTHONPATH="$ROOT:$ENGINE_SRC"
export TUPPI_NATIVE_LIBRARY="$ROOT/native/libtuppi.dylib"
export TUPPI_AI_PLAY_INFERENCE=0          # play inference only where a spec asks (pib=)
export TUPPI_AI_PLAY_INFERENCE_HUMANS=0   # no people at these tables
case "$OUT" in /*) ;; *) OUT="$(pwd)/$OUT" ;; esac
mkdir -p "$OUT/logs"
NICE="nice -n ${NICE_LEVEL:-10}"

M="$ROOT/models"
VRPO4="$M/vrpo4_final.pt";      VRPO4_LITE="$M/vrpo4_final.lite.npz"
STUDENT="$M/vrpo4sym_v1.pt";    STUDENT_LITE="$M/vrpo4sym_v1.lite.npz"
VRPO3="$M/vrpo3_final.pt"

NELLI11="lite:$VRPO4_LITE:c1h"
NELLI_S="lite:$STUDENT_LITE:c1h"
heidi() {  # worlds anchor
  echo "best:w=$1:pib=8:rs=1:bp=$2:pibp=$VRPO3"
}

if [ "${DRYRUN:-0}" = "1" ]; then
  WORKERS="${WORKERS:-2}"; WORKERS_1024="${WORKERS_1024:-2}"
  N_PLAIN=16; N_NELLI=16; NELLI_PAIRS=2; N_H128=2; N_H1024=2; SUFFIX="-dryrun"
else
  WORKERS="${WORKERS:-12}"; WORKERS_1024="${WORKERS_1024:-10}"
  N_PLAIN="${N_PLAIN:-4096}"; N_NELLI="${N_NELLI:-8192}"; NELLI_PAIRS="${NELLI_PAIRS:-3500}"
  N_H128="${N_H128:-1024}"; N_H1024="${N_H1024:-256}"; SUFFIX=""
fi

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

fail() {
  log "FAILED $1 (exit $2)"
  printf '{"step": "%s", "exit": %s, "time": "%s"}\n' "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT/failures.jsonl"
}

# run <label> <result.json> <command...>: the command writes <result.json>.tmp
run() {
  _label=$1; _result=$2; shift 2
  if [ -s "$_result" ]; then log "skip $_label (result exists)"; return 0; fi
  rm -f "$_result.tmp"
  log "start $_label"
  $PY "$ROOT/tools/ledger.py" --ledger "$OUT" --label "sym-$_label$SUFFIX" -- "$@" > "$OUT/logs/$_label.log" 2>&1
  _rc=$?
  if [ $_rc -eq 0 ] && $PY -c "import json,sys; json.load(open(sys.argv[1]))" "$_result.tmp" 2>/dev/null; then
    mv "$_result.tmp" "$_result"; log "done $_label"
  else
    fail "$_label" "$_rc"; return 1
  fi
}

dup() {  # label result candidate opponent deals scores seed workers
  run "$1" "$2" caffeinate -i env VECLIB_MAXIMUM_THREADS=1 $NICE $PY "$ROOT/tools/stage3_eval.py" \
    --checkpoint "$3" --opponent "$4" --ruleset v3 --deals "$5" --workers "$8" --scores "$6" --seed "$7" --out "$2.tmp"
}

verify_models() {  # the four networks must be the ones this comparison is about
  $PY - "$M" <<'EOF' || { fail verify-models 2; exit 2; }
import hashlib, sys
from pathlib import Path
m = Path(sys.argv[1])
want = {"vrpo4_final.pt": "0e980b4f3344c511cd7faf6e7258433a088be26431000e83cfb21c36c51d0deb",
        "vrpo4_final.lite.npz": "8ae2dd681938fee0aa1d5f71ca71d304c028d98f56df036798c0a63192839e88",
        "vrpo3_final.pt": "3f14de574e324ac2a2263e1c77626684a8031b4837d444967549be426e810590",
        "vrpo4sym_v1.pt": "5322bd22ed20db70aeb7d15f0d590fb6226922034a9b4630ec6fe44b858169a4",
        "vrpo4sym_v1.lite.npz": "88c2ea62a28ec94822e533d20ba751393813786f0e6eb3d674aba46cb737d13b"}
bad = [f for f, h in want.items() if hashlib.sha256((m / f).read_bytes()).hexdigest() != h]
if bad:
    sys.exit(f"model files differ from the registered ones: {bad}")
EOF
}

step_plain0() { dup plain0 "$OUT/plain_zero.json" "$STUDENT" "$VRPO4" "$N_PLAIN" zero sym-plain-zero-v1 "$WORKERS"; }
step_plainu() { dup plainu "$OUT/plain_uniform.json" "$STUDENT" "$VRPO4" "$N_PLAIN" uniform sym-plain-uniform-v1 "$WORKERS"; }
step_nelli_dup() { dup nelli_dup "$OUT/nelli_dup.json" "$NELLI_S" "$NELLI11" "$N_NELLI" uniform sym-nelli-dup-v1 "$WORKERS"; }
step_nelli_pairs() {
  run nelli_pairs "$OUT/nelli_pairs.json" caffeinate -i env VECLIB_MAXIMUM_THREADS=1 $NICE $PY "$ROOT/tools/stage3_eval.py" pairs \
    --checkpoint "$NELLI_S" --opponent "$NELLI11" --pairs "$NELLI_PAIRS" --seed sym-nelli-pairs-v1 --workers "$WORKERS" \
    --out "$OUT/nelli_pairs.json.tmp"
}
step_heidi128() {
  dup heidi128 "$OUT/heidi_w128.json" "$(heidi 128 "$STUDENT")" "$(heidi 128 "$VRPO4")" "$N_H128" uniform sym-heidi-w128-v1 "$WORKERS"
}
step_heidi1024() {
  dup heidi1024 "$OUT/heidi_w1024.json" "$(heidi 1024 "$STUDENT")" "$(heidi 1024 "$VRPO4")" "$N_H1024" uniform \
    sym-heidi-w1024-v1 "$WORKERS_1024"
}
step_report() { $PY "$ROOT/tools/sym_student_report.py" --dir "$OUT" || fail report $?; }

step() {
  case "$1" in
    plain0|plainu|nelli_dup|nelli_pairs|heidi128|heidi1024|report) "step_$1" ;;
    plain) step plain0; step plainu ;;
    nelli) step nelli_dup; step nelli_pairs ;;
    heidi) step heidi128 ;;
    confirm) step heidi1024 ;;
    cheap) step plain; step nelli ;;
    all) step cheap; step heidi ;;
    *) echo "unknown step $1" >&2; return 2 ;;
  esac
}

[ $# -eq 0 ] && { echo "name the steps or groups to run (see the header)" >&2; exit 2; }
verify_models
log "sym-student comparison: OUT=$OUT DRYRUN=${DRYRUN:-0} WORKERS=$WORKERS steps: $*"
for s in "$@"; do step "$s"; done
step_report
log "done: $*"
