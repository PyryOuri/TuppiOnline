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

## 7. If anyone wants to reopen this

Two options, and they should be chosen before any further measurement:

1. **Re-preregister with a powered bound.** Declare the shrinkage estimator of
   §5 in advance, or trade observations for completions — 128 observations ×
   2 048 completions is the same 131 072 rollouts and gives `z·se ≈ 0.0025`,
   still above δ but four times tighter. Resolving the bound honestly at δ =
   0.001 needs roughly 100× the rollouts, which is ~4.5 hours on the Mac and
   ~9 hours on the Fedora box — affordable, if the question is worth it.
2. **Accept §5 as the expected answer and stop.** A perfect selector at this
   decision looks worth ~0.0002 equity per deal. If δ = 0.001 is the right
   funding threshold, this intervention is not worth amortising into a network,
   and the review's Experiment 2 should not be funded on this scope.

The reviewer's own framing argues for the second: the point of putting the
cheapest, most favourable, most diagnosable test first was to be able to stop.
The test ran, it cost three minutes, and it did not find the headroom it was
looking for.
