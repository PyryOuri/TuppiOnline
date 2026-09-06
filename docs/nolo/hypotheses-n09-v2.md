# Preregistration v2 — N09 paired forced-NOLO validation

**Written before any deal of the v2 run was played, and before any effect
estimate from any run was computed.** Supersedes
[`hypotheses-n09-v1.md`](hypotheses-n09-v1.md), which is preserved unchanged.
Date: 2026-09-06.

## Why there is a v2, and what it does not change

The v1 run was **abandoned on wall-clock grounds after 90 of 512 blocks** and its
analysis was never computed. Its records are preserved, unanalysed, in
`work/nolo/n09/trial-v1-abandoned/`. No value from them enters this run or its
report except the timing figure quoted below.

The cause was a sizing error, and it is mine: the v1 cap of four hours was
justified from a pilot of six development deals measuring 245 CPU-seconds per
four-arm block. The real bank runs at about **490 CPU-seconds per block**, so 512
blocks need roughly five hours across 14 workers and could not have finished
inside four. Letting the run continue would have produced INCONCLUSIVE on
compute alone, which is not an evaluation of anything.

**The only parameter that changes is the wall-clock cap: 4 hours becomes 8.** The
bank, the seed, the arms, the candidate, the effect definitions, the analysis
parameters and every decision threshold are byte-identical to v1. A cap is a
resource guard, not an analysis parameter, and raising it cannot move an estimate
in a favourable direction — it can only decide whether an estimate exists at all.

**Disclosure of what was observed before this was written.** While monitoring
progress I looked at two aggregate counts from the partial v1 bank: 2 of 90
blocks showed any difference in Team-0 tricks between arms, and 10 corrections
had been made. No trick difference, deal-win difference, mean, interval or test
statistic was computed for any contrast, and nothing in this document could be
tuned by those counts, since no threshold, seed or definition is free to move.
It is recorded here because a reader is entitled to know what the author had
seen. **The v2 run starts from scratch on the full 512-block bank**; the partial
v1 records are not reused, pooled or substituted.

## Everything else, restated so this file stands alone

Scope: forced-NOLO deal play at the table at score `(0,0)`. Not whole-match
strength, not human-opponent performance, not any other scoreboard. No historical
trial is reopened and no sealed bank is used.

### The candidate, frozen

| File | SHA-256 |
| --- | --- |
| `src/tuppi_nolo/adapter.py` | `b5fc0ace150a6eaf3c7e8ca8589f15bd91948d5bcd4074f0cafb8669b0f3d22c` |
| `src/tuppi_nolo/trial.py` | `9ddb4982ba21e601…` |
| `tests/nolo/test_paired_validation.py` | `24a90171a3240fb5…` |

**B** is v2 (`partner_aware_lead_v2`); **C** is
`nolo_security_certified_v1`, budget `SupportBudget(3, 100, 100000)`, uncached
search. Exactly one candidate is tested and nothing is selected on this bank.
Gates: N08 PASS, N07 GO, G1 waived on the record.

### Design

512 independent base deals, root seed `nolo-info-strength-v1`, indices 0–511,
initial score `(0,0)`, initial dealer 0, round-robin dealer policy, identical
canonical NOLO showing forced in every arm. Each base deal is played four times:

| Arm | Team 0 (seats 0, 2) | Team 1 (seats 1, 3) |
| --- | --- | --- |
| BB | B | B |
| CB | C | B |
| BC | B | C |
| CC | C | C |

Both seats of a team use that team's policy. Agents are constructed fresh per arm
and per deal, so no certificate, plan or memo crosses an arm boundary. All 13
tricks are played. A failed arm makes its block incomplete and is never
substituted or removed. Complete and incomplete block counts are preserved.

**Run cap: 8 wall-clock hours.** If the cap prevents completion the result is
INCONCLUSIVE, and a completed subset is not evaluated in its place.

### Primary effects

Team 0 is the predeclared target. For base deal `i`, `T` the Team-0 trick total
and `W` the Team-0 deal win:

```
D_B_tricks[i] = T_BB[i] - T_CB[i]      D_B_wins[i] = W_CB[i] - W_BB[i]
D_C_tricks[i] = T_BC[i] - T_CC[i]      D_C_wins[i] = W_CC[i] - W_BC[i]
```

**Both families are signed so that positive favours the candidate**: fewer tricks
is better in NOLO, so tricks are baseline minus candidate; a deal win is better,
so wins are candidate minus baseline. `D_B` is the candidate against baseline
opponents, `D_C` the same replacement when the opponents also use it. **They
share deals and arms and are not independent replications**, and that is stated
wherever both are quoted.

### Analysis

`tuppi_eval.statistics.paired_value_summary`, one finite value per base deal,
confidence level 0.95, analysis seed `nolo-info-strength-analysis-v1`, 5,000
bootstrap and 5,000 permutation replicates. The declared bound is the returned
`bootstrap_confidence_interval` in every test, for both contrasts and both effect
families. No alternative interval or test is consulted or chosen after the fact.

Team-1 mirrored effects (`BB` vs `BC`, `CB` vs `CC`, targeting Team 1) are
reported **separately as orientation diagnostics only** and never pooled with the
Team-0 primaries: trick totals are conserved within a deal, so a pooled
complementary contrast can be algebraically the same observation counted twice.
Individual seats, the 13 tricks of a deal and score projections are not
additional independent observations. One base deal is one unit.

### Decision endpoints

**SUPPORTED: forced-NOLO deal improvement** requires all of:

1. All 512 four-arm blocks complete, with zero illegal actions, information
   leaks, invalid certificates or broken continuation commitments.
2. For **both** `D_B` and `D_C`: mean improvement at least **0.05 tricks per
   deal** and lower 95% bootstrap bound strictly greater than zero.
3. For both corresponding deal-win differences: point estimate at least zero and
   lower 95% bootstrap bound at least **−0.02**.
4. No unreported configuration or seed change, no post-outcome exclusion, no
   extra candidate. Fallback, commitment and latency counts recorded.

**HARM DETECTED:** a primary trick-effect upper 95% bound below zero, or a
deal-win upper bound below −0.02.

**INCONCLUSIVE / NOT ESTABLISHED:** a sound, complete trial meeting neither the
positive endpoints nor the harm condition. A small favourable mean with an
interval crossing zero is inconclusive, not a weak positive.

**INVALID:** any correctness violation, whatever the win rate.

The 0.05-trick and 2-point thresholds are proposed practical acceptance choices,
fixed before the run. They are not historical findings, and 512 deals is not
claimed to give high statistical power. Passing gives the bounded claim named
above and nothing wider.

**N will not be extended to reach significance, and no other seed will be
tried.** A further follow-up would need its own preregistration. The task
completes when the fixed result and its limitations are recorded, including a
negative one. **This cap correction is not a licence to rerun for a better
outcome: if the v2 run completes, its result stands as the answer.**

### Execution

```
python -B -m tuppi_nolo.trial paired --seed nolo-info-strength-v1 \
    --deals 512 --workers 14 --cap-hours 8 --out work/nolo/n09/trial
```

The trial runner is `src/tuppi_nolo/trial.py`, byte-identical to the version v1
used. The N07 runner is untouched, so the hash preregistered in
[`hypotheses.md`](hypotheses.md) keeps pinning the code that produced the
coverage screen. No production source is changed by this task.
