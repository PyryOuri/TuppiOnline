# Preregistration v1 — N09 paired forced-NOLO validation

**Written before any deal of `nolo-info-strength-v1` was generated or played.**
This document is versioned; a later change belongs in a `-v2` file beside it and
never as an edit here. Date: 2026-09-06.

This trial measures **forced-NOLO deal play at the table**. It is not a measure
of whole-match strength, not a measure of performance against human opponents,
and not a claim about any scoreboard other than `(0,0)`. No historical trial is
reopened and no sealed bank is used.

## The candidate under test, frozen

The N08 configuration, unchanged:

| File | SHA-256 |
| --- | --- |
| `src/tuppi_nolo/adapter.py` | `b5fc0ace150a6eaf3c7e8ca8589f15bd91948d5bcd4074f0cafb8669b0f3d22c` |

Identity `nolo_security_certified_v1:<partner_aware_v1 agent id>`, budget
`SupportBudget(3, 100, 100000)`, uncached search. **B** is v2
(`partner_aware_lead_v2`); **C** is that candidate. Exactly one candidate is
tested; nothing is selected on this bank.

Gates: N08 PASS ([results/N08.md](results/N08.md)), N07 GO, G1 waived on the
record.

## Design, fixed in advance

512 independent base deals, root seed `nolo-info-strength-v1`, indices 0–511,
initial score `(0,0)`, initial dealer 0, round-robin dealer policy, identical
canonical NOLO showing forced in every arm. Each base deal is played four times:

| Arm | Team 0 (seats 0, 2) | Team 1 (seats 1, 3) |
| --- | --- | --- |
| BB | B | B |
| CB | C | B |
| BC | B | C |
| CC | C | C |

Both seats of a team use that team's policy. Agents are constructed fresh per arm
and per deal, so no certificate, plan or memo crosses an arm boundary. All 13
tricks are played. A failed arm makes its block incomplete and is never
substituted or removed.

**Run cap: 4 wall-clock hours.** If the cap prevents completion the result is
INCONCLUSIVE. A completed subset is not evaluated in its place, and complete and
incomplete block counts are preserved either way.

## Primary effects

Team 0 is the predeclared target. For base deal `i`, with `T` the Team-0 trick
total and `W` the Team-0 deal win:

```
D_B_tricks[i] = T_BB[i] - T_CB[i]      D_B_wins[i] = W_CB[i] - W_BB[i]
D_C_tricks[i] = T_BC[i] - T_CC[i]      D_C_wins[i] = W_CC[i] - W_BC[i]
```

**Both families are signed so that positive favours the candidate.** Fewer tricks
is better in NOLO, so the trick contrast is baseline minus candidate; a deal win
is better, so the win contrast is candidate minus baseline. This orientation is
fixed here so the two cannot later be read with opposite signs.

`D_B` is the candidate against baseline opponents; `D_C` is the same replacement
when the opponents also use it. **They share deals and arms and are not
independent replications.** Wherever both are quoted, that is stated.

## Analysis, fixed in advance

`tuppi_eval.statistics.paired_value_summary`, one finite value per base deal,
confidence level 0.95, analysis seed `nolo-info-strength-analysis-v1`, 5,000
bootstrap and 5,000 permutation replicates. The declared bound is the returned
`bootstrap_confidence_interval` in every test, for both contrasts and both effect
families. No alternative interval or test is consulted, and none is chosen after
seeing an outcome.

Team-1 mirrored effects (`BB` vs `BC`, and `CB` vs `CC`, targeting Team 1) are
reported **separately as orientation diagnostics only**. They are never pooled
with the Team-0 primaries: trick totals are conserved within a deal, so a pooled
complementary contrast can be algebraically the same observation counted twice.
Individual seats, the 13 tricks of a deal, and score projections are not
additional independent observations. One base deal is one unit.

## Decision endpoints, fixed in advance

**SUPPORTED: forced-NOLO deal improvement** requires all of:

1. All 512 four-arm blocks complete, with zero illegal actions, information
   leaks, invalid certificates or broken continuation commitments.
2. For **both** `D_B` and `D_C`: mean improvement at least **0.05 tricks per
   deal** and lower 95% bootstrap bound strictly greater than zero.
3. For both corresponding deal-win differences: point estimate at least zero and
   lower 95% bootstrap bound at least **−0.02** (a predeclared 2-percentage-point
   noninferiority margin).
4. No unreported configuration or seed change, no post-outcome case exclusion, no
   extra candidate. Fallback, commitment and latency counts recorded.

**HARM DETECTED:** a primary trick-effect upper 95% bound below zero, or a
deal-win upper bound below −0.02.

**INCONCLUSIVE / NOT ESTABLISHED:** a sound, complete trial that meets neither
the positive endpoints nor the harm condition. A small favourable mean with an
interval crossing zero is inconclusive, not a weak positive.

**INVALID:** any correctness violation, whatever the win rate.

The 0.05-trick and 2-point thresholds are proposed practical acceptance choices,
fixed here before the run. They are not historical findings and 512 deals is not
claimed to give high statistical power. Passing gives the bounded claim named
above and nothing wider.

**N will not be extended to reach significance, and no other seed will be
tried.** A follow-up needs a new preregistration with a justified size and scope.
The task completes when the fixed result and its limitations are recorded,
including a negative one.

## Execution

```
python -B -m tuppi_nolo.trial paired --seed nolo-info-strength-v1 \
    --deals 512 --workers 14 --out work/nolo/n09/trial
```

Blocks are independent and every decision is deterministic given its
observation, so the bank is spread over worker processes purely to fit the wall
clock. Parallelism changes no value and no budget is shared between workers.

Two implementation notes, recorded so they cannot look like drift later:

- The trial runner is a **new** module, `src/tuppi_nolo/trial.py`. The N07 runner
  is left byte-identical so the hash preregistered in
  [`hypotheses.md`](hypotheses.md) keeps pinning the code that produced the
  coverage screen. No production source is changed by this task.
- A **timing pilot** was run on the development seed `nolo-info-dev-v1` to judge
  whether 512 blocks fit the cap. It touched no deal of the trial seed and
  informed only the worker count, which is not an analysis parameter.

## Runner hashes, recorded before any trial deal existed

Added before `nolo-info-strength-v1` was generated or played. The timing pilot
above used only the development seed.

| File | Digest |
| --- | --- |
| `src/tuppi_nolo/trial.py` | `9ddb4982ba21e601` |
| `tests/nolo/test_paired_validation.py` | `24a90171a3240fb5` |

The pilot measured 245 CPU-seconds per four-arm block on the development seed,
so 512 blocks are expected to take about 2.5 wall-clock hours across 14 worker
processes. That expectation is a scheduling judgement only; if the run misses the
cap regardless, the result is INCONCLUSIVE and will be reported as such rather
than rerun with a different worker count to obtain a completed bank.
