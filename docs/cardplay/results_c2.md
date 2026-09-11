# C2 results: the reachable headroom is larger than measured before, and the curve has not converged

**Status: COMPLETE. Outcome: MEASURED, with the secondary estimate unusable.**

Pre-registration: [hypotheses_c2.md](hypotheses_c2.md), committed as `e37d54e`
before `work/cardplay/c2_headroom.py` existed. Run 2026-09-11, 512 observations,
3,407,872 rollouts, 5,220 s at twelve workers. Artifacts under
`/Users/pyryouri/Developer/tuppi_c2_headroom_20260911/`.

## 1. Instrument gates — all four pass

| Gate | Result |
| --- | --- |
| **I1** `G_deploy(W) <= G_foresight` at every W | **pass** |
| **I2** paired monotonicity in W | **pass** — every increment positive |
| **I3** `G_deploy(256)-G_deploy(128) < G_deploy(64)-G_deploy(32)` | **pass** — 0.000321 < 0.000411 |
| **I4** replicates C3 at every overlapping budget | **pass** — all seven intervals overlap |

I4 is the one that earns trust. A fresh root seed (`tuppi-c2-headroom-v1`) and a
fourfold larger completion set reproduce C3's curve at all seven shared budgets,
and `G_foresight` comes out at +0.016015 against C3's +0.016136 — 0.8% apart.
Two independent runs, different seeds, different M, same curve.

## 2. The curve

| W | `G_deploy` | ci95 | | W | `G_deploy` | ci95 |
| ---: | ---: | --- | --- | ---: | ---: | --- |
| 1 | −0.000281 | [−0.001549, +0.000950] | | 32 | +0.000986 | [+0.000711, +0.001261] |
| 2 | −0.000216 | [−0.001140, +0.000705] | | 64 | +0.001397 | [+0.001165, +0.001630] |
| 4 | −0.000002 | [−0.000628, +0.000657] | | 128 | +0.001538 | [+0.001328, +0.001741] |
| 8 | +0.000105 | [−0.000340, +0.000574] | | **256** | **+0.001860** | **[+0.001668, +0.002050]** |
| 16 | +0.000545 | [+0.000190, +0.000908] | | | | |

## 3. Primary result

> **`G_legal >= 0.001702`** — the one-sided 95% bootstrap lower bound on
> `G_deploy(256)`, and therefore a lower bound on the best observation-compatible
> selector.
>
> **At least 10.6% of the perfect-information gain is reachable from the
> observation alone**, against `G_foresight` = +0.016015.

This needs no functional form and no model of the noise. It is valid because a
256-world selector *is* observation-compatible, which is the whole reason this
design replaced C1's shrinkage estimator rather than repairing it.

It is also **70% above δ**, and it is larger than anything previously measured
at the opening lead: C1's cross-fitted `G_deploy` was +0.001441 and C3's top
budget gave +0.001470. The headroom is bigger than the record said.

## 4. The secondary estimate is unusable, and the gate that should have caught it was too weak

The pre-registration says to report the extrapolated plateau when the fitted
exponent is negative. It is negative, so it is reported: **0.003040**, from
`b = −0.255`. It should carry almost no weight, and saying so is not a revision
of the pre-registration — section 5 labelled it model-dependent in advance, and
this is what that label was for.

Two reasons:

* **The fit adds 63% of the measured value.** `b = −0.255` means increments fall
  by a factor of only 0.838 per doubling, so the tail beyond W=256 sums to
  +0.001181 on top of +0.001860. An extrapolation doing that much work is not an
  estimate of an asymptote; it is a statement that no asymptote was observed.
* **The increments are not decaying.** In order: +0.000065, +0.000214,
  +0.000107, +0.000440, +0.000441, +0.000411, +0.000141, **+0.000321**. The step
  from 128 to 256 is more than twice the step from 64 to 128. C3's series over
  its smaller range looked cleanly decelerating (0.000530, 0.000509, 0.000363,
  0.000215); extended, that appearance does not survive.

**I3 passed on its literal terms while the property it was meant to certify did
not hold.** It compared the top increment against a mid-range one, which a
non-monotone series can satisfy while still rising. What it should have tested is
that the increments decrease from some point on. The gate is recorded as passed,
because a pre-registration may not revise itself after a result, and the design
defect is recorded here so the next use of it is written differently.

So the honest summary of the ceiling is: **not established.** `G_legal` is at
least 0.001702 and the curve was still climbing at the largest budget measured.

## 5. Predicted outcome versus what happened

Two of five. Recorded in advance in section 6 of the pre-registration.

| | Prediction | Actual | |
| --- | --- | --- | --- |
| **P1** | `G_deploy(128)` in [0.00150, 0.00170] | +0.001538 | **right** |
| **P2** | `G_deploy(256)` in [0.00155, 0.00178] | +0.001860 | **wrong**, above |
| **P3** | plateau in [0.00165, 0.00200] | 0.003040 | **wrong**, far above |
| **P4** | `G_legal / G_foresight < 0.15` | ≥10.6%, plateau 19.0% | **not established**, and contradicted by the plateau |
| **P5** | all four gates pass | all four pass | **right** |

The pattern is the same one the previous three failures had: I extrapolated a
decelerating trend and the quantity kept rising. That is now four pre-registered
predictions in this programme where the effect was larger or later-saturating
than I expected, which is worth more than any single one of them.

## 6. What this changes

**The largest affordable budget is the one to deploy, not W=64.** The curve is
still rising at 256 and W=64 is no longer the interesting point. Gate zero
measured W=128 at a 3.08 s cold maximum with eight workers; W=256 should be near
6 s, which is inside the 8 s anchor. That figure is scaled from the measured
W=128 result and **has not been measured** — it should be before anything is
deployed at 256.

**C1's kill is now doubly superseded.** Its `G_legal_eb` gate was void, and the
quantity it was trying to bound is at least 0.0017, not the 0.00057 that
estimator produced.

## 7. What this does not establish

`G_foresight − G_legal` is the **value of hidden information**, not an error
floor of any policy. At least 10.6% of the foresight gain is reachable and the
true fraction is unknown but larger; the remainder is decided by cards the
leader cannot see. This must never be quoted as "irreducibility", which is the
error I made before this experiment existed and which section 7 of the
pre-registration was written to prevent.

It says nothing about the *incumbent's* distance from `G_legal`. This measures
the far end of that interval. A candidate could win at most the gap between the
incumbent and `G_legal`, and the incumbent's position in it is not measured here.

Nothing about later tricks — C4 established the signal is opening-lead-specific
and this inherits that scope. Nothing about match equity: the endpoint is
per-deal points and C3's screening rule is not a promotion rule. Nothing about
transfer beyond the frozen reference, which continues on both arms. And nothing
licenses a candidate or a campaign.
