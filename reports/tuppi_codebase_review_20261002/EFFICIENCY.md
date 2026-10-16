# Bot and project efficiency

This is a prioritized measurement and implementation proposal, not a new benchmark. See [REPORT.md](REPORT.md) for scope and [FINDINGS.md](FINDINGS.md) for correctness prerequisites.

## Existing savings must be recognized first

The [September efficiency plan](../../TuppiAI/docs/EFFICIENCY_PLAN.md) and [results log](../../TuppiAI/docs/STATUS.md) report E0–E5 exact search optimizations: faster sooli and endgame solvers, sampler table reuse, sparse first-layer work and evaluator rollout chunking. Reported wall speedups were 2.16× at W128, 2.17× at W1024 and 2.32× for the 12-worker evaluator. E7 adaptive bidding was subsequently adopted, with about 1.5× less CPU per deal in its recorded comparison. These are historical measurements, not rerun here. E6 rank-equivalent root action reduction was not adopted, E9 was closed, and VN1/VN2 value leaves were not adopted.

The September profile attributed 39% of busy native CPU to sooli solving, 27% to the ordinary exact tail, 26% to network inference and 5% to sampling. About half of decision time was bidding, and the Python engine/bridge was only 0.4% in that profile. That was a particular short shared-laptop workload before subsequent changes. It is a good explanation for the tasks already completed, not a current cost model.

The older Python research engine's validation/observation hotspots belong to a different workload. Current evaluators already use private validated helpers and scoped trusted transitions. Applying the old percentages to native search would misallocate effort.

## Ranked work

| Priority | Work and concrete paths | Why it may help | Required evidence |
|---|---|---|---|
| 1 | Validate prepared infrastructure in `TuppiAI-prior`: `vrpo.py`, `experiment_queue.py`, `paired_results.py`, `match_statistics.py` | Avoid repeated manual launches, incompatible comparisons, missed endpoints and wasted learner work | Prepared runtime tests; zero-change parity; real small queue; correct frozen inputs; one-time final output |
| 2 | Current baseline with `tools/profile_search.py`, `tools/native_oracle.py`, `native/tuppi_env.c` | Determines where the present clone/VRPO1/VRPO3 controller spends time | Phase-stratified CPU/wall/latency/rows/nodes/worlds at W128 and W1024 |
| 3 | Lazy Python fallback buffers in `native.Env`; private native scratch reuse in `search_core`/`play_out` | Reduces allocation and memory traffic without adding information | Exact output/RNG fingerprints; allocation counts; RSS and repeated paired timing |
| 4 | Cache immutable native weights within a factory; native anchor inference in `_keep_blueprint` | Avoid duplicate export/load work and small Torch CPU forwards | Native/Python legal argmax agreement including ties; cold-start and steady-state timings |
| 5 | Learner batch decoding, host reads and monitoring cadence | Current `vrpo.py` computes unused actor/critic inputs and frequently synchronizes scalars | Device profile, same algorithm/trajectory gate, matched final checks and total compute |
| 6 | Allocation objective alignment: anchor, prior, RAMI offsets, counts | Spend worlds where they can change the final decision | Disabled-mode parity, per-action counts, paired strength and phase-specific latency tails |
| 7 | Diagnostic-bank reuse and compact training shards | Avoid repeated collection/export and preserve expensive labels | Whole-parent split checks, provenance, full trajectory confirmation |
| 8 | Product replay/review scheduling and caching | Improves perceived latency and contains background CPU | Cache identity/invalidation, concurrent-room trace, seat privacy and restart tests |

Priority 1 contains correctness and research-efficiency work, not only speed work. There is no recommendation to deploy the entire isolated branch at once.

## Measure the present workload

Freeze source, native binary, engine, equity table, the three model assets, configuration, lifecycle and worker layout. Use the same recorded deals in alternating before/after order. Separate cold construction, warm decisions, full deals and complete matches. Report CPU and wall separately: all-core native dispatch can lower latency while increasing work, whereas many worker processes may contend for the same cores.

At each decision record ruleset, phase, contract, tricks left, legal action count, evaluated action-world pairs, per-action sample counts, rollout network rows, offer calls, ordinary/sooli solver nodes, scratch allocation bytes and latency. Stratify rare expensive offers and bids rather than hiding them in a median over easy late-game moves. Retain actual deal/match throughput and p95/p99 decision latency. The research hard ceiling is a separate constraint from a mean-latency target.

For exact infrastructure changes, retain action/value/RNG fingerprints and component differential oracles. For float-changing inference or changed world/action allocation, legal argmax checks are necessary but do not establish strength. Run a fresh paired strength comparison with a predeclared non-inferiority margin and include total cost. These experiments were not launched here while the heuristic evaluation occupied the machine.

## Concrete memory opportunity

`Searcher` allocates `native.Env(worlds * max_actions, ...)`, with default `max_actions=26`. For the 1,951-feature encoder, `Env` eagerly allocates:

| Buffer per slot | Bytes |
|---|---:|
| Binary features | 1,951 |
| 156-action mask | 156 |
| Seat, phase, done (`int32`) | 12 |
| Reward (`float32`) | 4 |
| Eight info fields (`int32`) | 32 |
| **Python array payload total** | **2,155** |

At W1024 this is 26,624 slots, **57,374,720 bytes (54.7 MiB) per environment**, or **218.9 MiB for four seat environments**, before native game storage, native/Python model copies, solver tables and allocator overhead. This is calculated array capacity, not measured resident memory: zero-page behavior and actual touches affect RSS. The native root search operates on native game buffers and allocates its own per-search feature/logit arrays; it does not use every eager Python fallback buffer.

Proposed first change: allocate fallback observation/reward buffers only when Python stepping/observation APIs require them. Preserve the public API and avoid reallocating during active calls. A capacity-managed private scratch arena for root/native rollout buffers is the next independent change. Start with simple reusable arrays; a broad arena abstraction is unnecessary before measuring allocation cost.

Native solver tables are per thread and remain warm across solves. Many processes times many native worker threads can multiply their memory. Record thread/process counts with RSS; do not interpret an idle-worker count as actual parallel demand. `tc_set_parallel(False)` already exists and is used by heuristic mining; main evaluation currently sets Torch threads and rollout chunk but does not explicitly disable native dispatch. Benchmark process-only, native-thread-only and a bounded hybrid before selecting one.

## Network roles and export

The rollout clone and own-team VRPO1 are relatively small; VRPO3 is a larger root anchor. Keeping the larger network at the root is a sound cost separation: it is consulted once per decision instead of at every simulated step. The results log estimates roughly eightfold rollout cost for the larger dense architecture, but this review did not measure that ratio.

The factory shares Python network objects across seats, while each `Searcher` exports its own native rollout MLP and team MLP. Sharing read-only native weight objects within one factory may reduce startup time and memory. Keep each seat's environment, RNG, diagnostics and model lifetime separate; sharing a mutable controller would break the observation/lifecycle contract. Measure construction before adding a process-wide checkpoint cache, which would require invalidation when models change.

`_keep_blueprint()` currently invokes the anchor through Torch on CPU. A native root MLP could avoid that path. Native and Torch rounding are not universally bitwise identical; tie/near-tie actions must be tested on all legal phases and actual anchors. Also avoid allocating root feature buffers using the rollout encoder if a future anchor can use another encoder. The current models share the encoder, so that is an extension constraint rather than a demonstrated present defect.

## Learner efficiency and useful work

Main VRPO uses a shared `batch()` that unpacks actor features, privileged critic features and actor masks for both optimizer loops, even when some outputs are discarded. It converts losses/KL/clip diagnostics into host Python floats repeatedly. `TuppiAI-prior` has already separated those paths and grouped detached metrics. Validate the prepared work on the actual device before rewriting it.

Periodic evaluation currently performs multiple 8,192-base native checks every three iterations, exports models and saves checkpoints. Fewer checks may allow more useful learner updates, but the comparison must hold final evaluation size and selection rules fixed. Changing cadence currently also changes RNG consumption. The isolated implementation offers explicit Torch seed, evaluation-RNG separation, cadence zero and final snapshots; validate them together before attributing a gain to cadence. Final checking costs belong in total budget accounting.

SP1 logs collection, labeling, training and evaluation durations and stores compact iteration shards. Its labelled-state count is not equivalent to independent deals, environment steps, action branches or optimization samples. Report all those units separately, plus repeated replay use. The older Monte Carlo buffer stores dense binary rows; packing features is a potential memory saving if that historical method is reopened, but reviving a failed method only to optimize its storage is a poor first investment.

Small self-play jobs also need a split fix: the current fallback to a row-level holdout can split one parent trajectory. Parent-separated validation should precede deciding whether a gate is informative. A faster contaminated validation loop saves no scientifically useful compute.

## Whole-project efficiency

Use one registry of frozen experiment identities and results, including method, source/model/native/engine hashes, comparator, ruleset, score law, lifecycle, split roots, worker layout, grant, stopping rule and evidence class. A ledger that records resource reservations is not an OS limiter. The capped programmes already separate these responsibilities; preserve that structure.

The newest queue implementation freezes inputs, bounds sequential work, records unique attempts, requires explicit retries and compares exact deal sets. Standard-library tests passed during this review; actual native queue throughput and process cleanup with production workers remain unverified. It retains persistent-per-worker controller semantics, so it improves attestation without automatically making stochastic evaluation worker-order invariant.

Do not re-collect expensive labels for every downstream diagnostic. Reuse banks with aligned legal actions, full-world prices and source provenance for *development*. Partial adaptive prices need per-action counts and cannot be treated as full-world evidence. Changed policy trajectories still need full re-execution. Split on original parent before world branches, seat rotations or augmentation.

Keep discarded hypotheses in a searchable method ledger with the precise failing gate. C1's historical branch fraction illustrates the right stopping calculation: if a branch is fraction f of total cost, speeding it up by factor s changes total time by `1 - f + f/s`. At f=0.013, even eliminating the branch saves only 1.3%. N11 similarly shows that count of feasible worlds is not a sufficient predictor of tree expansion cost. Measure the structure generating cost before granting a large run.

For product work, preserve intentional 0.5-second pacing as a UX choice. Cache completed replay/review outputs by deal, seat, ruleset, reviewer and source/model/library configuration; invalidate when the configured reviewer changes. Profile locked-bid resolution, automatic after-deal reviews and concurrent analysis requests before adding a scheduler. Bounded background analysis capacity can be valuable, but no current multi-room bottleneck was measured here.

## Proposed order when compute becomes available

Freeze inputs and validate existing prepared code. Repair evaluator semantics and lifecycle attestation. Take a current baseline. Measure one exact scratch/buffer change and one learner-overhead change independently. Only then compare integrated hard keep, soft prior or other allocation variants at matched compute, including live W1024 and fresh complete-match endpoints. Reconsider the older programmes only when the proposed change addresses their recorded failure mechanism.
