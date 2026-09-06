# N09 — Test one frozen research candidate on paired NOLO deals

Status: WAITING_GATE. Requires N08 PASS and G1 adoption/waiver. This task is
prospective; **no trial has been run while creating this queue**. It measures
forced-NOLO deal play at the table, not whole-match strength or human-opponent
performance. Do not reopen historical trials or use their sealed banks.

## Lock the run before generating its outcomes

Write a versioned preregistration under `docs/nolo/` referencing the frozen
candidate code/configuration, these endpoints, seeds and analysis. Create a
research runner mode, `tests/nolo/test_paired_validation.py`, and final
`docs/nolo/results/N09.md`. No production source changes.

Use **512 independent base deals**, root seed `nolo-info-strength-v1`, indices
0–511, initial score `(0,0)`, initial dealer 0 and round-robin dealer policy.
Force identical canonical NOLO showing in every arm. Let B be v2 and C the
frozen candidate. Play these four seat assignments on every identical deal:

| Arm | Team 0 | Team 1 |
| --- | --- | --- |
| BB | B | B |
| CB | C | B |
| BC | B | C |
| CC | C | C |

Both seats of a team use its named policy. Construct fresh agents per arm/deal;
no certificate cache may leak between arms. Play all 13 tricks. Failed arms are
not silently substituted or removed. Use a 4-hour total run cap and preserve
the complete/incomplete block counts. If the cap prevents completion, the result
is INCONCLUSIVE, not an evaluation of a selected completed subset.

## Primary effects and analysis

Fix **Team 0** as the predeclared target for the two primary contrasts. For each
base deal i, with T denoting its Team-0 trick total:

```
D_B[i] = T_BB[i] - T_CB[i]   # candidate improvement versus baseline opponents
D_C[i] = T_BC[i] - T_CC[i]   # replacement benefit when opponents also use candidate
```

Positive means fewer tricks with C. Form analogous paired binary deal-win
differences for Team 0. Use `paired_value_summary` with one finite value per base
deal, confidence level 0.95, analysis seed `nolo-info-strength-analysis-v1`,
5,000 bootstrap and 5,000 permutation replicates. Use the returned
`bootstrap_confidence_interval` for the declared confidence-bound tests; do not
choose whichever interval or test looks better. Include the exact command and
parameters in the report.

The two contrasts share deals and arms and are not independent replications.
Report Team-1 mirrored effects as secondary orientation diagnostics, separately.
Do not pool complementary team contrasts and call that extra evidence:
zero-sum trick conservation can make such pooled comparisons algebraically
identical. Do not treat individual seats, 13 tricks, or multiple score projections
as additional independent observations.

## Clear decision endpoints

All of the following are required for **SUPPORTED: forced-NOLO deal improvement**:

1. All 512 four-arm blocks complete, with zero illegal actions, information leaks,
   invalid certificates or broken continuation commitments.
2. For **both** D_B and D_C: mean improvement at least **0.05 tricks per deal**
   and lower 95% bootstrap confidence bound strictly greater than zero.
3. For both corresponding deal-win differences: point estimate at least zero
   and lower 95% bootstrap confidence bound at least **−0.02** (a predeclared
   2-percentage-point noninferiority margin).
4. No unreported configuration/seed change, post-outcome case exclusion, or
   extra candidate selection. Record fallback, commitment and latency counts.

The 0.05-trick and 2-point thresholds are proposed practical acceptance choices,
not historical findings or a claim that 512 deals provides high statistical
power. Fix them before the run. Passing gives the bounded claim stated above;
it does not establish improved match equity at other scores.

**HARM DETECTED:** a primary trick-effect upper 95% bound is below zero, or a
deal-win upper bound is below −0.02. **INCONCLUSIVE/NOT ESTABLISHED:** sound,
complete trial that does not meet all positive endpoints and does not clearly
establish harm. A tiny favourable mean with a crossing interval is inconclusive.
Any correctness violation is **INVALID**, regardless of its win rate.

Do not extend N until significance or try another seed. A follow-up trial needs
a new preregistration with a justified size and scope. The task is complete when
its fixed results and limitations are recorded, including a negative result.

Harness tests must establish signs with simple hand-built paired totals, zero
effect when C delegates everywhere, correct four-arm pairing, and explicit
incomplete-block handling. Production adoption, different score states and
whole-match validation remain separate later decisions.
