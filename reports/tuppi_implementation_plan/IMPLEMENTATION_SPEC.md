# Tuppi research implementation specification

Version: 1.0 | Design date: 25 September 2026
Status: PROPOSED IMPLEMENTATION DESIGN, grounded in the supplied static audit.
This document specifies work; it does not report completed Tuppi implementation, passed game tests, measured speedups, or strength gains.

## 0. Purpose and decisions

Implement a reproducible research path for five mechanisms, not an indiscriminate rewrite of the current agent:

- C1: analytical control variates for ordinary NOLO-discard search.
- C2: consequential-event conditioning for blind bidding.
- C3b: exact surrogate-utility stopping in ordinary rollouts; C3a: policy-specific match-transition evaluation where a sufficient state model is justified.
- C4: jointly optimised, information-legal sooli giving and returning.
- C5: a small information-consistent continuation option invoked at an actual ordinary three-card boundary.

The first implementation milestone is C0 infrastructure plus C1 correctness and pilot readiness. The remaining mechanisms have concrete designs below and should be implemented in dependency order, not launched simultaneously as expensive experiments. Rejected mechanisms and blocked assumptions are legitimate results. A campaign is complete when each planned hypothesis has a recorded disposition, not when every hypothesis is promoted.

All implementation names introduced here are PROPOSED, unless explicitly marked EXISTING. Do not assume proposed CLI commands or functions already exist. Verify the supplied source identities locally before editing. A changed checkout requires a targeted compatibility review, not an automatic reset to an old commit.

### 0.1 Evidence baseline

The primary source is `TUPPI_DESIGN_HANDOFF.md` (SHA-256 `87b0efd3666d7b97493a845f30d2c19619d09cd489fe9e802de25d334f3adb38`), its two source supplements, index, evidence manifest and fixture recipes. Evidence IDs E001-E062 below refer to the audit's original files and hashes. Source statements are static findings, not newly executed tests.

Verified in this design session: all eleven files listed inside the supplied SHA256SUMS match their supplied sizes and hashes; the MD and TXT handoffs are identical; common pre/post repository metadata fields agree. This checks the uploaded package's internal integrity, not source/binary correspondence or authenticity of historical runtime claims. See INPUT_VERIFICATION.json.

Working identities reported by the audit:

| Alias | Checkout | HEAD | Role |
|---|---|---|---|
| AI | TuppiAI | 4220f249e351905deb3a3754de812a01acf152d7 | Current search and native implementation |
| ENGINE | TuppiProject-current | 1347153f7d6e7bed95edddce9d35d28a3df91750 | Authoritative v3 engine |
| RESEARCH | TuppiProject | 622d5599318e4f1b2a82ef53bfc141970edc24de | Older research; substantial uncommitted work |
| CLIENT | TuppiClient-current | 7ba8ca283f01794170d105ba08c5a799f7bd7909 | Current client; not an initial edit target |

The model uses encoder 2 with 1951 inputs, width 256 and two residual blocks. The ordinary head has 156 outputs. Sooli exchange action IDs are outside this head. Native layout and action encodings must be checked from E003/E006/E011, not guessed from dimensions.

Asset identities:
- `models/rollout_clone_small.pt`: `38737c9042695a4c960157fb77a8d17f308c5773899c2ec0c65b0d20546324f1`.
- `models/equity_incumbent.json`: `1496f77104f411c5cb55e2cef4573a10aead59acbd643261b755886bfeb60b91`.
- installed `native/libtuppi.dylib`: `02d9b4fad98ebb342e12cd9ecb4723aaee1406c6c6b539a1dc4a5b2b002c1ab8`.

No archived historical process state or proven correspondence between the installed binary and current C source was established. Do not claim to reproduce a historical result solely from these hashes.

### 0.2 Scope and authority

Keep the current factory, installed dylib, live server, client, persistent rooms, frozen registry and existing protected banks unchanged. Use isolated additions and a separate native build. Do not modify dirty research files to make an import convenient. Preserve their on-disk identities when extracting a permitted dependency.

Implementation and small contract tests are distinct from performance experiments, training, independent confirmation and deployment. The execution manifest must explicitly enable each execution stage and cap its resources. Missing budgets block the corresponding empirical launch, not writing the implementation or pure tests. No external spending, cloud calls, package upgrades, permission escalation, background jobs or live changes are implied.

A high-level design suggestion does not override an existing owner decision. In particular, the v3 ordinary-path sooli-setting defect remains in the as-is comparator. A separately named repair can be designed and tested only within its explicit scope; it is never smuggled into another mechanism.

### 0.3 Corrections to the earlier proposal

1. Do not build a 100-state match model and call it the literal current process. RNG/call history and inherited sooli settings matter (E002/E004).
2. Do not use the existing complementary-match CLI for v3 claims. It is v1-only and its opponent constructor is restricted (E013/E014).
3. Do not assume the old analytical mean is the expectation under the current native sampler (E022-E024 versus E005).
4. Do not assume all blind bid calls are harmless to persistent state. Reached-only and all-four commitment schedules differ computationally (E002/E020).
5. Do not insert C5 independently inside each sampled DD leaf. It must group worlds at the actual player's information sets and retain the chosen option.
6. The six fixture files are construction recipes, not validated game fixtures. Build and validate them before using them as tests.
7. An exact root-optimal C5 option cannot have negative expected advantage over a feasible root policy in the SAME complete fixed-opponent model. Negative action-minus-reference gaps are useful tests; a negative optimum-minus-feasible-policy gap is a bug or mismatched model. This qualifies the handoff's proposed positive/negative comparison test.

## 1. C0: reproducible implementation substrate

### 1.1 Files and package boundaries

Use the following initial structure, adjusting only to repository conventions documented in a compatibility note:

```
TuppiAI/
  tuppi_ai/research/
    identity.py          # Source/artifact/entrypoint/lifecycle identities
    records.py           # Validated envelopes, no policy access to offline truth
    observation.py       # Legal observation serialization/round-trip/keys
    lifecycle.py         # Replay snapshots and research-native state forks
    native_api.py        # Library-specific ownership, explicit-world interface
    clone_policy.py      # Masked encoder-2 deterministic continuation adapter
    streams.py           # Domain-separated experiment streams
    fixtures.py          # Bounded builders for F01-F06
    runner_v3.py         # Paired deals, full matches, transitions
    statistics.py        # Clustered endpoints and resource accounting
    c1_control_variate.py
    c2_blind_bids.py
    c3_utility_stop.py
    c3_kernel.py
    c4_exchange.py
    c4_training.py
    c5_option.py
    cli.py
  native/research/
    build_research.sh
    research_api.h
    overlay.patch        # Minimal reviewed patch against pinned original sources
  tests/research/
  research_runs/<run_id>/
```

This is not permission to alter existing protected packages. Treat ENGINE as the runtime dependency. Do not import both ENGINE and RESEARCH installations of `tuppi_engine` into one Python process. Reuse research algorithms through a narrow vendored/reference module with source attribution and equality tests, or via isolated oracle processes. Do not widen PYTHONPATH until an arbitrary checkout happens to import.

One integration owner owns native ABI/overlay, shared records and runner changes. Workstream owners may develop their own modules against a frozen interface version. If subagents are available, they can review independent workstreams; they must not concurrently edit shared native files or launch nested multicore jobs. All workers write durable task reports and return paths/hashes, not huge unverifiable summaries.

### 1.2 Comparator identities

Maintain distinct identities:

- `B0-installed`: supplied installed library, unmodified Python entrypoint and named construction history. Source correspondence unknown until tested.
- `B0-source`: isolated unmodified-source build. Its own binary hash is mandatory.
- `R0-parity`: instrumented research build with all strategy/repair switches disabled.
- `Ci-*`: one named intervention over R0-parity or another explicitly recorded parent.

Use `best_agents`, not a generic `search:` specification whose defaults differ. Preserve the factory's effective `seed + 2*seat` mapping for as-is comparisons. Store the complete per-seat seed map instead of describing it ambiguously as one seed. E001/E002/E013/E059 distinguish factories, CLI paths and the live seat-plan override.

Before a new native export is trusted:
1. Record paths, hashes, import resolution, compiler flags, model configuration, actual loaded library and ordered legal-action conventions.
2. Build an unmodified source library in a separate directory without overwriting the installed library.
3. Compare original-source and research-parity results on generated fixtures and recorded legal call sequences: selected actions, per-action values, output error status, root RNG and mutable configuration.
4. Separately compare installed and source builds where the installed APIs permit. Exact equality on these tests is a tested equivalence boundary, not a universal proof. Any discrepancy remains a blocker for claiming installed-baseline parity; analysis may still proceed explicitly against B0-source.

Native pointer ownership must be library-specific. Never construct an Env with one dylib and pass it to another. Prefer separate processes for installed/source comparisons. The research build may compile a patched scratch copy of E004 and the original other C files exactly once. It must not silently replace the production loader. Store the patch, complete build command, copied-source hashes and output hash.

### 1.3 Three lifecycle contracts

Use explicit lifecycle labels rather than pretending every comparison measures one policy:

**Historical compatibility.** Preserve the documented old worker/arm call order solely for continuity. It is not the primary independent-deal design, because worker reuse links unrelated deals.

**Independent duplicate-deal instrument.** For each base-deck bundle, create independent environments per arm/rotation/team assignment, with matched initial identities and seat seeds. Use an explicitly named cold or recorded-prefix snapshot. This creates independent clusters and is a new evaluation lifecycle, not the unknown live history. Counterfactual policies subsequently evolve normally within their own arm. Never force their post-divergence RNG/settings to stay equal.

**Complete-match instrument.** Construct policies at each match-leg start, then retain their state throughout every deal in that leg. Complementary legs use the same indexed decks and prescribed seat/seed mapping, but fresh independent environments. Cluster the pair. Later calls and settings can diverge as consequences of different play. Do not reset at each deal merely to simplify analysis.

A deployment-normalised policy with per-decision reseeding or fixed settings is another candidate. Do not use it as the as-is default.

### 1.4 Snapshots, forks and information containment

EXISTING `Env.set_state` and `tc_env_clone_from` copy deal state, not a complete search controller (E003/E004). A proposed `PolicySnapshot` contains:
- model/equity/native/source/encoder IDs and construction parameters;
- Python NumPy bit-generator state, scalar ctypes search RNG, main/show-searcher states;
- native environment dimensions, equity table as loaded, encoder, single-deal/random-start options and all sooli settings;
- relevant slot state/RNG/live flags/counters if the selected execution path uses them;
- option state for C5 and legal own-memory fields, if enabled;
- process-global chunk setting and scheduler policy as identity metadata.

Scratch arrays and diagnostic values need not be copied if a documented read/write audit proves they do not affect decisions. Solver caches may be omitted from value snapshots only after small cold/warm equality checks and the no-deadline pure-solver argument are recorded. They remain relevant to timing.

Provide two fork mechanisms:

**ReplayFork (first implementation).** Freshly construct the same agent and replay that seat's recorded sequence of legal observations and its original calls, validating actions at each step. This needs no undocumented native-memory scraping. It is expensive but sufficient for initial small paired fixtures. Counterfactual calls happen only on the fork; never advance a live baseline during diagnosis.

**NativeFork (optimisation).** Add schema-versioned research exports for full required mutable fields; serialize fields explicitly, not C padding or pointers. Export/import inverse tests and replay parity are mandatory. Snapshot once, clone many. Immutable model weights can be shared in process; mutable Env cannot.

The generic evaluator may hold full simulated layouts. A policy receives only a typed legal observation and its permitted personal state. `OfflineTruth`, layout IDs, cluster IDs, bank split flags, object addresses and true hidden hands must not enter model inputs or policy RNG derivation. Fresh experimental seed namespaces are not a channel for per-layout identity. Invariance tests change true hidden cards while holding the actor's complete legal input and seed fixed.

An agent's hypothetical world samples are computational state, not true opponent information. Never transplant another actor's posterior into a simulated actor's input. For C5, the other-seat clone has its own projected observation and no root posterior.

### 1.5 Observation and state transport

Use E017 `observation_to_data`/action serialization as the source of wire semantics. Implement a typed inverse only after inspecting every dataclass field and preserving ordered own hands/actions, public history, ruleset, phase, score, sooli decisions and legal exchange knowledge. Never assume encoder-2 vectors are injective information keys.

Transport public/actor-private information separately from evaluator truth. A `DecisionCase` contains the legal observation and a permitted policy-snapshot reference; the harness resolves it before calling a policy. No policy-facing object contains a truth reference. Store truth in a distinct access path used only by the runner/oracle.

JSON is the portable record. Native TcDeal bytes are supplementary, only with ABI version, size, offsets, endian and source hashes. Validate native integer ranges and phase/card/action bounds. Do not unpickle untrusted or protected datasets. New fixtures and banks should not require pickle.

### 1.6 Proposed typed interface contract

```
AgentIdentity = immutable source/model/native/equity/config/entrypoint/lifecycle IDs
DecisionCase = legal_observation + ordered_actions + own_state + population metadata
WorldBatch = evaluator-only pre-action TcDeal states + law_id + weights + seed trace
StreamPlan = sampler and continuation stream scheme + exact recorded seeds
ActionWorldBatch = values[W,K] + actions[K] + per-cell status + work/timing + trace
PolicyFork.choose(legal_observation) -> legal_action
DealTransition = source state + terminal result + next state + policy snapshots + cost
OptionPlan = own information-key -> action; scoped to one deal and model identity
ExperimentManifest = populations + contrasts + splits + budgets + analysis + hashes
```

Returned buffers belong to the caller. C uses explicit sizes/strides and rejects overflow in W*K and allocation sizes. Mean accumulation is float64; current terminal equity change is rounded to float32 then accumulated as in E004. Preserve source action order, including heuristic-first sooli ties. Invalid values are never silently converted into zeros.

## 2. Native evaluation and v3 runner

### 2.1 Explicit-world native interface

Add separate research exports with their own API version:

```
research_sample_worlds(obs, W, sampler_state, law_config)
    -> worlds[W], per_world_status, sampler_state_after
research_evaluate_worlds(env, mlp, obs, worlds[W], actions[K],
                         tail, continuation_plan, options)
    -> values[W,K], cell_status[W,K], trace, work
research_trace_search(...) -> same + actual internally sampled worlds
research_export_controller_state(...) / research_import_controller_state(...)
```

The evaluator never samples replacement root worlds. The sampler and evaluator are split at E004 `search_core`'s initial loop. The continuation path retains forced-action application, sooli handling, DD threshold, clone encoding, legal masking, rounding and aggregation. Keep the old wrapper available and unchanged in behaviour. A trace wrapper obtains the SAME worlds as the original call, rather than trying to recreate them after advancing its RNG.

C1 initially supports only ordinary NOLO discards. In this phase the continuation is deterministic clone/DD and cannot enter sooli, which makes explicit-world factoring much simpler. Do not delay this narrow export until every stochastic bidding corner is implemented. Generalisation to C2 must preserve or explicitly replace the action-slot-dependent stochastic continuation scheme; same worlds alone are not a guarantee of common random numbers.

Use a separate pure `evaluate_fixed_clone_suffix` without a DD tail for C5. Do not silently change the current search's tail to reuse that function.

### 2.2 RNG accounting and diagnostic shadow advancement

Original sampling consumes one mutable scalar RNG; sooli continuation derives per-slot streams from shared draws and slot indices (E004). Changing W, K or action order can affect later search streams. Distinguish:
- equality of population target;
- equality of finite-seed outputs;
- equality of subsequent controller state;
- wall/CPU equivalence.

For a mechanism-only C1 full-game arm, a useful proposed control is **shadow advancement**: independently compute the candidate estimate from a copy of the pre-call RNG, while advancing the persistent scalar exactly as the original W128 ordinary NOLO sampling loop would have done. A validated sample-only legacy wrapper can perform the W128 draws without expensive continuations. This costs sampling and must count against any speed claim. Confirm that no other persistent field read by later calls was changed in this branch. On matched legal histories, the post-call state must equal the original's; after choices diverge, do not force later states to agree.

A natural candidate that advances only its own used draws is also valid, but is a different complete policy. Report it separately. Population Monte Carlo claims and an as-is finite-seed comparison must not be confused. Reference/diagnostic searches run on forks and never mutate candidate or comparator states.

### 2.3 Error handling

The audit identifies a static sooli path that can mark a rollout done without recording utility. Its occurrence is unmeasured. Add observational status instrumentation in the research parity build; preserve original values when documenting parity, but mark invalid rows as unusable for a correctness claim. Any error-propagation repair receives a separate change ID.

For new interfaces: reject nonfinite results, invalid forced actions, infeasible layouts, mismatched actor/observation, allocation overflow and unsupported phases. Return a structured status; never fabricate a terminal result. A launched candidate may fall back to original W128 after an implementation-budget failure, with explicit timing/state-advancement semantics. Record failure incidence on an intention-to-run basis.

### 2.4 Authoritative v3 evaluation

Build a new runner around ENGINE match/deal operations (E018/E051), not by treating the old match_eval command as v3-compatible. Handle showing, both sooli offers, give, return, three-player play and ordinary play through legal engine actions. Reuse existing card/action conversion after parity tests.

Policy slots accept arbitrary named research factories, including current W128 on both opposing seats. Seat membership remains fixed; assignments swap which team has candidate versus baseline. Preserve the original four rotations and two assignments as an explicit instrument. Dealer0 remains the continuity instrument; a separate four-dealer design changes the population and is named accordingly.

New rows retain cluster, arm, rotation, assignment, dealer, initial score, ruleset, all policy IDs/snapshot IDs, terminal type, contract, soolaaja, winner, points, trick totals, next score/dealer, elapsed total CPU/wall, per-decision timing, error/fallback/cap flags and RNG scheme. Do not write actual hidden hands into live explanations.

Use task-independent seeds and environments: changing worker count cannot change policy construction histories. Parallelise at the bundle level; no sharing a mutable Env across threads. Native dispatch already uses multiple cores, so benchmark process counts before permitting nested concurrency. Default correctness tests use one process, not historical workers12.

Match caps produce **unresolved**, not draws. Report observed winners and bounds obtained by assigning each unresolved leg either0 or1. For paired policy differences, compute worst-case bounds for each leg/pair before aggregation, preserving pairing. Midpoint .5 may be shown as a descriptive sensitivity analysis only; it is not an unbiased match-win estimate. A practical candidate is not promoted while unresolved uncertainty can reverse the conclusion.

## 3. C1: analytical control variates

### 3.1 Hypothesis and eligibility

Hypothesis: a cheap world-dependent liability contrast predicts enough of the expensive paired NOLO-discard contrast to reduce estimator error or runtime. It is not a hypothesis that the old liability rule is itself a better strategy.

Eligibility: current phase ordinary TRICK_PLAY, contract NOLO, actor void in the led suit, at least two legal actions. No sooli, bids or leading decisions in version1. Use the exact current native sampling law, including its documented omissions. Strengthened fallback inference is a separate candidate.

Let a0 be a cheap deterministic reference chosen from the actor's observation alone. Recommended first implementation: the clone's preferred legal discard, evaluated once with the declared engine-action tie order. Charge its cost. Do not run a whole W128 search merely to select a0. Reference selection and all fitting must be independent of the fresh estimation batches.

For the fixed current continuation target Y, set `D_a(w)=Y_a(w)-Y_a0(w)`. The deployed candidate returns the argmax of estimated gaps, using the original ordered legal actions to resolve ties. Reference gap is exactly 0.

### 3.2 Per-layout proxy

The proxy is NOT `expected_ducking_tricks(observation)` copied identically across worlds. For each supplied complete remaining layout and candidate a, remove a from root's current hand. For each suit, sort remaining root ranks r_i and other-seat ranks q_ji from low to high, ordinary ace high. For each root index i, count 1 only if at least one other seat has an ith card and root's r_i exceeds all available q_ji. Sum over suits to obtain L_a(w). Define `G_a(w)=-(L_a(w)-L_a0(w))`.

Other seats include the partner. This own-hand liability is only a proxy for partnership equity; covariance is to be measured, not assumed. It ignores future cross-suit leads and the unresolved current trick. At a discard root cannot win that current trick, but its consequences for others are not claimed to be modelled.

Cards already played are absent. Discard a is removed, not reassigned. Actual unequal capacities are retained. Multiple public shown cards may share a suit. Validate against E022-E024's brute-force contested-round oracle on small complete layouts, not against the old analytical mean under different conditioning.

### 3.3 Estimator, fitting and allocation

Draw independent cheap and expensive batches from the SAME implemented sampler:

```
muG[a] = mean(G[a] on M cheap worlds)
res[a] = mean(D[a] - beta*G[a] on n expensive worlds)
gap[a] = beta*muG[a] + res[a]
```

A single frozen scalar beta is the first implementation. Fit it on separate development deals using within-case/action centred covariance, so between-hand strength differences cannot manufacture correlation. Pool with declared equal-case weights; beta0 if the proxy variance is zero. More elaborate beta(I,a) models are separate follow-ups. Fixed fitting data means beta can be held fixed conditional on training for the unbiasedness derivation.

For each action, conditional expectation is E[D_a]. The variance is `A/M+B/n`, with `A=beta^2 Var(G_a)` and `B=Var(D_a-beta G_a)`. Cost includes sampler and proxy costs for cheap worlds and the full paired continuation batch for expensive worlds. With measured batch costs cG,cD and fixed budget, the continuous ratio is `M/n=sqrt(A*cD/(B*cG))`; round under prespecified integer minima/caps and use a conservative aggregate over nonreference actions. Degenerate A/B cases must be handled explicitly.

Do not choose M/n from favourable validation outcomes. Calibrate them on the planning split. A small prespecified allocation grid on planning data is an acceptable simpler version. No sequential early stopping, action elimination or fixed positive deviation margin in C1v1. Those change the experiment.

If a deadline prevents completing a prespecified batch, return the declared fallback and record the failure; do not treat an outcome-dependent set of completed worlds as the original fixed-sample estimator. The timeout policy is a separate operational component.

A two-level implementation retaining independent batches is deliberately chosen for simple validation. A nested or adaptive variant requires its own variance and stopping analysis.

### 3.4 Correctness tests and measurement

Required tests: exact finite-law expectation with correct, wrong, constant and reversed proxies; beta0; sample-stream independence; zero reference gap; sign for both teams; unchanged input world arrays; action ordering; nonconstant proxy fixture; unequal hand sizes and repeated same-suit shown cards; strict separation of truth from policy inputs; explicit-world versus traced old NOLO search parity; post-call shadow advancement parity; all errors retained.

Use disjoint FIT, PLAN, SCREEN and CONFIRM base-deal namespaces. All observations and worlds from one source deal stay in its split. Suggested small planning sizes are 128 base deals and a 256-base-deal screen, subject to explicit resource caps; these are not powered confirmation sizes.

Primary mechanism endpoint: mean paired-action-gap MSE at equal total candidate CPU, averaged within case then within base deal. Use an independent high-budget reference. Independent reference noise cancels in EXPECTATION in a difference of MSEs; it does not cancel from their ratio. Estimate/subtract its variance using independent reference replications before claiming a 20% ratio reduction, or use an excess-MSE difference with a clearly stated estimand.

Also evaluate selected actions on fresh common worlds independent of selection. Compare candidate versus W128 selected action directly; do not call the reference argmax a known optimal action. Report recommendation disagreement, paired selected-value difference, estimator variance, branch frequency, CPU/wall and instrumentation costs.

A 20% local MSE reduction is not a 20% program speedup. Estimate branch CPU fraction f and within-branch saving r; total direct saving cannot exceed f*r before overhead. Full-game computational promotion requires 20% total CPU reduction and equity noninferiority at margin -0.0005 on a separately fixed population, OR a separately powered strength benefit. Reusing saved time for larger search is a new variant, not bundled into the first speed result.

## 4. C2: blind bidding conditional on consequence

### 4.1 Fixed-policy mechanism first

Implement C2 initially with deterministic encoder-2 clone predecessors and explicit frozen continuation settings. This is a MODEL experiment, not a recreation of every current search-predecessor history.

For focal reveal position k, E is the event that all earlier policies bid NOLO on their own masked precommit observations. Under a fixed simultaneous model with no consequential unused-call side effects:

`Q(a)-Q(b) = E[1(E)*(U_a-U_b)]`.

At an actually reached call the relevant conditional law is p(world|I,E); for comparing blind commitments the unconditional indicator-weighted gap includes reach probability. These targets share an action ranking when P(E)>0 under the stipulated model, but their units differ. Never report a conditional gain as unconditional gain.

### 4.2 Sampling and prefix reconstruction

For each fixed-W prior joint layout with the focal hand fixed:
1. Build legal predecessor observations from each predecessor's own original hand, public precommit context and reveal-position count. Earlier hidden bid contents are absent. Do not use focal hand features in those policies.
2. Query only predecessors needed to evaluate E, on isolated deterministic policies. Stop at the first RAMI. An out-of-event row has exactly zero CONTRAST, not a fabricated game outcome.
3. If reached, retain the actual chosen NOLO cards. Reconstruct a v3 pre-focal state by applying that legal prefix in evaluator-private state.
4. Apply each focal alternative to a copy and evaluate the frozen continuation on common joint worlds. No opponent changes its prior blind declaration when the focal candidate changes.
5. Accumulate indicator-weighted contrasts using denominator W, including zero-hit batches. Record hit counts and offer/sooli branch work.

Create a precommit-observation helper using the engine/native field definitions, not dummy true bids supplied to the policy. Nonreached focal contexts are offline counterfactual queries, not claims of an actual engine call. No skipped live calls should be added merely to estimate a denominator.

### 4.3 Ablations

Compare three distinct modelling changes on independent valuation worlds:
- `F`: existing forced-prefix reconstruction with uniform eligible NOLO cards.
- `R`: event weighting with predecessor pass decisions, retaining the old eligible-card generation for reached worlds.
- `RC`: event weighting with the predecessor's actual chosen cards.

All actions are ultimately evaluated under the same explicitly specified fixed-policy target. R isolates reach weighting; RC-R isolates shown-card selection. Forehand has no predecessor and is a negative control when all other code/streams are held fixed. Never-pass and all-pass policies are exact tests. Zero-hit samples are not resampled until favourable.

### 4.4 Stateful search extension

Search-predecessor modelling requires C0 forks and a documented reached-call schedule. Calls made only for inference must not mutate the actual predecessor. Cache keys include predecessor-local complete observation, model/configuration identity, legal order and RNG state. Cached literal calls must reproduce any required state advancement.

Keep the actual as-is call-suppression process intact for full-game evaluation. The mathematical cancellation identity is not automatically an end-to-end statement when changing computation changes future policy state. Report a reach-model improvement and a full-policy improvement separately. Do not ask all four mutable agents for unused bids and describe that as an unchanged baseline.

Primary screen target: +0.001 surrogate equity per blind commitment under the stated predecessor population. Power by base deal/seat-stratified paired variance, with all latent completions clustered. Confirm predecessor pass/card calibration against actual search forks before integrating. Then evaluate natural v3 games against named searching opponents; preserve score and reveal-position strata and unconditional reach frequency.

Mandatory fallback exclusions are NOT part of C2v1. They are an independent lawful-information repair described in section10, with special exchange handling.

## 5. C3b: exact utility-equivalent stopping

Implement this before attempting a large C3a transition experiment. It changes computation rather than the analytical valuation target.

### 5.1 Certificate

For an ordinary rollout state, let t0 be Team0's completed tricks and r=13-completed_tricks, including the incomplete current trick if any. Every final Team0 trick count lies in the conservative integer set `{t0,...,t0+r}`. A tighter independently proven bound may be added later; a superset is safe but less effective.

For every k in that set, call the SAME ordinary scoring transformation as E007 on a private copy, then E004's next-score/dealer and terminal-equity computation. Include RAMI declarer's identity and stolen-RAMI doubling. Compute the existing signed float32-rounded equity delta. If every feasible-superset result has the same finite target value, return a `UtilityCertificate(value, candidate_final_trick_range, model_id)` and stop further evaluation of this row.

This works beyond score48. At48 it still requires the eventual winner to be fixed, unless both possible results genuinely share the same target value. Being at48 alone is not a stop condition.

Do not manufacture a particular winner, trick total or next score when only utility is fixed. A utility-certified row is an abstract evaluator result, not a completed authoritative game. The real game must still play all ordinary tricks. Terminal statistics for certified rows must be marked unknown where not implied by the certificate. Add an exactly-once utility accumulator, not a fake PH_DONE with undefined outcome fields.

### 5.2 Equivalence and cost

Version1 applies only after a rollout is already ordinary, where no future sooli can arise. Keep all root sampling intact. The certificate is valid for each stopped row regardless of its continuation choices. Whole-evaluator bitwise parity additionally depends on batching: removing rows can change native MLP batch shapes and near-tie float results in OTHER rows. Test this explicitly. A row-level mathematical certificate is not, by itself, proof of whole-program finite-seed equality.

Start with a trace-preserving implementation and original batching for unaffected rows where feasible. If stable per-row numerical behaviour cannot be established, label the resulting variant as target-equivalent with a separate batching change, and test the full candidate empirically; do not claim every move is bit-identical. Do not disable correctness tests merely to obtain a speed number.

Test all legal score states, both contracts/declarer teams, ordinary partial-trick bounds, both winners at48, resets, overshoots and a misleading score48 case with uncertain winner. Compare certified values to exhaustive actual tiny continuations and the old evaluator. Report eligible-row rate, solver calls avoided, CPU and branch coverage. Existing sooli survival/offer early exits get no new credit (E008/E010).

## 6. C3a: policy-specific match-transition evaluation

### 6.1 The blocked assumption and a bounded alternative

The literal current process is not a 100-state score/dealer Markov model (E002/E004/E020). Do not silently cold-reset every simulated row.

There is, however, a concrete **proposed state analysis** worth implementing. Under the audited default factory, each search Env appears to have only three reachable sooli-setting tuples:
- C: cold `(belief=0, return_pi=0, play_heur=0, lambda=0)`;
- O: after an offer `(17,0,1,0.3)`;
- P: after searched give/play `(17,0,0,0.3)`.

This is a deduction to validate against all setters, forced/heuristic branches, main/show-searchers, overrides and construction/restoration paths. It is not an audited global theorem. Preserve C until it is actually left. Never assume all seats have reached O or P.

If these are the complete decision-relevant modes for the pinned factory, and future algorithmic random draws are modelled as independent, an augmented state is `(score25, dealer4, mode_for_each_seat)`: at most 100*3^4=8100 nominal states. Fixed policy IDs are part of the kernel identity; active C5 options expire at a deal boundary. Extra show-searchers or configurable policies invalidate this count. The recurrent subset may be smaller, but do not assume that cold states disappear with probability 1.

This preserves inherited configuration but replaces literal PRNG-bit evolution with an independent-randomness policy model. Name it `C3-marginal-RNG-mode-model-v1`. It is not B0's exact finite-seed machine and does not authorise a live initialisation repair. Validate its predictions against actual fresh complete B0 matches; model discrepancy remains possible.

### 6.2 Implementation gates

First build a pure transition solver and deterministic mode-transition tests. Enumerate an over-approximation of reachable mode states from source branches and test representative cold/offer/give/play/forced/heuristic call sequences. Record what facts establish state sufficiency and what remains an independence idealisation.

Only after a state-sufficiency report passes may a row sampler run for that model. Initialise the exact declared mode state, score and dealer; use independent policy random streams under this model, then preserve within-deal setting transitions. Do not sample arbitrary current rows by silently using cold agents.

A small observation-only clone kernel with 100 states can be a solver/instrument test. It is not a substitute for the current search pairing. A reset-policy kernel is likewise a separately named model, not an undocumented fallback.

No dense 8100-square inverse is needed. Store sparse row transitions. For small tested systems use a direct solve. For larger systems use a sparse solve or lower/upper value iteration:

```
lo_0 = 0; hi_0 = 1
lo_next = r + P*lo
hi_next = r + P*hi
```

For a valid known substochastic kernel these give truncation-based bounds. Floating numerical error and uncertainty in estimated P must be reported separately. If the gap does not contract or a row is unobserved, report unresolved. Do not invent pseudocounts or clip values into a plausible-looking answer. A fitted kernel needs absorption, conditioning/residual and row-coverage diagnostics.

### 6.3 Estimand and inference

For fixed P and immediate Team0 absorption vector r:

`v = (I-P)^(-1) r`.

For two identified policy pairings:

`vC-vB = (I-PC)^(-1) * [(rC-rB) + (PC-PB)*vB]`.

The intended starting state is score0-0, declared dealer and the declared initial mode vector, usually all cold for fresh-match evaluation. Do not average over a stationary mode distribution that has not been established.

Use paired decks across rows/arms only with full dependency bookkeeping. Bootstrap each shared deck bundle as one object, including all sampled rows/arms. Adaptive allocation to important rows uses planning data or a separately valid analysis; do not repeatedly add samples until a conventional interval turns favourable.

Primary resource hypothesis: equal match-win precision at no more than half direct-match CPU. Screen state count, cost per row and projected precision before sampling the full reachable graph. Independent direct v3 match pairs test a predeclared model-agreement tolerance; wide overlapping intervals are not agreement. Replacing the agent's equity table using a fitted kernel is a later separate playing candidate.

Stop the kernel branch if the augmented model is not sufficient, sampling cost is excessive, empirical rows remain unidentifiable within budget, or direct-match discrepancy exceeds the declared tolerance. C1/C2/C3b/C4/C5 can continue without it.

## 7. C4: joint, information-legal sooli exchange

### 7.1 Objective and population

Freeze offer selection and the later playing-policy functions. Select fresh v3 pre-give states accepted by that frozen offer policy, with source-deal IDs, rejected-offer denominators and legal controller snapshots retained. Do not use old v2 selected banks as confirmation (E030/E037). Existing `offer` bytes may support development after manifest/ABI checks; post-return `start` alone is insufficient to reconstruct an unselected population.

Let W be an offline complete accepted pre-give state, H the giver's original13 cards, P the partner's original13 cards and h the permitted public context. Giving g in H and returning r in P produces a legal exchanged state, with r!=g automatically if the original deal is valid. Receiver physically has P union{g}, but its legal return mask excludes g.

Policies are decentralised:

`E_theta(g | H,h_giver)` and `R_phi(r | P,g,h_receiver)`.

No controller selects both using H and P at deployment. The offline objective is expected actual survival under the frozen legal playing controllers. The transferred card is both an asset and a possible message; information transmission alone is not the objective.

### 7.2 Feature and model design

Use separate stage-specific 52-card output heads, not the ordinary 156-action head. First implementation: Python/PyTorch research scorers with two hidden layers of128 and GELU, fixed architecture and recorded initialisation. Derive input width from a versioned feature schema and assert it at load; no guessed fixed dimension.

Features are actor-local and explicit: own original52-card bitmap; public shown-card identities/owners/order/declarations/verbal flags; accepted/declined offers and soolaaja/declarer/seat/dealer identities; score; ruleset; stage; and, for receiver, given-card identity. Include explicit ace-low rank encoding and suit counts if used. Receiver reconstructs P by removing g from its legal14-card hand; it never consults offline truth. Do not use full-world tensors as a convenience and trust a mask to hide them.

Keep physical suit colours because bidding legality distinguishes red and black. No broad suit-permutation data augmentation until its invariance is proven for the entire context. Neither model receives seeds, data IDs, withheld outcomes or the giver's remaining12 cards through receiver features.

A switch-off wrapper must exactly delegate to the old policy. Initialised neural scores need not equal the searched giver; do not claim zero-initialisation reproduces W128. Optional imitation warm start is labelled approximate. The old return heuristic may be represented explicitly for a behaviour-cloning control. Native model export is deferred until Python-only correctness and benefit exist; the current native Mlp is not automatically compatible with this new head.

### 7.3 Counterfactual payoff tables and legal continuation

For a development accepted state, an evaluator can form `T_W[g,r]` by applying legal exchange actions and playing to an actual sooli outcome with masked frozen controllers. An exhaustive table costs169 full continuations, not169 cheap scalar values. Record that cost before deciding table coverage.

Each continuation starts from a matching playing-controller snapshot. For a mechanism-only factorial test, execute old give/return calls on forks as needed to establish their baseline computational advancement, then override the exchanged action. Later play uses those controlled post-exchange snapshots. These shadow computations count toward CPU. A natural candidate without shadow calls is a separate full-policy/latency variant.

Perfect-information survival may be a labelled development proxy, never the primary outcome. If inexpensive rollout policies generate training labels, compare that teacher explicitly and validate all finalists against fixed strong search defence/solo play. Do not call proxy survival an actual survival improvement.

Store reusable tables only under complete policy/model/settings/seed/ABI identity. A changed controller invalidates the table. Keep independent continuation randomness for final validation rather than selecting and confirming from the same noisy table.

### 7.4 Joint training and message-selection weighting

The receiver's training distribution depends on the giver. Enumerating all possible g uniformly and training R without this selection weighting does NOT train it to interpret the learned convention.

For full enumerated tables, optimise the paired objective:

`J(theta,phi) = mean_W sum_g E_theta(g|H_W,h) sum_r R_phi(r|P_W,g,h) T_W[g,r]`.

The network inputs remain legal even though the offline objective uses complete W. Differentiation through the finite legal sums is possible for soft policies. The first implementation may use alternating supervised policy evaluation/improvement instead:

1. Freeze E. Receiver targets for a candidate r are weighted by E(g|H_W,h) over development worlds compatible with receiver input. For g sampled from proposal mu rather than enumerated, use declared importance weight E/mu with support coverage; do not silently clip away missing support. Cheap zero-weight branches need not be evaluated.
2. Freeze R. For each giver action g, evaluate the receiver's chosen or soft-mixture return on the same paired table. Train the giver on those action values/advantages with own H+h only.
3. Use at most a prespecified small number of alternations (suggested initial cap 3), with separate development validation. Choose the checkpoint before independent confirmation.
4. If training uses soft exploration but deployment uses greedy actions, freeze the greedy giver and recalibrate/evaluate the receiver under its induced message distribution. A soft-policy result does not validate its greedy conversion.

A fixed small supervised alternative regresses centred action survival advantages plus a predeclared behaviour-cloning anchor. Record loss scales and target uncertainty. Do not introduce a large reinforcement-learning campaign, a general owner network or recursive expert iteration inside this workstream.

Do not infer that an unseen message is meaningful. Implement a declared out-of-distribution return fallback and measure its frequency. Offline continuation labels under a single deal do not grant a model knowledge of that deal's hidden hands; generalisation must be assessed by whole-deal holdouts.

### 7.5 Four-arm test and defence

On identical fresh accepted pre-give states evaluate:
- old giver + old returner;
- new giver + old returner;
- old giver + new returner;
- new giver + new returner.

All arms share the declared offer and play functions and controlled lifecycle. Primary contrast: new/new minus old/old actual survival. Report interaction `J11-J10-J01+J00`. To claim the joint convention exceeds either isolated improvement, test J11-J10 and J11-J01 with simultaneous inference; do not select the better single arm on the same data and ignore selection uncertainty.

Initial meaningful target: +0.03 survival probability per accepted sooli. Sample size depends on paired discordance and source-deal clustering, not four independent binomial calculations. Record acceptance rate separately; do not multiply into a full-game strength claim without natural v3 evaluation.

Include strong as-is defenders. A convention-aware robustness arm may integrate exchange likelihood over all compatible latent original hands and (g,r) pairs while keeping actual exchange cards hidden. The likelihood must include giver and returner policies and the known selection population. The native sampler's uniform-exchange/tilt/rejection mixture does not expose a ready-made proposal weight (E005); do not multiply arbitrary network probabilities onto it and call the result an exact posterior. Before launching that arm, derive proposal/target weights or use an independently validated generative sampler. If too expensive, report this robustness test as unresolved rather than calling the fixed-defender result general strength.

Required adversarial fixtures include: a message that conveys information but transfers a harmful card; a rare message misinterpreted by receiver; a shown card privately exchanged; a defender with identical legal information under two different exchanges; legal 13/14 intermediates, 13 dead cards, 39 active cards, ace-low comparison and immediate solo loss. A no-message ablation must not accidentally reveal g through a supposedly hidden legal mask; specify precisely what information is suppressed and what legal action mechanism remains.

## 8. C5: actual-root information-consistent three-card option

### 8.1 Eligibility and prior

Version1 triggers only when the real current actor is about to lead an ordinary trick, all four seats hold exactly3 cards,10 tricks are complete, and there are at least2 legal root actions. Root is therefore the leader of this three-trick suffix. Mid-trick eligibility is a separate extension.

Count complete hard-feasible support before enumeration. Initial maximum100 worlds, with deterministic node cap100000 and a separately configured wall deadline; these are conservative starting design caps, not measured safe latencies. Only complete enumeration qualifies. A sampled or truncated support is not an exact option.

To avoid attributing stronger fallback inference to information consistency, initially require agreement between the strict engine hard-constraint support and the native-law constraint support. It is sufficient to prove equivalence for that case, e.g. no active omitted fallback restrictions; otherwise compare complete sets under the cap. If they differ, record `CONSTRAINT_MODEL_MISMATCH` and fall back. A later strict-law extension is a separately identified intervention. This restriction may reduce coverage; measure it.

Reuse E025/E027/E055/E056's counting ideas, not their adversarial objective. Make a v3-preserving reconstruction that retains public sooli-decline history for ordinary RAMI, ruleset, score, dealer and all public plays. If unused masked commitments require canonical evaluator-only completions, prove they do not alter any later legal observation/policy input. Do not force an invalid full replay merely to satisfy an adapter.

### 8.2 Fixed other-seat policies

First use the deterministic native encoder-2 clone on the other three seats, including partner. Feed each its own projected legal observation, with canonical native legal-ID tie order. No root hand, root posterior, sample index or world ID reaches those policies. A fixed-policy model is deliberately narrower than actual searching opponents.

The root option may choose its current card and one subsequent non-forced card at each later information set; its last card is forced. It never chooses the partner's actions. Use current frozen equity-delta utility, not legacy signed score/52 and not worst-case trick security.

### 8.3 Weighted information-group algorithm

For each root action a:
1. Apply a to every support world with its prior mass.
2. Advance the three fixed policies until root next acts or the deal ends.
3. Group all surviving histories by the root's COMPLETE legal observation plus its permitted own option memory. Original hand/history, legal order and action history are part of the key; world identity is not.
4. For each group, evaluate every common legal b, integrating all group worlds with their conditional weights. Advance the fixed other-seat policies and the root's forced final card to the terminal outcome.
5. Select one b for the whole group; sum group mass times its optimal conditional value, plus already terminal masses.
6. Choose the root a with largest total value, using the declared root tie order. Store only the selected option's reachable key-to-action map and model/state identity.

`Q(a) = sum_o mass(o|a) * max_b E[U|I,a,o,b]`.

Deterministic observed other actions update weights by 0/1 likelihood; stochastic fixed policies need explicit likelihood factors and are outside version1. Do not reset the posterior to hard-uniform on the next real root turn. Retaining an exact contingent map is sufficient when it contains all reachable keys; retaining weighted histories allows verification and consistent re-solving.

On an unexpected information key, support failure, model mismatch, timeout or incomplete option construction: discard the option, use the original baseline fallback and record the reason. Never make a universal optimality claim after an off-model fallback.

### 8.4 Comparators and certificates

There are three distinct diagnostic values:
- old root action followed by the newly optimised future option;
- old W128 at every remaining root decision, with its forked own state;
- the complete root-optimal option against the frozen other policies.

Only the second is the complete current-root-policy comparator in this fixed model. Replicate the same root initial snapshot across indistinguishable worlds so its later RNG/policy state cannot encode the world. Batch these calls by full root information key/state when proven equivalent.

Under complete support and fixed other policies, the root-optimal option's value is at least that of every feasible root policy under the SAME model. A root-only clairvoyant optimiser gives an upper bound when the other policies are unchanged. The existing DD solver changes the other seats' information/control too and is not this bound.

Tests must include one negative candidate-action-minus-reference gap, positive gaps and an optimum-minus-feasible-policy gap that is never negative. Use two indistinguishable worlds with conflicting preferred b, then a companion observation that distinguishes them. Verify nonuniform posterior weighting, key-collision rejection, two-card forced-final-action control and an off-support fallback. An exact local model certificate is not an expert-human or worst-case team guarantee.

### 8.5 Cost and validation

Place the module outside per-world root search. At most one eligible option intervention per team/deal in the first whole-game diagnostic, preventing double counting; later simultaneous teammates' options are a separate composition test because each option initially assumed a fixed partner.

Use a small screen such as 64 eligible positions collected under a declared public gate. The +0.001 equity/option target is conditional on eligibility. Count all source deals and gate failures. The actual deadline must reserve measured baseline-fallback time; if no reserve can satisfy the experience target, disable the option. Initial 100 ms internal soft deadline is a design cap, not a latency guarantee. Meter deterministic node budgets as well as wall time.

First validate exact option values against an independently written tiny enumerator. Then compare against full W128 root continuation under fixed clone others. Finally evaluate actual searching teammates/opponents in fresh whole deals. An option that is optimal under clone continuations may lose against search; that is model mismatch, not a contradiction.

## 9. Experiment contracts and promotion

### 9.1 Populations and units

Default principal opponent for new incremental strength is the same frozen W128 family, on both opposing seats. Keep the old incumbent as a separate continuity control. Neither implies human transfer. A mixed human-partner deployment objective would require its own population and is not inferred from the source packet.

Maintain separate score instruments: historical0-0, a stated diagnostic grid, and a score-visit distribution measured from an independent baseline match corpus. The old `scores=uniform` samples zero with probability 1/13 and each nonzero state1/26; do not label it uniform over25states (E013). Store the exact weights. Do not pool score scales or assign an average equity gain a universal match-win conversion.

For every run fix: candidate parent identity; opponents/partners; lifecycle; one changed mechanism; population; endpoint; unit; cost target; failure rule; seed namespaces; split; sample-size/precision rule; final analysis and compute caps. A random seed is not by itself a bank split; provenance keeps all derivatives of a deal together.

### 9.2 Precision and stopping

For paired cluster SD s and desired effect delta, `n approximately 7.85*s^2/delta^2` is the conventional two-sided 5%,80% power planning approximation. For 95% half-width h, `n approximately (1.96*s/h)^2`. These are not substitutes for pilot variance, binary matched-outcome calculations or simulation for kernel/ratio endpoints.

Planning samples are not final significance samples. Freeze a candidate and its analysis before independent confirmation. Use one final look by default; a prespecified valid sequential design requires its own implementation. No ordinary 95% interval peeking followed by stopping when positive.

A strength study powered at+0.001 may test positivity; it does not prove the effect exceeds+0.001 unless its interval clears that threshold. A speed/noninferiority claim requires both its speed endpoint and noninferiority endpoint. A nondetectable effect is not a proof of equivalence. Stop for prespecified practical futility when an upper bound excludes a meaningful benefit or confirmation precision is unaffordable. Label budget-exhausted results unresolved.

If several candidates reach confirmation, either nominate one from development data or prespecify a multiple-comparison procedure across all confirmatory claims. Do not silently select the best of five on a reused bank. Multiple C4 pairwise superiority claims also require the declared simultaneous analysis.

### 9.3 CPU, latency and failures

Account for total CPU over every child process/native thread, end-to-end wall, warm/cold load, model loading, sample-only shadow work, proxy work, retained reference computation, peak memory, native task count, and p50/p95/p99 decision latency. Diagnostic reference searches are reported separately from deployment cost but not hidden from total experimental budget. Equal worlds is not equal CPU.

CPU bootstrap ratios must preserve paired base-deck bundles. Avoid reporting p99 from a handful of timings as a stable system estimate. Runtime caps, resource failures, unsupported cases and fallbacks are data, not deletable inconvenient runs.

Time-based caps may induce a different deployed policy from a deterministic node cap. Describe both, record cold/warm cache context, and do not reuse a runtime advantage obtained from one arm's warmer caches as an algorithmic gain.

### 9.4 Composition and deployment

Promote one mechanism at a time to a new immutable research parent. Test interactions where mechanisms touch the same world evaluator, utility, rollout policy or state schedule. C1+C3b may interact through cost/allocation; C2+C4 through sooli outcomes and bid utility; C5+C1 through late-game dispatch; C3a recalibration changes every action-value target.

A successful local endpoint is only eligibility for a full-game test. Deployment requires independently authorised server/profile/persistence/client changes and restore tests. Never rename old persisted policies or let an old room silently reconstruct a new algorithm. Existing durable action logs do not recreate historical native controller state.

## 10. Separate engineering changes, not hidden research gains

Record the following independently, with source links and tests:

- `E-setting-init`: v3 ordinary-path sooli initialisation. Explicitly deferred by owner; do not apply to B0.
- `E-fallback-support`: mandatory show-tier exclusions missing in native sampling. Apply original-hand deductions; private exchanges require a latent transfer model. Behavioural ducking remains soft, not a hard exclusion.
- `E-v3-runner`: the new v3 instrument. This changes measurement capability, not playing strength.
- `E-v3-reconstruction`: version-preserving hypothetical replay. Scope narrowly; do not modify dirty legacy research files without permission.
- `E-rollout-error`: checked propagation of illegal native sooli actions instead of zero-utility completion. Detect first, repair separately.
- `E-binary-provenance`: separate source/build/installed identities, never fabricated historical equivalence.

These issues may deserve practical priority, but a useful repair must not be falsely credited to a novel mechanism.

## 11. Deliverables, gates and execution order

Each task writes: source diff or new files; exact test commands; test outputs and failures; source/artifact hashes; parent candidate ID; assertions actually checked; known limitations; next dependency. Distinguish READY, IMPLEMENTED_NOT_TESTED, CONTRACT_PASS, PILOT_READY, PILOT_COMPLETE, CONFIRMATION_PASS, REJECTED, BLOCKED and NOT_AUTHORISED. Do not describe readiness as success.

Recommended sequence:
1. Verify source/import/build identities and implement legal records/replay forks.
2. Validate F01-F06 or mark a fixture unavailable within its cap; never invent reachable states.
3. Add explicit-world ordinary NOLO evaluation with disabled-mode parity.
4. Implement and unit-test C1; build the paired v3 runner and pilot manifests.
5. Implement C3b certificate tests; then C2 clone-model prefix/reach tests.
6. Implement C4 stage scorers, weighted joint objective and four-arm replay; no large training yet.
7. Implement C5 strict/native-support agreement gate, v3 reconstruction and exact small option tests.
8. Produce C3a mode/state-sufficiency report and pure solver; hold row sampling if assumptions fail.
9. After explicit budget approval, run C1 planning/screening first; use its findings to decide further experiments. Independently test promising survivors; reject or park the rest.
10. Compose confirmed interventions with one-at-a-time identities and only then consider separately authorised deployment.

The execution DAG and test catalogue accompany this specification. The main implementing LLM should not request another broad audit before starting: the source-level seams are known. A genuinely missing runtime fact becomes a precise gated task. Historical process state may be unrecoverable; do not block all new reproducible research on recreating it.
