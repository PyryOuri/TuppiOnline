# Phase 5D-C results

Phase 5D-C optimized execution without changing the Phase 5D-B search semantics.
The package version is `0.7.0`. No Phase 4, Phase 5C, or registered Phase 5D-B
agent identity was changed.

## Semantic and differential results

The frozen 14-position conformance corpus covered showing, RAMI and NOLO,
root seats 0–3, early/middle/late play, partial tricks of sizes 0–3, and both
partner-winning states. It contains three configurations per position. All 42
optimized records matched the pre-optimization semantic oracle: selected action,
diagnostic values, sampled-world IDs, root-node paths, and node keys all matched.

The independent differential run covered 1,000 complete remainder-of-deal
simulations and 16,000 transitions. Authoritative and optimized results matched
on every checked observation and transition field. The exact-information oracle
and strategy-fusion counterexample remained unchanged.

## Performance

Pure `agent.decide` timing at budget 8, excluding serialization and CLI overhead:

| Position | Authoritative | Optimized | Speedup |
| --- | ---: | ---: | ---: |
| RAMI early | 0.662 s | 0.082 s | 8.04× |
| RAMI middle | 0.619 s | 0.064 s | 9.62× |
| RAMI late | 0.521 s | 0.034 s | 15.55× |
| NOLO early | 0.790 s | 0.095 s | 8.28× |
| NOLO middle | 0.788 s | 0.064 s | 12.26× |
| NOLO late | 0.543 s | 0.035 s | 15.67× |

Aggregate speedup was 10.47×. The optimized profile now identifies frozen
`partner_aware_v1` feature and public-inference construction as the leading
remaining cost. Optimized `tracemalloc` peaks were approximately 96–187 KB in
the measured positions; the baseline instrumented peaks were 222–386 KB, but
those measurements used different profiling combinations and are descriptive,
not a formal memory benchmark.

The previous budget stability values were preserved exactly: 2→4 agreement
0.500 and 4→8 agreement 0.833. Showing remained delegated and no higher-budget
agent was registered.

## Strength feasibility and evaluation

One standard-budget pair took approximately 0.9 minutes. A new unsealed,
32-pair complementary complete-match comparison then completed in 5.8 minutes
with four workers, safety cap 96, no failures, and no censoring. The candidate
was `root_info_uct_standard_v1`; `development_reference_v1` resolves to the
unchanged `partner_aware_v1` agent.

Result: 0 wins, 0 ties, 32 losses; `p_win = 0.000`, 95% interval `[0.000, 0.000]`,
and Monte Carlo sign-flip `p = 0.0001` at the report's 10,000-replicate floor.
The result is unsealed development evidence, not promotion evidence. It shows
that optimization made a decision-relevant evaluation feasible, while root-only
information-set search remains clearly weak against the frozen reference.

## Decision gate

Phase 5D-C selects **Path F2 — optimization unlocks evaluation but UCT remains
clearly weak**. Root strategy fusion was removed and validated, and the execution
cost is no longer the blocking limitation. The remaining weakness is consistent
with the deliberate non-goals: partner and opponent policies remain fixed rather
than information-set searched or explicitly modelled.

The next phase should investigate multi-observer/re-determinizing search or an
explicit partner/opponent model. Further root-only micro-optimization should be
undertaken only if it supports that next algorithm family. The sealed promotion
bank remains unopened; archive hashes and the frozen Phase 5C negative baseline
remain unchanged.
