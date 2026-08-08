# Phase 5D-A handoff: what to run next, and in what order

Phase 5D-A execution is now complete for the required handoff: the migration baseline,
seat-balanced heterogeneous comparison, corrected convergence run, full decomposition run,
parallel-analysis implementation, and final regression suite have all been completed. This
document remains the runbook and provenance record for that work.

Results so far, and the reasoning that bounds them, are in
`docs/search/phase5d_a_results.md`. Hypotheses were pre-registered in
`docs/search/phase5d_a_hypotheses.md` and must not be edited in light of new numbers.

## Step 0: full suite — complete

The final post-implementation run was:

`1346 passed, 2 skipped` in 19:19. The two skips are existing feasibility/fully-determined
position conditions, not failures.

```bash
python -m pytest -q
```

## The one experiment that mattered most — complete

The seat-balanced heterogeneous comparison was run at `--workers 10`, with each seat
arrangement read separately. Both remained below parity: p_win 0.333 with 9 complete and 3
censored pairs in one arrangement, and p_win 0.375 with 12 complete and no censored pairs in
the other. This does not support partnership mismatch as the primary explanation and selects
Path D, subject to the recorded sample and censoring limits.

```bash
python -m tuppi_search.runner d-heterogeneous \
  --search uniform_feasible_pimc_small_v1 \
  --pairs 12 --safety-cap 96 --workers 8 \
  --output "$RUNS/hetero_full_pimc_12.json"
```

The corrected convergence run covered 112 positions, with adjacent agreement 0.839, 0.830,
0.839, and 0.875 from 2 to 32 worlds. The full decomposition run covered 768 positions.

## Remaining optional instruments

The requested completion set is done. These additional instruments remain explicitly unrun:

| Instrument | Status | Purpose |
| --- | --- | --- |
| Same-bank full-PIMC comparison | not run | Like-for-like comparator for play-only/show-only |
| Heterogeneous play-only comparison | not run | Test whether mismatch survives card-only search |
| Deal-level screens | not run | Cheap secondary confirmation |

They are useful follow-ups, but neither is required before the Path D closeout.

The original command forms are retained below for reproducibility:

```bash
export RUNS="$HOME/TuppiRuns/phase5d-a"   # never inside the repository or iCloud
source /path/to/venv/bin/activate

# 2. Completed: convergence on the corrected corpus.
python -m tuppi_search.runner converge --showing 64 --trick-play 96 --streams 96 \
  --showing-limit 48 --trick-play-limit 64 --budgets 2,4,8,16,32 \
  --output "$RUNS/convergence_v2.json"

# 3. Optional: full PIMC on the same bank as play-only and show-only.
python -m tuppi_search.runner d-compare --candidate uniform_feasible_pimc_small_v1 \
  --pairs 12 --safety-cap 96 --workers 8 --output "$RUNS/match_full_pimc_12.json"

# 4. Optional: heterogeneous play-only.
python -m tuppi_search.runner d-heterogeneous \
  --search uniform_feasible_pimc_play_only_v1 \
  --pairs 12 --safety-cap 96 --workers 8 \
  --output "$RUNS/hetero_play_only_12.json"

# 5. Completed: the corpus at the phase's original target.
python -m tuppi_search.runner decompose --showing 256 --trick-play 512 --streams 192 \
  --mismatch-positions 32 --output "$RUNS/decomposition_full.json"

# 6. Optional cheap screens.
python -m tuppi_search.runner d-screen --candidate uniform_feasible_pimc_play_only_v1 \
  --deals 64 --output "$RUNS/screen_play_only.json"
```

The compact report has now been regenerated from the permitted run directory, and the final
suite has been rerun. The assembler accepts `TUPPI_RUNS_DIR` so it can operate without reading
an unapproved home-directory path:

```bash
TUPPI_RUNS_DIR="$RUNS" python examples/search/assemble_phase5d_a_report.py
python -m pytest tests/search -q
```

The assembler picks up whichever artifacts exist and lists the rest under `not_run`, so
it is safe to run after each step.

## Operational lessons worth carrying over

These cost more time than the measurements did.

**Raise the per-leg cap once the machine is fast.** Phase 5D-A used a cap of 96 deals per leg
against Phase 5C's 704, because near-parity legs are long. It never bound - the longest leg was
71 deals - so 96 was adequate here, but a stronger candidate will hit it. Any cap change must
be recorded in `safety_cap_deviation` and its censoring rate reported, because censoring
removes the *closest* legs and is not missing-at-random.

**A comparison reports only on completed pairs, and a pair is two full legs.** The first
play-only attempt ran ten hours across six workers without emitting a line. Before starting a
long run, sanity-check the per-deal cost with a single instrumented leg - the probe used here
is about thirty lines and is described in the results document's cost section.

**Check that pool workers are actually working.** One heterogeneous run spent 100 minutes with
a single active worker while three sat idle at 0 % CPU; `d-compare` on the same machine held
five workers at 97 %. Dispatch is `chunksize=1`, so this is not a chunking bug and is worth
verifying empirically:

```bash
top -l 3 -s 30 -n 10 -stats pid,cpu,command | awk '/^PID/{s++} s==3'
```

**Near-parity candidates are the expensive ones.** `project_target_v1` resets the score to 0-0
whenever the down team wins a deal - about 9.8 resets per match here - so the closer a
candidate is to the reference, the longer its matches run. The weakest candidate is the
cheapest to evaluate, which is backwards from what a development loop wants. Budget for the
good candidates costing more.

## Invariants that must survive the move

- **Do not rewrite the Phase 5C negative result.** It is quoted, never recomputed;
  `tests/search/test_phase5d_architecture.py` pins `p_win = 0.15625` and 0/10/22.
- **Do not change `uniform_feasible_pimc_small_v1`'s identity.** The negative-baseline
  designation is metadata; the agent id, configuration id, and committed registry digest are
  asserted unchanged.
- **Do not add fields to `PimcConfiguration`.** Every Phase 5C content address would change.
  Phase 5D-A composes a separate `PhaseGatedConfiguration` for exactly this reason.
- **No recursive PIMC.** `tuppi_search.validation.recursive_search_problems` enforces it
  structurally: `rollout.py` and `exact_tail.py` may not construct a search agent.
- **Bulk output stays under `$HOME/TuppiRuns/`** - never in the repository, `~/Documents`, or
  iCloud. Only compact schemas, fixtures, summaries, and documentation belong in Git.
- **The promotion-sealed bank stays closed.** Every Phase 5D-A bank is a development bank and
  no result here is promotion evidence.
- **Read distinct-hand counts, not position counts,** as the effective sample size of any
  corpus analysis. That confusion produced the one defective result this phase had to retract.
