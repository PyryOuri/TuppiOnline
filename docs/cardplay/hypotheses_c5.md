# C5: does the measured headroom survive deployment and a real score?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/cardplay/c5_deployed.py` may deviate from this document. Committed before
that file is written, and this document may not revise itself after a result.

## 1. Why, and what C2 could not say

C2 established that at least **+0.001702** of frozen-continuation match equity per
opening lead is reachable by an observation-compatible selector, against a
δ of 0.001. Every number in C1, C2 and C3 was produced under two conditions that
deployment does not share:

* **Every deal started at 0-0.** `c1_headroom._start` builds
  `MatchScore(0, 0)` and nothing varies it. A real match visits a wide range of
  score states, a deal point is worth a different amount at each, and Phase 5A's
  own score-state bank is labelled "never part of the 0-0 primary distribution".
  The gain at 0-0 is one point on a curve nobody has traced.
* **Nothing played.** The arms were enumerated and priced inside an instrument.
  No scoped selector has chosen a card in the arena, against an opponent, under
  the duplicate design.

This experiment supplies both. It is a **screening** campaign and is not capable
of supporting a promotion claim: Phase 5A fixed the promotion endpoint as
orientation-averaged match win probability over complete complementary pairs, and
that is a separate and far more expensive experiment. C3's screening rule is not
a promotion rule, and neither is this.

## 2. Estimand

The **deployed per-deal frozen-continuation match equity difference** between

* **candidate** — the opening-lead-scoped selector: one-ply PIMC at the opening
  lead only, `world_count = 128`, delegate and rollout continuation both
  `partner_aware_lead_v2`; and
* **reference** — the production incumbent `partner_aware_lead_v2` in both
  partner seats, unmodified,

measured in the same units as C2 so the two are directly comparable, with
δ = 0.001.

The candidate configuration is the one C2 actually measured.
`c1_headroom._resources` builds `partner_aware_lead_v2` for all four seats, so
the incumbent was the continuation throughout; a candidate delegating to the
frozen reference would be a different selector whose headroom is unmeasured.

W = 128 rather than 256 because its cold maximum is 4.35 s against 8.58 s, inside
the 8 s admission margin rather than over it, and C2 measured +0.001538 there.
Choosing the cheaper admissible budget is a deliberate concession: if the effect
does not appear at 128 there is no case for paying for 256.

## 3. Design

**The canonical duplicate design.** 8 transformed games per base deal — 4
rotations x 2 team assignments — with cluster inference by base deal. Identical
teams must cancel to exactly 0.0, which is gate I1 below.

**N = 256 base deals, 2,048 games.** The candidate team holds the leading seat
in 4 of the 8 transformations, so **1,024 searched decisions**. At 4.35 s each on
eight workers that is about 75 minutes of search; the engine time for 2,048 deals
is negligible beside it.

That N is deliberately generous. C2's per-decision dispersion implies a standard
deviation of 0.00238, so 54 decisions would suffice to clear δ if deployment were
as quiet as the instrument. 1,024 decisions tolerates a deployed standard
deviation **4.4x** C2's before the one-sided bound stops clearing. The extra cost
of that margin is under an hour, and a campaign that cannot distinguish "no
effect" from "too noisy to tell" is worth nothing.

**Initial score states are drawn from the match-visit distribution**, not fixed
at 0-0. This is the single thing the design exists to add, so it is not optional
and not a variant: a result at 0-0 has already been obtained and re-obtaining it
would establish nothing. The draw is from the Phase 5A calibrated visit
distribution, and the realised distribution is reported.

Root seed `tuppi-c5-deployed-v1`, bootstrap seed `tuppi-c5-bootstrap-v1`, 5,000
replicates resampled **over base deals**, which are the independent unit.

## 4. Instrument gates — declared now, checked before any science is read

A failure voids the science rather than being reported alongside it.

> **I1 — identical teams cancel.** A block in which both teams are the reference
> must return paired utility of exactly 0.0. This is the duplicate design's own
> self-test; a non-zero value means the transformation or the pairing is wrong.
>
> **I2 — block completeness.** Every included base deal contributes all 8
> transformations. Partial blocks are excluded entirely, never averaged, and the
> count of exclusions is reported. `tuppi_eval.qualification` already enforces
> this and is used rather than reimplemented.
>
> **I3 — the scope is what it claims.** Across the whole campaign the candidate
> searched exactly the opening leads of the deals its team led, and no other
> decision. Counted, not asserted: expected 1,024, and any other number means the
> gate is not scoping what section 2 says it scopes.
>
> **I4 — no failure was silently absorbed.** Zero illegal actions, zero rollout
> failures, zero censored or truncated games. A campaign that repaired anything
> is void.
>
> **I5 — the score draw is real.** The realised initial-score distribution must
> place fewer than 40% of base deals at 0-0. If nearly everything lands at 0-0
> the campaign has re-run C2 with extra steps and may not be read as new.

## 5. Decision rule

The four-way rule of `tuppi_research.decisions.decide` on the equity endpoint at
δ = 0.001, with the equivalence branch checked first, applied to the
orientation-averaged per-deal equity difference over base-deal clusters.

**SCREENED_IN** if the one-sided 95% lower bound exceeds δ. **EQUIVALENT** if the
interval lies wholly within ±δ. **SCREENED_OUT** if the upper bound is below δ.
**INCONCLUSIVE** otherwise. A SCREENED_IN result licenses designing a match-endpoint
promotion campaign and nothing else.

## 6. Predicted outcome, recorded in advance

Four consecutive pre-registered predictions in this programme have been wrong —
C1's direction, C3's threshold location, C4's generalisation, and C2's ceiling —
and every one of the last three erred in the same direction: the effect was
larger or saturated later than I expected. These are recorded because the record
is the point, not because the run of errors has taught me the trick.

* **P1** — deployed gain positive and SCREENED_IN, in [+0.0008, +0.0018].
* **P2** — the deployed point estimate is **below** C2's +0.001538. C2 chooses
  among 13 arms with the full completion set available to the estimator; a
  deployed selector at W=128 pays sampling noise in its own choice. Recorded
  knowing my last three misses were all in the opposite direction.
* **P3** — the gain is **not** constant in score state: the per-deal equity gain
  is larger when the match is close to its target than at 0-0, because a deal
  point moves equity more when fewer deals remain.
* **P4** — all five instrument gates pass.

## 7. What this will not establish

Not a promotion claim. The endpoint is per-deal equity, the bank is a development
bank, and Phase 5A fixed promotion on orientation-averaged match win probability
over complementary pairs. SCREENED_IN here is a reason to design that campaign,
not a substitute for it.

Nothing about later tricks; C4 established the signal is opening-lead-specific
and this inherits that scope. Nothing about opponents other than the incumbent —
both arms continue with it, so this measures selection quality, not transfer or
opponent modelling. Nothing about W = 256, which is measured by C2 but not run
here. Nothing about the ten-second production requirement, which includes
showing, encoding, transfers and synchronisation under a watchdog, and which a
cold maximum on an idle host is a necessary condition for and not a measurement
of.
