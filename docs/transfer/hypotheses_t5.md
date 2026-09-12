# T5: does the improvement survive a genuinely foreign opponent, or only a familiar one?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/transfer/t5_range.py` may deviate from this document. Committed before that
file is written, and this document may not revise itself after a result.

## 1. Why

T4 measured the incumbent's margin over its predecessor against three foreign
opponents and found it held: 93.5%, 89.0% and 84.6% of the control margin, every
interval overlapping. But T4's opponent set spanned only **0.9% to 8.7%** action
divergence from the predecessor, while the improvement under test itself diverges
by **10.1%**. No opponent was more foreign than the change being measured, so the
result was recorded as a weak test.

T4's results also claimed no more foreign opponent existed in the repository.
That was **false**, and corrected in `5354737`: the Phase 3 controls diverge by
**45.2% to 61.5%** — roughly seven times the ladder's maximum. T5 uses them.

## 2. Estimand

Unchanged from T4: for each opponent `X`,

```
margin(X) = E[ equity(partner_aware_lead_v2 vs X) ]
          - E[ equity(partner_aware_v1        vs X) ]
```

on identical deals under the canonical duplicate design, per-deal
frozen-continuation match equity, δ = 0.001, every deal from 0-0.

## 3. The confound this design exists to handle

The controls are not merely foreign, they are **weak**. Against `first_legal` the
candidate partnership wins nearly every deal, so equity may **saturate** and
compress the margin for reasons that have nothing to do with transfer.
Difference-in-differences does not remove this: saturation is a nonlinearity, not
an additive strength effect, and T4's cancellation argument does not cover it.

The opponents therefore vary on **two axes**, and the design's whole purpose is
to separate them:

* **divergence** — how differently `X` plays from the predecessor, measured as
  action-divergence over a fixed decision set;
* **strength** — how much the predecessor beats `X` by, which is
  `E[equity(partner_aware_v1 vs X)]` and is already computed as the second term
  of every margin, at no extra cost.

The four Phase 3 controls supply the leverage: they sit in a narrow divergence
band (45-62%) while differing in strength. So **strength varies at roughly
constant divergence**, which is exactly the contrast that identifies saturation.

## 4. Opponent set

| `X` | Group | Divergence from `partner_aware_v1` |
| --- | --- | ---: |
| `partner_aware_v1` | control | — |
| `reactive_contract_v1` | peer | 3.7% |
| `reactive_contract_legacy_show_v1` | peer | 5.3% |
| `legacy_heuristic_port_v1` | peer | 8.7% |
| `lowest_legal_card` | foreign | 45.2% |
| `first_legal` | foreign | 55.7% |
| `highest_legal_card` | foreign | 59.3% |
| `seeded_random_legal` | foreign | 61.5% |

`show_selection_nolo_low` is excluded: it is a showing-phase control and would
confound the trick-play comparison with a showing difference.

## 5. Design

Canonical duplicate design, 8 transformations per base deal, cluster inference by
base deal, identical teams cancelling to within 1e-12. **N = 1,024 base deals per
opponent**, both arms on the same deals: 8 x 1,024 x 8 x 2 = **131,072 deal
executions**. No search; T4 executed 65,536 in 136 s.

Root seed `tuppi-t5-range-v1`, bootstrap seed `tuppi-t5-bootstrap-v1`, 5,000
replicates over base deals. The seeded random control takes policy seed
`tuppi-t5-opponent-v1`, fixed here so it is not chosen after seeing a result.

## 6. Decision rule, fixed before the numbers

Let `peer` be the mean margin over the three peer opponents and `foreign` the
mean over the four controls.

> **ROBUST_TRANSFER** — every opponent's margin interval overlaps the control
> margin's interval. The improvement is not opponent-specific at any divergence
> measured.
>
> **SATURATION** — `foreign` is below the control margin, **and** among the four
> foreign opponents margin is ordered by strength (Spearman |rho| >= 0.8 against
> strength) rather than by divergence. The compression is a ceiling artefact.
>
> **TRANSFER_DEGRADES** — `foreign` is below the control margin, **and** margin
> among the four foreign opponents is *flat* in strength (Spearman |rho| < 0.8),
> so the drop tracks foreignness rather than weakness.
>
> **AMBIGUOUS** — anything else, reported as ambiguous and not argued into one of
> the above after the fact.

With four foreign points a Spearman coefficient is a weak instrument, and that is
stated now rather than discovered later: |rho| >= 0.8 on n = 4 is not
significance, it is a declared tie-break between two pre-named explanations.

## 7. Instrument gates

> **I1 — identical teams cancel** to within 1e-12; largest magnitude reported.
>
> **I2 — block completeness.** Every base deal contributes all 8 transformations.
>
> **I3 — the control replicates T2's V5.** `margin(partner_aware_v1)` must have a
> 95% interval containing **+0.00574**. Same anchor as T4.
>
> **I4 — T4 replicates.** The three peer margins must each have an interval
> overlapping T4's for that opponent. A fresh seed and a changed opponent list
> must not move a measured margin.
>
> **I5 — the range is real.** Minimum opponent divergence below 10% and maximum
> above 40%, or T5 has not done the thing it exists to do.

## 8. Predicted outcome, recorded in advance

Five consecutive pre-registered predictions here have been wrong, every one in
the same direction: the measured phenomenon was stronger or more robust than I
expected.

* **P1** — I3 and I4 pass.
* **P2** — every margin is positive.
* **P3** — `foreign` is below the control margin. Saturation is a mechanical
  effect and I expect it to be visible.
* **P4** — the verdict is **SATURATION**, not TRANSFER_DEGRADES.
* **P5** — `seeded_random_legal`, the most divergent opponent, does **not** have
  the lowest margin. If foreignness drove the compression it should; I predict
  strength drives it instead.

## 9. What this will not establish

Nothing about human opponents. A control that plays the first legal card is
foreign in a way no person is, and being robust against it is not evidence of
being robust against a person playing badly *on purpose*.

Nothing at non-zero score states; every deal starts at 0-0, which is also why
`match_aware_v1` remains excluded.

Nothing about promotion — per-deal equity on a development bank is not Phase 5A's
match-win endpoint. And nothing that licenses a change to the incumbent: this
adjusts the confidence owed to existing numbers.
