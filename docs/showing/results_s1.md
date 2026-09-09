# S1 results: observation-compatible headroom at the first show

**Status: COMPLETE. Outcome: INCONCLUSIVE by the pre-registered gates, which
stops the programme at this budget.**

Pre-registration: [hypotheses_s1.md](hypotheses_s1.md), committed as `59b7c32`
before the instrument in `work/showing/s1_headroom.py` existed. Instrument run
2026-09-08. Artifacts under
`/Users/pyryouri/Developer/TuppiRuns/phase7/s1/s1_headroom.json`.

**One of the two kill gates was unreachable by construction. That is a defect in
the pre-registration, recorded in §4 rather than repaired after the fact.**

---

## 1. What was measured

512 forehand hands × 128 exact conditional completions × 2 executable arms =
**131 072 completed-deal rollouts** in 179.5 s on 12 workers (730 rollouts/s).

Endpoint checks passed before anything was priced:

| Check | Result |
| --- | --- |
| symmetric-model control, `V(0-0)` | 0.500000 exactly |
| empirical `V(0-0)`, dealing side | 0.500076 |
| equity range over all 50 states | [0.2475, 0.7525], within the dealer asymmetry |
| baseline arm reproduces the reference | 32/32 deals, against an independently written loop |

Deal model fitted from **46 184 reference self-play deals**:
`P(dealer's team wins) = 0.4951`, mean 11.31 points.

## 2. The result

All figures are equity per evaluated deal, deployment-normalised (× ½ for the
seat share, so they are what a deployed candidate would gain across *all* deals,
not conditional on holding the forehand or on overriding).

| Quantity | Value | 95% CI |
| --- | ---: | --- |
| **`G_deploy`** — the cross-fitted selector | **+0.000096** | [−0.000042, +0.000243] |
| **`G_legal_upper`** — optimistic bound | **+0.001184** | [+0.000954, +0.001425] |
| **`G_foresight`** — the oracle | +0.006223 | — |
| δ — the funding threshold | 0.001000 | — |

- **PASS?** No. `G_deploy`'s lower bound is −0.000042, far below δ, and its
  interval contains zero.
- **SCIENTIFIC KILL?** No. `G_legal_upper`'s upper bound is +0.001425, above δ.
- **Therefore INCONCLUSIVE**, and the pre-registration is explicit about what
  that means: the programme stops at this budget, this is not licence to
  escalate completions until something appears, and it is not evidence that no
  learned Tuppi player is possible.

Descriptive, for interpretation only:

| | |
| --- | ---: |
| observations where the alternative's mean beat the baseline | 49/512 = **9.6%** |
| mean per-completion Δ | **−0.0186** |
| sd per-completion Δ | 0.0586 |
| completions where the intervention changed the outcome | 85.7% |
| reference's own declaration | NOLO 385, RAMI 127 (**24.8% RAMI**) |
| best / worst observation mean | +0.0289 / −0.0785 |

So the intervention *matters* — it changes the outcome in 86% of completions —
and it is *bad* on average, by a wide margin. The reference's declaration rule
is already close to right on about nine hands in ten.

## 3. The finding that survives: the foresight gap is 65×

This is what the experiment was built to measure, and it is unambiguous.

```
G_foresight  = +0.006223      an oracle that sees the hidden layout
G_deploy     = +0.000096      a selector that sees only the observation
ratio        = 65x
```

`docs/database/phase7_charter.md` §1.7 reported that the reference captures 30.6%
of a perfect-foresight ceiling and read that as a 3.3× headroom. **The external
review's objection was that the foresight column is not a learnable bound, and
that the gap between it and observation-compatible headroom can be arbitrarily
large. On this decision the gap is a factor of 65.**

A consistency check: undoing the seat-share normalisation, the oracle's gain over
the reference is +0.0124 equity per forehand deal. §1.7's independent study puts
the same difference at 0.02126 − 0.00652 = +0.0147. The two agree to within
about 15%, which is reassuring given that this intervention is restricted to a
fixed alternative-card selector while that study's oracle chose freely — a
restricted oracle should score lower, and it does.

## 4. The defect: one gate could never have fired

`G_legal_upper` was defined as `E_o[max(0, Δ̄(o) + z·se(Δ̄(o)))]`. At 128
completions with a per-completion sd of 0.0586:

```
se        ≈ 0.0050
z · se    ≈ 0.0097   =  10 × δ
```

So the additive noise allowance alone is ten times the threshold the gate had to
fall below. **Any observation whose true mean exceeded −0.0097 contributed
positively, and the statistic was measuring the Monte Carlo noise floor rather
than headroom.** Driving `z·se` under δ needs about **13 200 completions per
observation** — a hundred times the pre-registered budget.

This is a design error in `hypotheses_s1.md` §6–§7, not a property of the game,
and it is why the run returned INCONCLUSIVE rather than resolving. The
pre-registration forbids revising itself after a result, so the gate stands as
written and the run is reported as inconclusive.

## 5. Post-hoc analysis, clearly labelled as such

The following was **not** pre-registered and **cannot** be used to declare a
kill. It is recorded because it says what a properly powered version of this
experiment would most likely find, and because it should inform whether anyone
funds one.

Decompose the spread of the 512 per-observation means into real between-hand
signal and Monte Carlo noise:

| Component | Variance | sd |
| --- | ---: | ---: |
| observed across observations | 2.371e-04 | 0.0154 |
| Monte Carlo noise (mean se²) | 2.518e-05 | 0.0050 |
| **implied between-hand signal** | **2.119e-04** | **0.0146** |

**89.4% of the spread is real.** The forehand's own hand genuinely predicts
whether the other declaration would have been better — the signal exists and is
not a measurement artifact.

It is almost entirely negative. Shrinking each observation's mean toward the
grand mean by its noise share (James–Stein style) leaves **39/512 = 7.6%** of
hands with a positive true mean, and

```
seat_share · E[max(0, shrunk mean)]  =  +0.000217
```

against δ = 0.001. So a selector that knew `E[Δ|o]` *exactly* — no estimation
error at all — would gain about **a fifth of the funding threshold** on this
intervention.

That is the honest expectation to carry forward, and it is consistent with
`G_deploy = +0.000096`: a 64-completion estimate captured roughly 44% of what a
perfect selector would.

## 6. What this does and does not establish

**Establishes:**

- The cross-fitted selector tested here does not reach δ, with a tight interval
  that excludes it.
- The perfect-foresight framing of §1.7 overstates learnable headroom on this
  decision by a factor of about 65. That correction stands independently of the
  inconclusive verdict.
- Between-hand signal is real (89.4% of observed spread), so the failure is not
  "the hand tells you nothing". It is that what the hand tells you is almost
  always *don't deviate*.
- The endpoint works. The equity table, its model-free controls, and the
  baseline-identity check all behave, and `tuppi_valuation.equity` is usable as
  the primary endpoint for anything that follows.

**Does not establish:**

- That observation-compatible headroom at this decision is below δ. The gate
  that would have shown it was unreachable (§4), and the post-hoc estimate in §5
  is not a substitute.
- Anything about **card play**, which is 95.3% of decisions and untouched here.
- Anything about a **freely chosen** alternative card. The alternative arm used a
  declared lowest-eligible-rank selector; a candidate free to choose both
  contract and card has a larger action space and was not tested.
- Anything about **later showing seats**, **non-zero scores**, or **transfer** to
  any policy family other than the reference.

## 7. If anyone wants to reopen this: the budget

The cost is dominated by **which estimator gets declared**, not by the question.
All rollout rates below are measured: 730 rollouts/s on the Mac (12 workers,
from this run) and ~190 on the Fedora box (scaling by its measured 0.40
per-worker ratio across 8 workers).

| Option | Rollouts | Mac | Fedora |
| --- | ---: | ---: | ---: |
| S1 as run | 131 072 | 3 min | 11 min |
| **A: fresh 512×128 with the shrinkage estimator declared first** | **131 072** | **3 min** | **11 min** |
| B: same budget, 128 obs × 2 048 completions | 131 072 | 3 min | 11 min |
| C: brute-force the bound as originally written | **13 513 563** | **5.1 h** | **19.8 h** |

**Option A is the recommendation, and it costs nothing extra.** Bootstrapped on
the existing data, the shrinkage estimator's one-sided 97.5% upper bound is
**+0.000337**, three times below δ. Declared in advance, it would fire the
scientific kill.

But it must be declared and then run on **fresh observations**. The shrinkage
estimate in §5 was computed after seeing the result, so declaring it now and
firing a kill on the same 512 hands would be pre-registration in name only. Same
design, new seeds, three minutes.

**Option B does not help.** Trading observations for completions leaves
`z·se ≈ 0.0025`, still 2.5× δ, so the original gate remains unreachable while
the between-observation interval gets wider.

**Option C is the whole deferred corpus over again.** 13.5M rollouts is 103× this
run, 7.3× everything else in the programme put together, and **0.99× the wall
time of generating T1's 10M deals** — the tier D7 deferred. Brute-forcing a badly
specified statistic would cost exactly what the thing it was meant to justify
skipping costs.

For scale, the rest of the adopted programme against the same rates:

| Workload | Rollouts | Mac | Fedora |
| --- | ---: | ---: | ---: |
| Experiment 0 diagnostics | 100 000 | 2 min | 9 min |
| Experiment 2, showing model | 440 000 | 10 min | 39 min |
| Experiment 4, card play | 300 000 | 7 min | 26 min |
| Experiment 5, on-policy round | 1 000 000 | 23 min | 1.5 h |
| **all five experiments including S1** | **1 971 072** | **45 min** | **2.9 h** |
| T1 corpus, deferred | 10M deals | 5.2 h | 20.1 h |

**The entire five-experiment programme is 14% of one T1 run.** That is the
practical case for the review's ordering, and it survives this inconclusive
result: the programme is cheap enough that a wasted experiment costs three
minutes, which is what just happened.

## 8. Recommendation

Run option A — three minutes on fresh seeds with the estimator declared first —
or accept §5 as the answer and stop. Do not run option C.

If option A fires the kill, Experiment 2 is not funded on this scope, and the
open question becomes whether a *freely chosen* alternative card (rather than the
declared lowest-eligible-rank selector) or a **card-play** intervention has
headroom the declaration does not. Those are different experiments with their own
pre-registrations, and §6 records that this run says nothing about either.
