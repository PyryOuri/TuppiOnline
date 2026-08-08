# Phase 5D-C profiling

Phase 5D-C began from commit `f12823399661caf736558da9d763955339a7e136`,
package version `0.6.0`, with the complete suite at 1367 passed and 2 skipped.
The profiling target was the existing `root_info_uct_standard_v1` configuration:
eight simulations, `sqrt(2)` exploration, frozen `partner_aware_v1` rollouts,
and no exact tail. Timing covered `agent.decide` only. CLI startup, JSON output,
pretty printing, report assembly, and the test harness were excluded.

The representative set contained six real trick-play observations: RAMI and NOLO,
each at early, middle, and late deal stages. Function-level `cProfile`, process
CPU time, wall time, call counts, and `tracemalloc` peaks were recorded. The raw
profile is outside Git at:

`/Users/pyryouri/Developer/TuppiRuns/phase5d-c/profiles/baseline_profile.json`.

## Ranked baseline hotspots

The instrumented cumulative totals across the six budget-8 decisions were:

| Component | Calls | Cumulative time |
| --- | ---: | ---: |
| authoritative engine `apply_action` | 1,664 | 9.77 s |
| canonical `observation_for` | 1,664 | 9.45 s |
| Phase 5B hypothetical continuation construction | 48 | 3.17 s |
| frozen rollout policy calls | 1,248 | 1.24 s |
| root information-state keys | 844 | 0.31 s |
| tree lookup, UCT selection, and backpropagation | — | under 0.18 s combined |

The engine cost was principally repeated complete `DealState` validation,
event-log construction, dataclass replacement, and legal-action projection.
The sampler itself was not the hotspot: its counted plan was built once per
decision and its eight-draw sample cost about 0.015 seconds in this instrumented
run. This ruled out sampler replacement as a justified optimization target.

The baseline profile also showed that JSON diagnostics were not in the simulation
loop. Serialization of one completed diagnostic was roughly 0.015–0.023 ms in
the same measurement, so moving it would not explain the observed latency.

## Methodological limits

`cProfile` and `tracemalloc` are diagnostic instruments and make a decision slower;
their times are used for hotspot ranking, not for the before/after speedup claim.
The pure-decision benchmark in the results document runs each mode without those
instruments. Memory peaks are reported with their instrumentation context and are
not treated as a precise allocator benchmark.
