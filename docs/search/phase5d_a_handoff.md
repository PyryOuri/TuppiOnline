# Phase 5D-A handoff: what to run next, and in what order

Phase 5D-A was wrapped up before four planned measurements completed, to move the remaining
compute to a faster machine. This document is the runbook for finishing it. Nothing here
requires new code: every command below exists and is exercised by the test suite.

Results so far, and the reasoning that bounds them, are in
`docs/search/phase5d_a_results.md`. Hypotheses were pre-registered in
`docs/search/phase5d_a_hypotheses.md` and must not be edited in light of new numbers.

## Step 0: run the full suite

**The Phase 5D-A commit was made without a full-suite run.** On the laptop it projected 45-75
minutes - the Phase 5D-A corpus tests alone take about 17 of those - and the remaining compute
was being moved rather than spent. What *was* run green before committing:

| Test file | Result |
| --- | --- |
| `tests/search/test_phase5d_diagnostics.py` | 28 passed |
| `tests/search/test_phase5d_documentation.py` + `test_phase5d_architecture.py` | 28 passed |
| `tests/search/test_phase5d_hybrid.py` | 26 passed |

That covers the change surface: `corpus.py` was the only module edited, and its only consumers
are `runner.py`, `convergence.py`, and `decomposition.py`, all exercised by those files. No test
outside `tests/search/` references `tuppi_search` at all. Still, confirm it:

```bash
python -m pytest -q
```

## The one experiment that matters most

The phase ends with **Path A eliminated** and **Path B versus Path D open**. The seat-balanced
heterogeneous comparison is the only instrument that tests partnership mismatch behaviourally,
and it decides between them:

```bash
python -m tuppi_search.runner d-heterogeneous \
  --search uniform_feasible_pimc_small_v1 \
  --pairs 12 --safety-cap 96 --workers 8 \
  --output "$RUNS/hetero_full_pimc_12.json"
```

Read `arrangements[*].primary_match_inference` for each seat arrangement **separately** - they
share streams and pooling them would understate the dependence.

- If one PIMC seat with a reference partner is competitive while the homogeneous team is
  strongly negative, that is **Path B**: the defect is partner modelling. The next step is an
  explicit partner-action model or multi-observer search, not a deeper tree over the same wrong
  continuation assumption. Recursive PIMC remains forbidden - see the hypotheses document for
  why the regress does not terminate.
- If it still loses, that is **Path D**: freeze PIMC as a negative baseline and proceed to
  observation-safe information-set search.

## The rest, in priority order

```bash
export RUNS="$HOME/TuppiRuns/phase5d-a"   # never inside the repository or iCloud
source /path/to/venv/bin/activate

# 2. Convergence on the corrected corpus. The committed convergence numbers came from the
#    defective corpus and must be replaced. Cheapest outstanding item.
python -m tuppi_search.runner converge --showing 64 --trick-play 96 --streams 96 \
  --showing-limit 48 --trick-play-limit 64 --budgets 2,4,8,16,32 \
  --output "$RUNS/convergence_v2.json"

# 3. Full PIMC on the same bank as play-only and show-only. Without it those two numbers
#    have no like-for-like comparator.
python -m tuppi_search.runner d-compare --candidate uniform_feasible_pimc_small_v1 \
  --pairs 12 --safety-cap 96 --workers 8 --output "$RUNS/match_full_pimc_12.json"

# 4. Heterogeneous play-only: does the mismatch effect survive when only cards are searched?
python -m tuppi_search.runner d-heterogeneous \
  --search uniform_feasible_pimc_play_only_v1 \
  --pairs 12 --safety-cap 96 --workers 8 \
  --output "$RUNS/hetero_play_only_12.json"

# 5. The corpus at the phase's original target, now affordable. 31 h projected on a laptop.
python -m tuppi_search.runner decompose --showing 256 --trick-play 512 --streams 192 \
  --mismatch-positions 32 --output "$RUNS/decomposition_full.json"

# 6. Optional cheap screens.
python -m tuppi_search.runner d-screen --candidate uniform_feasible_pimc_play_only_v1 \
  --deals 64 --output "$RUNS/screen_play_only.json"
```

Then regenerate the committed reports and re-run the suite:

```bash
python "$RUNS/assemble_report.py"     # writes reports/phase5d_a/
python -m pytest tests/search -q
```

`assemble_report.py` picks up whichever artifacts exist and lists the rest under `not_run`, so
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
