# C4: does the opening-lead signal generalise to later decisions?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/cardplay/c4_depth.py` may deviate from this document. C2, the corrected
headroom bound, remains reserved for its own pre-registration.

## 1. Why this and not C2

C2 was next on my own list and C3's result demoted it. For any selector,
`G_deploy(W) <= G_legal`, and C3 put `G_deploy(64)`'s lower bound at **+0.001226**,
above δ = 0.001. So the ceiling is already known to exceed δ and **C2 cannot
produce a kill** — it can only size the remaining gap. That is worth knowing and
it is not the sharpest question available.

The sharpest question is that C3 measured **one decision out of roughly
twenty-six**, and the one with the most open action space and no play history at
all. If the opening lead is special, the result does not extend and the branch is
much narrower than it looks. If it extends, the aggregate is much larger.

## 2. Estimand

`G_deploy(64)` — the deployment-normalised gain of a 64-world sampling selector,
exactly as fixed in [hypotheses_c3.md](hypotheses_c3.md) — at four decision
depths for the **same seat within the same deal**:

```
cards_left in {12, 9, 6, 3}
```

`cards_left = 12` is C3's opening lead and serves as the within-run replication
anchor. The evaluated seat is the deal's opening leader, followed through the
deal, so the four decisions are paired within a deal and depth comparisons are
paired.

Endpoint, δ = 0.001, deployment normalisation and the frozen reference
continuation are as in C1/C3.

## 3. Conditioning — the validated sampler, not a hand-rolled dealer

C1 and C3 pinned shown cards and dealt the rest by hand. That is adequate before
any card is played and **wrong afterwards**: a seat that failed to follow suit is
void, and ignoring that samples impossible worlds.

C4 therefore uses `tuppi_exact.UniformFeasibleSampler.for_observation`, which
carries played cards, void suits, show exclusions, capacities and Hall
feasibility, and whose hard ownership exclusions the T0–T3 audit checked against
202,800 true deals with zero violations. Measured: 0.3 ms to build, 11 ms for 64
draws, at every depth.

**Reconstruction.** A sampled assignment gives what each seat still *holds*. The
public history gives what each seat has *played*. The initial thirteen-card hand
is the union, and the deal is replayed from the start through the recorded show
and play sequence to reach the same decision point. Pricing therefore costs a
full deal at every depth, so deeper decisions are cheaper only through having
fewer arms, not through shorter rollouts.

## 4. Design

- **N = 256 observations** (deals). Half of C3's, because each deal now carries
  four decisions with 13 + 10 + 7 + 4 ≈ 34 arms in total; ~1.11M rollouts, of the
  same order as C3's 850k.
- **M = 128 sampled worlds** per decision, choose on `[0:64]`, score on `[64:128]`,
  averaged with the mirrored split — identical to C3 at W = 64.
- Root seed `tuppi-c4-depth-v1`, bootstrap `tuppi-c4-bootstrap-v1`, 5,000
  replicates over observations.
- A decision is **skipped and recorded as skipped** if it has fewer than two legal
  actions, or if the sampler reports fewer than 128 feasible assignments (worlds
  would then repeat and the choose/score split would not be independent).

## 5. Instrument gates — checked before any science is read

> **I1 — bounded by foresight.** `G_deploy <= G_foresight` at every depth, on
> point estimates.
>
> **I2 — replication at the anchor.** `G_deploy` at `cards_left = 12` must have an
> interval overlapping C3's [+0.001226, +0.001717]. This depth is the same
> estimand C3 measured, on a fresh seed and through a different sampler. Failure
> means the sampler swap or the reconstruction changed the measurement, and the
> depth comparison would then be meaningless.
>
> **I3 — feasible-world sufficiency.** Every included decision must report at
> least 128 feasible assignments, and the count must be recorded.

A failure of I1 or I2 voids the science. I2 is the gate that matters: it is the
first time this sequence has had an independent replication target to check a new
instrument against, and it exists because C3's sampler is being replaced.

## 6. Science gates

> For each depth, does `G_deploy(64)`'s lower bound exceed δ = 0.001?
>
> **GENERALISES** if at least one depth other than 12 clears δ.
> **OPENING-LEAD-SPECIFIC** if only depth 12 clears δ.
> **INCONCLUSIVE** if depth 12 itself fails to clear, which would contradict C3
> and put the instrument rather than the science in question.

Reported alongside: the paired per-deal difference between each depth and depth
12, so "the gain shrinks with depth" is measured rather than eyeballed.

**No aggregate across depths will be reported.** E6 established that
per-decision counterfactuals are not additive — fixing one decision changes the
position facing the next — so summing four depths would repeat that error. Any
statement about a whole-deal gain requires a selector run at every decision, which
this is not.

## 7. Predicted outcome, recorded in advance

The gain **falls with depth**, clearing δ at 12 and 9 and not at 6 or 3, on the
reasoning that later positions have fewer arms, tighter feasible-world sets and
less room for a lead choice to matter. Verdict GENERALISES.

My last two predictions were wrong — C1's direction and C3's threshold location —
so this is recorded with low confidence and with the same purpose: so that a
surprise is visible as one.

## 8. What this will not establish

Nothing about a whole-deal or per-match gain, for the non-additivity reason in §6.
Nothing about non-zero scores, transfer beyond the frozen reference, or
opponent-model play. Nothing about production cost beyond what C3 measured for the
opening lead; deeper decisions have fewer arms and therefore cost less, but the
watchdog and load questions remain untouched. And no candidate is licensed.
