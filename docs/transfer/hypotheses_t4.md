# T4: does the incumbent's improvement survive an opponent it was not developed against?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/transfer/t4_transfer.py` may deviate from this document. Committed before
that file is written, and this document may not revise itself after a result.

## 1. Why

Every measurement in this programme — C1 through C5, S1, S1b, T0 through T3 —
has the incumbent, or its predecessor, on **both** sides of the table. So
everything measured is "how well can I choose against an opponent that plays
exactly as I do". If `partner_aware_lead_v2` is partly fitted to
`partner_aware_v1`, every one of those numbers is optimistic and nothing
currently in the record would detect it.

The cross-play machinery for this already exists — `src/tuppi_eval/crossplay.py`,
a schema, a request manifest and a 66-cell matrix in
`reports/phase4/baseline_report.json`. It cannot answer the question: every cell
holds **8** independent base deals and the report states it "is descriptive
only", and the incumbent post-dates the matrix and is absent from it. This is a
run, not a build.

## 2. Estimand

For each opponent `X`, the **difference in differences**

```
margin(X) = E[ equity(partner_aware_lead_v2 vs X) ]
          - E[ equity(partner_aware_v1        vs X) ]
```

on identical deals under the canonical duplicate design, in per-deal
frozen-continuation match equity — the same units as C2 and C5, δ = 0.001.

Differencing is what makes the result interpretable. A harder opponent lowers
*both* terms, so opponent strength cancels to first order and a change in
`margin(X)` is a statement about the improvement rather than about X.

## 3. The opponent set

| `X` | Divergence from `partner_aware_v1` at 0-0 | Why it is in the set |
| --- | ---: | --- |
| `partner_aware_v1` | — | **The development opponent.** The control: `margin` here is the improvement as originally measured. |
| `legacy_heuristic_port_v1` | **8.7%** | A different lineage entirely — the ported legacy emulator, and the most divergent policy available. |
| `reactive_contract_legacy_show_v1` | **5.3%** | A different showing policy, which is live at every score. |
| `reactive_contract_v1` | **3.7%** | The base rung: different play, no public inference. |

Chosen on **measured** divergence rather than on what the profile names suggest.
See section 9 — the original set was amended because two of its members do not
play differently at all. A ladder of weaker versions of the same policy would
test strength rather than transfer, but a set of *identical* policies tests
nothing whatsoever, and that is what the names concealed.

## 4. Design

Canonical duplicate design: 8 transformed games per base deal, 4 rotations x 2
team assignments, cluster inference by base deal, identical teams cancelling to
within 1e-12 (see C5's amendment — the equity endpoint is a float lookup and
exact 0.0 belongs to the integer deal-points endpoint).

**N = 1,024 base deals per opponent**, both arms on the same deals, so 4 x 1,024
x 8 x 2 = **65,536 deal executions**. No search is involved — every policy here
is a heuristic costing microseconds — so this is minutes of engine time, not
hours. T2 executed 22,000 deals in 44.3 s on twelve workers.

N is sized from C5's measured deployed dispersion of **0.0146** per base deal,
not from an estimator's dispersion. That was C5's error and it cost that campaign
its conclusion. A difference of two paired margins has roughly twice the variance,
so take 0.021: detecting a margin shortfall of 0.002 needs SE < 0.00102, hence
about 425 base deals. 1,024 carries a factor of 2.4 in standard deviation over
that, and costs nothing.

Root seed `tuppi-t4-transfer-v1`, bootstrap seed `tuppi-t4-bootstrap-v1`, 5,000
replicates resampled over base deals.

## 5. The discriminator: exposure, not just effect

A drop in `margin(X)` has two explanations that a margin alone cannot separate:

* **transfer failure** — the improvement is worth less against X;
* **composition** — X changes how often the improvement's conditions arise at
  all, so it has less opportunity to matter.

They are distinguished by measuring the mechanism's **exposure**: the
**action-divergence rate**, the fraction of decisions on which
`partner_aware_lead_v2` and `partner_aware_v1` choose differently from the same
observation. This is recorded per opponent alongside the margin.

> **Transfer failure** — `margin(X)` is significantly below `margin(control)`
> while the divergence rate is within 20% of the control's.
>
> **Composition** — `margin(X)` and the divergence rate fall together, the margin
> per unit of divergence being within 20% of the control's.
>
> **Ambiguous** — anything else, reported as ambiguous and not resolved by
> argument after the fact.

This is the question the design exists to answer and it is fixed here because,
after a result, either story fits any number.

## 6. Instrument gates — declared now, checked before any science is read

> **I1 — identical teams cancel.** Reference-versus-reference blocks return
> paired utility within 1e-12 of 0.0; the largest magnitude is reported.
>
> **I2 — block completeness.** Every included base deal contributes all 8
> transformations; partial blocks are excluded entirely and counted.
>
> **I3 — the control replicates T2.** `margin(partner_aware_v1)` must have a 95%
> interval containing **+0.00574**, T2's V5 positive control for removing both
> lead layers. A new instrument that cannot reproduce a measured number on the
> same quantity is not measuring that quantity, and nothing else in the run may
> be read.
>
> **I4 — no failure absorbed.** Zero illegal actions, zero censored or truncated
> deals.
>
> **I5 — the opponents actually differ.** Each foreign opponent must produce a
> contract mix or an action-divergence rate distinguishable from the control's.
> An "opponent" that plays identically to the control is not a transfer test.

## 7. Predicted outcome, recorded in advance

Four consecutive pre-registered predictions here have been wrong — C1's
direction, C3's threshold, C4's generalisation, C2's ceiling — and the last three
all erred the same way, with the effect larger or later-saturating than expected.
C5's P1 was wrong too. That is a poor record and these are recorded because the
record is the point.

* **P1** — I3 passes: the control margin reproduces +0.00574.
* **P2** — every foreign margin is positive. The lead layers are structural
  heuristics about card play, not opponent models, so they should not invert.
* **P3** — at least one foreign margin is **significantly below** the control's.
  Some fitting to the development opponent is likely after a long improvement
  programme conducted entirely in self-play.
* **P4** — where a margin falls, the verdict is **composition** rather than
  transfer failure, because the mechanism is structural.
* **P5** — *void.* It named `partner_aware_legacy_convention_v1`, which the
  section 9 amendment removed from the set. It is struck rather than rewritten:
  a prediction whose subject no longer exists cannot be scored, and replacing it
  with a fresh one after seeing the divergence table would be writing a
  prediction with the answer already in hand.

## 8. What this will not establish

Nothing about human opponents. Every opponent here is a frozen heuristic from
this repository, and a policy that transfers across four of them may still fail
against a person. This bounds self-play overfitting within the family; it does
not measure it outside.

Nothing about promotion. The endpoint is per-deal equity on a development bank,
and Phase 5A fixed promotion on orientation-averaged match win probability over
complete complementary pairs.

Nothing about cardplay search — no PIMC runs here. Nothing about the showing
phase in isolation. And nothing that licenses a change to the incumbent: a
transfer result is a statement about the confidence owed to existing numbers,
not a candidate.


## 9. Amendment, made before any science was collected

The opponent set was chosen from what the profile names imply. Measured against
what the profiles actually *do*, two of the three foreign opponents were not
opponents at all. Divergence from `partner_aware_v1` over 435 decisions at score
0-0:

| policy | divergence |
| --- | ---: |
| `partner_aware_lead_v2` *(the incumbent itself)* | 10.1% |
| `legacy_heuristic_port_v1` | 8.7% |
| `reactive_contract_legacy_show_v1` | 5.3% |
| `reactive_contract_v1` | 3.7% |
| `partner_aware_legacy_convention_v1` | **0.9%** |
| `public_counting_v1` | **0.2%** |
| `match_aware_v1` | **0.0%** |
| `match_aware_no_match_features_v1` | **0.0%** |

`match_aware_v1` agrees with `partner_aware_v1` on **100.0%** of decisions here,
because its match-state features are inert at 0-0 — a match-aware policy has
nothing to be aware of when the score is level. It is the same policy under this
design. `partner_aware_legacy_convention_v1`, the "different convention" that
section 3 called the sharpest test, differs on 0.9% of decisions.

Gate I5 was written for exactly this and it fired on the smoke test, before any
science run: the margin and exposure against `match_aware_v1` matched the
control to six decimal places. The set is amended to the three policies that
measurably play differently.

**This bounds the experiment, and the bound is worth stating plainly.** The most
divergent opponent available differs from the predecessor on 8.7% of decisions,
while the incumbent differs from it on 10.1%. So no opponent in this repository
is *more* different from the development opponent than the improvement under
test is. Whatever T4 finds, it is a weak test of transfer — the strongest
available inside this family, and no substitute for an opponent from outside it.

An alternative fix was available and rejected: varying the score state would make
`match_aware_v1` genuinely distinct. It is rejected because gate I3 replicates
T2's +0.00574, which was measured at 0-0, and changing the score distribution
would put the run's only anchor to a known number at risk. Score variation is a
separate experiment, not a repair to this one.
