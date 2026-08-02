# Calibration methodology and sample-size recalculation

Phase 5A's calibration run exists to estimate the quantities a *future*
experiment needs in order to be designed properly. It is not a promotion
measurement and cannot become one; see `docs/match/bank_lifecycle.md`.

## What was run

| | |
| --- | --- |
| Bank | `phase5a_calibration_v1`, role `calibration`, 512 streams |
| Pairs per comparison | 256 |
| Comparisons | four ladder steps plus the match-aware ablation |
| Safety cap | 512 (pilot-derived), never approached |
| Total complete matches | 2 560 legs across 1 280 pairs |
| Censored pairs | **0** |
| Failed pairs | **0** |
| Wall clock | 125 minutes at six workers |

Agents were frozen throughout. No profile was touched, and the behaviour digest
in `reports/phase5a/phase4_frozen_agents.json` proves it.

## Estimated quantities

### Match length

Pooled over 2 560 completed legs: minimum 2, median 23, mean 32.6, p90 70,
p95 97, p99 134, **maximum 227**. 27.1 % of legs exceed 40 deals. See
`docs/match/censoring.md` for how this fixes the safety cap.

Match length depends on the pairing. The decisive `reactive_contract_v1` versus
`legacy_heuristic_port_v1` comparison produced the shortest matches (median 20,
max 135); the near-identical `match_aware_v1` versus `partner_aware_v1` pairing
produced the longest (median 25, max 227). This is the expected direction: the
closer two policies are, the more often the rising score resets and the longer a
match runs.

### Paired variance and leg correlation

| Comparison | mean `D` | sd(`D`) | ties | leg correlation |
| --- | --- | --- | --- | --- |
| reactive vs legacy port | 0.793 | 0.406 | 20.7 % | −0.114 |
| counting vs reactive | 0.242 | 0.557 | 63.3 % | −0.343 |
| partner-aware vs counting | 0.113 | 0.442 | 79.3 % | −0.606 |
| match-aware vs partner-aware | −0.004 | 0.273 | 92.6 % | −0.851 |
| match-aware vs match-state-off | −0.004 | 0.273 | 92.6 % | −0.851 |

Two structural facts fall out of this table.

**The tie rate is the effective sample-size killer, and it is informative.** A
pair ties when the same seats win both legs, which means the deals decided the
match rather than the policies. The tie rate rises monotonically as the two
policies get closer, from 21 % for the widest gap to 93 % for the narrowest.

**Complementary-leg correlation measures how much deal luck the duplicate design
removed.** Near −1 means the deals dominated and the pair correctly scored zero;
near 0 means the policy decided the outcome. At −0.851, the match-aware
comparison is almost pure deal luck - which is another way of saying the two
policies rarely do anything different.

### Secondary behaviour

Resets per match average 11.3 for the closely-matched pairings and 7.5 for the
decisive one. RAMI is declared in 77 % of deals among the simple-showing agents
and 57 % when the legacy showing profile is present; roughly 22 % of RAMI
declarations are stolen. These are descriptive and cannot override a primary
result.

## Sample-size recalculation

For a target half-width `h` on mean `D_match` at 95 % confidence:

```text
n = (1.96 * sd(D) / h)^2
```

A half-width on the reported win probability is half the half-width on mean `D`,
because `p = (1 + mean D) / 2`.

Using the observed standard deviations:

| Comparison | sd(`D`) | n for ±0.02 on mean `D` (±0.01 on `p`) | n for ±0.05 (±0.025 on `p`) |
| --- | --- | --- | --- |
| reactive vs legacy port | 0.406 | 1 583 | 253 |
| counting vs reactive | 0.557 | 2 975 | 476 |
| partner-aware vs counting | 0.442 | 1 872 | 300 |
| match-aware vs partner-aware | 0.273 | 715 | 114 |

Read this honestly: **256 pairs resolves a large effect and cannot resolve a
small one.** The three lower ladder steps were resolved comfortably at 256
because their effects are large relative to their standard errors. Detecting a
one-percentage-point edge in match win probability would need roughly three
thousand pairs for the noisier comparisons - about five hours of wall clock at
the throughput measured here.

### The procedure for a new comparison

1. **Pilot.** Run 16 to 32 pairs at a generous safety cap.
2. **Cap.** Pool the completed leg lengths and call `calibrate_safety_cap`.
3. **Variance.** Take `sd(D)` from the pilot, or use 0.55 as a conservative
   prior - that is the largest value observed here and corresponds to a
   moderate tie rate.
4. **Size.** Choose the smallest effect worth detecting, convert it to a
   half-width, and apply `n = (1.96 * sd / h)^2`.
5. **Budget.** Multiply by the observed pair cost (about 5.9 s at six workers
   against these agents, longer for closer pairings) and decide whether the
   question is worth the compute.
6. **Commit the size before running.** The manifest fixes `pair_count`; growing
   a sample until a result appears is exactly what the bank roles exist to
   prevent.

Formal sequential testing remains deferred. The manifest records a fixed pair
count, and there are no interim looks.

## What this calibration does not license

- It is not a promotion result and does not designate a champion.
- It must not be re-used as a tuning target. A changed profile is a new agent
  identity and belongs to a later experiment on different fixtures.
- Its sample sizes are specific to the frozen Phase 4 agents. A search agent
  with different decisiveness will change both the match-length distribution and
  `sd(D)`, so both must be re-estimated in Phase 5B.
