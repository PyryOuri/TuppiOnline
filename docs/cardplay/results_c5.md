# C5 results: the measured headroom did not appear in deployment, and the campaign could not have found it

**Status: COMPLETE. Outcome: INCONCLUSIVE, underpowered by a knowable factor.**

Pre-registration: [hypotheses_c5.md](hypotheses_c5.md), committed as `d515f3b`
before `work/cardplay/c5_deployed.py` existed, amended as `49a5e0c` before the
campaign ran. Run 2026-09-11, 256 base deals, 2,048 games, 1,024 searched
decisions, 4,925 s. Artifacts under
`/Users/pyryouri/Developer/tuppi_c5_deployed_20260911/`.

## 1. Instrument gates — all four pass

| Gate | Result |
| --- | --- |
| **I1** identical teams cancel | **pass** — largest control magnitude 5.55e-17 |
| **I2** every block contributes all 8 transformations | **pass** — 256 blocks, all 8 |
| **I3** searched exactly the opening leads its team led | **pass** — **1,024 / 1,024** |
| **I5** the score draw is faithful | **pass** — 39.8% at 0-0 against the visit distribution's 36.3% |

I3 landing exactly on 1,024 is worth stating: the scope is verified by counting,
not asserted, and the count is exact because showing is delegated in both
assignments, so `first_leader` is settled identically and belongs to the
candidate in exactly one of them.

**The I5 amendment turned out not to be load-bearing.** The realised 0-0 share
was 39.8%, which would have cleared the original absolute 40% bar — by 0.2
percentage points. The amendment was still right ex ante, since a faithful draw
had roughly a one-in-nine chance of voiding the run, but it did not change this
outcome and should not be credited with doing so.

## 2. Result

> **Mean deployed equity difference −0.000225, 95% CI [−0.002053, +0.001525].**
>
> **INCONCLUSIVE** under the pre-registered four-way rule: the interval spans
> zero, spans δ = 0.001, and is not contained within ±δ.

The point estimate is slightly negative. The interval is consistent with C2's
+0.001538 — but only at its extreme upper edge — and equally consistent with
zero and with a small negative effect. **The campaign cannot distinguish them.**

This does **not** establish that the effect is absent. It establishes that this
design, at this size, could not see it.

## 3. Why it could not see it, and the error was mine

The realised standard deviation across base deals is **0.0146**. The
pre-registration sized N from C2's dispersion of 0.00238 and claimed tolerance up
to 4.4x that. The realised figure is **6.1x**, outside the margin.

The cause was knowable in advance and I did not think of it. **C2's 0.00238 is
the dispersion of an estimator that averages 128 completions per arm; deployment
plays one.** A deployed observation is a single draw from the distribution C2
averaged over, so its standard deviation is larger by something of the order of
sqrt(128) ≈ 11. Using an estimator's SD as a proxy for a single realisation's SD
is the mistake, and it inflated my effective sample size by more than an order of
magnitude.

What would have been needed, at C2's effect size and the now-measured dispersion:

| goal | SE required | base deals | wall clock |
| --- | ---: | ---: | ---: |
| interval excludes zero | 0.000785 | **347** | ~1.9 h |
| one-sided bound clears δ | 0.000327 | **1,994** | ~10.6 h |

So 256 was not close. This is the fourth design defect of this kind in the
programme — C1's gate that could never fire, C2's I3 that passed while the
property failed, C5's I1 and I5, and now C5's power calculation — and all four
erred the same way, toward believing the instrument was sharper than it was.

## 4. Predicted outcome versus what happened

| | Prediction | Actual | |
| --- | --- | --- | --- |
| **P1** | positive and SCREENED_IN, in [+0.0008, +0.0018] | −0.000225, INCONCLUSIVE | **wrong** |
| **P2** | deployed estimate below C2's +0.001538 | −0.000225 | **right** |
| **P3** | gain larger near the target than at 0-0 | — | **not evaluable** |
| **P4** | all instrument gates pass | all pass | **right** |

**P3 could not be evaluated because the instrument threw the data away.** Each
block's score state was drawn and used, and then not persisted; only the
aggregate 0-0 share survived. A prediction the instrument cannot test is not a
prediction, and this one was written without checking that the run would record
what it needed. The instrument now saves per-block rows; this run's P3 is simply
lost.

P2 was the prediction deliberately made against my own recent bias, and it was
right. It should be given very little credit: I predicted "below" because a
deployed selector pays sampling noise in its own choice, and the actual gap is
far larger than that mechanism explains.

## 5. What to do with this

**Treat C5 as a variance pilot.** It measured the one quantity nobody had: the
deployed per-base-deal dispersion, 0.0146. That number is what a confirmatory
campaign must be sized from, and using a pilot's variance to size a confirmatory
run is standard practice rather than a rescue.

**Do not extend this run.** Adding base deals until an interval moves is optional
stopping, and it would destroy the error rate the pre-registered rule is there to
protect. A follow-up needs its own pre-registration with N fixed from 0.0146
before it starts.

The honest state of the branch: C2 established that at least +0.0017 of equity
per opening lead is *reachable* by some observation-compatible selector; C5 did
not show that this particular selector, at W=128, captures any of it in play.
Those are compatible, and the gap between them is exactly the question a properly
sized campaign would answer.

## 6. What this does not establish

Not that the selector is worthless, and not that it works. An inconclusive
interval is not a null result, and quoting it as one would be the same error as
quoting C1's void gate as a kill.

Nothing about W = 256, which C2 measured at +0.001860 and which was not run here.
Nothing about match win probability, which is the promotion endpoint and a
separate and far larger campaign. Nothing about score-state dependence, per
section 4. Nothing about opponents other than the incumbent, which plays both
arms throughout.
