# T6: is it rigidity, and not foreignness, that collapses the margin?

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/transfer/t6_rigidity.py` may deviate from this document. Committed before
that file is written, and this document may not revise itself after a result.

## 1. Why, and the status of the hypothesis being tested

T5 found the incumbent's margin over its predecessor retains only 29-43% of its
home value against three foreign opponents, on disjoint intervals — but 87.7%
against a fourth that is *more* divergent still. The three that compressed it all
play a fixed rule; the one that did not plays at random.

The reading offered was **rigidity**: a deterministic opponent collapses the
position space the lead layers exploit, while a random one keeps it open. That
reading was generated after seeing the data and T5 recorded it as untested. This
experiment tests it.

Two weaknesses in the evidence it rests on, stated now:

* it is **one point**. `seeded_random_legal` is a single opponent, and its
  interval is the widest in T5 (±0.0023 against ±0.001 elsewhere), because a
  random opponent adds variance;
* **rigidity and strength are confounded** in T5. The stochastic opponent is also
  the weakest (strength +0.0659 against +0.0378 to +0.0491).

## 2. The design turns that confound into the discriminator

Construct a family of opponents that interpolates continuously between rigid and
random: with probability `epsilon` play a uniformly random legal action,
otherwise play `first_legal`. Sweep

```
epsilon in {0.00, 0.25, 0.50, 0.75, 1.00}
```

Along this sweep the opponent becomes **less rigid** and **weaker** at the same
time. That is precisely what makes it decisive, because the two live hypotheses
predict **opposite signs**:

| hypothesis | prediction along increasing `epsilon` |
| --- | --- |
| **rigidity** | margin **rises** — the position space reopens |
| **saturation** | margin **falls** — the opponent is weaker, so equity ceilings bite harder |

A single monotone sweep separates them. No regression over confounded opponents
is needed, and none is used.

`first_legal` is the base because it sits mid-range among T5's rigid controls
(55.7% divergence, 36.7% of control margin) rather than at either extreme.

## 3. The opponent's randomness is keyed to the position, not to a stream

The random choice is a deterministic function of `(seed, deal index, epsilon,
seat, completed tricks, cards in the current trick)` rather than draws from a
running stream.

This matters and is not a detail. The incumbent arm and the predecessor arm
diverge during the deal, so a stream-based opponent would desynchronise and
behave differently in the same position across arms, adding variance to the very
difference being measured. Position-keyed randomness gives both arms the same
opponent behaviour in the same position — common random numbers — and the
opponent remains reproducible from the seed.

## 4. Design

Canonical duplicate design, 8 transformations per base deal, cluster inference by
base deal, identical teams cancelling to within 1e-12. **N = 1,024 base deals per
epsilon**, both arms on the same deals, plus the `partner_aware_v1` control arm
for the anchor: 6 x 1,024 x 8 x 2 = **98,304 deal executions**. T5 ran 131,072 in
219 s.

Root seed `tuppi-t6-rigidity-v1`, opponent seed `tuppi-t6-opponent-v1`, bootstrap
seed `tuppi-t6-bootstrap-v1`, 5,000 replicates over base deals. All deals from
0-0, as in T4 and T5.

## 5. Decision rule, fixed before the numbers

Let `rho` be the Spearman correlation between `epsilon` and margin over the five
sweep points.

> **RIGIDITY_SUPPORTED** — `rho >= +0.9` and the margin at `epsilon = 1.00` is
> significantly above the margin at `epsilon = 0.00` (disjoint 95% intervals).
>
> **SATURATION_SUPPORTED** — `rho <= -0.9` and the margin at `epsilon = 1.00` is
> significantly *below* that at `epsilon = 0.00`.
>
> **NEITHER** — the two endpoint intervals overlap. T5's contrast was then a
> single noisy point and the rigidity reading should be withdrawn.
>
> **AMBIGUOUS** — endpoints differ but the sweep is not monotone.

Five points give a Spearman of exactly ±1.0 for any monotone sequence, so the
`0.9` threshold is a monotonicity requirement, not a significance claim. The
endpoint contrast carries the statistical weight. Both are stated here so neither
is chosen afterwards.

## 6. Instrument gates

> **I1 — identical teams cancel** to within 1e-12.
>
> **I2 — block completeness.** Every base deal contributes all 8 transformations.
>
> **I3 — the control replicates T2's V5.** `margin(partner_aware_v1)` must have a
> 95% interval containing +0.00574. The same anchor as T4 and T5.
>
> **I4 — the rigid endpoint replicates T5.** `epsilon = 0.00` *is* `first_legal`,
> so its margin interval must overlap T5's [+0.001083, +0.003056]. A different
> harness must not move a measured margin.
>
> **I5 — the sweep does what it claims.** Opponent strength must increase
> monotonically with `epsilon`; if it does not, the mixture is not weakening the
> opponent and the discriminator in section 2 does not hold.

## 7. Predicted outcome, recorded in advance

The hypothesis under test is mine and was formed after seeing T5, which is the
weakest position a prediction can be made from.

* **P1** — the verdict is **RIGIDITY_SUPPORTED**.
* **P2** — I3 and I4 pass.
* **P3** — the margin at `epsilon = 1.00` reaches at least 70% of the
  `partner_aware_v1` control margin, mirroring T5's 87.7%.
* **P4** — the rise is **not** linear in `epsilon`: most of the recovery happens
  by `epsilon = 0.50`, because a little unpredictability should reopen the
  position space faster than proportionally.

## 8. What this will not establish

Nothing about human opponents. A mixture of `first_legal` and uniform noise is
not a model of a person, and neither endpoint resembles one.

Nothing about *why* rigidity would matter, if it does. Confirming the direction
does not identify the mechanism, and a confirmed direction with an unexamined
mechanism is exactly the kind of result this programme has learned to distrust.

Nothing at non-zero score states. Nothing about promotion. And nothing that
licenses a change to the incumbent.
