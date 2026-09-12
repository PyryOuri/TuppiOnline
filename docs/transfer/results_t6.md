# T6 results: rigidity is refuted, and T5's exception was a noisy point

**Status: COMPLETE. Outcome: NEITHER — the rigidity reading is withdrawn.**

Pre-registration: [hypotheses_t6.md](hypotheses_t6.md), committed as `68e7812`
before `work/transfer/t6_rigidity.py` existed. Run 2026-09-12, 1,024 base deals
per condition, 98,304 deal executions, 163 s. Artifacts under
`/Users/pyryouri/Developer/tuppi_t6_rigidity_20260912/`.

## 1. Instrument gates — all five pass

| Gate | Result |
| --- | --- |
| **I1** identical teams cancel | **pass** — 8.3e-17 |
| **I2** block completeness | **pass** |
| **I3** control replicates T2's V5 | **pass** — +0.006027 [+0.004822, +0.007277] contains +0.00574 |
| **I4** the rigid endpoint replicates T5 | **pass** — epsilon 0.00 is `first_legal`; +0.002337 [+0.001433, +0.003254] overlaps T5's |
| **I5** strength rises monotonically with epsilon | **pass** — +0.0464, +0.0526, +0.0592, +0.0642, +0.0676 |

## 2. Result

| `epsilon` | Margin | 95% CI | Strength | vs control |
| ---: | ---: | --- | ---: | ---: |
| control | +0.006027 | [+0.004822, +0.007277] | −0.0000 | — |
| 0.00 *(pure `first_legal`)* | +0.002337 | [+0.001433, +0.003254] | +0.0464 | 38.8% |
| 0.25 | +0.002756 | [+0.001647, +0.003884] | +0.0526 | 45.7% |
| 0.50 | +0.002122 | [+0.000712, +0.003594] | +0.0592 | 35.2% |
| 0.75 | +0.002431 | [+0.000724, +0.004176] | +0.0642 | 40.3% |
| 1.00 *(uniform random)* | +0.002525 | [+0.000758, +0.004292] | +0.0676 | 41.9% |

> **The margin is flat across the entire sweep**, at 35-46% of the control, with
> Spearman +0.200 and endpoint intervals overlapping heavily.
>
> **Rigidity does not explain T5's pattern.** The pre-registered verdict is
> NEITHER, whose stated consequence is that "T5's contrast was then a single
> noisy point and the rigidity reading should be withdrawn". It is withdrawn.

## 3. What actually happened in T5

T5's `seeded_random_legal` margin was +0.004943, **87.7%** of control, and that
one point was the whole basis of the rigidity reading. Its interval was
[+0.002614, +0.007198] — the widest in T5, because a random opponent adds
variance. T6's uniform-random endpoint gives +0.002525, [+0.000758, +0.004292].

**Those intervals overlap.** The apparent recovery to 87.7% is fully consistent
with ~42%, and the exception that motivated an entire experiment was noise.

The T6 pre-registration said so before any of this ran: "it is **one point**...
its interval is the widest in T5". Writing that down did not stop me predicting
the hypothesis would be confirmed, but it did make the refutation legible instead
of arguable.

**This simplifies T5's headline rather than weakening it.** The margin compresses
to roughly 30-45% of its home value against foreign opponents — *all* of them,
rigid or random. There is no exception to explain.

## 4. Predicted outcome versus what happened

| | Prediction | Actual | |
| --- | --- | --- | --- |
| **P1** | verdict RIGIDITY_SUPPORTED | NEITHER | **wrong** |
| **P2** | I3 and I4 pass | both pass | **right** |
| **P3** | epsilon 1.00 reaches >=70% of control | 41.9% | **wrong** |
| **P4** | most recovery by epsilon 0.50 | no recovery at all | **vacuous** |

One of four, and the failure mode is the expected one for a hypothesis generated
from the data that is supposed to test it. T5's reading was post-hoc, T6's
pre-registration said so in section 1, and it was still wrong. That is the
argument for the discipline in its cleanest form: the hypothesis was mine, it was
plausible, it was explicitly flagged as untested, and it did not survive contact
with a designed test.

## 5. The first run was void, and why it is worth recording

The first execution failed gate I5 and was void. Investigating why turned up a
defect in the instrument: the stochastic opponent keyed its choice on
`(seed, epsilon, seat, tricks, cards in trick, phase, hand size)` and **not on
the deal**. Across 1,024 deals that is 2,704 distinct keys, so the "random"
opponent replayed one fixed table of positional decisions in every deal — uniform
in its action distribution, and perfectly determined by position.

The experiment built to test whether rigidity collapses the margin had
accidentally made its own random arm rigid. Its `epsilon = 1.00` margin came out
at **6.2%** of control, against **41.9%** after the fix.

That contrast is suggestive, and it is **not** evidence. It comes from a void
run, the two intervals are not cleanly disjoint, and reviving the rigidity
hypothesis from the data of a defective experiment designed to test that same
hypothesis would be the exact error this document is recording. Anyone who wants
to test whether cross-deal determinism matters should pre-register it. The void
run's payload is kept beside the valid one so the claim can be checked rather
than taken on trust.

## 6. What this does not establish

Nothing about *why* the margin compresses against foreign opponents. Two
candidate explanations have now been tested and rejected — saturation in T5,
rigidity here — and the mechanism remains unknown. That is a better position than
before only in the sense that two wrong answers are gone.

Nothing about human opponents, at either endpoint of this sweep.

Nothing at non-zero score states. Nothing about promotion. And nothing that
licenses a change to the incumbent: the margin is positive at every point
measured here.
