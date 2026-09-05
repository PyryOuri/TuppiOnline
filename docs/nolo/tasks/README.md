# NOLO follow-up task queue

Prepared 2026-09-05 from [framing 1](../framings/1.md). This packet creates work;
it does not report that the proposed implementation or strength evaluation has
been completed. Existing source files, the charter, and the framing are unchanged.

Start with **N01**, then follow the dependency column. Give an executor one task
at a time, together with [BACKGROUND.md](BACKGROUND.md). The packet fixes the
initial scope and technical choices so the executor need not choose a new theory.
The programme-wide framing gate is still open; only one framing currently exists.

| ID | Task | Dependencies | Initial status | Main endpoint |
| --- | --- | --- | --- | --- |
| [G1](G1-independent-comparison.md) | Finish the independent-framing gate | Two fresh independent contexts | WAITING_INPUTS | Three independent reports and a ranked comparison, or an explicit recorded waiver |
| [N01](N01-evidence.md) | Turn the three witnesses into reproducible fixtures | Supplied task data | READY | A/B/C replay correctly; exact counts and negative controls agree |
| [N02](N02-support.md) | Build an observation-only feasible-hand interface | N01 | WAITING_DEPENDENCY | Complete supports of 20/2/24; zero illegal or missing assignments |
| [N03](N03-verifier.md) | Verify contingent-line certificates | N02 | WAITING_DEPENDENCY | A is universal; B's correct line is safe; its wrong line fails |
| [N04](N04-security-search.md) | Find a safe line without seeing the layout | N03 | WAITING_DEPENDENCY | Finds A's `8S` and B's `9C → 3C`; preserves information sets |
| [N05](N05-score-and-ambiguity.md) | Price the score state and label uncertainty | N04 | WAITING_DEPENDENCY | Correct reset/52-point ties; no posterior or dominance overclaim |
| [N06](N06-compression.md) | Test one exact speed improvement | N04 | WAITING_DEPENDENCY; optional | Zero value/plan discrepancies and at least 20% fewer engine transitions |
| [N07](N07-coverage.md) | Measure usefulness on new reference positions | N05; N06 if successful | WAITING_DEPENDENCY | Sound decisions on new deals, with all unresolved cases in the denominator |
| [N08](N08-research-adapter.md) | Build a research-only executable agent | G1 adoption/waiver, N07 GO | WAITING_GATE | Rankings, actual actions, and promised continuations agree |
| [N09](N09-paired-validation.md) | Run one frozen paired strength check | N08, G1 adoption/waiver | WAITING_GATE | Predeclared paired trick improvement against two opposition settings |

N01–N07 are bounded follow-up research on this branch. They do not turn framing
1 into the programme's agreed recommendation. N08–N09 await the comparison's
adoption of this direction, or a user decision explicitly waiving that comparison.
There is no deployment, server integration, release, or live-profile task here.

## Background already prepared

- [fixtures.json](fixtures.json): full synthetic deal inputs and legal play
  prefixes for positive witnesses A/B and negative witness C. Initial hand order
  is preserved. These are **research-private fixture inputs**, not policy inputs.
- [source_manifest.json](source_manifest.json): hashes of the relevant current
  sources. The repository is dirty; a Git commit alone does not identify them.
- [BACKGROUND.md](BACKGROUND.md): definitions, evidence, API locations, proposed
  module boundaries, budget semantics, and reporting requirements.
- [preparation.json](preparation.json): what was actually checked while preparing
  this queue. That is preparation evidence, not completion of N01–N09.

The JSON fixture format is a new task-data format, not an existing engine schema.
N01 supplies its small loader. Do not pass it to an unrelated engine JSON loader.

## What “worked” means

| Level | Positive finding | What does not count |
| --- | --- | --- |
| Reproducibility | The same inputs reproduce the expected supports, actions and terminal totals | A script exits successfully but never reaches a choice |
| Correctness | Every issued certificate survives an independent exhaustive verifier | Agreement with a full-information oracle alone |
| Decision usefulness | A non-baseline choice has a strict, score-relevant guarantee on new positions | Different cards with equal score consequences |
| Efficiency | The same mathematical answers cost fewer transitions | A faster result obtained by dropping possible worlds |
| Playing strength | The frozen candidate improves paired deal outcomes under N09's criteria | Passing witnesses, stable actions, or a favourable selected example |

Engineering correctness is binary. Research results may be **SUPPORTED**, **NO
USEFUL SIGNAL**, **HARM DETECTED**, or **INCONCLUSIVE**. An inconclusive fixed-size
trial is not proof of no effect. A faithfully measured negative result completes
a task; it must not be rewritten as a positive result or trigger unplanned tuning.

## Executor prompt

> Complete task Nxx only. Read its task file and docs/nolo/tasks/BACKGROUND.md.
> Verify its dependencies and the current source manifest first. Implement only
> its listed outputs, run its acceptance checks, and write its completion report.
> Treat expected values as assertions that can fail. Do not edit the charter,
> historical findings, frozen profiles, or unrelated work. Do not execute the
> next task automatically. If a mathematical claim fails, preserve the smallest
> counterexample and report the failed endpoint rather than adjusting the target.

Use G1's separate neutral prompt for independent framings. Do not give those
fresh contexts this queue or its background: both reveal framing 1's answer.

## Completion report required for every task

Write `docs/nolo/results/<ID>.md` when executing that task, with:

1. Task status: `COMPLETE`, `BLOCKED_INPUT`, or `FAILED_CHECK`.
2. Scientific outcome, if applicable, separately from task completion.
3. Source/input hashes, exact commands, runtime, budget and software version.
4. Every endpoint: target, observed result, `PASS`/`FAIL`/`NOT_RUN`.
5. Unresolved cases and their denominators; smallest counterexample if any.
6. Files changed, assumptions, limitations, and which task may run next.

Do not change this task's predeclared thresholds after seeing its result. Any
revision gets a new task/version and a reason recorded before new measurements.
