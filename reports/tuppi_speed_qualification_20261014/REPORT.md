# Tuppi speed qualification before strength comparisons

The selected analysis baseline combines exact equity-bucket endgames, a shared immutable VRPO1 rollout model, rollout batches of 128, and omission of forced moves from network inference. It passed the recorded engineering gates. On the fixed W1024 bank, median paired serial CPU fell **34.6%**. Native-parallel median two-deal wall time fell from **11.05 to 7.97 seconds**, a **27.8%** reduction. Every checked action, searched value and RNG state matched the captured reference.

This qualifies a common implementation for the prepared strength analyses on this Mac. It establishes neither stronger play nor a gain across arbitrary deals/devices. The repeated timing bank contains two retained-controller deals starting at 24–0 and 40–0, each repeated five times per variant and execution mode. They are technical repetitions, not independent strength samples. Broader parity cases cover both ordinary contracts, all 25 nonterminal score cells, partial tricks and accepted sooli.

## Combined results

| Implementation | Median serial child CPU for two deals | Median paired CPU reduction | Native-parallel median wall time | Median paired p95 decision ratio | Median paired p95 bid ratio |
|---|---:|---:|---:|---:|---:|
| Captured reference, chunk 32 | 62.23 s | Reference | 11.05 s | 1.000 | 1.000 |
| Reward buckets and shared model, chunk 32 | 46.64 s | 25.2% | 8.61 s | 0.686 | 0.927 |
| Reward buckets and shared model, chunk 128 | 43.12 s | 30.7% | 8.40 s | 0.640 | 0.965 |
| Above plus forced-row compaction | 40.29 s | 34.6% | 7.97 s | 0.579 | 0.958 |

Ratios compare the same round's candidate and reference. Median CPU reduction is the median paired reduction, rather than a ratio of the displayed median CPU totals. Wall-time reduction above uses the displayed wall medians. [SUMMARY.json](SUMMARY.json) contains all five observations and the [analysis code](analyse.py) defines the percentile interpolation.

Increasing the batch from 32 to 128 saved a further median **7.2% CPU** relative to the reward/shared-model combination. Compaction then saved another **6.6% CPU** relative to that larger-batch implementation. These percentages have different comparators and must not be added. The full combination saved 31.5–38.3% CPU across its five paired rounds.

Overall decision p95 improved substantially on this bank, but bid p95 improved by only about **4.2%** relative to the original. Larger batches made bid p95 about **4.3% worse** than the simpler chunk-32 combination; that stayed within the predefined 5% material-regression band. Compaction recovered a small part of it. Slow bids remain an important latency limit.

Native-parallel median peak RSS was approximately 542 MiB for the reference and 518 MiB for the selected implementation. These are process measurements including the Python/runtime/model/solver footprint on this host, rather than device-memory estimates.

## Behavior and state qualification

All four implementations passed the same serial and native-parallel corpus:

- **78 native roots:** the preceding 14 fixtures plus 64 additional ordinary tails, spanning both contracts, all 25 legal score cells, partial tricks and C/O/P options. The earlier fixtures include W1024 exact tails; the additional random roots use W16.
- **84 authoritative history-bank decisions:** twelve fixed scripted v3 deals, including bids, ordinary play, seven accepted-sooli exchanges and their play. Controllers persist across the bank. The checked decision inputs include six C, seven O and 71 P histories.
- **Six forced-sooli probes at W1024:** offer, give, return and the first three play decisions on the fixed accepted-sooli fixture.

Every native-parallel corpus trace also matched its serial trace. The repeated two-deal bank produced **80 complete-deal executions**, 40 serial and 40 native-parallel, from the same two unique inputs. All 4,600 decision records across those repetitions shared the same complete trace identity. [PARALLEL_CROSS_CHECK.json](PARALLEL_CROSS_CHECK.json) and the stage records under `runs` preserve the comparisons.

An additional natural 0–0 W1024 deal is checked separately by [ZERO_CHECK.json](ZERO_CHECK.json). Its seed is chosen solely as the first finite deterministic seed giving the required score cell, without consulting a controller's outcome or cost. It adds a distinct input for parity rather than a repeated timing estimate.

That additional input showed about 16.7% less serial CPU in one pair, a smaller reduction than the repeated bank. Its deck and score both differ. This illustrates why the 34.6% result should stay attached to the measured two-deal bank.

Native sooli settings are tracked through writes to the environment's setter, starting from the captured calloc-zeroed state. The source assigns those options only through that setter. This avoids guessing private struct offsets and verifies retained behavior after sooli. The as-is v3 setting persistence is preserved; the qualifier does not reset it each decision or deal.

## Engineering gates and selected scope

[GATES.json](GATES.json) was recorded before the W1024 timing stages. Selection required all exact traces, at least 10% median serial CPU saving versus the original, at least 2% incremental saving for added mechanisms, and no more than 5% median p95 decision or bid regression versus either the original or the preceding selected implementation. All three additions passed.

[QUALIFIED_BASELINE.json](QUALIFIED_BASELINE.json) pins the selected native binary and settings. W1024, the six-trick ordinary tail, VRPO1 on both rollout teams, VRPO3 anchor, keep margins 0.003/0.03, adaptive bid batch 128, z=2.5, delta=0.005, showing fix, equity table and extra NOLO tail remain fixed. Saved computation is not converted into additional worlds.

The new [build](BUILD.json) contains no scratch pool or inference telemetry. The network source is byte-identical to the frozen comparator. Private patches change ordinary root evaluation and its rollout batching; exact-trick interfaces and non-root learner calls retain their original paths. All assets and original packages remain captured separately.

Native-parallel measurements use the existing dispatch configuration with one Torch/BLAS lane. They do not measure SwiftUI/network/end-to-end app latency. Browser, portable-backend and physical-device acceptance remain separate work; the existing app/server were not changed or restarted.

## Prepared strength analyses

The [common factory](bindings.py) applies the same selected speed settings to baseline, hard-anchor and suit-ensemble arms. [FACTORY_CHECK.json](FACTORY_CHECK.json) records one legal W256 bid per arm with the current margins, separate mutable seat state and shared immutable weights. [WRAPPER_CHECK.json](WRAPPER_CHECK.json) records sixteen authoritative W4 games forming two baseline identity-control bundles, both exactly zero.

The new [analysis launcher](launch_analysis.py) uses this factory with the preceding frozen evaluation/statistics code. Original packages remain immutable. New parent-bundle costing plans use 600-second child CPU caps and 720-second wall caps: two parents require sixteen games, and the observed selected cost of roughly twenty seconds per retained game makes the earlier 300-second cap too tight as a starting reservation. Fresh indexed-game lifecycle and diverse deals can cost differently. The plans retain their original seeds, opponents, world budget, score design and sample dose; actual costing remains execution-disabled by default.

The complete-match costing plan retains its prior finite cap and treats unresolved outcomes as unknown. The new comparator has its own package/context identity, so results must not be pooled with earlier controller or lifecycle definitions. No strength campaign, training or live integration was executed during qualification.

## Evidence and reproduction

[PLAN.json](PLAN.json), [PARALLEL_PARITY_PLAN.json](PARALLEL_PARITY_PLAN.json) and [ZERO_PLAN.json](ZERO_PLAN.json) define finite sequential jobs. Each child has aggregate CPU and wall limits; failed attempts retain their reservation, without automatic retries. Successful stage CPU charges include process startup/shutdown. Timing order is reversed/rotated across five rounds. Model construction and decision CPU are recorded separately; construction was small relative to the observed savings.

[BUILD.json](BUILD.json) records compiler commands and private source/binary hashes. [FIXTURES.json](FIXTURES.json) captures only synthetic inputs from the preceding browser/rules qualification, with current decisions checked anew against the frozen authoritative engine. [PACKAGE.json](PACKAGE.json) seals this implementation, protocol and evidence; [VALIDATION.json](VALIDATION.json) records final integrity and link checks. Commands and future costing entry points are in [README.md](README.md).
