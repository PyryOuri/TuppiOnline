# Checked comparisons and frozen experiment queues

Prepared 2026-10-02 in `TuppiAI-prior`, branch
`research/policy-prior-infra-20261002`, following the policy-prior infrastructure
commit `319e121`. This is coding work under the user's CPU restriction.
No real queue was prepared or executed; model hashing, native builds, training
and game benchmarks remain deferred. The tools import only the standard
library until an explicitly executed job starts the existing evaluator.

## Compare completed results

```bash
cd /Users/pyryouri/Developer/TuppiAI-prior
python3 -m tuppi_ai.paired_results candidate.json reference.json --out comparison.json
```

The sign is **candidate minus reference**, each evaluated against the same
opponent. This is not a direct head-to-head comparison between the two
candidates. The analyser checks the ruleset, seed, starting-score design,
opponent and complete sample count. It pairs by explicit deal ID, so reordered
rows are supported. It rejects different sample sets, duplicate IDs,
misaligned value arrays, nonfinite values and invalid starting scores. No
prefix truncation or silent intersection is allowed.

New evaluator outputs (`tuppi.duplicate_eval.v2`) contain a `deal_records`
array with index, ID, score and raw mean equity change. The ID hashes the
actual shuffled hands, index, initial score and dealer. Policy code and the
eight rotations/team assignments are unchanged; worker scheduling can still
affect persistent controller state. Evaluation now
requires at least two base deals; the CLI also accepts `--equity-path`.

Strict comparison requires a frozen-input context on both files, normally
provided by the queue. It checks identical source/model/native/equity input
fingerprints and execution design, including workers. Standalone evaluator
outputs have deal IDs but cannot attest frozen inputs by themselves.

For historical outputs, explicit weaker analysis is available:

```bash
python3 -m tuppi_ai.paired_results old_candidate.json old_reference.json --allow-legacy
```

Legacy analysis still rejects known metadata mismatches and unequal lengths.
If IDs are absent, pairing relies on the old evaluator's ordered indices and
matching seed. The report labels this `legacy_metadata_only`; if only frozen
context is missing it labels `deal_ids_without_frozen_inputs`. Warnings are
part of the JSON, and opting in cannot upgrade missing provenance. Unknown
rulesets or missing required metadata are never guessed. The historical
`tools/cmp.sh` is unchanged; use this analyser instead of its array subtraction.

Reports include paired differences, their mean and a normal-approximation
95% interval over base deals. These intervals are unadjusted for parameter
tuning or multiple comparisons. Persistent controller state can create
dependence; the context records that design and a fixed seed does not prove
independent observations or deterministic runtime. Use fresh confirmation
seeds and the full searched bot/complete-match endpoints before claiming a
stronger player. Complete-match outputs are deliberately not accepted as
duplicate-deal equity arrays. An existing report is never overwritten.

## Preview and prepare a queue

The [example plan](../examples/policy_prior_queue.json) contains three W=128
development arms and three checked comparisons. W=128 is an inexpensive
first screen; the hard arm tests scoring equivalence there, not E7 allocation.
To test allocation later, create a separate plan at W=1024 with the common
`adb=128:adz=2.5:add=0.005` settings. The example's 32 samples are a smoke/development
size, not a power calculation or a confirmation budget.

Safe preview, with no model hashing, native import or workload launch:

```bash
python3 -m tuppi_ai.experiment_queue preview examples/policy_prior_queue.json
```

Use the project's existing Python interpreter when preparing/running real
jobs. If `python` is omitted from the plan, preparation freezes the absolute
path of the interpreter executing the tool; it must have the evaluator's
dependencies. The plan can instead supply an explicit absolute interpreter
path. Package versions and the interpreter binary are not frozen by this tool.

After runtime validation and once compute is available:

```bash
python3 -m tuppi_ai.experiment_queue prepare examples/policy_prior_queue.json runs/queues/prior_dev_20261002
python3 -m tuppi_ai.experiment_queue status runs/queues/prior_dev_20261002
python3 -m tuppi_ai.experiment_queue run runs/queues/prior_dev_20261002
```

`run` is a **dry run by default**. It reads the queue state without starting
jobs or creating attempt files. Preparation hashes model/equity inputs, AI
Python source, native C/header/build source and library, engine Python source
and rules JSON. It requires an existing isolated native library, so it cannot
silently trigger a build. It writes `frozen.json` and `state.json` in a fresh
directory inside this checkout's `runs/`. Each executed job verifies frozen
inputs and completed dependencies; newly added source files are also detected.

An explicit `best` alias is rejected: expand it into an explicit search spec
to freeze parameters and model paths. Search/greedy/conservative checkpoints
and `profile:`/`heur:` candidates are supported. Opponents are incumbent
profiles or explicit search specs. Candidate and opponent searchers must
agree on process-wide sampler/NOLO settings. Unknown fields, duplicate options,
cycles and incompatible comparison designs fail before work starts.

## Execute and resume later

Only once the current CPU restriction has ended and runtime checks passed:

```bash
python3 -m tuppi_ai.experiment_queue run runs/queues/prior_dev_20261002 --execute
python3 -m tuppi_ai.experiment_queue run runs/queues/prior_dev_20261002 --execute --retry-failed
```

Jobs run sequentially, with at most the declared worker count. The interpreter
receives the exact checkout and canonical engine on `PYTHONPATH`; commands
use argument arrays without shell interpolation. Output and logs stay in the
queue directory. This version supports duplicate-deal evaluations and their
paired analyses, not training or complete-match scheduling. Resume works at
**job boundaries**: completed results are skipped, while explicitly retried
failed evaluations start again. It is not VRPO optimizer/RNG checkpoint resume.

Each attempt has its own directory containing command, PID acknowledgement,
process log and raw worker output. Only a validated result is atomically
published as `result.json`; partial and failed attempts remain evidence and
are never reused. Published results carry queue/job/attempt identity. Missing
or altered completed results and changed frozen inputs stop the queue. To
change source, seed, models or budgets, prepare a new queue.

The queue has a total active-attempt **wall-time budget**, a per-job timeout
and a maximum process-worker count. It reserves the entire available timeout
before launch, then reconciles it to observed attempt time. Retries consume
the same total budget. If a runner vanishes, its full reservation stays
charged. Launch waits for the process ID to be saved before evaluation is
released; a live recorded process group blocks another runner. Normal timeout
or interruption terminates that attempt's process group and checks for
surviving descendants, including after a normal or failed parent exit.
Queue locks prevent concurrent runners on one queue.

These are not operating-system CPU quotas: native parallelism can use several
cores. Preparation/initial verification are outside the attempt budget;
startup, result validation and post-job verification are inside. Cleanup and
validation can take time beyond the child timeout and are recorded; no next
job starts once the remaining budget is exhausted. The queue does not wait
for the heuristic job to finish or automatically decide when compute is free.

## Validation and remaining gate

Standard-library tests cover strict and legacy pairing, inputs/configuration
changes, exclusive publication, dependency order, skip/retry semantics, budget
history and reservations, stale/live children and duplicate-run prevention.
Two tiny Python process smoke tests check the launch acknowledgement and
failure before release; a mocked process-group test checks descendant cleanup.
Queue tests use fixture files and fake evaluators, with disk-barrier calls
mocked to avoid unnecessary IO on the busy host. They do not prove native
game correctness, model forwards, MPS reproducibility or power-loss durability.

Before a real queue: build and validate only this worktree's native library,
run the deferred policy-prior/VRPO tests from
[POLICY_PRIOR_INFRASTRUCTURE.md](POLICY_PRIOR_INFRASTRUCTURE.md), and perform a
small real evaluator smoke check to verify deal-record and context publication.
Freeze the main engine only when its concurrent work is stable. No experiment
winner is selected automatically, and no live configuration is changed.
