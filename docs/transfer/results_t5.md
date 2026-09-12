# T5 results: the margin collapses against rigid opponents — but not against the most foreign one

**Status: COMPLETE. Outcome: TRANSFER_DEGRADES by the pre-registered rule, with a
pattern neither branch of that rule anticipated.**

Pre-registration: [hypotheses_t5.md](hypotheses_t5.md), committed as `5b77e42`
before `work/transfer/t5_range.py` existed. Run 2026-09-12, 1,024 base deals per
opponent, 131,072 deal executions, 219 s. Artifacts under
`/Users/pyryouri/Developer/tuppi_t5_range_20260912/`.

## 1. Instrument gates — all five pass

| Gate | Result |
| --- | --- |
| **I1** identical teams cancel | **pass** — largest magnitude 6.9e-17 |
| **I2** block completeness | **pass** |
| **I3** control replicates T2's V5 | **pass** — +0.005634 [+0.004530, +0.006765] contains +0.00574 |
| **I4** T4's peer margins replicate | **pass** — all three intervals overlap T4's |
| **I5** the divergence range is real | **pass** — 3.7% to 61.5% |

I4 matters as much as I3. A fresh seed, a changed opponent list and a different
instrument reproduce T4's three peer margins, so the two runs are measuring the
same quantity.

## 2. Result

| Opponent | Divergence | Margin | 95% CI | vs control | Overlaps control |
| --- | ---: | ---: | --- | ---: | --- |
| `partner_aware_v1` *(control)* | — | +0.005634 | [+0.004530, +0.006765] | — | — |
| `reactive_contract_v1` | 3.7% | +0.005647 | [+0.004254, +0.007039] | 100.2% | yes |
| `reactive_contract_legacy_show_v1` | 5.3% | +0.006741 | [+0.005470, +0.008026] | 119.7% | yes |
| `legacy_heuristic_port_v1` | 8.7% | +0.006003 | [+0.004748, +0.007246] | 106.6% | yes |
| `lowest_legal_card` | 45.2% | +0.002404 | [+0.001340, +0.003501] | **42.7%** | **no** |
| `first_legal` | 55.7% | +0.002065 | [+0.001083, +0.003056] | **36.7%** | **no** |
| `highest_legal_card` | 59.3% | +0.001617 | [+0.000581, +0.002677] | **28.7%** | **no** |
| `seeded_random_legal` | 61.5% | +0.004943 | [+0.002614, +0.007198] | 87.7% | yes |

> **Against three genuinely foreign opponents the improvement retains only 29-43%
> of its home margin, on intervals disjoint from the control's.** This is the
> first evidence in the programme that a measured improvement is partly specific
> to the kind of opponent it was developed against.
>
> **It never inverts.** All eight margins are positive with intervals excluding
> zero. The improvement is worth less against alien play, not harmful.

## 3. The pattern is not the one the rule was built to find

The pre-registered rule returns **TRANSFER_DEGRADES**: the foreign mean
(+0.002757) is below the control, and margin is not ordered by strength among
the foreign group (Spearman +0.200, against the |rho| >= 0.8 tie-break). That is
the correct verdict by its own terms and it stands.

But the rule offered two explanations — saturation or foreignness — and the data
fit **neither**:

* It is not **saturation**, because margin does not fall with opponent weakness.
  The weakest opponent measured, `seeded_random_legal` at strength +0.0659, has
  the *highest* foreign margin.
* It is not **foreignness**, because `seeded_random_legal` is also the *most*
  divergent opponent at 61.5%, and its margin overlaps the control's.

What separates them is **rigidity**:

| group | mean margin | share of control |
| --- | ---: | ---: |
| three **deterministic** degenerate controls | +0.002028 | **36.0%** |
| the one **stochastic** control | +0.004943 | **87.7%** |

The three opponents that compress the margin all play a fixed rule — always the
first, highest or lowest legal card. The one that does not compress it plays at
random. A plausible reading is that a rigid opponent collapses the position space
the lead layers exploit, so there is less for a better lead to win; a random
opponent keeps that space open. **This is a hypothesis generated after seeing the
data and is recorded as such.** It is not tested here and must not be quoted as
though it were.

## 4. Predicted outcome versus what happened

| | Prediction | Actual | |
| --- | --- | --- | --- |
| **P1** | I3 and I4 pass | both pass | **right** |
| **P2** | every margin positive | all eight, intervals excluding zero | **right** |
| **P3** | foreign mean below the control | +0.002757 vs +0.005634 | **right** |
| **P4** | the verdict is SATURATION | TRANSFER_DEGRADES | **wrong** |
| **P5** | the most divergent opponent does not have the lowest margin | it has the highest foreign margin | **right** |

Four of five. That ends a run of five consecutive pre-registrations whose
substantive prediction was wrong, and the one miss is instructive: I predicted
the *phenomenon* correctly and its *mechanism* wrongly. I expected the
compression and attributed it to a ceiling effect; it is not a ceiling effect,
and the alternative I named was not right either.

## 5. What this changes

**T4's conclusion needs qualifying, not retracting.** T4 measured transfer across
opponents spanning 0.9-8.7% divergence and found it held. That remains true and
is replicated here. What T4 could not see is that the ladder it drew from is
homogeneous: extend the range sevenfold and a third of the margin survives
against rigid opponents.

**The confidence owed to every self-play number in this record is lower than it
was.** Every measurement in this programme — C1 through C5, S1, T0-T3, T4 — was
taken against opponents from the 0.9-8.7% band. T5 says that band is where the
improvement looks best.

## 6. What this does not establish

Nothing about human opponents, and the gap is wide. A control that always plays
the highest legal card is rigid in a way no person is, and a person playing badly
is not playing a fixed rule. That the margin compresses against `first_legal` is
not evidence it compresses against a weak human, and the rigidity hypothesis in
section 3 would if anything predict the opposite for a human, who is variable.

Nothing about the mechanism, per section 3.

Nothing at non-zero score states; every deal started at 0-0.

Nothing about promotion, and nothing that licenses a change to the incumbent. The
improvement remains positive against every opponent measured.
