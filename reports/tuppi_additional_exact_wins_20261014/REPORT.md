# Additional Tuppi computation savings before strength comparisons

Two further changes deserve a small qualification pass: use larger rollout batches for serial evaluation, and omit network inference for rollout moves with a single legal action. Both preserved the checked search values, actions and RNG. Their observed savings are smaller than the preceding reward-bucket opportunity. Reusing network scratch buffers showed no useful CPU gain and should be parked.

This work uses the inputs of the [sealed preparation package](../tuppi_cheap_wins_preparation_20261014/README.md), without changing that package or the product. Private native patches and hashes are in [BUILD.json](BUILD.json) and [COMPACT_BUILD.json](COMPACT_BUILD.json). Results are in [PROBES.json](PROBES.json) and [FOLLOWUP.json](FOLLOWUP.json).

## Results and priorities

| Change | Checked behavior | Cost observation | Priority |
|---|---|---|---|
| Rollout chunk 32 to 128 | Identical complete traces on two retained W128 deals and 14 ordinary native roots | Three timing pairs saved 7.1%, 10.2% and 7.2% CPU; median 7.2% | First for serial evaluation; qualify W1024 and live latency separately |
| Remove forced rows from the shared-model network batch | Identical two-deal W128 trace, one complete W1024 trace and 14 native roots | About 4.0% less CPU than the shared-model comparator in one W128 pair | Second, subject to broader parity and repeated timing |
| Keep matrix shapes while bypassing forced-row encoding | Identical two-deal W128 trace and 14 native roots | About 2.0% less CPU in one W128 observation | Simpler fallback if row compaction fails wider parity |
| Reuse the network's three temporary buffers | Identical network logits, thread checks, two-deal W128 trace and 14 native roots | About 0.7% more CPU in one observation | Park; allocation removal alone did not pay |

These are small cost probes on synthetic fixed inputs, not strength comparisons. The W128 games have 115 decisions: seven bids, four sooli offers and 104 plays. Accepted-sooli histories and a broad contract/deal corpus remain outside the full-game check. Native root fixtures include both ordinary contracts, partial tricks, C/O/P settings and W1024 exact tails. The W1024 compaction check covers the same 58-decision deal used in the preceding package; it is implementation qualification rather than an independent timing pair.

## Larger batches are an existing setting

The [native loop](../../TuppiAI/native/tuppi_env.c) uses rollout chunk 32 by default. Evaluators adopted 128 historically in the [E5 programme](../../TuppiAI/docs/EFFICIENCY_PLAN.md); this is a current recheck of a useful setting, rather than a new algorithm. The proposed prepared launcher still explicitly uses 32.

At W128, changing the chunk reduced network calls from 39,277 to 9,878 on the same 693,081 rollout rows. Three separate-process timing pairs used the same two deals and retained controller state, with reference/candidate, candidate/reference, then reference/candidate order. Each process used one native execution lane and capped Torch/BLAS threads. The changing reference CPU times, 11.06 to 12.39 seconds, make the paired design useful and limit interpretation of timings collected far apart.

Larger chunks can change floating-point kernels and dispatch granularity. The checked values were bitwise identical here. Test W1024 with repeated pairs and check p95 decision latency in the intended native thread configuration before using it in the live app. Browser/portable backends need their own check. An evaluation setting that saves serial CPU does not automatically improve parallel latency.

## Forced moves still receive network inference

The current ordinary rollout loop encodes and forwards every live row before discovering its legal actions. A single legal move needs no policy decision. In the checked games, 109,888 of 693,081 rows were forced, about 15.9%.

The conservative prototype leaves other rows at their original matrix positions, blanks forced features, and skips forwarding a chunk only if every row is forced. It preserves shapes, but removes just 994 complete network rows: forced rows are mostly mixed with ordinary decisions. That explains why this version captures only a small saving.

The compact prototype builds legal actions first and sends only unforced rows through the shared immutable rollout model. It preserves row order among the remaining rows, legal-action order, tie-breaking, one-action-per-wave scheduling and all RNG calls. It runs compaction only when a single model is used and incremental first-layer state is disabled; other configurations retain their layout. The rollout row count stays 693,081, while network rows fall to 583,193. Thus the change removes inference rather than sampled worlds or game transitions.

Compaction depends on the [previously prepared identical-model arm](../tuppi_cheap_wins_preparation_20261014/candidates.py). The 4.0% observation compares compaction with that shared-model comparator, not with an independently chosen weaker policy. Tests on both current models and 11 batch sizes found no logit changes on retained rows when neighboring rows were blanked or removed. Whole-search and whole-deal fingerprints provide the additional behavioral check. Wider parity remains necessary because changing matrix shapes is a numerical implementation change.

## Scratch reuse did not earn its complexity

The [native forward](../../TuppiAI/native/tuppi_mlp.c) allocates and releases three float buffers on every call. The prototype retained capacity per thread and supplied both a thread-exit destructor and explicit main-thread release. It removed roughly 118,000 buffer allocations in the two-deal probe, but total CPU did not fall. It adds lifetime handling and retained capacity without a demonstrated speed benefit.

Both models passed 11 batch-size oracles, concurrent shared-weight calls, explicit clear/reallocation checks and comparison with the captured native library. This validates the checked implementation behavior, not a reason to adopt it.

## Combining the existing savings

A separate prototype combined reward buckets, the identical-model factory, the conservative forced-row bypass and scratch reuse. It preserved the 14 native roots and two complete W128 traces, with about 22.9% less CPU than the reference in one observation. This does not isolate either old speed candidate or justify adding individual percentage savings. The scratch component should be removed from a later combined comparator unless it earns a separate benefit.

Before strength comparisons, the useful sequence is to qualify the reward-bucket/shared-model combination, measure larger serial batches at W1024, then qualify forced-row compaction against the shared-model baseline. Once selected changes pass broader action/value/RNG parity, prepare a new sealed comparator and apply the same speed settings to every strength arm. Preserve the current package and avoid spending the saved CPU on extra worlds during that comparison.

## Reproduction and scope

[build.py](build.py), [build_compact.py](build_compact.py), [probe_one.py](probe_one.py), [probe.py](probe.py) and [followup.py](followup.py) capture the exact private implementations and bounded jobs. Each child has a 60-second aggregate CPU limit and a 90-second wall alarm, with a 92-second parent timeout. Jobs run sequentially; the small MLP concurrency oracle deliberately uses two threads to check shared weights and thread-local scratch. Completed files use exclusive creation, so repeating a programme requires a new attempt directory/version.

One initial harness attempt failed before gameplay because it called the snapshot loader twice. Its [log](checks/roots_installed.log) is preserved; the explicit corrected attempt is under `checks_v2`. It did not produce a game result. The original packages, production source, models, installed native library, server and app were preserved. [VALIDATION.json](VALIDATION.json) records final input/evidence hashes and link checks.
