# C1 results: the gate is void, and the unaffected estimator says the opposite of what I predicted

**Status: COMPLETE. Outcome: INCONCLUSIVE by pre-registration defect.**

Pre-registration: [hypotheses_c1.md](hypotheses_c1.md), committed as `6934da7`
before `work/cardplay/c1_headroom.py` existed. Runs 2026-09-10. Artifacts under
`/Users/pyryouri/Developer/tuppi_c1_cardplay_20260910/`.

**The pre-registered estimator is defective. The gate it defines cannot be
applied, and per §6 the pre-registration may not revise itself after a result, so
the run is reported inconclusive.** This is S1's failure mode repeating, and §5's
power check did not catch it because it measured noise and signal share, not the
estimator's internal consistency.

---

## 1. What ran

| Variant | Observations | Rollouts | Draws/world | Wall clock |
| --- | ---: | ---: | ---: | ---: |
| HARD | 508 / 512 | 845,312 | 2.27 | 1,122 s |
| POLICY | 488 / 512 | 812,032 | 21.68 | 1,277 s |

Endpoint controls passed in both: 46,184 deals fitted, dealer_win 0.49515, mean
points 11.3134, symmetric `V(0-0) = 0.500000` exactly, equity range inside the
dealer asymmetry.

The feasibility probe put POLICY acceptance at 13.85%, about 7 draws per world.
The real figure is **21.7**, so that estimate was optimistic by roughly 3×. It
barely mattered: the extra cost is show replays, which are cheap beside 13
rollouts, so POLICY ran only 14% slower than HARD.

## 2. The defect

| | HARD | POLICY |
| --- | ---: | ---: |
| `G_legal_eb` — what a **perfect** selector would gain | +0.000570 [0.000472, 0.000676] | +0.000779 [0.000654, 0.000913] |
| `G_deploy` — what a **cross-fitted** selector actually gains | **+0.001441** [0.001205, 0.001680] | **+0.001520** [0.001307, 0.001742] |
| `G_foresight` — the oracle | +0.015884 | +0.013544 |

**A deployed selector cannot beat a perfect one.** `G_deploy` exceeds
`G_legal_eb` by a factor of 2.5 in HARD and 2.0 in POLICY, with disjoint
intervals, in both conditioning models. That ordering is impossible, so
`G_legal_eb` as specified does not estimate what §4 claims.

A fresh 24-observation diagnostic isolates two independent causes:

**(a) Correlated arms treated as independent.** §4 sets
`noise = mean_a(s_a^2)`, but all 13 arms are priced on the *same* completions, so
their sampling errors are strongly positively correlated and the noise in arm
*differences* is far smaller than that expression implies. Signal is understated,
lambda collapses, the estimator over-shrinks. Measured: lambda 0.150 under the
pre-registered form against 0.338 when the same data is re-expressed as paired
per-completion gains, moving the estimate from +0.000386 to +0.000969.

**(b) Shrinkage applied across the wrong index.** S1 shrinks across
**observations** — 512 hands, each contributing one paired difference — and so
estimates the distribution of `E[Delta|o]` over hands. §4 shrinks across **arms
within** an observation. That is not S1's construction and does not estimate the
perfect-selector gain: `max` of shrunken means is a compressed estimator of
`max` of true means, biased toward zero whenever lambda < 1.

Correcting (a) alone leaves the impossible ordering in 11 of 24 observations, so
(a) is necessary and not sufficient. The pre-registered estimator cannot be
repaired inside this pre-registration.

## 3. What the unaffected estimators say, and it is not what I predicted

`G_deploy` is cross-fitted — argmax chosen on one half of the completions, scored
on the other — so neither defect touches it. `G_foresight` is a per-completion
maximum and is likewise unaffected.

> **A selector that samples worlds at the opening lead and picks the best card
> gains about +0.0014 to +0.0015 equity per deal, deployment-normalised, with
> intervals excluding delta = 0.001 from above, and the two conditioning models
> agree to within 6%.**

Section 8 of the pre-registration recorded my prediction — *"a kill"* — precisely
so that this could not be presented as anything other than a miss. **It is a
miss.** I expected the showing result to carry over, on the reasoning that
irreducible hidden-layout variance is a property of hidden information rather
than of which decision is being made. That reasoning does not survive: at the
opening lead a world-sampling selector captures **about 10%** of the foresight
gap (0.0014 / 0.0146 pooled), against the **3.9%** S1b measured for a perfect
observation-only selector at showing.

## 4. What this does and does not establish

**Establishes:**

- The pre-registered `G_legal_eb` is invalid, for two identified and separately
  measured reasons. No headroom bound is claimed by this run.
- `G_deploy` above delta at the opening lead, replicated across two conditioning
  models with disjoint intervals from delta. This is the first observation-
  compatible signal above the funding threshold anywhere in this programme.
- Conditioning a card-play decision on its show history is affordable. Hard
  constraints accept 44% of draws in practice; the exact policy-dependent
  conditional needs about 22 draws per world and costs 14% more wall clock.
- The endpoint transfers unchanged from showing to card play.

**Does not establish:**

- Any bound on observation-compatible headroom. That was the point of the run and
  the estimator failed to deliver it.
- That `G_deploy`'s selector is *deployable*. It picks the argmax over 64 sampled
  worlds, which is PIMC in all but name, and the ten-second production budget
  remains unmeasured. A rule that needs 64 world samples per decision is not
  obviously affordable, and nothing here says it is.
- Anything about later tricks, non-zero scores, transfer beyond the frozen
  reference, or opponent-model play.
- That any candidate should be built. `G_deploy` measures a selector given
  reference continuation in both arms, not a full search agent.

## 5. What a corrected run needs

A new pre-registration under a new name, on fresh seeds, fixing:

1. **Paired per-completion gains** `d_a(c) = V(a,c) - V(policy,c)` as the unit,
   so the pairing that makes the arms comparable is preserved.
2. **Shrinkage across observations**, matching S1: per observation reduce the
   arms to a single scalar first — the natural choice is the cross-fitted best-arm
   gain, which is already unbiased — then shrink that scalar across the 512
   observations exactly as S1b did.
3. **An internal consistency check as a gate on the instrument, not the science:**
   assert `G_legal_eb >= G_deploy` before any result is reported. Had that
   assertion existed, this run would have failed in its first minute instead of
   its last.

Item 3 is the transferable lesson. S1 lost a run to an unreachable gate; C1 lost
one to an inconsistent estimator. Both were detectable before the science, and
neither power analysis looked for them.

## 6. Cost

| | Rollouts | Wall clock |
| --- | ---: | ---: |
| C1 both variants | 1,657,344 | 40 min at 10 workers |
| S1 + S1b together | 262,144 | 6.2 min |
| the deferred T1 corpus | 10M deals | 5.2 h |

Forty minutes bought one void gate and one replicated surprise. The surprise is
worth more than the gate would have been, but it was bought by accident, which is
not a method.
