# T4 results: the improvement transfers — within a family that is barely diverse

**Status: COMPLETE. Outcome: TRANSFERS, on a weak test.**

Pre-registration: [hypotheses_t4.md](hypotheses_t4.md), committed as `b80128e`
before `work/transfer/t4_transfer.py` existed, amended as `9950203` before the
run. Run 2026-09-12, 1,024 base deals per opponent, 65,536 deal executions,
136 s. Artifacts under `/Users/pyryouri/Developer/tuppi_t4_transfer_20260912/`.

## 1. Instrument gates — all four pass

| Gate | Result |
| --- | --- |
| **I1** identical teams cancel | **pass** — largest control magnitude 4.2e-17 |
| **I2** block completeness | **pass** — every base deal contributed all 8 transformations |
| **I3** the control replicates T2's V5 | **pass** — see below |
| **I5** the opponents actually differ | **pass** — after the section 9 amendment |

**I3 is the gate that earns the rest.** The control margin is **+0.006364**
[+0.005228, +0.007486], and T2's independently measured V5 positive control for
the two lead layers is **+0.00574** — inside the interval. A new instrument, a
new seed, a different harness, and the same number on the same quantity.

## 2. Result

| Opponent | Margin | 95% CI | Exposure | vs control |
| --- | ---: | --- | ---: | ---: |
| `partner_aware_v1` *(control)* | **+0.006364** | [+0.005228, +0.007486] | 11.07% | — |
| `legacy_heuristic_port_v1` | +0.005952 | [+0.004707, +0.007191] | 12.39% | 93.5% |
| `reactive_contract_legacy_show_v1` | +0.005385 | [+0.004164, +0.006637] | 12.19% | 84.6% |
| `reactive_contract_v1` | +0.005661 | [+0.004324, +0.007039] | 11.66% | 89.0% |

> **The incumbent's advantage over its predecessor holds against every opponent
> tested.** All three foreign margins are positive with intervals excluding zero,
> and every one overlaps the control's interval substantially. The verdict is
> `transfers` in all three cases.

Exposure — how often the incumbent and its predecessor disagree — is *higher*
against every foreign opponent (105-112% of the control), so the improvement
gets more opportunity to matter, not less. Composition is not concealing a drop.

**One thing not to overlook: all three point estimates sit below the control**,
at 93.5%, 89.0% and 84.6%. No single one is significantly lower, but three of
three in the same direction is a one-sided sign-test p of 0.125. That is not
evidence of degradation; it is a pattern consistent with a mild one, and it is
recorded here so that a later, sharper test knows to look for it rather than
rediscovering it.

## 3. Predicted outcome versus what happened

| | Prediction | Actual | |
| --- | --- | --- | --- |
| **P1** | I3 passes, control reproduces +0.00574 | +0.006364 contains it | **right** |
| **P2** | every foreign margin positive | all three, intervals excluding zero | **right** |
| **P3** | at least one foreign margin significantly below control | none | **wrong** |
| **P4** | where a margin falls, the verdict is composition | never fired | **vacuous** |
| **P5** | — | struck before the run | **void** |

P3 was the substantive prediction and it was wrong. I expected a long
improvement programme conducted entirely in self-play to have fitted itself to
its development opponent, and it had not — at least not detectably here.

That continues an unbroken run: five pre-registered predictions in this
programme have now gone the same way, with the measured phenomenon stronger or
more robust than I expected — C1's direction, C3's threshold, C4's
generalisation, C2's ceiling, and now the incumbent's robustness. The consistency
of the bias is worth more than any of the individual misses.

## 4. The result is real, and the test is weak

Both halves matter.

The margin is genuine: 1,024 base deals per opponent, the duplicate design's own
cancellation check passing, and the control anchored to a number measured
independently by a different instrument.

But section 9 recorded the bound before the run, and it stands: **no opponent in
this repository is more foreign to `partner_aware_v1` than the improvement under
test is.** The most divergent available policy differs from the predecessor on
8.7% of decisions; `partner_aware_lead_v2` differs on 10.1%. Four of the seven
Phase 4 profiles differ on under 1%, and two are byte-identical in play at 0-0.
The ladder's names imply far more variety than the ladder contains.

So T4 says: the improvement is not an artefact of one specific opponent's quirks.
It does **not** say the improvement survives an opponent drawn from outside this
family, because no such opponent exists here to test against.

## 5. What this does not establish

Nothing about human opponents, which is the case that matters most and the one
this repository cannot supply.

Nothing about score states: every deal started at 0-0, which is also why
`match_aware_v1` had to be removed from the set. A match-aware opponent is a
genuinely different opponent only where the score is not level, and that is a
separate experiment.

Nothing about promotion — the endpoint is per-deal equity on a development bank,
and Phase 5A fixed promotion on orientation-averaged match win probability over
complete complementary pairs.

Nothing that licenses a change to the incumbent. A transfer result adjusts the
confidence owed to existing numbers; it is not a candidate.
