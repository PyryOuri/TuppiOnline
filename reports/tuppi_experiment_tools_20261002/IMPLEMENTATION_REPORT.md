# Checked comparisons and resumable evaluation queues

Prepared 2026-10-02 under the user's instruction to work independently for up
to two hours, continuing the two selected infrastructure tasks while heuristic
research occupies the CPU. Both coding tasks are implemented. Runtime
validation and experiments remain deferred; no stronger-bot result is claimed.

## Exact source and scope

- Checkout: `/Users/pyryouri/Developer/TuppiAI-prior`.
- Branch: `research/policy-prior-infra-20261002`.
- Implementation: `aab6511f3ac47497fd1838c8c41aff1348b9b3bf`.
- Final provenance fix: **`0799508ad5a48a5db9eca99693534f998f0ebcf2`**.
- Previous infrastructure snapshot: `319e12134ef10945d842f8306b811061128d9ad7`.
- Canonical engine for eventual execution: `/Users/pyryouri/Developer/TuppiProject-current/src`.
- Usage and limits: [EXPERIMENT_TOOLS.md](../../TuppiAI-prior/docs/EXPERIMENT_TOOLS.md).
- Frozen file inventory: [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json).

This follows the [policy-prior/VRPO infrastructure report](../tuppi_policy_prior_infrastructure_20261002/IMPLEMENTATION_REPORT.md).
That report and its manifest still attest their original `319e121` snapshot.
The returned C0–C5 and self-play planning packages remain preserved and were
not activated by this work. The main AI checkout, engine source, training,
live search settings and model files were not edited.

## Task 1: checked paired-results analyser

`python3 -m tuppi_ai.paired_results candidate.json reference.json` compares
completed duplicate-deal evaluations against the same opponent. It reports
candidate-minus-reference equity differences and a normal-approximation
95% interval over base deals. It does not compare those candidates directly
against one another or select a winner automatically.

The analyser requires the same ruleset, seed, initial-score design, opponent,
sample count and complete deal set. It rejects truncation/intersection,
duplicate identities, inconsistent values, invalid scores and nonfinite
numbers. Reordered rows are paired by explicit deal identity. New evaluator
output records the actual shuffled cards, score, dealer and index in a hashed
deal ID; the eight rotations/team assignments are unchanged.

Strict comparison also requires a queue-provided frozen context. Shared
source, engine, native library, equity, opponent assets and declared extra
inputs must match, as must worker and execution settings. Candidate assets
and the full queue inventory have separate fingerprints recorded in the
report. This permits manual reuse of compatible baselines from separate
queues when only candidate assets or unrelated jobs change. Absolute input
paths are part of these fingerprints, so moving a checkout can invalidate
compatibility even when its bytes match.

Historical results require explicit `--allow-legacy`; the report retains
weaker-provenance warnings. Missing rulesets are never inferred from a seed.
Standalone new evaluator outputs have deal IDs but still need this opt-in
if no frozen context was supplied. Existing reports are never overwritten.
The old `tools/cmp.sh` is unchanged; use the checked analyser for new decisions.

## Task 2: frozen, resumable experiment queue

`python3 -m tuppi_ai.experiment_queue` provides `preview`, `prepare`, `status`
and `run`. Preview validates configuration and input paths without model
hashing, loading or workload launch. Preparation requires an existing native
library, freezes input hashes and creates a fresh queue directory under this
checkout's `runs/`. It never silently builds that library.

`run` is a dry run unless `--execute` is explicitly supplied. Supported jobs
are duplicate-deal evaluations and their paired analyses. Jobs execute
sequentially with dependencies, individual timeouts, a shared wall-time
budget and a process-worker limit. Resume skips checked completed jobs;
failed attempts require `--retry-failed` and retain separate logs/output.
Resume is at job boundaries, not at an optimizer checkpoint. Training and
complete-match scheduling are outside this implementation.

Each attempt reserves its full timeout before launch. The worker waits for
its PID to be durably recorded before evaluation is released. A vanished
runner retains the full reservation; a live recorded process group blocks
overlapping recovery. Timeout, interruption and surviving descendants after
parent exit trigger cleanup of that attempt's process group. Results are
published only after metadata, frozen-input and dependency checks. Changed
inputs, added source files or altered completed results prevent reuse.

The budget measures active-attempt wall time, not operating-system CPU
quotas. Native parallelism can still occupy multiple cores. Initial input
verification/preparation are outside that budget; startup, output validation,
post-job checks and cleanup are included. Cleanup can exceed the child
timeout. Python path is frozen, but interpreter bytes, package versions,
hardware and the full inherited environment are not. The queue does not
detect when heuristic research has ended or decide when compute is available.

## Validation and evidence

**63 standard-library tests are covered by passing checks**, comprising the
24 retained infrastructure tests and 39 analyser/queue/process tests. A
56-test full-suite run passed earlier in this work; final targeted reruns
cover the changed modules. This is not a claim that one final 63-test suite
was run. Details are recorded in [TEST_REPORT.json](TEST_REPORT.json).

| Final relevant check | Tests | Observed wall time | Result |
| --- | ---: | ---: | --- |
| Paired-results module | 14 | 3.089 s | passed |
| Queue module | 21 | 226.893 s | passed |
| Process module, unchanged by final provenance fix | 4 | 4.137 s | passed |

The host was busy; these timings are test observations, not throughput
measurements. Queue tests use tiny fixture files and fake evaluators, with
disk barriers mocked. Two actual tiny Python processes verify release after
PID acknowledgement and suppression after acknowledgement failure. Process
cleanup is checked with mocks. No test imports Torch/NumPy/native code or
plays a real game. These checks do not prove power-loss durability or native
controller correctness.

Additional checks:

- AST parsing passed for eight changed/new Python files. Fresh imports of
  the queue, analyser and evaluator left Torch, NumPy and the native bridge
  unloaded: [STATIC_CHECK.json](STATIC_CHECK.json).
- The supplied six-job example preview passed using current model paths,
  without reading model contents: [EXAMPLE_PREVIEW.json](EXAMPLE_PREVIEW.json).
- Read-only analysis of stored `cmp_keep05.json` and `cmp_keep0.json` correctly
  rejected their absent ruleset even with legacy opt-in. Their hashes were
  unchanged after inspection: [LEGACY_RESULT_CHECK.json](LEGACY_RESULT_CHECK.json).
- Whitespace checks passed for the committed change range; the isolated
  source checkout was clean after both commits.

No actual queue was prepared or executed. No real models were hashed or
loaded, no native build or game evaluation ran, and no training, deployment,
measured compute saving or measured strength improvement occurred. The
isolated native library is currently absent, deliberately keeping real
preparation behind the runtime gate.

## Continuation when runtime work is assigned

1. Preserve this snapshot and confirm compute is available. Stabilise and
   freeze the canonical engine; the changing main checkout is not a valid
   frozen comparison arm.
2. Build this worktree's native library and run the deferred checks in
   [POLICY_PRIOR_INFRASTRUCTURE.md](../../TuppiAI-prior/docs/POLICY_PRIOR_INFRASTRUCTURE.md).
   Validate disabled-prior behavior against its separately frozen parent.
3. Use a project Python interpreter with the required dependencies. Run a
   small real evaluator/queue smoke check for identities, publication,
   timeout/cleanup and resume before a research-sized queue.
4. Review the [example plan](../../TuppiAI-prior/examples/policy_prior_queue.json).
   Its 32 base deals and W=128 are development settings, not confirmation
   evidence. Use separate plans and fresh confirmation seeds for larger
   search budgets and complete-match strength endpoints.

Safe inspection now:

```bash
cd /Users/pyryouri/Developer/TuppiAI-prior
python3 -m tuppi_ai.experiment_queue preview examples/policy_prior_queue.json
```

The expected benefit is avoiding repeated completed work and invalid
comparisons. Its size has not yet been measured. Runtime results should be
recorded separately rather than replacing this implementation evidence.
