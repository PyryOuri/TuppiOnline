# Phase 5F profiling report

Phase 5F optimizes the corrected Phase 5E `redeterminizing_ismcts_v1`
implementation. The target is execution cost only. The tree protocol, exact
uniform sampler, re-determinization coordinates, `sqrt(2)` exploration, frozen
rollout policy, utility, normalization, showing delegation, and registered
budgets remain unchanged.

## Baseline and method

The pre-optimization baseline was the clean Phase 5E checkout at commit
`5bd461307cee74768d30b4c1a4738bd2a8de8758`. The full preflight suite passed
`1,398` tests with `2` skips. Representative positions were selected at the
start, middle, and late trick-play portions of deterministic reference-policy
deals. Timing excluded CLI startup, JSON serialization, and report assembly.
The cProfile measurements below include profiler overhead, so they are used for
ranking rather than as throughput numbers.

At an early 32-simulation decision, the baseline profile was approximately:

| Component | Calls | Cumulative time | Share of profiled decision |
| --- | ---: | ---: | ---: |
| indexed exact sampling | 1,248 samples | 3.71 s | 70.5% |
| hard-constraint model build | 1,249 | 1.11 s | 21.2% |
| `PublicInference` | 1,249 | 0.31 s | 5.9% |
| information-state keys | 2,913 | 0.24 s | 4.5% |
| tree lookup and bookkeeping | 1,664 lookups | 0.19 s | 3.6% |

The early profile total was 5.26 s with cProfile. Mid-deal profiling put exact
sampling at 1.30 s of 2.21 s and model construction at 0.58 s. Late profiling
put exact sampling at 0.41 s of 0.70 s. The exact sampler was therefore the
first safe target, but the constraint builder was measured as a separate
substantial cost rather than assumed away.

The corrected early decision contained 1,248 observer re-determinizations and
1,633 information nodes. A wrapper around the canonical model builder recorded
1,249 builds and 1,249 distinct observer information keys: there were zero
reusable observer-context hits in this representative full-tree traversal.
That result is why a broad decision-local observer cache was not added as a
nominal optimization.

## Post-optimization performance corpus

The fixed performance corpus contains 24 early, 24 middle, and 24 late
trick-play positions, with role and stream variation. The external artifact is
`/Users/pyryouri/Developer/TuppiRuns/phase5f/benchmarks/phase5f_performance_v1.json`.
It has digest
`sha256:9c56d7cfcf8c9b08581dcc616da5307dcbcd5391d84ee022d5398fd2b9349312`.

For the registered 32-simulation budget, median timings were:

| Position class | Median decision | P90 | Median simulations/s |
| --- | ---: | ---: | ---: |
| early | 0.556 s | 0.569 s | 57.5 |
| middle | 0.342 s | 0.358 s | 93.5 |
| late | 0.122 s | 0.132 s | 261.3 |

The matched three-position legacy-versus-optimized timings were 1.09 s versus
0.596 s early, 0.563 s versus 0.339 s middle, and 0.175 s versus 0.128 s late.
The aggregate speedup was 1.72x. This is useful but below the 2x milestone;
the complete-match measurement, not this threshold alone, determines practical
feasibility.

A representative `tracemalloc` sample at budget 32 recorded 4.96 MB current
and 18.46 MB peak Python-traced memory. The tree and sampled worlds are local
to one decision and are released when the decision returns. No compiled
extension was needed: after optimization, cost remains distributed across
constraint construction, public observation/key materialization, and exact
sampling rather than one isolated stable kernel.

All profiler and benchmark output is outside the repository and outside any
synced folder. No timing field is part of a semantic identity.
