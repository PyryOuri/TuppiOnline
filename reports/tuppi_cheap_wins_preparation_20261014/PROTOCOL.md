# Tuppi cheap improvements analysis protocol

The final cheap round has two strength hypotheses and two speed candidates. All comparisons use the captured v3 engine and the final VRPO1/VRPO1/VRPO3 controller. The first analyses establish cost and implementation behavior. They cannot establish a strength gain or justify live adoption.

## Frozen comparator

[FROZEN.json](FROZEN.json) captures 293 files and 22,725,220 bytes from the current source and required assets. It includes the current uncommitted lazy-buffer wrapper. The original source remains under `frozen/ai` and `frozen/engine`; a separate private runtime adds only a native-library selector and optional immutable-MLP injection. Production checkouts and the earlier assessment are preserved.

Common bot settings are W1024, exact ordinary tail 6, VRPO1 for both rollout teams, VRPO3 anchor, play keep 0.003, bid keep 0.03, batch 128, z=2.5, delta=0.005, sampler fix enabled, RAMI bonus zero and extra NOLO tail zero. The incumbent-derived equity model stays fixed. No training, new belief model, bid-margin grid or rollout-role mixture is included.

The configured study jobs use one process, Torch/BLAS thread caps of one, native serial mode and rollout chunk 32. This bounds interference with concurrent work. It differs from all-core product latency; first report CPU work and serial latency. A later fixed-core latency study needs its own resource design.

The as-is v3 sooli-setting persistence stays in the comparator. Fresh constructors start cold; subsequent sooli calls may change retained settings. Do not silently reset options on every decision or every deal.

## Candidate definitions

| Arm | Exact intervention | Expected endpoint |
|---|---|---|
| `baseline` | Captured current bot with diagnostic sample counts | Reference |
| `hard_anchor` | Apply the current bid anchor's 0.03 offset in adaptive leadership, elimination and stopping; return the surviving leader | Strength and decision cost |
| `suit_ensemble` | Average remapped legal softmax probabilities of VRPO3 over identity, H↔D, C↔S and both; use that action in the existing keep rule | Strength and added root cost |
| `reward_bucket` | Private native ordinary root tails determine exact float32 equity buckets; exact-trick API and non-root learners remain unchanged | Exact value/action/RNG parity, then CPU |
| `same_net` | One shared immutable VRPO1 native MLP and one rollout inference batch for both teams; separate mutable seat controllers | Exact parity first; numerical variant if parity fails |

Each arm changes one mechanism. Do not combine arms, reuse saved CPU for more worlds, replace the policy anchor's inference backend in the baseline, or merge the older prior branch wholesale. The prepared hard-anchor arm explicitly retains the current separate bidding margin, which the old infrastructure snapshot lacked.

The root ensemble receives only the acting player's native observation. It changes neither the sampler nor other rollout actors. Both seats of the candidate partnership adopt it in the primary comparison. Suit names preserve red/black colour; all-24-suit augmentation and action merging are excluded. Legal order and the baseline tie rule remain explicit.

Reward buckets return abstract evaluator utility. They do not manufacture winners, terminal scores or final trick counts. A separate per-search marker excludes each valued private row exactly once. Its lookup table is built from the actual loaded native equity table and shared read-only across that root's parallel work. Existing APIs requiring an exact trick count are untouched.

## Duplicate deal design

Every parent uses a fixed shuffled deck, score and dealer 0, four hand rotations and two candidate team assignments. All eight games must complete before that parent's mean is included. Both candidate seats change together. Actual cards, score, dealer and index determine the parent ID. Initial hand order and authoritative legal-action order are preserved.

Each indexed game gets fresh environments, RNG objects and cold sooli settings. Model weights are immutable and cached. The two team assignments share the same initial indexed seat streams in independently owned controllers; later streams diverge naturally with policy choices. Parent bundles are independent. This replaces the historical persistent-per-worker design and must not be pooled with its results.

The `uniform` score design draws uniformly from the 25 legal nonterminal score cells. It is deliberately explicit; older tools used a different distribution under the same informal label. The zero-score guard is separate and can be added in a new frozen plan. The primary strong panel consists of the current searched baseline and VRPO3 with its documented authoritative sooli fallback. The heuristic v3 is a secondary regression guard.

Candidate and reference results must match the entire frozen context, opponent, seed, score design, sample count and complete parent set. Pair by parent ID; do not truncate to an intersection. Paired differences are candidate-minus-reference against the same opponent, not a direct match between those two candidates. Development intervals use a normal approximation across parents, without multiple-testing correction.

The existing interpreter and dependencies are reused rather than installed or upgraded. Worker outputs record Torch, NumPy, Python and interpreter identity; differing runtime identities fail paired comparison. This is dependency attestation, not a distributable environment lock file.

## First finite analyses

All four JSON plans default to `execution_enabled: false`; `launch.py run` also defaults to preview. They are finite proposed runs for later explicit execution, not work launched by this preparation.

| Plan | Jobs and sample dose | CPU reservation ceiling | Worker wall reservation ceiling | Purpose |
|---|---|---:|---:|---|
| [strength_costing](configs/strength_costing.json) | Baseline, hard anchor and ensemble against each strong opponent; two parent bundles per job | 1,800 s | 2,160 s | Measure actual cost and confirm complete record publication |
| [speed_validation](configs/speed_validation.json) | Baseline, reward buckets, baseline repeat and identical-model arm; two full deals per job | 960 s | 1,200 s | Complete trace parity and initial cost observations |
| [match_costing](configs/match_costing.json) | One baseline-vs-baseline pair; four-deal cap per leg | 600 s | 660 s | Bound initial complete-match expense while retaining censoring |
| [heuristic_guard_costing](configs/heuristic_guard_costing.json) | Baseline and both strength arms vs heuristic v3; two parents per job | 540 s | 720 s | Price the secondary guard |

These ceilings are reservations, not expected durations. Child CPU limits include all native threads. Successful attempts charge measured child CPU through process shutdown; failed or timed-out attempts retain the full CPU reservation. Worker wall timeout and cleanup can add approximately two seconds beyond the nominal child wall cap. Initial manifest verification is outside active child budgets. No automatic retry, expansion or continuation after a failed cap is implemented. Every run requires a new output directory; retained failed attempts are evidence.

The two-parent dose is for costing and plumbing. It is too small for a useful variance estimate or efficacy decision. After costing, price a development bank with enough parent clusters to estimate paired variance, phase-specific cost, action-world counts and changed-decision frequency. Reuse compatible baselines and decision diagnostics, but execute complete changed trajectories for outcome tests.

The initial default planning effect is 0.001 equity per parent deal. It is a proposal for sizing, not an established gain or permission to run a confirmation. For a frozen two-arm confirmation, account for testing both candidates; for example, a 97.5% two-sided interval per arm gives a Bonferroni family-wise 5% bound for the two primary comparisons. Size from the development paired-cluster variance and the agreed target before outcomes. A strong-panel average must be clustered by the common parent across opponents. Confirm each selected frozen candidate on fresh W1024 parents and separately on naturally completed match pairs.

Match legs own fresh controllers that persist across that leg's deals. Paired legs use a common card stream and independently owned controller state. A capped leg has `result: null`; identification bounds include it. Never call an incomplete leg a draw, exclude it as if random, or use the partial cost to claim a fully priced confirmation. OS termination without a complete pair is a failed costing attempt, not a match outcome.

All complete-match legs start at 0–0 and follow the authoritative rising score and dealer rotation.

## Validation and promotion gates

[PREPARATION_CHECKS.json](PREPARATION_CHECKS.json) records small candidate checks, native root fingerprints, an authoritative W4 pipeline identity control and one complete W1024 trace comparison per speed arm. The W1024 qualification covers four bids, two sooli offers and 52 plays on one fixed deal; it does not cover accepted/forced-sooli histories or every contract. Both speed arms matched that deal's action/value/RNG fingerprints. Single-deal CPU reductions of about 22.5% for reward buckets and 10.6% for identical-model batching are observations, not general speed estimates. These establish preparation properties, without establishing strength or a validated whole-bot speed gain.

The current costing worker records total process CPU and per-decision wall time. It does not separate construction CPU from decision CPU. Extend that instrumentation in a new frozen version before making claims about either component.

Before a speed claim, require whole-deal action/value/RNG fingerprints on W1024 bids, RAMI, NOLO, partial tricks and forced sooli phases, with retained C/O/P history modes. Measure repeated alternating CPU/wall runs on matched deals, separating construction and decisions. A useful preliminary speed bar is at least 10% CPU saving with exact fingerprints and no material latency regression; smaller valid savings may be retained as such. If batching changes any fingerprint, label it as a numerical/policy variant and require a separate non-inferiority design before adoption.

Before a strength claim, freeze the arm and its parameters, use fresh matched W1024 parent bundles against strong opponents, apply the chosen multiplicity rule and require a positive lower bound with a practically useful point estimate. Then verify the direction in completed matches. The heuristic guard is reported separately because the owner's objective prioritizes strong opponents. No live integration occurs as part of preparation or scientific execution.
