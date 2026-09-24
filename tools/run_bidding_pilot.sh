#!/bin/bash
# Bidding-explanation pilot (docs/BIDDING_EXPLANATION_PLAN.md). PARKED: run it
# when decided, on mains power; it keeps the Mac awake and resumes if stopped.
#
#   bash tools/run_bidding_pilot.sh            # 5,000 deals, 256-deal play tests
#   DEALS=2000 EVAL_DEALS=128 bash tools/run_bidding_pilot.sh
#
# About 3 hours of machine time at the defaults: the game database ~1.5 h,
# fitting ~1 min, three play tests ~30-40 min each.
set -eo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-$HOME/.venvs/tuppi-v2/bin/python}"
DEALS="${DEALS:-5000}"
EVAL_DEALS="${EVAL_DEALS:-256}"
DB="${DB:-runs/games/v3_bidding_pilot}"
OUT="${OUT:-runs/bidding/pilot}"
mkdir -p "$OUT"

echo "== 1/4 game database: $DEALS deals -> $DB"
caffeinate -i "$PY" tools/gen_game_db.py --deals "$DEALS" --out "$DB" 2>&1 | tee -a "$OUT/gen.log"

echo "== 2/4 bid decisions"
"$PY" tools/bid_dataset.py --db "$DB" --out "$OUT/bids.jsonl.gz" | tee "$OUT/dataset.log"

echo "== 3/4 readable models (held-out numbers in $OUT/report.md)"
"$PY" tools/bid_explain.py --data "$OUT/bids.jsonl.gz" --out "$OUT" | tee "$OUT/explain.log"

# The point count to play: the best held-out agreement with at most five features.
BEST=$("$PY" - "$OUT/report.json" <<'PYEOF'
import json, sys
models = json.load(open(sys.argv[1]))["models"]
pcs = {k: v for k, v in models.items() if k.startswith("point_count_") and int(k.rsplit("_", 1)[1]) <= 5}
print(max(pcs, key=lambda k: pcs[k]["test"]["agreement"]))
PYEOF
)
echo "== 4/4 play tests against the bot: $BEST, tree_3, old_rule ($EVAL_DEALS base deals each)"
for M in "$BEST" tree_3 old_rule; do
  if [ -f "$OUT/play_$M.json" ]; then echo "   $M: done already"; continue; fi
  SRC="$OUT/model_$M.json"; [ "$M" = old_rule ] && SRC=old_rule
  caffeinate -i "$PY" tools/bid_rule_eval.py --model "$SRC" --deals "$EVAL_DEALS" --out "$OUT/play_$M.json" \
    | tee "$OUT/play_$M.log"
done
echo "done: read $OUT/report.md and $OUT/play_*.json against the plan's pass criteria"
