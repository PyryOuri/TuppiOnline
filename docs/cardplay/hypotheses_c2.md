# C2: how much of the opening lead's headroom is reachable at all?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/cardplay/c2_headroom.py` may deviate from this document. Committed before
that file is written, and this document may not revise itself after a result.

## 1. Why, and what went wrong last time

`G_foresight >= G_legal >= G_deploy(W)`. C1 measured the two ends — foresight at
+0.016 and a realisable selector at +0.0014 — and tried to estimate the middle,
`G_legal`, with an empirical-Bayes shrinkage estimator. That estimator was
**defective**: it put `G_deploy` 2-2.5x *above* `G_legal_eb` with disjoint
intervals, which is impossible, because a realisable selector cannot beat the
best observation-compatible one. Two causes were identified — noise treated as
independent across arms priced on the same completions, and shrinkage applied
across arms rather than across observations. C1 was reported INCONCLUSIVE rather
than repaired.

C3 then measured `G_deploy(W)` for W up to 64 and found a monotone, decelerating
curve. Its section 6 records the plateau as **descriptive only** and says in as
many words that "an asymptote read off seven correlated points is not a
substitute for a declared estimator with an interval".

This experiment supplies that estimator. It does **not** repair the shrinkage
approach; it abandons it. `G_deploy(W)` is itself a valid lower bound on
`G_legal` at every W, because a W-world selector *is* observation-compatible, so
pushing W as far as the budget allows and reporting a confidence bound on it
needs no model of the noise at all.

There is a second reason to want this number. I have previously asserted "91.5%
irreducibility at the opening lead" and had to withdraw it as unsupported. The
ratio `G_legal / G_foresight` is the quantity that claim should have been about,
and nothing in the record measures it.

## 2. Estimand

**`G_legal`** at the opening lead: the deployment-normalised gain of the best
observation-compatible selector, i.e. `lim_{W->inf} G_deploy(W)`.

Endpoint, conditioning (HARD), decision, δ = 0.001 and deployment normalisation
are exactly as fixed in [hypotheses_c1.md](hypotheses_c1.md), and the arm pricing
is exactly C3's. The only thing that changes is how far the world-count curve is
extended and what is read off it.

## 3. Design

`W in {1, 2, 4, 8, 16, 32, 64, 128, 256}`.

**M = 512 completions sampled once per observation.** As in C3 the choice at
budget W is made on completions `[0:W]` and scored on `[W:2W]`, averaged with the
mirrored split, so choosing and scoring sets are always disjoint and each
`G_deploy(W)` is free of selection-on-noise bias. Disjointness is what caps W at
`M/2`; reaching W = 256 is the whole reason M is 512 rather than C3's 128.

Estimates at different W are **correlated by construction** — nested subsets of
one completion set — exactly as in C3. That is why the monotonicity and
deceleration gates below are **paired** tests.

N = 512 observations. Root seed `tuppi-c2-headroom-v1` — deliberately *not*
C3's, so that the overlapping budgets are an independent replication rather than
a re-read of the same numbers. Bootstrap seed `tuppi-c2-bootstrap-v1`, 5,000
replicates resampled over observations.

Budget: 512 x 512 x 13 = 3,407,872 rollouts, about four times C3's sweep, which
ran 850,304 rollouts in 1,108 s at ten workers. Expected around 75 minutes.

## 4. Instrument gates — declared now, checked before any science is read

A failure voids the science rather than being reported alongside it.

> **I1 — bounded by foresight.** `G_deploy(W) <= G_foresight` for every W, on
> point estimates.
>
> **I2 — monotone in W.** The paired per-observation difference
> `G_deploy(2W) - G_deploy(W)` is non-negative in mean for every adjacent pair.
> A single flat pair is permitted; a negative mean at any pair fails.
>
> **I3 — decelerating into the new range.** The paired increment
> `G_deploy(256) - G_deploy(128)` must be smaller in mean than
> `G_deploy(64) - G_deploy(32)`. If the curve is still rising as fast at the top
> of the new range as it was at the top of C3's, then 256 is not near an
> asymptote either and **no plateau may be reported** — only the lower bound.
>
> **I4 — replication of C3.** At every overlapping budget `W <= 64`, C2's 95%
> interval must overlap C3's. A fresh seed and a fourfold larger completion set
> should reproduce the same curve; if it does not, one of the two runs is wrong
> and neither result may be read.

## 5. Estimators

**Primary, assumption-free.** The one-sided 95% bootstrap **lower** confidence
bound on `G_deploy(256)`, reported as a lower bound on `G_legal`. This requires
no functional form and no model of the noise: it is valid because a 256-world
selector is observation-compatible.

**Secondary, model-dependent and labelled as such.** Fit
`log(increment) = a + b * log(W)` by ordinary least squares over the paired
increments at `W in {8, 16, 32, 64, 128}`, where the increment at W is
`G_deploy(2W) - G_deploy(W)`. If `b < 0`, the tail beyond 256 sums to
`exp(a) * 256^b / (1 - 2^b)`, and the extrapolated plateau is
`G_deploy(256)` plus that tail, bootstrapped over observations for an interval.
If `b >= 0` the extrapolation is not reported at all.

**The ratio.** `G_legal / G_foresight`, computed from both the lower bound and
the plateau, is the headline. It is the fraction of the perfect-information gain
that an observation-compatible selector can actually reach.

## 6. Predicted outcome, recorded in advance

My last three pre-registered predictions in this programme — C1's direction,
C3's threshold location, C4's generalisation — were **all wrong**. These are
recorded for the same reason, not because they deserve confidence.

Extrapolating C3's increment series (0.000530, 0.000509, 0.000363, 0.000215 at
W = 4, 8, 16, 32) gives a ratio between successive increments approaching about
0.59:

* **P1** — `G_deploy(128)` point estimate in [0.00150, 0.00170].
* **P2** — `G_deploy(256)` point estimate in [0.00155, 0.00178].
* **P3** — extrapolated plateau in [0.00165, 0.00200].
* **P4** — `G_legal / G_foresight < 0.15`. Most of the perfect-information gain
  at the opening lead is **not** reachable from the observation.
* **P5** — all four instrument gates pass.

## 7. What this will not establish

`G_foresight - G_legal` is the **value of hidden information**, not an error
floor of any policy. A small `G_legal / G_foresight` says the opening lead is
largely decided by cards the leader cannot see; it does **not** say the
incumbent is near-optimal, and it must never be quoted as "irreducibility". The
distance from the incumbent to `G_legal` is what a candidate could win, and this
experiment measures the far end of that interval, not the near end.

Nothing about later tricks — C4 established the signal is opening-lead-specific,
and this inherits that scope. Nothing about match equity: the endpoint is
per-deal points, and C3's screening rule is not a promotion rule. Nothing about
transfer beyond the frozen reference, which continues on both arms. Nothing that
licenses a candidate or a campaign; a headroom bound is a reason to design an
experiment, not a result about an agent.
