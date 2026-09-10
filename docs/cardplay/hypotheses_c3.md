# C3: how many sampled worlds does the opening-lead selector need, and what does it cost?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/cardplay/c3_worlds.py` may deviate from this document.

C2 — the corrected headroom bound — is deliberately *not* this experiment. It is
reserved for a separate pre-registration with the estimator repaired.

## 1. Why

C1's gate was void, but its cross-fitted `G_deploy` was untouched by either
defect and came out **above** δ: +0.001441 [0.001205, 0.001680] under HARD
conditioning and +0.001520 [0.001307, 0.001742] under POLICY, agreeing to within
6%. That is the first observation-compatible signal above the funding threshold
anywhere in this programme, and it contradicted the kill I had predicted.

Because a perfect selector must do at least as well as a realisable one, the
*existence* of above-δ headroom at the opening lead is already established. What
is not established is whether it can be **afforded**. The selector that produced
that number samples **64 worlds and prices 13 arms per decision** — 832 rollouts.
At the 753 rollouts/s the C1 run itself achieved on ten workers that is about
**1.1 s per decision**; single-process at 85 rollouts/s it is **9.8 s**, the whole
production budget for one decision.

The ten-second requirement has read "NOT MEASURED" since R1. It is now on the
critical path.

## 2. Estimand

`G_deploy(W)` — the deployment-normalised gain of a selector that estimates
`E[V(a|o)]` from **W** sampled worlds and plays the argmax — for

```
W in {1, 2, 4, 8, 16, 32, 64}
```

with wall clock reported alongside. Endpoint, conditioning, decision, δ = 0.001
and deployment normalisation are all exactly as fixed in
[hypotheses_c1.md](hypotheses_c1.md). HARD conditioning only; C1 showed the two
models agree to within 6% and a second variant buys nothing here.

## 3. Design

**M = 128 completions sampled once per observation**, then for each W the choice
is made on completions `[0:W]` and scored on `[W:2W]`, averaged with the mirrored
split. Choosing and scoring sets are always disjoint, so each `G_deploy(W)` is
free of selection-on-noise bias.

Reusing one set of completions across all W means the estimates at different W
are **correlated by construction** — nested subsets. That is stated so it is not
later mistaken for independence, and it is why the monotonicity gate below is a
**paired** test, which is stronger. It also keeps the whole sweep to the same
852,000 rollouts as one C1 variant, about 19 minutes at ten workers, rather than
multiplying the budget by seven.

N = 512 observations, root seed `tuppi-c3-worlds-v1`, bootstrap seed
`tuppi-c3-bootstrap-v1`, 5,000 replicates over observations.

## 4. Instrument gates — declared now, checked before any science is read

This is C1's transferable lesson: both S1 and C1 lost runs to estimator defects
that were detectable before the result. These assertions run first and a failure
voids the science rather than being reported alongside it.

> **I1 — bounded by foresight.** `G_deploy(W) <= G_foresight` for every W, on
> point estimates. A selector with W sampled worlds cannot beat one that sees the
> actual layout. Violation means the choosing and scoring sets are leaking.
>
> **I2 — monotone in W.** The paired per-observation difference
> `G_deploy(2W) - G_deploy(W)` must be non-negative in mean for every adjacent
> pair. More information cannot hurt a selector that is estimating an expectation.
> A single adjacent pair may be flat; a **negative** mean at any pair fails.
>
> **I3 — a plateau below foresight.** `G_deploy(64) - G_deploy(32)` must be
> smaller in mean than `G_deploy(8) - G_deploy(4)`. The curve must be
> decelerating, not still rising linearly, or 64 worlds is not near any asymptote
> and no statement about the ceiling may be made.

An explicit non-gate: `G_deploy(1) ≈ 0` is **not** asserted. A one-world selector
still ranks arms on a noisy but informative sample, so a small positive value
there is expected and is not evidence of a defect. Recording this because it was
my first instinct for a gate and it is wrong.

## 5. Science gates

> **AFFORDABLE** if some W has a `G_deploy(W)` lower bound above δ **and** a
> measured per-decision cost at or under 10 s on this host at ten workers. The
> smallest such W is the reported answer.
>
> **UNAFFORDABLE** if only W values whose cost exceeds 10 s clear δ.
>
> **INCONCLUSIVE** if no W clears δ, which would also contradict C1 and put
> `G_deploy` itself in doubt.

Cost is reported three ways: rollouts per decision, seconds single-process, and
seconds at ten workers, all from throughput measured inside this run rather than
carried over.

## 6. Secondary, and clearly secondary

If I3 passes, the plateau of `G_deploy(W)` is an empirical estimate of the
perfect observation-only selector's gain — the quantity C1's shrinkage estimator
failed to produce. It is reported as **descriptive**, never as C2's bound: an
asymptote read off seven correlated points is not a substitute for a declared
estimator with an interval.

## 7. Predicted outcome, recorded in advance

Monotone increase clearing δ between **W = 8 and W = 32**, plateauing below
`G_foresight` ≈ 0.014, and affordable at ten workers at the W that clears. I was
wrong about C1's direction, so this prediction is offered with less confidence
than that one was, and it is recorded for the same reason.

## 8. What this will not establish

Nothing about later tricks, non-zero scores, transfer beyond the frozen
reference, or opponent-model play. Nothing about a full search agent: both arms
continue with the frozen reference, so this is opening-lead selection, not PIMC
play. Nothing about production qualification — a measured per-decision cost on an
idle machine is not the ten-second requirement, which includes showing, encoding,
transfers, synchronisation and first-move lazy initialisation under a watchdog. It
is a necessary condition, not the qualification.

And nothing licenses a candidate. PIMC sits on the charter's list of proposals
that are not current implementation orders; C1 is a genuine changed premise for
reopening it, but reopening is a governance decision.
