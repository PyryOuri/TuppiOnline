# Tuppi design handoff — static audit, 25 September 2026

Authoritative purpose: enable precise later implementation plans for C1–C5 without access to this workspace. This is an evidence audit, not candidate implementation, performance measurement, deployment approval, or proof of improvement. All proposed interfaces and fixture recipes below are labelled PROPOSED. All existing tests are **present, NOT RUN** in this audit. No playing-strength numbers were newly measured.

## 1. Executive findings

The current AI factory is W128 with a six-trick double-dummy tail, the small incumbent clone, and the incumbent-derived equity model. The AI checkout is `4220f249e351905deb3a3754de812a01acf152d7`. ENGINE is the separate v3 checkout `1347153f7d6e7bed95edddce9d35d28a3df91750`; RESEARCH is `622d5599318e4f1b2a82ef53bfc141970edc24de` with substantial uncommitted NOLO, valuation and server work. They are not interchangeable installations. The historical 25 September description is consistent with the present factory, but does not identify a complete process-state snapshot. No archived native binary or historical process state was established. Historical claims therefore remain reported claims, not reproducible identities merely because a commit agrees.

The model is encoder **2**, width 256, two residual blocks: input width **1951**, not the generic 1223-feature description applicable to encoder 1. The model file SHA-256 is `38737c9042695a4c960157fb77a8d17f308c5773899c2ec0c65b0d20546324f1` (3,224,261 bytes). The equity JSON is `1496f77104f411c5cb55e2cef4573a10aead59acbd643261b755886bfeb60b91` (2,112 bytes). The installed arm64 native library is `02d9b4fad98ebb342e12cd9ecb4723aaee1406c6c6b539a1dc4a5b2b002c1ab8` (121,024 bytes). Source hashes are separately recorded: binary correspondence to this exact source is **unproven**, not inferred from timestamps or exported symbols.

There are useful implementation surfaces, but none of the five requested methods is already validated as specified:

- C1 has a complete analytical oracle and a native per-world output API. The API still samples internally; an explicit-world input hook is missing. The old analytical mean is not the deployed sampler's expectation.
- C2 exposes a real conditional-decision mismatch. Reached AI calls reconstruct forced earlier NOLO cards; they do not estimate the probability that actual predecessor policies pass. The cancellation identity is not automatically valid for persistent computational state.
- C3a's naive 100-state reduction fails for the literal current process. C3b remains plausible, but sooli already has several early-exit optimisations; those cannot be claimed again.
- C4 has legal private exchange observations and pre-exchange bank-generation code. Current neural features/action heads do not implement legal learned exchange scorers. Existing accepted banks are selected by an older offer instrument, not a fresh paired-convention confirmation population.
- C5 has exact-support and information-group infrastructure for a different, adversarial NOLO objective. Reuse requires ruleset-preserving reconstruction and a new expected-value option evaluator.

Engineering issues are distinct from research: v3 omits ordinary-path sooli configuration initialisation; native sampling omits mandatory fallback exclusions; the existing complementary-match runner defaults to v1 and handles only ordinary phases; legacy hypothetical replay does not pass v3 ruleset identity. None was repaired. E058 explicitly records the owner’s 24 September decision to leave the v3 settings issue unchanged. The normative v3 configuration (E057) defines project-specific legality; source comments claiming generic uniform feasible sampling or identical self-play are narrower in practice than their wording suggests, as documented below. In addition, the native sooli error path can terminate a rollout without recording utility; this is a static error-handling concern, not evidence that it occurred in production.

Inspected scope comprises the AI factory/search/native core/samplers/solvers/equity/evaluators/reviewer/training loaders/bank generators; current engine rules/observations/serialization/match/server construction; research valuation/support/security/constraints; and narrow client profile compatibility. It excludes private rooms, human records, sealed contents, broad UI code and raw training banks. Repository instructions and architecture boundaries were inspected; no applicable AGENTS.md was located by the scoped workspace search. Dirty files indicate collision risks, not knowledge of which person or process owns active work.

## 2. C0 answers and shared contracts

### G01–G05: identity, information and search

**G01 | ESTABLISHED-IN-CODE, binary provenance UNKNOWN | E001–E004, E011–E015, E020, E035, E050, E059–E062 | Pin entrypoint plus construction history, not “W128” alone | historical binary/process snapshot unavailable.** `best_agents(seats=range(4), worlds=128, seed=0) -> dict` loads one Python model/table then separate SearchAgent/Searcher/native Env/Mlp per seat. Tail `dd_left=6` means `13-floor(n_played/4)<=6`, including an incomplete current trick. Bid search is enabled. Effective best seed is `seed+2*seat`: factory adds seat, SearchAgent adds it again. Explicit `search:` specifications default to `w=32,dd=0,show=0` and their seed path differs. Live `tuppi_ai_search_v1` constructs best agents; deal evaluation `--checkpoint best` does too, but ignores a separately supplied equity file for candidate construction. Replay/review has distinct budgets/configuration initialisation; review defaults W256/confirmation1024 and resets sooli settings on evaluation. It is not a literal live policy replay. A second live entrypoint, `tools/serve_human.py`, replaces the server constructor with a seat-plan wrapper: default `1:incumbent,2:search,3:incumbent`, W128 unless TUPPI_AI_WORLDS overrides, v3 rules and review enabled. It retains old profile labels, so a displayed incumbent label does not identify its actual seat policy. This differs from the native server profile selecting best for all requested seats. Actual running process environment and virtual-environment import resolution were not inspected; E062 documents the v3 environment pointing to ENGINE. Command templates require that environment, not an arbitrary system Python.

Root ordinary argmax uses engine legal-action order; native rollout argmax scans increasing integer action IDs. Give/play search put the heuristic action first to win ties. Offer accepts only when accept-minus-decline exceeds .02. Return is heuristic. Default belief is 17, exposure lambda .3, heuristic offer continuation, searched give/play. Native rollout chunk defaults32 (global setter clamps8..512), dispatch uses system concurrent queues; no fixed native thread count is exposed. Evaluation sets torch threads1 and defaults12 processes; these are not live thread guarantees. Build script records clang `-O3 -Wall -Wextra -Wno-unused-parameter -isysroot ... -dynamiclib -framework Accelerate`; no rebuild was performed.

**G02 | ESTABLISHED-IN-CODE / UNKNOWN for historical runtime state | E002–E004, E008–E010, E013–E015, E020, E058 | PolicyFork and lifecycle ledger prerequisite to exact comparisons | no supported complete snapshot/restore API.** Searcher retains NumPy RNG, mutable ctypes uint64 RNG and native environment. Native slots retain RNG and deal state; setting/cloning a deal does not copy/reset RNG or sooli configuration. `reset_all` starts matches using current RNG, not cold construction. Python globals in evaluation hold policies throughout worker tasks. Each best seat has its own mutable search environment, but process-global rollout chunk and thread-local solver caches persist. Model inference has no recurrent state; `last_values` is diagnostics, not an explicit memory of blind intent. Solvers use thread-local tables; absence of deadlines makes cache contents intended to affect work rather than exact values, contingent on solver correctness, which was not re-probed.

The v3 defect remains: `choose_action` initialises ordinary-path sooli options only for `ruleset==2`. A fresh calloc environment has belief0/return_pi0/play_heur0/lambda0. A sooli offer sets belief17/lambda.3/play_heurTrue; give or play sets play_heurFalse; heuristic return and forced actions can leave settings untouched. Later v3 bidding therefore depends on previous calls, across deals and matches while agents survive. Server restoration reconstructs agents while replaying durable game actions, not their old RNG/configuration snapshots. Evaluator rotation/arm ordering and worker assignment change histories. Separate instances prevent one seat's environment from directly becoming another's, but comparisons in one process still share global settings. A clean initialisation fix or per-deal reset is a new comparator, not the as-is baseline.

**G03 | ESTABLISHED-IN-CODE | E006–E007, E011, E016–E017, E041–E043 | Use full typed observations; neural vectors are insufficient information keys | own hidden-commit memory is not in the engine observation.** PlayerObservation includes actor/observer/team/partner, dealer/forehand, phase, ordered own hand and legal actions, shows/public shown cards, contract/declarer/leader, completed/current tricks, team trick totals, score/terminal flags, ruleset/schema/visibility and protocol refs. V3 adds `bids_locked`; sooli adds decisions, soolaaja, exchange flag, given/returned cards and three-player trick history. Nonacting seats have empty legal-action tuples. Blind observations hide all committed declarations, including one's own, until resolution; `bids_locked` gives count, not cards. The live UI's remembered submitted bid is a different information channel from this policy interface.

Ordinary lead allows any held card; follow requires led suit when held; discard otherwise permits all held cards. Bid choices use the mandatory card tiers for each declaration. Offer has decline/accept; give has13 cards; return has13 of14, excluding the received card. Exchange participants know both transferred cards when available; defenders receive neither. Historical shown cards remain public even if privately transferred. Sooli has three active hands, dead partner excluded, mandatory following, ace low for trick comparison. Ordinary ace is high. The native observation preserves public card order but not engine hand ordering/protocol identity. Encoder2 adds full ordinary trick-history planes to encoder1, but neither its156-action head nor ordinary features implement a sooli message-aware exchange policy. Tests for masking and serialization exist; no test pass is claimed here.

**G04 | ESTABLISHED-IN-CODE with mathematical-law qualifications | E005–E008, E027, E038–E039 | Name the exact sampler version and approximation; do not call it all legal information | fallback constraints absent natively; sooli rejection truncation.** Ordinary native sampling fixes own cards, unplayed public shown owners, played-card removal, proven voids and each seat's capacity. Capacity uses actual per-seat play counts, so an incomplete trick is asymmetric. Suit count allocations are weighted by combinatorial completion counts using floating log arithmetic, then cards shuffled/split. The intended base law is uniform over these constraints, drawn pseudorandomly with replacement; layouts can repeat. SplitMix/modulo and floating arithmetic are not a proof of exact rational uniformity. No importance weights are returned.

Blind v3 sampling uses own precommit hand and count/order context while suppressing hidden shows. It draws layouts first, then manufactures legal earlier NOLO cards uniformly among eligible cards, without predecessor-policy likelihood. Ordinary and sooli native samplers do not apply all public fallback-card exclusions. `test_sampler_v2` explicitly skips verbal-show cases because those constraints are ignored. Multiple shown cards can occupy the same suit; no one-card-per-suit assumption is valid.

Sooli sampling handles12/14 exchange intermediates and13-card dead hands. Participants remap known exchanges; defenders retain uncertain locations of the two relevant historical shown cards. Completion counts and compatible exchange counts determine a latent uniform-exchange prior. Mode17 combines offer-prefilter rejection with exposure tilt; tilted DP and rejection variants are distinct. Rejection is capped at2000 and can return the final rejected draw, so the default is not an exact conditional law. No external weights correct this. Conditioning accepted-offer hands on a new learned giver convention is a separate model change, not automatic in this sampler.

**G05 | ESTABLISHED-IN-CODE / MISSING-INTERFACE | E003–E004, E009, E012 | Existing per-world output is useful but does not accept explicit worlds | add one research-only input seam without altering baseline entrypoints.** For acting team t, the native value is `sign(t)*float32(V0(next_score,next_dealer)-V0(source_score,dealer))`, accumulated in float64 and averaged over W. V0 is a fitted match-win surrogate in [0,1], so Y is an equity change in [-1,1], not tricks or probability of winning this deal. Subtracting the common starting value cancels in action gaps. Terminal V0 is1/0. Table rows:0 for0–0,1..12 for Team0 scores4..48,13..24 for Team1 scores4..48; column1 means Team0 deals, column0 Team1 deals. `Equity.load` recomputes values from the stored DealModel, not from a trusted frozen table blob.

`search_world_values(env,mlp,obs,actions,worlds,dd_left,rng_state)->float64[W,K]` converts actions to contiguous int32, allocates owned NumPy output, calls synchronous C, and discards the returned means. `search_values` returns float64[K]. C takes pointers to Env/Mlp/TcObs/action array, k,w,tail, uint64 RNG, mean and optional W*K buffer in world-major order. Rc -1 is sampling failure, -2 environment too small, -3 invalid forced action. It returns no layouts, seed trace, weights, variances, terminal trick counts, score summaries or per-row errors. Searcher/native handle ownership is explicit; sharing one Env concurrently is unsafe. The initial sample loop overwrites any states preloaded via `Env.set_state`. Minimum explicit-world hook must factor that loop from the existing continuation/aggregation, preserving rounding, action order and tail semantics.

### G06–G10: replay, evaluation, data and boundaries

**G06 | PARTIAL / MISSING-INTERFACE | E003, E016–E017, E025, E028–E029 | Observation serialization is real; exact policy replay is not solved by it | v3 continuation and policy-state reconstruction need narrow additions.** `observation_to_data(PlayerObservation)->dict` is a real actor-local wire form. `action_to_data` and `action_from_data` exist; a symmetric general `observation_from_data` was not found in the inspected serialization module. Native TcObs can be encoded without true hands. `hypothetical_continuation(observation,assignment,...)->HypotheticalContinuation` rebuilds original hands from remaining assignment and public played cards, replays shows/plays, and returns research-private state. However it calls `create_deal_state` without `ruleset_id`, defaulting to v1. NOLO support subsequently compares an information key containing ruleset, so a v3 case is not established reusable. FastTrickState is a sanctioned search-local ordinary suffix, but its fields also omit ruleset and sooli/private exchange. Do not bypass containment guards by importing full state into a frozen policy. A new evaluator may keep hypothetical layouts privately and project each simulated seat's own observation, preserving original card-order conventions and allowed personal history.

**G07 | ESTABLISHED-IN-CODE, v3 match runner MISSING | E013–E014, E018 | Repair the research instrument under a new identity before confirmation | current opponent API only takes incumbent profiles.** Existing command templates, **not run**:

```text
python -m tuppi_ai.evaluate --checkpoint best --ruleset v3 --deals N --scores zero --opponent partner_aware_lead_v2 --workers P --seed DEV_NAMESPACE --out OUT.json
python -m tuppi_ai.match_eval --checkpoint best --pairs N --cap 400 --opponent partner_aware_lead_v2 --workers P --seed DEV_NAMESPACE --out OUT.json
```

The second is a v1 instrument, not a valid v3 full-match template. Deal evaluation creates one base shuffled deck per index, four rotations `hands[s]=base[(s+rotation)%4]`, dealer fixed0, and two candidate-team assignments, yielding8 games. Both teammates use candidate; an isolated decision-branch override needs a wrapper. Score is shared across arms. `scores=uniform` draws level0..12 uniformly then a side: zero has probability1/13, each other state1/26, not uniform1/25. The fixed default zero score is a different estimand. Output retains base-deal `values`, flattened game outcomes and summary mean/std/normal95% CI; the row-level score/index relationship is not fully retained as explicit transition records.

CI uses sample standard deviation of base-deal means, ddof1, divided by sqrt(n), times1.96. Failed tasks raise rather than becoming retained missing-outcome rows; no decision timeout protocol exists. Workers reuse agents across blocks, rotations and arms, so base-deck clustering removes duplicate-deal dependence but does not magically remove process-history dependence. Complete matches use shared indexed deck streams and complementary candidate teams, start0–0/dealer0, cap400 by default; unfinished legs score.5. They report pair summaries, not a complete retained per-pair transition ledger. Searching opponents cannot be requested through the current incumbent-profile-only opponent constructor. Seat-specific RNGs are not exchanged/reset with teams: complementary search self-play is not a deterministic .5 identity. Strong-search pairing and policy forks are additive instrument work.

**G08 | DOCUMENTED-ONLY for bank contents, ESTABLISHED-IN-CODE for generator schemas | E030–E034, E037, E046, E053 | Reuse development material only with its selection/split lineage | no new independent confirmation bank established.** The legacy lifecycle documents development64 streams, calibration512, score diagnostics128, and sealed promotion512 reserved/unopened at the document's time. This audit did not establish current sealed opening history by reading hidden files. No sealed payload, hidden seed, or human room was opened. Those legacy v1 banks cannot become v3 confirmation merely by relabelling.

The sooli generator stores `{index,offer:bytes(TcDeal),start:bytes(TcDeal),gain}` plus bank-level metadata: `offer` is before acceptance; `start` after give/return before play. It generates v2, clone bids, prefilters offers, accepts via searched gain>.02, then searched give/heuristic return. Its belief/config differs from current default17/.3. STATUS reports1219 accepted cases from14000 source deals; this is a selected development count, not an audited payload count or independent sample-size estimate. ABI bytes need struct/version validation. Do not infer original hands from `start` alone; the stored `offer`, if verified, is the correct source.

`gen_game_db` specifies a parked `tuppi_ai.game_db.v1` database: index,dealer,score,test flag,offline full hands, per-decision seat/phase/action/rounded values or null, terminal contract/declarer/soolaaja/outcome/points/winner/tricks/score_after. It explicitly resets game RNG/configuration and uses half-zero scores, not the live lifecycle or evaluator distribution. Shadow bids are separately reconstructed after a game, not all four actual simultaneous bids under unchanged call history. Metadata records source/native/settings, but a complete model checksum/lifecycle identity still needs strengthening. No raw database was opened or execution inferred from generator presence.

BC/distillation shards contain packed feat/mask, actions and optional search values/blueprint/phase. Existing learners randomly split **rows**, which is not valid whole-deal independence for the proposed pilots. Reports of failed belief fine-tuning and non-gaining larger solver caches are preserved as reported negatives; none supplies new C1 covariance, C2 reach probabilities, C4 paired discordance or C5 coverage. Current branch costs remain empirical pilot quantities.

**G09 | metadata inspected; hardware details partly BLOCKED | E050 and audit ledger | Budget before execution; historical timings are not capacity promises | chip/core/memory and designated-venv package versions unknown.** Available shell reports macOS27.0 build26A428, arm64 target, Python3.14.2, Apple clang21.0.0/clang-2100.1.1.101. The library is arm64 Mach-O linked with Accelerate/libSystem. The sysctl request for chip/core/memory information was denied by the sandbox; no load benchmark or permission escalation was used. Installed dependencies in the production-designated environment were not imported to discover versions. Source uses NumPy/PyTorch and the launcher selects a separate virtual environment. Historical M3 Max reports are contextual only. No current resource budget was granted for future pilots.

**G10 | ESTABLISHED-IN-CODE / DOCUMENTED-ONLY | E020–E021, E044–E049, E054 | Add isolated AI research modules; preserve frozen registries | deployment identity/schema migration remains later work.** Frozen `tuppi_agents` policies exclude random/learning stacks, private engine state, search budgets and checkpoints; provenance may not be upgraded on intuition. Exact/search layers are downstream and may not be imported into earlier frozen packages. Research-private hypotheses/worlds stay in evaluator buffers; diagnostics must not export hidden hands. These restrictions do not prohibit the already separate TuppiAI native-search path. Proposed initial locations are `tuppi_ai/research/` and isolated tools, with separately named native research exports if later authorised. Do not edit current factory/registry to start the audit candidates. Server profile construction and durable `ai_profile_key` are deployment seams. Client ReferencePolicy's accepted set is for analysis references and retains older names; it is not evidence that an arbitrary new search ID is accepted throughout the network schema. Persisted records replay actions but not native state. Fixture manifests/checksums and client strict identity validation need coordinated migration only at deployment. Current dirty support/security/valuation/client files require ownership coordination before later edits.

### Shared contract mapping and minimal schemas

These are **PROPOSED JSON envelopes**, not extracted runtime records. `obs` below means the exact existing `observation_to_data` output in capsule E017; `action` means its existing action wire form. `null` means unavailable, not a default to invent. Strings denoting types below are schema notation.

| Contract / status | Existing surface | Minimal additive schema and types |
|---|---|---|
| AgentSnapshot / PARTIAL | best factory; Searcher; generator metadata | `{id:string,ruleset:string,code_hashes:map,model_sha256:string,native_sha256:string,equity_sha256:string,config:map,construction_log:array,rng_states:object|null,slot_rng_states:array|null,threading:object,seat_policy_ids:string[4]}`. Snapshot native configuration and Python RNG separately; literal replay may require native export. |
| DecisionCase / PARTIAL | PlayerObservation, observation_to_data | `{cluster_id:string,observation_id:string,observation:obs,ordered_action_ids:int[],policy_state:object|null,baseline_id:string}`. Separate file/object `OfflineTruth{cluster_id,initial_hands,action_history}` never passed to policy/encoder. |
| WorldBatch / PARTIAL | TcDeal; HiddenHandAssignment; internal sampler | `{case_id:string,law_id:string,hard_constraint_version:string,layouts:simulation_state[],weights:number[],rng_before:object,rng_after:object,independence:string}`. No world IDs or assignment hashes in deployed features. |
| ActionWorldBatch / PARTIAL | float64[W,K] only | `{action_ids:int[],world_ids:string[],values:number[W][K],weights:number[W],continuation_streams:object,terminal_summaries:array|null,cpu_s:number,wall_s:number,work:object,failures:array,baseline_id:string}`. Layout axis world-major; keep errors, not zero substitutes. |
| PolicyFork / MISSING | constructors, no complete clone | `fork(snapshot:AgentSnapshot,seat:int)->FrozenPolicy`; `FrozenPolicy.choose(obs:PlayerObservation)->Action`, `export_state()->object`. Copy only that seat's allowed memory/RNG/configuration, not another hand. Shared model immutable; fresh Env with exact copied settings. |
| DealTransition / PARTIAL | engine result; generator terminal record | `{cluster_id,arm,source_score:int[2],source_dealer:int,policy_snapshot_ids:string[4],ruleset,terminal_type,winner:int,points:int,next_score:int[2],next_dealer:int|null,next_policy_state:object|null,cpu_s,wall_s,failed:bool,censored:bool}`. Retain complete row/arm dependence. |
| InformationKey / PARTIAL | semantic_observation_key, ordinary only | `key(full_legal_record,own_policy_memory)->string`. Public-only key omits own hand/message and is separately named. Root-private key includes original/remaining own cards, ordered public history, private bid/exchange memory where relevant, legal ordering and configuration; never world identity. |
| ExperimentManifest / PARTIAL | CLI arguments, bank lifecycle | `{hypotheses,baseline_ids,policy_pairing,estimands,units,population,cluster_definition,score_distribution,split_by_deal,protected_policy,stream_namespaces,compute_caps,endpoints,precision,stopping_rules,checksums}`. Missing fields block launch, not static design. |

Existing typed structures and decisive function signatures appear in section6; the index separates their concrete input/output types from these proposed additions. JSON observation emission does not yet imply lossless policy-state restoration. A public key is insufficient for C5; a neural vector is not assumed injective.

## 3. Workstream dossiers

### C1 — fixed-target analytical control variates

**C1-01 | ESTABLISHED-IN-CODE / DERIVED-WITH-ASSUMPTIONS | E022–E024 | Use the tested contested-round oracle as a layout proxy | no exact deployed-law analytical mean.** Canonical `suits.play_out(own_ranks,opponent_ranks,*,times_led,policy)->tuple[int,...]` sorts hands and makes each nonempty holder play its lowest/highest rank each abstract round, recording winners. `conditional_layouts(...seen_ranks,hand_sizes,void)` yields three rank-tuples and exact Fraction weights based on filler-card capacity combinatorics. The compact agent copy's `expected_ducking_tricks` uses contested rounds only. Its brute-force equality test walks rank index i and counts a root win only if some other hand has an ith card. The exactness is combinatorial under fixed simplified play, not a theorem about optimal Tuppi strategy. `card_liability` is kept expected tricks minus shed expected tricks; a discarded card is removed, not reassigned to opponents.

**C1-02 | MISSING-INTERFACE | E002–E004 | Factor native initial-world loop; retain its continuation loop | no current explicit-world action evaluator.** The call graph is SearchAgent→Searcher.action_values→native.search_values→search_core→sample_world_sooli→forced actions→sooli/DD/MLP→signed mean. Per-world variant shares this path. Proposed `research_evaluate_worlds(env:Env,mlp:Mlp,obs:TcObs,worlds:Sequence[TcDeal],actions:int32[K],tail:int,streams:StreamPlan)->ActionWorldBatch` must not sample, reconfigure, reload, or substitute tails. Preserve native batching and sufficient-statistics streaming; Python per-rollout callbacks would create an uncosted implementation change.

**C1-03 | ESTABLISHED-IN-CODE / DERIVED-WITH-ASSUMPTIONS | E002–E005 | Explicit independent stream namespaces; preserve comparator call schedule | batching invariance not newly tested.** One shared RNG produces layouts; sooli continuations get a base draw mixed with world/action slot index. Same worlds therefore do not imply identical continuation randomness. Changing K/action order changes streams. Ordinary NOLO continuation has deterministic clone/DD and no sooli, so evaluating the reference once on each fixed world and reusing it preserves its conditional distribution. Do not generalise that to bids. Proposed stream namespaces `fit`, `cheap`, `expensive`, `reference`, `validation` derive independently from recorded experiment seeds, with fitting deals disjoint. The frozen comparator runs its original RNG allocation; candidate instrumentation must not consume its stream. Chunk32→128 is reported move-preserving, not revalidated here; regrouping worlds/actions can change more than throughput.

**C1-04 | ESTABLISHED-IN-CODE | E005, E022–E024, E027 | Monte Carlo mean under exact chosen law, not imported closed form | strengthen constraints only as a separate candidate.** Old conditioning knows own ranks, gone cards, capacities and suit voids, but not multiple shown-card ownership, cross-suit constraints or fallback implications. Native sampling has the former ownership constraints but lacks fallback exclusions. Per-world liability is still defined for every supplied layout. At a mid-trick discard, remove all already played cards, then remove candidate from root hand; start fresh abstract within-suit rounds over the remaining unequal hands. This deliberately does not resolve the partial current trick. Because root is void in its led suit, it cannot win that trick; future cross-suit lead effects remain a proxy limitation.

**C1-05 | UNKNOWN for proposed-branch costs/covariance | E037, E053 | Pilot must measure attainable end-to-end benefit | no W128 NOLO-discard frequency, proxy/target covariance or buffer cost established.** Historical profiling reports bids58%, early play33% and solver/network shares for a small batch, not the requested discard branch's coverage or avoidable CPU. No extrapolated whole-program gain is justified.

**PROPOSED minimal algorithm.** Choose a0 by a frozen observation-only baseline before new batches. For each supplied layout and each legal discard a, compute L of the root's remaining four suits: sorted root ranks `r_i`, sorted opponent ranks `q_ji`; count `i` with at least one existing `q_ji` and `r_i > max_j q_ji`. Sum suits. This is the contested variant of E022's LOWEST oracle, whose equality is checked in E024. Set `G_a=-(L_after_a-L_after_a0)`. Compute `D_a=Y_a-Y_a0` with unchanged expensive continuation. Fixed coefficients give `beta_a*mean_M(G_a)+mean_n(D_a-beta_a*G_a)` on independent samples from the same law. Conditional expectation is the frozen model's population action gap. An observation-constant G provides no variance benefit; misspecified G remains unbiased with the correction and independent sampling. Maximisation bias and continuation-model bias remain.

With independent samples and fixed beta, the conditional variance is `beta² Var(G)/M + Var(D-beta*G)/n`; the optimum depends on real sampling/proxy/target costs as well as covariance. If the affected branch uses fraction f of baseline CPU and saves fraction r of its own work, the direct total saving is at most f*r before overhead. This is an accounting bound, not a strength forecast.

Proposed modules: explicit-world native export plus wrapper; `liability_proxy(world,seat,actions)->float64[K]`; `estimate_gaps(cheap,expensive,beta)->GapEstimate`; replay comparator retaining action ordering, work, failures. Fit beta by declared observation/action features on separate deals; unavailable categories need a prespecified default such as0, not outcome-guided adjustment. Tests: beta0; constant/zero proxy; tiny exact expectation; intentionally wrong proxy with unbiased correction; sign/order; separate stream/split enforcement; hidden-world invariance of deployed action inputs; baseline fingerprint unchanged; retained timeout/error. Include cases with at least two genuinely different proxy/action outcomes. First later pilot: ≥20% lower gap MSE at equal measured CPU against an independent high-budget reference with estimated reference-error contribution, plus independent selection-loss evaluation. Stop for a prespecified futility upper bound or unaffordable precision, not ordinary nonsignificance. Full-game strength and use of saved compute are separate.

### C2 — consequential blind commitment

**C2-01 | ESTABLISHED-IN-CODE | E005, E007, E016, E020, E041 | Define commitment versus reached-call estimands separately | native reconstruction is not behavioural conditioning.** Live humans commit without seeing prior bids; the runner resolves them in order, requesting AI bids only while reached. Engine/native collection is sequential computationally. At seat k, having been called means earlier actual bids were NOLO, although their cards are hidden in the observation. Native sampler reconstructs earlier NOLO cards from hypothetical hands using random legal choices. It is solving a reached decision approximation with a hand law that did not condition on actual predecessor pass policies. Later unused human commitments have no direct rules effect.

**C2-02 | DERIVED-WITH-ASSUMPTIONS / BLOCKED for literal cancellation | E002, E004, E020 | Side-effect-isolated policy forks are required | querying all four is not behaviourally neutral.** Four clone bids can be obtained from separate own masked precommit observations under common complete layouts. Four actual search calls consume RNG, can initialise/update sooli settings, and affect later play. Even when an unused commitment has no rules effect, evaluating it can have computational effects. Current best has no explicit remembered-bid feature, but its random/configuration history persists. Thus `Q(a)-Q(b)=E[1(E)*(Ua-Ub)]` is valid for a fixed simultaneous-policy model with action-independent unused-call state; it is not established for the literal current call-suppression process. Document either a faithful fork/call schedule or a separately identified model experiment; do not silently clean up the live baseline.

**C2-03 | ESTABLISHED-IN-CODE / MISSING-INTERFACE | E003–E004, E011, E035 | Begin with the deterministic clone predecessor model | actual-search cache needs complete configuration and seed key.** Native Mlp logits plus ascending legal-ID greedy selection provide a cheap deterministic declaration/card under the proper encoder/mask. This is the rollout policy, not a sampled hand-marginal model. A legitimate cache key is complete predecessor-local precommit information, model/rules/config hash, legal ordering and RNG state when searching. The focal private hand and true-world ID cannot be deployed inputs; they may remain evaluator bookkeeping only. A cache hit must preserve any state advancement if literal search lifecycle equivalence is claimed.

**C2-04 | ESTABLISHED-IN-CODE / UNKNOWN frequencies | E005, E032 | Separate predecessor-event computation from public shown-card generation | unconditional reach denominators absent from inspected summaries.** Current forced cards are chosen by eligible-NOLO mask and modulo random index. Proposed seam1 asks predecessor policy whether NOLO; seam2 preserves that same chosen legal card for reached public play. Database shadow bids and selected reached records do not prove pass frequency by reveal seat/score/policy. Collect all precommit denominators later, including zero-hit batches, without passing hidden bids into focal features.

**C2-05 | ESTABLISHED-IN-CODE | E005, E027, E039, E052 | Missing sound constraints are an independent engineering intervention | re-derive after exchange before use.** Mandatory tiers use eligible ranks3–9 and declaration colour, then eligible opposite colour, then any card. Public fallback/verbal cards imply missing normal-colour eligible cards or all eligible cards in the original hand. Python HardConstraintModel derives these exclusions; native sampling does not. Later public plays preserve initial-hand reasoning; private exchanges require tracking possible transfers rather than excluding a card from a current hand categorically.

**PROPOSED algorithm/interfaces.** `precommit_worlds(case,seed,W)->WorldBatch`; `masked_bid(policy,world,seat,precommit_context)->BidAndState`; `event(prefix_bids,k)->bool`; `continue_revealed_prefix(world,prefix,focal_action,forks)->Y`. Construct each predecessor observation without earlier hidden declaration content, use the same predecessor bids for every focal alternative, keep actual chosen cards, and return contrast zero outside E. Fixed W and unnormalised indicator avoid unbounded rejection and preserve per-commitment units. Count hits and effective information; never force a positive batch. Forehand E=1 is a negative control for weighting alone, although other changed reconstruction code may still change outputs and must be held fixed.

Tests: forehand equality; all-pass and never-pass predecessors; zero outside contrasts; focal-action invariance of E; legal fallback cards; no hidden-bid dependence; enumerated small joint-hand toy where product marginals gives a wrong answer; call-order/configuration accounting. First later endpoint +.001 equity per blind commitment, including pass-event factor, against clone predecessors. Need reach probabilities, calibration against actual searching predecessors, per-cluster variance and CPU before power planning. A positive conditional-when-reached result cannot substitute for this endpoint.

### C3 — match transitions and exact utility stopping

**C3-01 | ESTABLISHED-IN-CODE / lineage partly UNKNOWN | E004, E007, E012, E018–E019, E036 | Distinguish surrogate equity from score and match wins | equity artifact's exact generation sample not recorded.** At0–0 winner receives points; when already up, same team's win adds points, other team's win resets to0–0. Terminal is score≥52; overshoot is legal. Nonterminal completed deals rotate dealer. Current equity solves a50-state approximation (25scores × dealer parity), using one dealer-win probability and conditional point distributions for all scores. The artifact's dealer-win probability is.49575. Fitter source defaults20000 incumbent self-play deals at0–0 with rotating dealer; a default is not proof of the file's sample size/seed. Legacy `match_transition_value` is signed score/52 with terminal±1, not this table. Do not transplant it into C1/C2/C5.

**C3-02 | BLOCKED for unaugmented literal 100-state model | E002–E004, E013–E014, E020 | A stationary score/dealer kernel requires an explicitly justified policy-state model | no practical finite reduction established for full persistent state.** Score/dealer omit sooli settings, RNG/call history and restoration/construction context. Independent-randomness idealisation removes literal PRNG bits only if state transitions and policy marginal laws are stationary; it does not remove the v3 configuration defect. A possible augmentation includes each seat's relevant sooli mode, policy identity and option state, but reachable-state and transition sufficiency still need proof. Complete literal machine state is finite in principle, not a practical100-state method. Cold-resetting every row would define a different instrument and may be useful only with a new identity.

**C3-03 | PARTIAL | E018–E020 | Engine supports legal starting scores/dealers; correct policy row state is missing | cannot assume seat-rotation symmetry.** `create_match` and `begin_explicit_deal` accept explicit nonterminal score/dealer/ruleset. Native new_deal can set them too. Neither reconstructs an arbitrary stationary distribution over inherited search configurations. Four dealer states are needed when fixed seats differ; even parity reductions need policy/configuration/seed symmetry. The current equity's parity reduction is its modelling assumption, not an established symmetry for every proposed pairing.

**C3-04 | PARTIAL / UNKNOWN available populated logs | E013–E014, E032 | Add retained joint transition rows; existing summaries insufficient | no inspected unsealed complete transition dataset with lifecycle snapshots.** Generator schema retains hands/source score/dealer/next score and terminal result, but not arbitrary row-policy state, paired transition kernel covariance or full elapsed CPU. Evaluator flattened outcomes and match summaries discard fields required to reconstruct the proposed kernel. No private human logs are needed or permissible for this audit; selected development logs cannot establish natural visitation without their denominator and selection rules.

**C3-05 | ESTABLISHED-IN-CODE / PROPOSED addition | E004, E007–E010 | Ordinary score-utility stopping is distinct from existing solver pruning | finite-seed equivalence needs RNG accounting.** Ordinary DD computes exact team trick totals with alpha-beta/cache, not score-equivalence bounds. Sooli already terminates when the solo player takes a trick and uses exact survival pruning; offer heuristic stops solving when the4-of8 threshold is settled but still samples remaining worlds to preserve RNG advancement. Proposed ordinary early termination belongs before further rollout/tail work when a proven set of feasible final results all maps to the same current surrogate utility. At48, margin does not affect the winning team's next score utility, but winner identity still matters. With history-dependent future policies, equal next scores alone do not establish equal actual match value.

**PROPOSED contract.** `sample_transition(state_key,deck,policy_forks)->DealTransition`; `solve_kernel(P,r)->{v,residual,condition,absorption_diagnostics}`; cluster bootstrap/simulation resamples each base-deck bundle across all rows and arms together. Do not invent pseudocounts for sparse rows, clip values, or turn failures into wins/draws. For proper fixed P, unfinished mass after H deals is `e_x^T P^H 1`; a truncation bound requires state sufficiency, a substochastic kernel, known handling of terminal outcomes and uncertainty in P. Empirical termination of a few matches gives no universal guarantee.

For a justified state space, define `P[x,y]=Pr(next nonterminal state y | x)` and `r[x]=Pr(Team0 absorbs as winner | x)`. Solve `(I-P)v=r` with substochastic-row checks, an absorption/spectral-radius argument, conditioning and residual diagnostics. For paired kernels, `vC-vB=(I-PC)^(-1)*[(rC-rB)+(PC-PB)*vB]`; this explains why an arbitrary score-weighted one-deal gain need not be a match-win gain. Estimated rows and their dependence remain uncertain, so report uncertainty in the solution rather than treating the fitted matrix as exact.

Tests: reset and overshoot, score48 both winners and differing margins, dealer rotation, deterministic analytic chains, known stochastic kernels with independent simulation, clustered matrix uncertainty and an apparently nonabsorbing empirical chain. C3b needs exhaustive small-state utility equality with the existing float-rounding target; skipping deterministic ordinary clone/DD work may preserve RNG, but skipping sooli sampling must explicitly advance equivalent streams before claiming finite-seed equality. C3a's later target is equal match-win precision at≤half direct-match CPU, validated by independent complementary matches at a prespecified discrepancy tolerance/precision. Wide overlapping intervals do not suffice. Recalibrated playing utilities are another candidate, never bundled into validation of the measurement method.

### C4 — jointly legal sooli exchange

**C4-01 | ESTABLISHED-IN-CODE | E006–E008, E016–E017, E042–E043 | Giver and receiver have different inputs/masks | full learned-feature parity not present.** Acceptance selects the solo player; give removes one held card (12/14), return excludes given (13/13), then partner's13 are dead and39 cards active. Soolaaja and partner know exchange cards; RAMI defenders do not. Shown-card facts remain historical. Three-player observations use sooli trick arrays; serializer puts those into common trick-list wire keys. Ace-low is required for sooli scoring and heuristics. From a verified pre-give full development state and branch action history, offline original H,P,g,r are reconstructible. Only H+h_solo goes to giver; only original P+g+h_partner goes to receiver.

**C4-02 | ESTABLISHED-IN-CODE for schema / DOCUMENTED-ONLY population | E030, E037 | Pre-offer bytes are promising but selected population differs | manifest and ABI verification before later reuse.** Existing generator captures original hands in `offer`, not just post-return `start`; intermediate12/14 state is reconstructible from selected give, not a separately guaranteed stored field. Selection is prefilter plus searched acceptance, not an unselected natural bank and not necessarily oracle survivors only. Its v2 policy/settings differ from current v3. The first confirmatory bank must be fresh offers accepted by the frozen target offer policy, with originating-deal IDs and rejected-offer counts retained.

**C4-03 | ESTABLISHED-IN-CODE | E002, E008, E030–E031 | Change give and return jointly; freeze offer/play explicitly | rollout conventions and defenders' beliefs remain hidden coupling.** SearchAgent has independent give/return/play settings, but native Env settings and heuristics also define rollout exchanges. Current return is deterministic heuristic; give/play search use heuristic-first tie order. Defenders search with narrow exposure tilt and old exchange-prior assumptions. Changing deployed convention while freezing defenders leaves a potentially misspecified defender model. A convention-aware defender robustness test is separate from the initial fixed-defence factorial experiment. Changing rollout exchange policy at the same time would add an unreported intervention.

**C4-04 | ESTABLISHED-IN-CODE with limits | E005, E016, E039 | Preserve uncertainty of privately transferred public cards | no blanket proof of all exchange constraints.** Native sooli sampler does not simply keep original shown owners: participants know exact remappings and defenders enumerate possible S/P locations weighted by compatible exchanges. Existing sampler tests check masked projection and reachable exchange histories, but explicitly skip verbal fallback cases and were not run. Ordinary ownership/exclusion helpers cannot be reused unmodified after exchange. No new defect fixing is authorised inside C4; any found constraint defect gets separate identity and tests.

**C4-05 | PARTIAL / MISSING-INTERFACE | E003, E007, E033–E035 | Add stage-specific legal scorers and data schema | existing156-head clone omits exchange action/message features.** BC loads packed `feat,act,mask`, expands to feature width and156 mask bits, optimises masked cross-entropy; distillation additionally loads `bp,phase,val`, supports hard labels or masked softmax value targets, stores QNet checkpoints. Those are action-imitation objectives, not direct paired survival targets. Existing row-random holdouts must be replaced by whole-deal partitions for this experiment. Proposed `GiveScorer(own_original_hand,public_context)->float[52]` and `ReturnScorer(original_partner_hand,given_card,public_context)->float[52]`, with held-card masks and explicit ace-low rank features, can initialise to current deterministic scores. Offline labels may include full layouts, but deployed feature construction must be independently tested for hidden-hand invariance. Export requires a separate52-card head/native evaluator or a costed Python-only research implementation; current Mlp export is not automatically compatible.

**C4-06 | PARTIAL | E003, E007, E030–E031 | Branch from identical accepted pre-give state and restore policy forks | four-arm paired replay and full lifecycle cache missing.** Native TcDeal copies plus tc_apply/observe support evaluator-local exchange branching. Exhaustive exchange alternatives are13 gives ×13 returns =169 per complete layout, each followed by a legal continuation. Approximate work is `N_layouts*169*C_play` plus sampling/policy overhead, not169 cheap scalar scores. Four selected policy arms need only four exchanges/continuations per position, though training may require more labels. Cache immutable post-exchange states and deterministic continuation results only under full policy/configuration identity; common random streams must be explicit, not presumed from reused Env.

**PROPOSED first implementation family.** Separate small masked value scorers trained on paired branch survival labels by alternating giver/receiver updates, with offer and playing policies frozen. Receiver uses g legally as both transferred asset and possible signal; no need to build an unvalidated full posterior. If a posterior is later used, include accepted-offer selection and the giver likelihood, not an arbitrary uniform prior. Four arms old/old,new/old,old/new,new/new share pre-exchange positions; report interaction `J11-J10-J01+J00` and new/new versus the better single change. Reuse bank generator mechanics but not its selected data as independent confirmation.

Tests include a give that conveys a useful message but transfers a strategically harmful card, and a receiver that misreads a rare giver choice: outcomes must be allowed to reject signalling. Add return≠give,13 cards each,39active/13dead, dead hand never plays, ace ordering, private shown-card transfer ambiguity, and hidden-hand invariance at fixed full legal input. Later meaningful target +3 percentage points actual survival among frozen accepted offers. Plan using paired discordance clustered by originating deal, not independent arm binomials. Strong convention-aware defence remains blind to exchange cards; natural v3 confirmation reports acceptance frequency and unconditional deal/match effects separately.

### C5 — actual-root information-consistent continuation

**C5-01 | PARTIAL / objective mismatch ESTABLISHED-IN-CODE | E025–E028, E055–E056 | Reuse support machinery, replace objective/recursion | ordinary RAMI and v3 adapters not established.** NOLO support returns EXACT_COMPLETE only with all worlds, otherwise no partial set; defaults3 tricks,100worlds,100000 transitions, explicit ceilings3/1680/50million. Counts precede enumeration. ResearchWorld contains assignment and replay state, no probability. Uniform full hard-feasible assignments is a possible explicitly chosen root prior, not the current behavioural posterior. Historical security solver minimises worst team tricks over nature and adversarial choices of all other seats, including partner. Its information grouping is useful; its utility and partner objective are not C5. Count/enumeration constraints include fallback exclusions absent in native W128, so model comparisons must name that difference.

**C5-02 | PARTIAL / BLOCKED for generic lossless key | E006–E007, E016–E017, E025, E028–E029 | Key complete actor legal history and personal state | reconstruction may lose ruleset and other-seat hand order.** semantic_observation_key covers ordinary observation fields, ordered hand/actions and public history, excluding protocol IDs; it lacks sooli and policy-private memory. That suffices only for its scoped ordinary memoryless agent assumptions, not arbitrary controllers. Encoder2 is richer than encoder1 but not a verified lossless key. Reconstructed root order is preserved; other hands are canonicalised, which can affect engine-order tie policies. Native clone continuations use canonical ID tie order and avoid that ambiguity if explicitly selected. Each other seat must receive its own simulated observation from the world and public history, never root's posterior or hand.

**C5-03 | ESTABLISHED-IN-CODE / proposed adapter | E003–E004, E011, E035 | Deterministic native clone is the simplest fixed-policy model | actual search integration requires PolicyFork.** Clone greedy actions can be computed from each seat's observation and legal mask without stochastic enumeration. That is competent rollout modelling, not a claim it equals actual searching players. Search continuations need nested sampling/RNG-state integration and cannot be substituted silently. Fixed partner policy is also fixed; C5 does not optimise it cooperatively.

**C5-04 | MISSING-INTERFACE | E025–E026 | Add weighted-history groups and persistent root option | no existing expected-value contingent-plan store.** Proposed `WeightedHistory{world_state,weight,seat_policy_states,root_memory}` and `InfoGroup{root_key,histories,legal_actions}`. For each root action advance frozen other seats; group by complete later root observation; evaluate one common b for each group using normalised conditional weights and accumulate group mass times best conditional utility. Deterministic observed other actions give likelihood0/1; stochastic policies require likelihood factors. Do not reset to hard-uniform belief on the next real root turn. Store the chosen option's mapping and posterior or re-solve from exactly that posterior through deal end.

**C5-05 | PARTIAL / costs UNKNOWN for new objective | E025–E026, E053 | Gate on public information and full-support completion, enforce caps | 1680 is a count ceiling, not a runtime proof.** Existing NOLO code meters transitions and returns budget statuses; N11 reports cost for its adversarial objective, not this expected-value option. At a three-card trick boundary9 unseen cards have at most1680 unconstrained allocations, but future observations/actions and policy cost still matter. Proposed gate: ordinary actual actor, exactly three remaining cards each at boundary, complete support under declared constraint model below a prespecified cap, compatible deterministic policies and reconstructible information. Mid-trick eligibility needs a separately justified bound. A monotonic node/time cap triggers unchanged W128 fallback, records reason and discards incomplete exact claims. Off-support observations or policy mismatches invalidate the option and fall back, with failures retained. The .5-second experience target is distinct from an old10-second ceiling; no cap chosen from favourable pilot outcomes.

**C5-06 | MISSING-INTERFACE | E002–E004, E025–E026 | Compare complete options, not just first actions | W128 future-call state fork is prerequisite.** Diagnostic1 values W128's selected root action followed by C5-optimised later root play. Comparator2 actually runs W128 at every later root decision against the same named other policies, with the correct lifecycle. Only2 represents its deployed continuation under that model. For an information-relaxation bound, reveal world only to root while holding other policies fixed. Double-dummy changes the information/control of other seats too and is not automatically an upper bound on this asymmetric objective.

The option value is `Qlegal(a)=sum_o P(o|I,a)*max_b E[U|I,a,o,b]`. There is one b for the entire information group, not one per hidden layout. At a three-card boundary, after current a, root has at most one later non-forced card choice; the last card is forced. This structural simplification does not remove the need to integrate the other seats’ actions and resulting observation probabilities.

**PROPOSED implementation.** Actual-root dispatcher outside per-world DD; complete-support adapter; frozen-seat masked evaluator; lossless root key; option evaluator and per-deal plan store. New code stays downstream of engine/exact infrastructure and outside frozen policy registries. New native dependence is optional for rollout speed, not an excuse to weaken masking. Independent toy enumeration must check: two indistinguishable worlds with conflicting optimal b require one compromise; different observed future events permit different b; forced/constant controls; root-only clairvoyance bound; intentionally colliding information keys rejected; nonuniform posterior changes optimum; two-card present choice with forced last card. Use at least one strictly positive and one strictly negative comparison relative to an arbitrary baseline choice to detect vacuous evaluators. Later screen targets+.001 equity per eligible **option**, with coverage and latency. Confirm against actual search before whole-game claims; no summing two decisions as independent gains.

## 4. Dependency and safety map

C0 precedes every empirical claim. C1 first touches native sampling/evaluation separation, then analytical proxy/estimator tools. C2 shares explicit-world evaluation and needs masked precommit reconstruction plus stronger PolicyFork handling. C3a touches match runner, lifecycle and statistics; it can proceed only after a state model is justified. C3b touches shared rollout termination and must keep equity/rounding and any random advancement fixed. C4 touches exchange replay, new features/model heads and paired data; C5 touches support/replay, information keys and persistent option state. Both are larger downstream projects, not automatically next implementations because their seams exist.

Collision risks: current dirty RESEARCH support/security/server/valuation files; global native configuration/chunk settings; shared bridge encoders; source/native ABI; policy IDs used in persistence/client schemas. Proposed additions should live in separately named research modules with immutable baseline imports. Later native builds must use separate output libraries and identities, not replace `libtuppi.dylib` in place. The audit did neither. Frozen baseline defects remain explicit comparator properties. Constraint repairs, utility recalibration, rollout-policy changes and using saved compute are separately identified interventions and cannot be attributed to C1/C2/C4/C5.

## 5. Experiment readiness and statistics

All thresholds below are provisional user targets, not measured gains or automatic shipping criteria. Whole-deal split keeps all rotations, assignments, observations and hypothetical completions together. Complete matches cluster complementary pairs. Transition rows using shared decks preserve the full deck bundle across rows and arms.

| Endpoint | Runner/comparator | Unit and population | Cluster/paired contrast | Retain / current missing quantities | Later confirmation |
|---|---|---|---|---|---|
| Fixed full-deal benefit +.001 | extended evaluate, as-is W128 vs candidate against fixed named opponents | signed surrogate equity/base deck; explicit zero or named score law | base deck, average8 rotations/assignments; equal lifecycle protocol | outcomes,score,dealer,IDs,failures,timing; new contrast SD unknown | fresh independent deal bank, frozen candidate and compute |
| ≥20% total CPU saving, margin−.0005 | same full-deal instrument | CPU and equity/deal | paired deck bundles | actual CPU/wall/loading/threads/latency; baseline branch share unknown | noninferiority plus speed; freed-compute variant separate |
| +.02 match wins | v3 complementary runner addition | match-win probability | complementary pair | per-leg decks,termination,censoring,IDs,work; variance unknown | prespecified cap/censor treatment, fresh pair bank |
| C1 ≥20% gap-MSE reduction | explicit-world instrument missing | paired gap MSE equal CPU, ordinary NOLO discards | originating deck, all actions/cases together | reference uncertainty,selection loss,covariance,cost,coverage unknown | local mechanism then independent whole games |
| C2 +.001/commitment | joint-precommit adapter missing | unconditional equity per blind commitment | base deal, seat/score strata | E hits/denominator,actual shown cards,policy forks,variance unknown | search-predecessor calibration then natural v3 |
| C3a half CPU at equal precision | row kernel + direct v3 pair runner missing | match-win precision from declared state | decks across rows/arms; independent direct pairs | row counts,failure,absorption,condition,resampling; state model blocked | discrepancy tolerance with adequate direct precision |
| C3b exact stopping | native evaluator hook | identical target, saved work | same case/world/action streams | float target,solver nodes,RNG advancement,CPU | full-deal equal-compute and finite-seed claim separately |
| C4 +.03 survival | accepted pre-give four-arm adapter | actual survival under frozen offer/play | source deal, interaction and best single-policy contrast | accepted/rejected denominator,paired discordance,cost unknown | fresh non-oracle-selected bank; informed strong defence; natural v3 |
| C5 +.001/option | actual-root evaluator missing | root equity per eligible continuation option | originating deal; complete policy comparator | support,coverage,nodes,latency,failures,option posterior; variance unknown | actual search then fresh games |

For paired-cluster SD s and effect delta, `n≈7.85*s²/delta²` is only the two-sided5%,80%-power approximation. For half-width h, `n≈(1.96*s/h)²`. Do not borrow historical SD as measured new-contrast SD. Binary matched survival, CPU ratios and estimated-kernel values need corresponding variance or simulation treatment. Detecting positive benefit is different from establishing benefit exceeds the meaningful target. Futility requires a predeclared upper bound or unaffordable precision; repeated ordinary CI peeking is invalid. Failed/time-capped outcomes remain in records; complete-case deletion and arbitrary.5 imputation are not generally unbiased. Record warm/cold loading, total CPU, end-to-end wall, threads/processes, median/tail latency and instrumentation overhead. This static audit cannot estimate p99.

Progression: Stage A reproducible instruments and discriminating tiny tests; Stage B independent pilots beginning C1 and then C2 if justified; Stage C frozen candidate on new bank, multiplicity plan for several survivors; Stage D one-at-a-time composition with flags/factorial ablations; Stage E separately authorised deployment. No outcome-dependent promotion or additive strength forecast follows from this audit.

## 6. Source capsules

These are static source excerpts, not executed examples. Line ranges and hashes identify the original files. Comments are source claims, not audit validation. Type definitions precede the native evaluator. Python imports and unrelated functions are omitted; dependencies are identified in the interface inventory and evidence manifest. Full selected C files are included in `NATIVE_SOURCE_CAPSULES.txt` because splitting their tightly coupled helpers would obscure sampling and RNG semantics. That file is part of this bundle. No executable candidate is supplied.

### E001 — best_agents, lines 28–36

```python
def best_agents(seats=range(4), worlds: int = WORLDS, seed: int = 0) -> dict:
    from . import model as qmodel
    from .equity import Equity
    from .search import SearchAgent

    net = qmodel.load(ROLLOUT, "cpu")
    table = Equity.load(EQUITY).table
    return {s: SearchAgent(net, table, s, worlds=worlds, dd_left=SOLVER_TAIL, search_showing=1, seed=seed + s)
            for s in seats}
```

### E011 — mask_of, lines 31–35

```python
def mask_of(cards) -> int:
    m = 0
    for card in cards:
        m |= 1 << card_to_index(card)
    return m
```

### E011 — action_id, lines 38–47

```python
def action_id(action) -> int:
    if isinstance(action, PlayCardAction):
        return card_to_index(action.card)
    if isinstance(action, ShowAction):
        return 52 + 52 * _CONTRACT[action.declared_contract] + card_to_index(action.shown_card)
    if SooliDecisionAction is not None and isinstance(action, SooliDecisionAction):
        return ACT_SOOLI_ACCEPT if action.play_sooli else ACT_SOOLI_DECLINE
    if SooliExchangeAction is not None and isinstance(action, SooliExchangeAction):
        return ACT_EXCHANGE + card_to_index(action.card)
    raise TypeError(f"unknown action {action!r}")
```

### E011 — engine_action, lines 50–59

```python
def engine_action(action: int, seat: int):
    if action in (ACT_SOOLI_DECLINE, ACT_SOOLI_ACCEPT):
        return SooliDecisionAction(seat=seat, play_sooli=action == ACT_SOOLI_ACCEPT)
    if action >= ACT_EXCHANGE:
        return SooliExchangeAction(seat=seat, card=card_from_index(action - ACT_EXCHANGE))
    if action < 52:
        return PlayCardAction(seat=seat, card=card_from_index(action))
    contract, card = divmod(action - 52, 52)
    return ShowAction(seat=seat, shown_card=card_from_index(card),
                      declared_contract=_CONTRACTS[contract])
```

### E011 — obs_from_player_observation, lines 62–111

```python
def obs_from_player_observation(observation) -> TcObs:
    o = TcObs()
    o.hand = mask_of(observation.own_hand)
    o.seat = observation.observing_seat
    o.dealer = observation.dealer
    o.phase = _PHASE.get(observation.phase, PH_DONE)
    shows = observation.show_actions
    # project_target_v3 showing: no bid is visible, only how many were taken.
    o.n_shows = len(shows) + getattr(observation, "bids_locked", 0)
    for i, show in enumerate(shows):
        o.show_seat[i] = show.seat
        o.show_card[i] = card_to_index(show.shown_card)
        o.show_contract[i] = _CONTRACT[show.declared_contract]
        o.show_verbal[i] = int(show.verbal_required)
    o.contract = -1 if observation.contract is None else _CONTRACT[observation.contract]
    o.declarer = -1 if observation.declarer is None else observation.declarer
    o.first_leader = 0 if observation.first_leader is None else observation.first_leader
    sooli = getattr(observation, "soolaaja", None) is not None and getattr(observation, "sooli_exchanged", False)
    if sooli:
        tricks, current = observation.sooli_tricks, observation.sooli_current_trick
    else:
        tricks, current = observation.completed_tricks, observation.current_trick
    n = 0
    for trick in tricks:
        for play in trick.plays:
            o.play_card[n] = card_to_index(play.card)
            o.play_seat[n] = play.seat
            n += 1
    for play in current:
        o.play_card[n] = card_to_index(play.card)
        o.play_seat[n] = play.seat
        n += 1
    o.n_played = n
    o.score[0] = observation.match_score.team0
    o.score[1] = observation.match_score.team1
    ruleset = getattr(observation, "ruleset_id", None)
    o.ruleset = {"project_target_v2": 2, "project_target_v3": 3}.get(getattr(ruleset, "value", None), 1)
    o.trick_size = 3 if sooli else 4
    decisions = getattr(observation, "sooli_decisions", ())
    o.n_decisions = len(decisions)
    for i, (seat, accept) in enumerate(decisions):
        o.decision_seat[i] = seat
        o.decision_accept[i] = int(accept)
    soolaaja = getattr(observation, "soolaaja", None)
    o.soolaaja = -1 if soolaaja is None else soolaaja
    given = getattr(observation, "sooli_given_card", None)
    returned = getattr(observation, "sooli_returned_card", None)
    o.known_given = -1 if given is None else card_to_index(given)
    o.known_returned = -1 if returned is None else card_to_index(returned)
    return o
```

### E059 — _plan, lines 46–54

```python
def _plan() -> dict[int, str]:
    raw = os.environ["TUPPI_AI_SEATS"]
    plan = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        seat, kind = item.split(":")
        if kind not in ("incumbent", "search"):
            raise SystemExit(f"unknown seat kind {kind!r}")
        plan[int(seat)] = kind
    return plan
```

### E059 — main, lines 57–81

```python
def main() -> None:
    from tuppi_server import app, match_runner

    from tuppi_ai.best import ROLLOUT, WORLDS, best_agents

    plan = _plan()
    worlds = int(os.environ.get("TUPPI_AI_WORLDS", str(WORLDS)))
    original = match_runner._construct_ai_agents

    def construct(seats, *, profile_key):
        agents = original(seats, profile_key=profile_key)
        searched = [s for s in seats if plan.get(s) == "search"]
        agents.update(best_agents(searched, worlds=worlds))
        return agents

    match_runner._construct_ai_agents = construct
    if os.environ.get("TUPPI_AI_REVIEW", "1") == "1":
        # After-deal review of the human's own decisions by the best agent's search.
        from tuppi_ai.review import ServerReviewer
        app.app.rooms.deal_reviewer = ServerReviewer()
    print(f"TuppiAI seat plan: {plan}; best agent ({ROLLOUT.name}, W={worlds}); "
          f"rules {os.environ['TUPPI_SERVER_RULESET']}; review "
          f"{'on' if os.environ.get('TUPPI_AI_REVIEW', '1') == '1' else 'off'}")
    print(f"server data dir: {os.environ['TUPPI_SERVER_DATA_DIR']}")
    app.main(sys.argv[1:])
```

### E060 — incumbent_agents, lines 8–19

```python
def incumbent_agents(profile_key: str = INCUMBENT) -> dict[int, object]:
    from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
    from tuppi_agents.improved_registry import (
        improved_agent_from_specification, improved_specifications_by_profile_key)

    improved = improved_specifications_by_profile_key()
    if profile_key in improved:
        spec = improved[profile_key]
        return {s: improved_agent_from_specification(spec, profile_key=profile_key, seat=s)
                for s in range(4)}
    spec = phase4_specifications_by_profile_key()[profile_key]
    return {s: construct_agent(spec, seat=s) for s in range(4)}
```

### E002 — Searcher, lines 28–199

```python
class Searcher:
    """`belief` > 1 enables policy-based inference: that many times `worlds`
    candidate worlds are drawn, each weighted by the blueprint's likelihood of
    the other three seats' past unforced choices (softmax at `belief_t`, mixed
    with uniform at `belief_eps`), and `worlds` of them are resampled by weight.
    """

    def __init__(self, net: qmodel.QNet, equity_table: np.ndarray, worlds: int = 32,
                 dd_left: int = 0, seed: int = 0, max_actions: int = 26, belief: int = 0,
                 belief_t: float = 1.0, belief_eps: float = 0.1, belief_seats: str = "all",
                 belief_net=None, belief_n: int = 1024, belief_alpha: float = 0.5, team_net=None,
                 opp_temp: float = 0.0, native_loop: bool = True):
        self.net = net
        self.worlds = worlds
        self.dd_left = dd_left
        self.belief, self.belief_t, self.belief_eps = belief, belief_t, belief_eps
        self.belief_seats = belief_seats
        # Learned card-location belief: uniform candidates reweighted by the
        # product of the network's per-card probabilities, tempered by alpha.
        self.belief_net, self.belief_n, self.belief_alpha = belief_net, belief_n, belief_alpha
        self.last_ess = None
        # Optional different rollout policy for the searching seat's own team.
        self.team_net = team_net
        # If > 0, opponents' rollout moves are sampled from softmax(logits / opp_temp)
        # instead of taken greedily: less reliance on predicting them exactly.
        self.opp_temp = opp_temp
        # The whole search in C (same steps and rounding; the network's float
        # arithmetic differs from PyTorch only in the last digits). Used when no
        # Python-only option is active.
        self.native_loop = (native_loop and belief <= 1 and belief_net is None and team_net is None
                            and not opp_temp)
        self.mlp = native.Mlp(net) if self.native_loop else None
        self.np_rng = np.random.default_rng(seed)
        self._hf = np.zeros((64, native.feature_dim(net.encoder)), dtype=np.uint8)
        self._hm = np.zeros((64, native.NUM_ACTIONS), dtype=np.uint8)
        self._ha = np.zeros(64, dtype=np.int32)
        self.env = native.Env(worlds * max_actions, seed, equity_table, single_deal=True,
                              encoder=net.encoder)
        self.rng = C.c_uint64(seed * 2654435761 + 1)

    def action_values(self, obs: native.TcObs, actions: list[int]) -> np.ndarray:
        if self.mlp is not None:
            return native.search_values(self.env, self.mlp, obs, actions, self.worlds, self.dd_left, self.rng)
        k, w = len(actions), self.worlds
        env = self.env
        worlds = self.sample_worlds(obs, w)
        n = w * k
        for wi, world in enumerate(worlds):
            for ai in range(k):
                env.set_state(wi * k + ai, world)
        for i in range(n, env.n):  # park unused slots as finished
            env.set_state(i, worlds[0])
            env.deal(i).phase = native.PH_DONE
        me_team = obs.seat & 1
        total = np.zeros(n)
        live = np.ones(n, dtype=bool)
        first = np.array([actions[i % k] for i in range(n)] + [0] * (env.n - n), dtype=np.int32)
        env.step(first)
        self._collect(total, live, n)
        while live.any():
            if self.dd_left:
                env.dd_finish(self.dd_left)
                self._collect(total, live, n)
                if not live.any():
                    break
            feat, mask, seat, _ = env.observe()
            with torch.no_grad():
                x = torch.from_numpy(feat)
                q = self.net(x).numpy()
                if self.team_net is not None:
                    mine = (seat & 1) == me_team
                    if mine.any():
                        q[mine] = self.team_net(torch.from_numpy(feat[mine])).numpy()
                qm = np.where(mask == 1, q, -np.inf)
                acts = qm.argmax(1).astype(np.int32)
                if self.opp_temp > 0:
                    opp = (seat & 1) != me_team
                    if opp.any():
                        z = qm[opp] / self.opp_temp
                        z -= z.max(1, keepdims=True)
                        pr = np.exp(z)
                        pr /= pr.sum(1, keepdims=True)
                        u = self.np_rng.random((len(pr), 1))
                        acts[opp] = (pr.cumsum(1) < u).sum(1).astype(np.int32)
            acts[mask.sum(axis=1) == 0] = 0
            env.step(acts)
            self._collect(total, live, n)
        values = total.reshape(w, k).mean(axis=0)
        return values if me_team == 0 else -values

    def _direct_belief_worlds(self, obs: native.TcObs, w: int) -> list:
        """Exact draws from the tempered product of the network's card marginals."""
        feat = native.encode(obs, encoder=self.belief_net.encoder)[None]
        with torch.no_grad():
            p = torch.softmax(self.belief_net(torch.from_numpy(feat)), dim=2)[0].numpy()
        wt = p ** self.belief_alpha
        worlds = []
        for _ in range(w):
            world = native.sample_world_weighted(obs, wt, self.rng)
            if world is None:  # belief and constraints disagree completely: fall back
                world = native.sample_world(obs, self.rng)
            worlds.append(world)
        return worlds

    def _learned_belief_worlds(self, obs: native.TcObs, w: int) -> list:
        if self.belief_n <= 0:
            return self._direct_belief_worlds(obs, w)
        n = self.belief_n
        cands = []
        while len(cands) < n:
            world = native.sample_world(obs, self.rng)
            if world is None:
                raise RuntimeError("no world consistent with the observation")
            cands.append(world)
        feat = native.encode(obs, encoder=self.belief_net.encoder)[None]
        with torch.no_grad():
            logp = torch.log_softmax(self.belief_net(torch.from_numpy(feat)), dim=2)[0].numpy()  # (52, 3)
        hands = np.array([[c.hand[(obs.seat + r) & 3] for r in (1, 2, 3)] for c in cands], dtype=np.uint64)
        bits = np.unpackbits(hands.view(np.uint8).reshape(n, 3, 8), axis=2, bitorder="little")[:, :, :52]
        # log p of each candidate's placement: sum over cards held by others
        lw = self.belief_alpha * np.einsum("nrc,cr->n", bits.astype(np.float32), logp)
        wts = np.exp(lw - lw.max())
        wts /= wts.sum()
        self.last_ess = 1.0 / float(np.sum(wts ** 2))
        # Systematic resampling keeps duplicates to the minimum the weights force.
        u = (self.np_rng.random() + np.arange(w)) / w
        pick = np.minimum(np.searchsorted(np.cumsum(wts), u), n - 1)
        return [cands[i] for i in pick]

    def sample_worlds(self, obs: native.TcObs, w: int) -> list:
        if self.belief_net is not None:
            return self._learned_belief_worlds(obs, w)
        n = w * self.belief if self.belief > 1 else w
        cands = []
        while len(cands) < n:
            world = native.sample_world(obs, self.rng)
            if world is None:
                raise RuntimeError("no world consistent with the observation")
            cands.append(world)
        if self.belief <= 1:
            return cands
        others = 0b1111 & ~(1 << obs.seat)
        if self.belief_seats == "opp":
            others &= ~(1 << ((obs.seat + 2) & 3))
        feats, masks, acts, owner = [], [], [], []
        for i, world in enumerate(cands):
            r = native.history_rows(world, others, self.net.encoder, self._hf, self._hm, self._ha)
            if r > 0:
                feats.append(self._hf[:r].copy()); masks.append(self._hm[:r].copy())
                acts.append(self._ha[:r].copy()); owner.append(np.full(r, i))
        if not feats:
            return cands[:w]
        f, m, a, o = (np.concatenate(x) for x in (feats, masks, acts, owner))
        with torch.no_grad():
            logits = self.net(torch.from_numpy(f)).numpy() / self.belief_t
        logits = np.where(m == 1, logits, -np.inf)
        logits -= logits.max(1, keepdims=True)
        p = np.exp(logits)
        p /= p.sum(1, keepdims=True)
        k = m.sum(1)
        taken = (1 - self.belief_eps) * p[np.arange(len(a)), a] + self.belief_eps / k
        logw = np.zeros(n)
        np.add.at(logw, o, np.log(taken))
        wts = np.exp(logw - logw.max())
        wts /= wts.sum()
        pick = self.np_rng.choice(n, size=w, replace=True, p=wts)
        return [cands[i] for i in pick]

    def _collect(self, total, live, n):
        done = self.env.done[:n].astype(bool)
        total[done] += self.env.delta0[:n][done]
        live[done] = False
```

### E002 — SearchAgent, lines 214–316

```python
class SearchAgent:
    """Engine-interface agent: blueprint for showing, search for trick play."""

    #: Plays every sooli decision itself (servers must not wrap it in a fallback).
    handles_sooli = True

    def __init__(self, net, equity_table, seat: int, worlds: int = 32, dd_left: int = 0,
                 search_showing=False, seed: int = 0, keep: float | None = None,
                 show_worlds: int | None = None, rami_bonus: float = 0.0, sooli: dict | None = None,
                 **belief):
        """search_showing: False (blueprint shows), True/1 (search every legal show), or 2
        (search only the blueprint's preferred card for each contract, then keep
        the blueprint's card within the chosen contract)."""
        self.seat = seat
        self.net = net
        self.search_showing = search_showing
        self.keep = keep  # None: plain argmax; >= 0: keep the blueprint's action unless beaten by more
        # Added to the value of declaring RAMI (RETURN_SCALE units): the rollouts
        # play the rest of the deal with the clone, which undervalues contracts
        # this agent's own (better) play would make.
        self.rami_bonus = rami_bonus
        self.searcher = Searcher(net, equity_table, worlds=worlds, dd_left=dd_left, seed=seed + seat, **belief)
        self.show_searcher = None
        if show_worlds and show_worlds != worlds:
            self.show_searcher = Searcher(net, equity_table, worlds=show_worlds, dd_left=dd_left,
                                          seed=seed + seat + 17, **belief)
        self._feat = np.zeros((1, native.feature_dim(net.encoder)), dtype=np.uint8)
        self.sooli = {**SOOLI_DEFAULTS, **(sooli or {})}
        #: The last decision's searched values, {action id: equity change for this
        #: seat's team}, or None when it was forced or taken by a heuristic. Read by
        #: the game database (tools/gen_game_db.py); never affects the choice.
        self.last_values: dict[int, float] | None = None

    def _sooli_action(self, obs: native.TcObs, ids: list[int]) -> int:
        cfg, phase = self.sooli, obs.phase
        self.last_values = None
        env = self.searcher.env
        if self.searcher.mlp is None:  # only the native search loop handles sooli phases
            a = native.sooli_policy(obs, self.searcher.rng)
            return a
        if phase == native.PH_SOOLI_OFFER:
            env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])
            order = [native.ACT_SOOLI_DECLINE, native.ACT_SOOLI_ACCEPT]
            v = self.searcher.action_values(obs, order)
            self.last_sooli_values = dict(zip(order, v))
            self.last_values = {a: float(x) for a, x in zip(order, v)}
            return native.ACT_SOOLI_ACCEPT if v[1] - v[0] > cfg["offer_margin"] else native.ACT_SOOLI_DECLINE
        key = {native.PH_SOOLI_GIVE: "give", native.PH_SOOLI_RETURN: "return", native.PH_SOOLI_PLAY: "play"}[phase]
        h = native.sooli_policy(obs, self.searcher.rng)
        if cfg[key] == "heur":
            return h
        order = [h] + [i for i in ids if i != h]
        env.set_sooli(cfg["belief"], False, False, cfg["lam"])
        v = self.searcher.action_values(obs, order)
        self.last_sooli_values = dict(zip(order, v))
        self.last_values = {a: float(x) for a, x in zip(order, v)}
        return order[int(np.argmax(v))]

    def choose_action(self, observation):
        legal = observation.legal_actions
        self.last_values = None
        if len(legal) == 1:
            return legal[0]
        obs = obs_from_player_observation(observation)
        ids = [action_id(a) for a in legal]
        if obs.phase in native.SOOLI_PHASES:
            return legal[ids.index(self._sooli_action(obs, ids))]
        if obs.ruleset == 2:  # soolis inside the rollouts are played as at the offer
            cfg = self.sooli
            for sr in {id(self.searcher): self.searcher, id(self.show_searcher): self.show_searcher}.values():
                if sr is not None:
                    sr.env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])
        searcher = self.show_searcher if (obs.phase == native.PH_SHOW and self.show_searcher) else self.searcher
        if obs.phase == native.PH_SHOW and self.search_showing != 1 and self.search_showing is not True:
            native.encode(obs, self._feat[0], self.net.encoder)
            with torch.no_grad():
                q = self.net(torch.from_numpy(self._feat))[0].numpy()
            if not self.search_showing:
                return legal[int(np.argmax([q[i] for i in ids]))]
            # Two-stage: one representative card per contract, chosen by the blueprint.
            reps = []
            for contract in (0, 1):
                cands = [i for i in ids if (i - 52) // 52 == contract]
                if cands:
                    reps.append(max(cands, key=lambda i: q[i]))
            if len(reps) == 1:
                return legal[ids.index(reps[0])]
            values = searcher.action_values(obs, reps)
            self.last_values = {a: float(x) for a, x in zip(reps, values)}
            return legal[ids.index(reps[int(np.argmax(values))])]
        values = searcher.action_values(obs, ids)
        self.last_values = {a: float(x) for a, x in zip(ids, values)}
        if self.rami_bonus and obs.phase == native.PH_SHOW:
            values = values + self.rami_bonus * np.array([1.0 if i >= 104 else 0.0 for i in ids])
        best = int(np.argmax(values))
        if self.keep is not None:
            native.encode(obs, self._feat[0], self.net.encoder)
            with torch.no_grad():
                q = self.net(torch.from_numpy(self._feat))[0].numpy()
            bp = int(np.argmax([q[i] for i in ids]))
            if values[bp] >= values[best] - self.keep:
                best = bp
        return legal[best]
```

### E003 — TcDeal, lines 25–42

```python
class TcDeal(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64 * 4),
        ("dealer", C.c_uint8), ("phase", C.c_uint8), ("cur", C.c_uint8),
        ("n_shows", C.c_uint8),
        ("show_seat", U8x4), ("show_card", U8x4), ("show_contract", U8x4), ("show_verbal", U8x4),
        ("contract", C.c_int8), ("declarer", C.c_int8),
        ("first_leader", C.c_uint8),
        ("n_played", C.c_uint8),
        ("play_card", U8x52), ("play_seat", U8x52),
        ("team_tricks", C.c_uint8 * 2),
        ("score", C.c_uint8 * 2),
        ("winner_team", C.c_int8), ("points", C.c_uint8), ("stolen", C.c_uint8),
        ("ruleset", C.c_uint8), ("trick_size", C.c_uint8), ("n_decisions", C.c_uint8),
        ("decision_seat", C.c_uint8 * 2), ("decision_accept", C.c_uint8 * 2),
        ("soolaaja", C.c_int8), ("given", C.c_int8), ("returned", C.c_int8),
        ("sooli_won", C.c_uint8),
    ]
```

### E003 — TcObs, lines 45–59

```python
class TcObs(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64),
        ("seat", C.c_uint8), ("dealer", C.c_uint8), ("phase", C.c_uint8),
        ("n_shows", C.c_uint8),
        ("show_seat", U8x4), ("show_card", U8x4), ("show_contract", U8x4), ("show_verbal", U8x4),
        ("contract", C.c_int8), ("declarer", C.c_int8),
        ("first_leader", C.c_uint8),
        ("n_played", C.c_uint8),
        ("play_card", U8x52), ("play_seat", U8x52),
        ("score", C.c_uint8 * 2),
        ("ruleset", C.c_uint8), ("trick_size", C.c_uint8), ("n_decisions", C.c_uint8),
        ("decision_seat", C.c_uint8 * 2), ("decision_accept", C.c_uint8 * 2),
        ("soolaaja", C.c_int8), ("known_given", C.c_int8), ("known_returned", C.c_int8),
    ]
```

### E003 — search_world_values, lines 358–368

```python
def search_world_values(env: "Env", mlp: Mlp, obs: TcObs, actions, worlds: int, dd_left: int,
                        rng_state: C.c_uint64) -> np.ndarray:
    """(worlds, actions) values, observer's sign; the same worlds for every action."""
    a = np.ascontiguousarray(actions, dtype=np.int32)
    mean = np.zeros(len(a), dtype=np.float64)
    out = np.zeros((worlds, len(a)), dtype=np.float64)
    rc = lib.tc_search_world_values(env._h, mlp._h, C.byref(obs), a.ctypes.data, len(a), worlds, dd_left,
                                    C.byref(rng_state), mean.ctypes.data, out.ctypes.data)
    if rc != 0:
        raise RuntimeError(f"native search failed ({rc})")
    return out
```

### E003 — search_values, lines 371–379

```python
def search_values(env: "Env", mlp: Mlp, obs: TcObs, actions, worlds: int, dd_left: int,
                  rng_state: C.c_uint64) -> np.ndarray:
    a = np.ascontiguousarray(actions, dtype=np.int32)
    out = np.zeros(len(a), dtype=np.float64)
    rc = lib.tc_search_values(env._h, mlp._h, C.byref(obs), a.ctypes.data, len(a), worlds, dd_left,
                              C.byref(rng_state), out.ctypes.data)
    if rc != 0:
        raise RuntimeError(f"native search failed ({rc})")
    return out
```

### E003 — Env, lines 232–318

```python
class Env:
    """N parallel matches in native code, observed and stepped as numpy arrays."""

    def __init__(self, n: int, seed: int, equity: np.ndarray | None = None,
                 p_random_start: float = 0.0, single_deal: bool = False, encoder: int = 1):
        self.n = n
        self.encoder = encoder
        self._h = lib.tc_env_new(n, seed)
        lib.tc_env_set_encoder(self._h, encoder)
        if equity is not None:
            self.set_equity(equity)
        lib.tc_env_set_options(self._h, float(p_random_start), int(single_deal))
        self.feat = np.zeros((n, feature_dim(encoder)), dtype=np.uint8)
        self.mask = np.zeros((n, NUM_ACTIONS), dtype=np.uint8)
        self.seat = np.zeros(n, dtype=np.int32)
        self.phase = np.zeros(n, dtype=np.int32)
        self.done = np.zeros(n, dtype=np.int32)
        self.delta0 = np.zeros(n, dtype=np.float32)
        self.info = np.zeros((n, 8), dtype=np.int32)

    def set_sooli(self, belief: int = 0, return_pi: bool = False, play_heur: bool = False,
                  lam: float = 0.0) -> None:
        """Search options for sooli decisions (see tc_sample_world_sooli, resolve_sooli)."""
        lib.tc_env_set_sooli(self._h, belief, int(return_pi), int(play_heur), float(lam))

    def set_equity(self, equity: np.ndarray) -> None:
        eq = np.ascontiguousarray(equity, dtype=np.float64).reshape(25, 2)
        lib.tc_env_set_equity(self._h, eq.ctypes.data_as(_P(C.c_double)))

    def observe(self):
        lib.tc_env_observe(self._h, self.feat.ctypes.data, self.mask.ctypes.data,
                           self.seat.ctypes.data, self.phase.ctypes.data)
        return self.feat, self.mask, self.seat, self.phase

    def step(self, actions: np.ndarray) -> int:
        a = np.ascontiguousarray(actions, dtype=np.int32)
        return lib.tc_env_step(self._h, a.ctypes.data, self.done.ctypes.data,
                               self.delta0.ctypes.data, self.info.ctypes.data)

    def set_deal(self, i: int, hands_masks, dealer: int, score0: int, score1: int) -> None:
        arr = (C.c_uint64 * 4)(*hands_masks)
        lib.tc_env_set_deal(self._h, i, arr, dealer, score0, score1)

    def dd_finish(self, dd_left: int) -> int:
        return lib.tc_env_dd_finish(self._h, dd_left, self.done.ctypes.data, self.delta0.ctypes.data)

    def observe_live(self):
        """(features, masks, game indices) for live games only, compact."""
        if not hasattr(self, "_idx"):
            self._idx = np.zeros(self.n, dtype=np.int32)
        k = lib.tc_env_observe_live(self._h, self.feat.ctypes.data, self.mask.ctypes.data, self._idx.ctypes.data)
        return self.feat[:k], self.mask[:k], self._idx[:k]

    def step_live(self, idx: np.ndarray, actions: np.ndarray) -> None:
        idx = np.ascontiguousarray(idx, dtype=np.int32)
        a = np.ascontiguousarray(actions, dtype=np.int32)
        self.done[:] = 0
        lib.tc_env_step_live(self._h, idx.ctypes.data, a.ctypes.data, len(idx),
                             self.done.ctypes.data, self.delta0.ctypes.data)

    def set_state_repeat(self, j: int, deal: TcDeal, count: int) -> None:
        lib.tc_env_set_state_repeat(self._h, j, C.byref(deal), count)

    def park_all(self) -> None:
        lib.tc_env_park_all(self._h)

    def set_state(self, i: int, deal: TcDeal) -> None:
        lib.tc_env_set_state(self._h, i, C.byref(deal))

    def deal(self, i: int) -> TcDeal:
        return lib.tc_env_deal(self._h, i).contents

    def hands(self) -> tuple[np.ndarray, np.ndarray]:
        """(n, 4) uint64 hands and current actors - research labelling only."""
        h = np.zeros((self.n, 4), dtype=np.uint64)
        a = np.zeros(self.n, dtype=np.int32)
        lib.tc_env_hands(self._h, h.ctypes.data, a.ctypes.data)
        return h, a

    def reset_all(self) -> None:
        lib.tc_env_reset_all(self._h)

    def __del__(self):
        h = getattr(self, "_h", None)
        if h:
            lib.tc_env_free(h)
            self._h = None
```

### E003 — Mlp, lines 321–350

```python
class Mlp:
    """A QNet's weights in native memory, for rollouts without Python."""

    def __init__(self, net):
        sd = {k: v.detach().cpu().float().numpy() for k, v in net.state_dict().items()}
        cfg = net.config
        parts = [sd["inp.weight"], sd["inp.bias"]]
        for b in range(cfg["blocks"]):
            for name in ("norm.weight", "norm.bias", "fc1.weight", "fc1.bias", "fc2.weight", "fc2.bias"):
                parts.append(sd[f"blocks.{b}.{name}"])
        parts += [sd["norm.weight"], sd["norm.bias"], sd["out.weight"], sd["out.bias"]]
        flat = np.ascontiguousarray(np.concatenate([p.ravel() for p in parts]), dtype=np.float32)
        self.encoder = cfg.get("encoder", 1)
        self.width = cfg["width"]
        self._h = lib.tc_mlp_new(feature_dim(self.encoder), cfg["width"], cfg["blocks"], NUM_ACTIONS,
                                 self.encoder, flat.ctypes.data)
        if not self._h:
            raise ValueError("unsupported network shape")

    def forward(self, feat: np.ndarray) -> np.ndarray:
        x = np.ascontiguousarray(feat, dtype=np.uint8)
        out = np.zeros((len(x), NUM_ACTIONS), dtype=np.float32)
        lib.tc_mlp_forward(self._h, x.ctypes.data, len(x), out.ctypes.data)
        return out

    def __del__(self):
        h = getattr(self, "_h", None)
        if h:
            lib.tc_mlp_free(h)
            self._h = None
```

### E012 — DealModel, lines 22–50

```python
@dataclass(frozen=True)
class DealModel:
    dealer_win: float
    points_given_dealer: dict[int, float]
    points_given_other: dict[int, float]

    @classmethod
    def from_outcomes(cls, outcomes) -> "DealModel":
        """outcomes: iterable of (dealer_team_won: bool, points: int)."""
        dealer: dict[int, int] = {}
        other: dict[int, int] = {}
        for won, points in outcomes:
            bucket = dealer if won else other
            bucket[points] = bucket.get(points, 0) + 1
        nd, no = sum(dealer.values()), sum(other.values())
        return cls(nd / (nd + no),
                   {p: c / nd for p, c in sorted(dealer.items())},
                   {p: c / no for p, c in sorted(other.items())})

    def to_json(self) -> dict:
        return {"dealer_win": self.dealer_win,
                "points_given_dealer": {str(k): v for k, v in self.points_given_dealer.items()},
                "points_given_other": {str(k): v for k, v in self.points_given_other.items()}}

    @classmethod
    def from_json(cls, data: dict) -> "DealModel":
        return cls(data["dealer_win"],
                   {int(k): v for k, v in data["points_given_dealer"].items()},
                   {int(k): v for k, v in data["points_given_other"].items()})
```

### E012 — solve, lines 60–92

```python
def solve(model: DealModel, tol: float = 1e-14) -> dict[tuple[int, int, bool], float]:
    """P(we win) from (level, sign, we_deal); sign +1 we are up, -1 they are up, 0 at 0-0."""
    states = [(0, 0, d) for d in (False, True)] + [
        (lv, sg, d) for d in (False, True) for lv in range(1, LEVELS) for sg in (1, -1)]
    index = {s: i for i, s in enumerate(states)}
    rows = []
    for level, sign, we_deal in states:
        const, row = 0.0, []
        for we_won, points, p in _outcomes(model, we_deal):
            step = points // 4
            if level == 0:
                target = step
                if target >= LEVELS:
                    const += p * (1.0 if we_won else 0.0)
                    continue
                row.append((index[(target, 1 if we_won else -1, not we_deal)], p))
            elif we_won == (sign == 1):
                target = level + step
                if target >= LEVELS:
                    const += p * (1.0 if we_won else 0.0)
                    continue
                row.append((index[(target, sign, not we_deal)], p))
            else:
                row.append((index[(0, 0, not we_deal)], p))
        rows.append((const, row))
    value = np.full(len(states), 0.5)
    for _ in range(200_000):
        new = np.array([c + sum(p * value[j] for j, p in r) for c, r in rows])
        delta = np.max(np.abs(new - value))
        value = new
        if delta < tol:
            break
    return {s: float(value[i]) for s, i in index.items()}
```

### E012 — native_table, lines 95–102

```python
def native_table(values: dict[tuple[int, int, bool], float]) -> np.ndarray:
    table = np.zeros((25, 2))
    for col, team0_deals in ((0, False), (1, True)):
        table[0, col] = values[(0, 0, team0_deals)]
        for level in range(1, LEVELS):
            table[level, col] = values[(level, 1, team0_deals)]
            table[12 + level, col] = values[(level, -1, team0_deals)]
    return table
```

### E012 — Equity, lines 105–130

```python
class Equity:
    """Team-0 match equity and per-deal equity deltas."""

    def __init__(self, model: DealModel):
        self.model = model
        self.values = solve(model)
        self.table = native_table(self.values)

    def team0(self, score0: int, score1: int, dealer: int) -> float:
        if score0 >= 52:
            return 1.0
        if score1 >= 52:
            return 0.0
        row = 0 if score0 == 0 and score1 == 0 else (score0 // 4 if score0 else 12 + score1 // 4)
        return float(self.table[row, 1 if dealer % 2 == 0 else 0])

    def delta0(self, before: tuple[int, int], after: tuple[int, int], dealer: int) -> float:
        return self.team0(*after, dealer + 1) - self.team0(*before, dealer)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"model": self.model.to_json(),
                                    "table": self.table.tolist()}, indent=1))

    @classmethod
    def load(cls, path: Path) -> "Equity":
        return cls(DealModel.from_json(json.loads(Path(path).read_text())["model"]))
```

### E013 — _init, lines 40–50

```python
def _init(candidate: str, opponent: str, equity_path: str, ruleset: str = "v1") -> None:
    import torch

    torch.set_num_threads(1)
    from .equity import Equity
    from .incumbent import incumbent_agents

    _W["equity"] = Equity.load(Path(equity_path))
    _W["ruleset"] = ruleset
    _W["opponent"] = _with_sooli(incumbent_agents(opponent), ruleset)
    _W["candidate"] = _with_sooli(_make_candidate(candidate), ruleset)
```

### E013 — _make_candidate, lines 53–86

```python
def _make_candidate(spec: str) -> dict:
    """`profile:<key>`, a policy spec (see policies.py), or
    `search:<ckpt>[:w=32][:dd=6][:show=1][:belief=4][:bt=1.0][:be=0.1]`."""
    if spec == "best":
        from .best import best_agents
        return best_agents()
    if spec.startswith("profile:"):
        from .incumbent import incumbent_agents
        return incumbent_agents(spec.split(":", 1)[1])
    if spec.startswith("search:"):
        from . import model as qmodel
        from .search import SearchAgent
        parts = spec.split(":")[1:]
        opts = dict(p.split("=") for p in parts[1:])
        net = qmodel.load(parts[0], "cpu")
        table = _W["equity"].table
        belief = {"belief": int(opts.get("belief", 0)), "belief_t": float(opts.get("bt", 1.0)),
                  "belief_eps": float(opts.get("be", 0.1)), "belief_seats": opts.get("bs", "all")}
        if "ot" in opts:
            belief["opp_temp"] = float(opts["ot"])
        if "team" in opts:
            belief["team_net"] = qmodel.load(opts["team"], "cpu")
        if "bn" in opts:
            from .belief import load as load_belief
            belief.update(belief_net=load_belief(opts["bn"]), belief_n=int(opts.get("bN", 1024)),
                          belief_alpha=float(opts.get("ba", 0.5)))
        return {s: SearchAgent(net, table, s, worlds=int(opts.get("w", 32)), dd_left=int(opts.get("dd", 0)),
                               search_showing=int(opts.get("show", "0")),
                               keep=float(opts["keep"]) if "keep" in opts else None,
                               rami_bonus=float(opts.get("rb", 0.0)),
                               show_worlds=int(opts["sw"]) if "sw" in opts else None, **belief) for s in range(4)}
    from .policies import PolicyAgent, from_spec
    policy = from_spec(spec, "cpu")
    return {s: PolicyAgent(policy, s) for s in range(4)}
```

### E013 — _score_for, lines 89–96

```python
def _score_for(index: int, mode: str, seed: str) -> tuple[int, int]:
    if mode == "zero":
        return (0, 0)
    rng = random.Random(f"{seed}|score|{index}")
    level = rng.randrange(13)
    if level == 0:
        return (0, 0)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)
```

### E013 — _play, lines 99–139

```python
def _play(hands, score, candidate_team):
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_rules import MatchScore

    cand, opp = _W["candidate"], _W["opponent"]
    ruleset = _W.get("ruleset", "v1")
    if ruleset == "v1":
        match = create_match(initial_score=MatchScore(*score), initial_dealer=DEALER, match_ref="tuppi-ai-eval")
        active = (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY)
    else:
        from tuppi_engine.state import ACTIVE_PHASES
        from tuppi_rules import RulesetId
        match = create_match(initial_score=MatchScore(*score), initial_dealer=DEALER, match_ref="tuppi-ai-eval",
                             ruleset_id=RulesetId(RULESETS[ruleset]))
        active = ACTIVE_PHASES
    state = begin_explicit_deal(match, ExplicitDeal(dealer=DEALER, hands=hands))
    while state.phase in active:
        seat = state.current_actor
        actor = cand[seat] if seat % 2 == candidate_team else opp[seat]
        state = apply_match_action(state, actor.choose_action(match_observation_for(state, seat)))
    r = state.completed_deals[-1].public_result
    d0 = _W["equity"].delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), DEALER)
    value = d0 if candidate_team == 0 else -d0
    declarer_team = None if r.declarer is None else r.declarer % 2
    return {
        "value": value,
        "won": r.deal_score.winner_team.value == candidate_team,
        "points": r.deal_score.points if r.deal_score.winner_team.value == candidate_team else -r.deal_score.points,
        "tricks": r.team_tricks[candidate_team],
        "rami": r.contract.value == "RAMI",
        "cand_declared": declarer_team == candidate_team,
        "opp_declared": declarer_team is not None and declarer_team != candidate_team,
        "stolen": bool(getattr(r.deal_score, "stolen_rami", False)),
        "cand_sooli": getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 == candidate_team,
        "opp_sooli": getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 != candidate_team,
        "cand_sooli_won": (getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 == candidate_team
                           and r.deal_score.winner_team.value == candidate_team),
        "opp_sooli_won": (getattr(r, "soolaaja", None) is not None and r.soolaaja % 2 != candidate_team
                          and r.deal_score.winner_team.value != candidate_team),
    }
```

### E013 — measure, lines 142–161

```python
def measure(index: int, seed: str, scores: str) -> dict:
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules.cards import FULL_DECK

    rng = random.Random(f"{seed}|deal|{index}")
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    base = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
    score = _score_for(index, scores, seed)
    games = []
    with trusted_transitions():
        for rotation in range(4):
            hands = tuple(base[(seat + rotation) % 4] for seat in range(4))
            for team in (0, 1):
                games.append(_play(hands, score, team))
    out = {"index": index, "score": score, "value": statistics.fmean(g["value"] for g in games),
           "games": games}
    for key in STAT_KEYS:
        out[key] = statistics.fmean(float(g[key]) for g in games)
    return out
```

### E013 — summarise, lines 168–178

```python
def summarise(rows: list[dict]) -> dict:
    values = [r["value"] for r in rows]
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else float("nan")
    se = sd / math.sqrt(n)
    summary = {"base_deals": n, "games": 8 * n, "equity_per_deal": mean, "sd": sd,
               "ci95": [mean - 1.96 * se, mean + 1.96 * se]}
    for key in STAT_KEYS:
        summary[key] = statistics.fmean(r[key] for r in rows)
    return summary
```

### E013 — evaluate, lines 181–194

```python
def evaluate(candidate: str, deals: int, seed: str = "tuppi-ai-eval-v1", scores: str = "zero",
             opponent: str = "partner_aware_lead_v2", workers: int = 12,
             equity_path: str = str(ROOT / "models" / "equity_incumbent.json"), ruleset: str = "v1") -> dict:
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init,
                             initargs=(candidate, opponent, equity_path, ruleset)) as pool:
        rows = list(pool.map(measure, range(deals), [seed] * deals, [scores] * deals, chunksize=8))
    summary = summarise(rows)
    summary.update({"candidate": candidate, "opponent": opponent, "seed": seed, "scores": scores,
                    "ruleset": RULESETS[ruleset],
                    "seconds": round(time.time() - t0, 1),
                    "values": [r["value"] for r in rows],
                    "games": [g for r in rows for g in r["games"]]})
    return summary
```

### E014 — _leg, lines 29–52

```python
def _leg(pair: int, seed: str, candidate_team: int, cap: int) -> dict:
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action,
                              begin_explicit_deal, create_match, match_observation_for)
    from tuppi_rules import MatchScore
    from tuppi_rules.cards import FULL_DECK

    cand, opp = _W["candidate"], _W["opponent"]
    state = create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="tuppi-ai-match")
    deals = 0
    while not state.terminal and deals < cap:
        rng = random.Random(f"{seed}|pair|{pair}|deal|{deals}")
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
        state = begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=hands))
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            actor = cand[seat] if seat % 2 == candidate_team else opp[seat]
            state = apply_match_action(state, actor.choose_action(match_observation_for(state, seat)))
        deals += 1
    if not state.terminal:
        return {"result": 0.5, "deals": deals, "censored": True}
    won = state.score.for_team(__import__("tuppi_rules").Team(candidate_team)) >= 52
    return {"result": 1.0 if won else 0.0, "deals": deals, "censored": False}
```

### E014 — measure_pair, lines 55–62

```python
def measure_pair(pair: int, seed: str, cap: int) -> dict:
    from tuppi_engine.trusted import trusted_transitions

    with trusted_transitions():
        a = _leg(pair, seed, 0, cap)
        b = _leg(pair, seed, 1, cap)
    return {"pair": pair, "score": (a["result"] + b["result"]) / 2,
            "deals": a["deals"] + b["deals"], "censored": int(a["censored"]) + int(b["censored"])}
```

### E014 — evaluate_matches, lines 65–83

```python
def evaluate_matches(candidate: str, pairs: int, seed: str = "tuppi-ai-match-v1",
                     opponent: str = "partner_aware_lead_v2", workers: int = 12,
                     cap: int = DEFAULT_CAP, equity_path: str | None = None) -> dict:
    from .evaluate import ROOT
    equity_path = equity_path or str(ROOT / "models" / "equity_incumbent.json")
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init_worker,
                             initargs=(candidate, opponent, equity_path)) as pool:
        rows = list(pool.map(measure_pair, range(pairs), [seed] * pairs, [cap] * pairs, chunksize=1))
    scores = [r["score"] for r in rows]
    mean = statistics.fmean(scores)
    se = statistics.stdev(scores) / math.sqrt(len(scores)) if len(scores) > 1 else float("nan")
    return {"candidate": candidate, "opponent": opponent, "pairs": pairs, "seed": seed,
            "p_win": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se],
            "pair_wins": sum(s == 1.0 for s in scores), "pair_ties": sum(s == 0.5 for s in scores),
            "pair_losses": sum(s == 0.0 for s in scores),
            "censored_legs": sum(r["censored"] for r in rows),
            "mean_deals_per_leg": statistics.fmean(r["deals"] for r in rows) / 2,
            "seconds": round(time.time() - t0, 1)}
```

### E016 — PlayerObservation, lines 33–112

```python
@dataclass(frozen=True, slots=True)
class PlayerObservation:
    match_ref: str
    deal_ref: str
    observing_seat: int
    team: Team
    partner_seat: int
    dealer: int
    forehand: int
    phase: EnginePhase
    current_actor: int | None
    own_hand: tuple[Card, ...]
    show_actions: tuple[RulesShowAction, ...]
    publicly_shown_cards: tuple[tuple[int, Card], ...]
    contract: Contract | None
    declarer: int | None
    first_leader: int | None
    completed_tricks: tuple[CompletedTrick, ...]
    current_trick: tuple[PlayedCard, ...]
    team_tricks: tuple[int, int]
    match_score: MatchScore
    legal_actions: tuple[Action, ...]
    deal_terminal: bool
    match_terminal: bool
    schema_version: str = field(default=OBSERVATION_SCHEMA_VERSION, init=False)
    ruleset_id: RulesetId = RulesetId.PROJECT_TARGET_V1
    visibility: str = field(default="player_private", init=False)
    # project_target_v2 (sooli). The exchanged cards are visible only to the
    # soolaaja and the partner; the RAMI pair sees that the exchange happened.
    sooli_decisions: tuple[tuple[int, bool], ...] = ()
    soolaaja: int | None = None
    sooli_exchanged: bool = False
    sooli_given_card: Card | None = None
    sooli_returned_card: Card | None = None
    sooli_tricks: tuple[SooliTrick, ...] = ()
    sooli_current_trick: tuple[PlayedCard, ...] = ()
    # project_target_v3 (locked bids): during showing no bid is visible, not
    # even one's own; only how many bids have been taken (public through the
    # bid_locked events). Zero in every other case.
    bids_locked: int = 0

    def __post_init__(self) -> None:
        if not is_valid_match_ref(self.match_ref):
            raise StateInvariantError("observation match_ref is invalid")
        if not is_valid_deal_ref(self.deal_ref):
            raise StateInvariantError("observation deal_ref is invalid")
        if type(self.observing_seat) is not int or self.observing_seat not in range(4):
            raise StateInvariantError("observing_seat must be in 0..3")
        if self.team is not team_for_seat(self.observing_seat):
            raise StateInvariantError("observation team disagrees with seat")
        if self.partner_seat != partner_for_seat(self.observing_seat):
            raise StateInvariantError("observation partner disagrees with seat")
        if type(self.own_hand) is not tuple:
            raise StateInvariantError("own_hand must be an immutable tuple")
        if type(self.show_actions) is not tuple or type(self.completed_tricks) is not tuple:
            raise StateInvariantError("public histories must be immutable tuples")
        if type(self.current_trick) is not tuple or type(self.legal_actions) is not tuple:
            raise StateInvariantError("partial trick and legal actions must be tuples")
        if self.current_actor != self.observing_seat and self.legal_actions:
            raise StateInvariantError("nonacting observation cannot contain legal actions")
        if self.deal_terminal and self.legal_actions:
            raise StateInvariantError("terminal observation cannot contain legal actions")
        if type(self.deal_terminal) is not bool or type(self.match_terminal) is not bool:
            raise StateInvariantError("terminal fields must be booleans")
        if self.publicly_shown_cards != tuple(
            (action.seat, action.shown_card) for action in self.show_actions
        ):
            raise StateInvariantError("public shown-card list disagrees with show history")
        if self.match_terminal and not self.deal_terminal:
            raise StateInvariantError("match-terminal observation must be deal-terminal")
        hidden = self.ruleset_id in LOCKED_BID_RULESETS and self.phase is EnginePhase.SHOWING
        if type(self.bids_locked) is not int or not 0 <= self.bids_locked <= 3:
            raise StateInvariantError("bids_locked must be an integer in 0..3")
        if hidden and self.show_actions:
            raise StateInvariantError("locked bids are hidden until showing resolves")
        if self.bids_locked and not hidden:
            raise StateInvariantError("bids_locked is only for locked-bid showing")
        in_exchange = self.soolaaja is not None and self.observing_seat in (self.soolaaja, (self.soolaaja + 2) % 4)
        if not in_exchange and (self.sooli_given_card is not None or self.sooli_returned_card is not None):
            raise StateInvariantError("exchanged cards are private to the soolaaja and the partner")
```

### E016 — _observation_for_validated, lines 198–241

```python
def _observation_for_validated(state: DealState, seat: int) -> PlayerObservation:
    """Project a state the immediate caller just validated, for a checked seat.

    ``match_observation_for`` reuses its own match validation - which already
    revalidates the active deal - through this helper and the legal-action
    helper above, so one public observation performs one full deal validation.
    """

    current_score = state.ending_score or state.starting_score
    hidden = state.ruleset_id in LOCKED_BID_RULESETS and state.phase is EnginePhase.SHOWING
    visible_shows = () if hidden else tuple(state.show_actions)
    return PlayerObservation(
        match_ref=state.match_ref,
        deal_ref=state.deal_ref,
        observing_seat=seat,
        team=team_for_seat(seat),
        partner_seat=partner_for_seat(seat),
        dealer=state.dealer,
        forehand=state.forehand,
        phase=state.phase,
        current_actor=state.current_actor,
        own_hand=tuple(state.hands[seat]),
        show_actions=visible_shows,
        publicly_shown_cards=tuple((action.seat, action.shown_card) for action in visible_shows),
        contract=state.contract,
        declarer=state.declarer,
        first_leader=state.first_leader,
        completed_tricks=tuple(state.completed_tricks),
        current_trick=tuple(state.current_trick),
        team_tricks=state.team_tricks,
        match_score=current_score,
        legal_actions=_legal_actions_for_validated(state, seat),
        deal_terminal=state.complete,
        match_terminal=state.terminal,
        ruleset_id=state.ruleset_id,
        sooli_decisions=tuple(state.sooli_decisions),
        soolaaja=state.soolaaja,
        sooli_exchanged=state.sooli_returned is not None,
        sooli_given_card=state.sooli_given if _knows_exchange(state, seat) else None,
        sooli_returned_card=state.sooli_returned if _knows_exchange(state, seat) else None,
        sooli_tricks=tuple(state.sooli_tricks),
        sooli_current_trick=tuple(state.sooli_current),
        bids_locked=len(state.show_actions) if hidden else 0,
    )
```

### E017 — action_to_data, lines 107–125

```python
def action_to_data(action: Action) -> dict[str, object]:
    if isinstance(action, ShowAction):
        return {
            "declared_contract": action.declared_contract.value,
            "seat": action.seat,
            "shown_card": card_to_code(action.shown_card),
            "type": "show",
        }
    if isinstance(action, PlayCardAction):
        return {
            "card": card_to_code(action.card),
            "seat": action.seat,
            "type": "play",
        }
    if isinstance(action, SooliDecisionAction):
        return {"play_sooli": action.play_sooli, "seat": action.seat, "type": "sooli_decision"}
    if isinstance(action, SooliExchangeAction):
        return {"card": card_to_code(action.card), "seat": action.seat, "type": "sooli_exchange"}
    raise SerializationError("cannot serialize a non-engine action")
```

### E017 — _sooli_observation_data, lines 261–275

```python
def _sooli_observation_data(observation: PlayerObservation) -> dict[str, object]:
    return {
        "decisions": [
            {"play_sooli": accepted, "seat": seat} for seat, accepted in observation.sooli_decisions
        ],
        "exchanged": observation.sooli_exchanged,
        "given_card": (
            None if observation.sooli_given_card is None else card_to_code(observation.sooli_given_card)
        ),
        "partner": None if observation.soolaaja is None else (observation.soolaaja + 2) % 4,
        "returned_card": (
            None if observation.sooli_returned_card is None else card_to_code(observation.sooli_returned_card)
        ),
        "soolaaja": observation.soolaaja,
    }
```

### E017 — observation_to_data, lines 278–298

```python
def observation_to_data(observation: PlayerObservation) -> dict[str, object]:
    """Wire form of an observation.

    project_target_v1 observations keep their original keys. Under the sooli
    rulesets a ``sooli`` block is added, and a sooli deal's three-card tricks
    are reported in ``completed_tricks`` and ``current_trick`` (the four-card
    trick lists are empty in a sooli deal). Under locked bids ``bids_locked``
    counts the hidden bids taken during showing.
    """

    if not isinstance(observation, PlayerObservation):
        raise SerializationError("observation must be a PlayerObservation")
    sooli_deal = observation.sooli_exchanged
    completed = observation.sooli_tricks if sooli_deal else observation.completed_tricks
    current = observation.sooli_current_trick if sooli_deal else observation.current_trick
    data = _observation_data(observation, completed, current)
    if observation.ruleset_id in SOOLI_RULESETS:
        data["sooli"] = _sooli_observation_data(observation)
    if observation.ruleset_id in LOCKED_BID_RULESETS:
        data["bids_locked"] = observation.bids_locked
    return data
```

### E017 — _observation_data, lines 301–333

```python
def _observation_data(observation: PlayerObservation, completed, current) -> dict[str, object]:
    return {
        "completed_tricks": [
            completed_trick_to_data(trick) for trick in completed
        ],
        "contract": None if observation.contract is None else observation.contract.value,
        "current_actor": observation.current_actor,
        "current_trick": [_played_card_data(play) for play in current],
        "deal_ref": observation.deal_ref,
        "deal_terminal": observation.deal_terminal,
        "dealer": observation.dealer,
        "declarer": observation.declarer,
        "first_leader": observation.first_leader,
        "forehand": observation.forehand,
        "legal_actions": [action_to_data(action) for action in observation.legal_actions],
        "match_ref": observation.match_ref,
        "match_score": _score_data(observation.match_score),
        "match_terminal": observation.match_terminal,
        "observing_seat": observation.observing_seat,
        "own_hand": [card_to_code(card) for card in observation.own_hand],
        "partner_seat": observation.partner_seat,
        "phase": observation.phase.value,
        "publicly_shown_cards": [
            {"card": card_to_code(card), "seat": seat}
            for seat, card in observation.publicly_shown_cards
        ],
        "ruleset_id": observation.ruleset_id.value,
        "schema_version": observation.schema_version,
        "show_actions": [_show_data(show) for show in observation.show_actions],
        "team": observation.team.value,
        "team_tricks": list(observation.team_tricks),
        "visibility": observation.visibility,
    }
```

### E019 — transition_rising_score, lines 53–69

```python
def transition_rising_score(current: MatchScore, deal_score: DealScore) -> MatchScore:
    validated = _validate_match_score(current)
    deal_score = validate_deal_score(deal_score)
    if is_match_terminal(validated):
        raise TerminalMatchError("a terminal match cannot accept another deal score")

    winner = deal_score.winner_team
    up_team = validated.up_team
    if up_team is None:
        if winner is Team.TEAM_0:
            return MatchScore(deal_score.points, 0)
        return MatchScore(0, deal_score.points)
    if winner is up_team:
        if up_team is Team.TEAM_0:
            return MatchScore(validated.team0 + deal_score.points, 0)
        return MatchScore(0, validated.team1 + deal_score.points)
    return MatchScore(0, 0)
```

### E022 — SuitPolicy, lines 87–91

```python
class SuitPolicy(StrEnum):
    """How each seat chooses which card of the suit to contribute."""

    LOWEST = "lowest"
    HIGHEST = "highest"
```

### E022 — play_out, lines 428–462

```python
def play_out(
    own_ranks: Sequence[int],
    opponent_ranks: Sequence[Sequence[int]],
    *,
    times_led: int,
    policy: SuitPolicy,
) -> tuple[int, ...]:
    """Play the suit out *times_led* times and return tricks won per seat.

    Index 0 is the analysed seat. Every seat that still holds the suit follows;
    a seat that has run out contributes nothing and cannot win. The trick goes
    to the highest card contributed, which under a fixed policy makes the result
    independent of the order the seats play in.
    """

    if type(times_led) is not int or times_led < 0:
        raise CombinatoricsError("times_led must be a nonnegative integer")
    if not isinstance(policy, SuitPolicy):
        raise CombinatoricsError("policy must be a SuitPolicy value")
    if len(opponent_ranks) != OPPONENT_COUNT:
        raise CombinatoricsError("exactly three opponent holdings are required")

    hands = [sorted(own_ranks)] + [sorted(hand) for hand in opponent_ranks]
    wins = [0, 0, 0, 0]
    for _ in range(times_led):
        contributed: dict[int, int] = {}
        for seat, hand in enumerate(hands):
            if not hand:
                continue
            contributed[seat] = hand.pop(0 if policy is SuitPolicy.LOWEST else -1)
        if not contributed:
            break
        winner = max(contributed, key=lambda seat: contributed[seat])
        wins[winner] += 1
    return tuple(wins)
```

### E022 — conditional_layouts, lines 742–793

```python
def conditional_layouts(
    own_ranks: Sequence[int],
    *,
    seen_ranks: Sequence[int] = (),
    hand_sizes: tuple[int, int, int] = (CARDS_PER_HAND,) * OPPONENT_COUNT,
    void: tuple[bool, bool, bool] = (False,) * OPPONENT_COUNT,
) -> Iterator[tuple[tuple[tuple[int, ...], ...], Fraction]]:
    """Yield every layout of the *unseen* outstanding ranks, with probability.

    The mid-deal generalisation of :func:`layouts`. Cards in *seen_ranks* are
    removed from circulation, hand sizes may differ (they do part-way through a
    trick, where seats that have already played hold one card fewer), and a
    proven void forbids any placement in that hand. Probabilities are
    renormalised over the layouts the evidence permits and sum to 1.

    This enumerates ``3**outstanding`` rank assignments and is the **reference**
    implementation: correct, and far too slow to consult inside a decision. Use
    it to verify a faster law, which is what
    ``test_conditioned_ducking_matches_the_reference_enumeration`` does.
    """

    outstanding_ranks = _conditioned_outstanding(own_ranks, seen_ranks)
    outstanding = len(outstanding_ranks)
    unseen = _check_conditioning(outstanding, hand_sizes, void)
    if 3 ** outstanding > MAX_LAYOUTS:
        raise CombinatoricsError("layout enumeration exceeds the exact budget")

    placements: list[tuple[tuple[tuple[int, ...], ...], int]] = []
    total = 0
    for assignment in itertools.product(range(OPPONENT_COUNT), repeat=outstanding):
        buckets: tuple[list[int], ...] = ([], [], [])
        for rank, owner in zip(outstanding_ranks, assignment):
            buckets[owner].append(rank)
        counts = tuple(len(bucket) for bucket in buckets)
        if any(flag and count for flag, count in zip(void, counts)):
            continue
        remainder = tuple(
            size - count for size, count in zip(hand_sizes, counts)
        )
        if any(part < 0 for part in remainder):
            continue
        ways = multinomial(unseen - outstanding, remainder)
        if not ways:
            continue
        placements.append((tuple(tuple(bucket) for bucket in buckets), ways))
        total += ways
    if total == 0:
        raise CombinatoricsError(
            "the stated voids and hand sizes admit no placement of the suit"
        )
    for layout, ways in placements:
        yield layout, Fraction(ways, total)
```

### E023 — ducking_probabilities, lines 95–162

```python
@lru_cache(maxsize=8192)
def ducking_probabilities(
    own_ranks: tuple[int, ...],
    outstanding_ranks: tuple[int, ...],
    hand_sizes: tuple[int, int, int],
    void: tuple[bool, bool, bool],
    max_leads: int,
    *,
    contested_only: bool = False,
) -> tuple[Fraction, ...]:
    """P(this holding wins round *i*) for i = 1..max_leads, everyone ducking.

    Round *i* is contested by each seat's *i*-th lowest card, and an opponent's
    *i*-th lowest lies below a given card exactly when that opponent holds *i* or
    more cards below it. So a round turns only on how the outstanding ranks split
    into those below the card and those above it, never on which ranks they are -
    which is what replaces an enumeration over rank assignments with a pair of
    three-part compositions.

    With *contested_only*, a round counts only while some opponent can still
    contribute to it. That is the form a liability needs: a round nobody can lead
    is not a trick anybody takes.
    """

    mine = sorted(own_ranks)
    unseen = sum(hand_sizes)
    outstanding = len(outstanding_ranks)
    if outstanding > unseen:
        raise AgentsValidationError("more of the suit is outstanding than is unseen")
    filler = unseen - outstanding
    caps = tuple(0 if flag else size for flag, size in zip(void, hand_sizes))

    normaliser = 0
    for counts in _capped_compositions(outstanding, caps):
        remainder = tuple(size - count for size, count in zip(hand_sizes, counts))
        normaliser += _multinomial(outstanding, counts) * _multinomial(filler, remainder)
    if normaliser == 0:
        raise AgentsValidationError("the public record admits no placement of the suit")

    rounds = min(max_leads, len(mine))
    totals: list[Fraction] = []
    for index in range(rounds):
        card = mine[index]
        needed = index + 1
        below = sum(1 for rank in outstanding_ranks if rank < card)
        above = outstanding - below
        winning = 0
        for lows in _capped_compositions(below, caps):
            highs_caps = tuple(cap - low for cap, low in zip(caps, lows))
            for highs in _capped_compositions(above, highs_caps):
                held = tuple(low + high for low, high in zip(lows, highs))
                if contested_only and max(held) < needed:
                    continue
                if any(
                    total >= needed and low < needed
                    for total, low in zip(held, lows)
                ):
                    continue
                remainder = tuple(
                    size - count for size, count in zip(hand_sizes, held)
                )
                winning += (
                    _multinomial(below, lows)
                    * _multinomial(above, highs)
                    * _multinomial(filler, remainder)
                )
        totals.append(Fraction(winning, normaliser))
    return tuple(totals) + (Fraction(0),) * (max_leads - rounds)
```

### E023 — expected_ducking_tricks, lines 165–181

```python
def expected_ducking_tricks(
    own_ranks: tuple[int, ...],
    outstanding_ranks: tuple[int, ...],
    hand_sizes: tuple[int, int, int],
    void: tuple[bool, bool, bool],
) -> Fraction:
    """Expected tricks this holding takes while the suit is still contested."""

    if not own_ranks:
        return Fraction(0)
    return sum(
        ducking_probabilities(
            own_ranks, outstanding_ranks, hand_sizes, void,
            len(own_ranks), contested_only=True,
        ),
        Fraction(0),
    )
```

### E023 — card_liability, lines 184–203

```python
def card_liability(
    rank: int,
    own_ranks: tuple[int, ...],
    outstanding_ranks: tuple[int, ...],
    hand_sizes: tuple[int, int, int],
    void: tuple[bool, bool, bool],
) -> Fraction:
    """Expected tricks that keeping *rank* costs, over discarding it.

    The card discarded joins the outstanding pool only in the sense that it is
    gone from this hand; it cannot win a later trick for anybody, so it is
    dropped from the analysis rather than handed to an opponent.
    """

    if rank not in own_ranks:
        raise AgentsValidationError("the card must be held to be discarded")
    kept = expected_ducking_tricks(own_ranks, outstanding_ranks, hand_sizes, void)
    without = tuple(value for value in own_ranks if value != rank)
    shed = expected_ducking_tricks(without, outstanding_ranks, hand_sizes, void)
    return kept - shed
```

### E023 — public_conditioning, lines 225–268

```python
def public_conditioning(observation: PlayerObservation, suit: Suit) -> tuple:
    """Outstanding ranks, hand sizes and proven voids for *suit*.

    Only played cards and proven voids are used. A card shown at deal start but
    not yet played stays outstanding with an unknown owner, which is the
    documented weakening in this module's docstring.
    """

    seat = observation.observing_seat
    others = opponent_order(seat)
    plays = _played_cards(observation)

    played_in_suit = {card.rank.value for _, card in plays if card.suit is suit}
    held = {card.rank.value for card in observation.own_hand if card.suit is suit}
    outstanding = tuple(
        sorted(
            (
                rank
                for rank in range(2, 15)
                if rank not in played_in_suit and rank not in held
            ),
            reverse=True,
        )
    )

    counts = {other: 0 for other in others}
    for actor, _ in plays:
        if actor in counts:
            counts[actor] += 1
    hand_sizes = tuple(CARDS_PER_HAND - counts[other] for other in others)

    # A seat is void when it failed to follow a suit that was led.
    void_seats: set[int] = set()
    groups = [trick.plays for trick in observation.completed_tricks]
    if observation.current_trick:
        groups.append(tuple(observation.current_trick))
    for group in groups:
        if not group or group[0].card.suit is not suit:
            continue
        for play in group[1:]:
            if play.card.suit is not suit:
                void_seats.add(play.seat)
    void = tuple(other in void_seats for other in others)
    return outstanding, hand_sizes, void
```

### E024 — test_contested_rounds_match_a_brute_force_walk, lines 66–91

```python
@pytest.mark.parametrize("own,seen,hand_sizes,void", GRID)
def test_contested_rounds_match_a_brute_force_walk(own, seen, hand_sizes, void):
    """A round nobody can lead is not a trick anybody takes."""

    mine = sorted(own)
    rounds = len(mine)
    expected = [Fraction(0)] * rounds
    for layout, probability in conditional_layouts(
        list(own), seen_ranks=list(seen), hand_sizes=hand_sizes, void=void
    ):
        hands = [sorted(hand) for hand in layout]
        survives = max((len(hand) for hand in hands), default=0)
        for index in range(rounds):
            if index + 1 > survives:
                continue
            others = [hand[index] for hand in hands if len(hand) > index]
            if not others or mine[index] > max(others):
                expected[index] += probability
    local = ducking_probabilities(
        tuple(mine), _outstanding(own, seen), hand_sizes, void, rounds,
        contested_only=True,
    )
    assert local == tuple(expected)
    assert expected_ducking_tricks(
        tuple(mine), _outstanding(own, seen), hand_sizes, void
    ) == sum(expected, Fraction(0))
```

### E025 — SupportBudget, lines 62–74

```python
@dataclass(frozen=True, slots=True)
class SupportBudget:
    max_remaining_tricks: int = DEFAULT_REMAINING_TRICKS
    max_worlds: int = DEFAULT_WORLDS
    max_engine_transitions: int = DEFAULT_ENGINE_TRANSITIONS

    def __post_init__(self):
        for name, ceiling in (("max_remaining_tricks", CEILING_REMAINING_TRICKS),
                              ("max_worlds", CEILING_WORLDS),
                              ("max_engine_transitions", CEILING_ENGINE_TRANSITIONS)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= ceiling:
                raise ValueError(f"{name} must be an integer in 0..{ceiling}")
```

### E025 — ResearchWorld, lines 110–119

```python
@dataclass(frozen=True, slots=True)
class ResearchWorld:
    assignment: HiddenHandAssignment
    continuation: HypotheticalContinuation

    @property
    def content_key(self) -> tuple[tuple[int, ...], ...]:
        """Private allocation identity, independent of sample/protocol metadata."""
        return tuple(tuple(sorted(map(card_to_index, hand)))
                     for hand in self.assignment.hands)
```

### E025 — SupportResult, lines 122–149

```python
@dataclass(frozen=True, slots=True)
class SupportResult:
    """Research-private result. Only diagnostics() is suitable for explanations."""
    status: SupportStatus
    decision_key: str | None
    world_count: int | None
    counted_candidates: int | None
    assignments_attempted: int
    engine_transitions: int
    reason: str | None
    # Not included in diagnostic output; this object must not enter a policy.
    research_worlds: tuple[ResearchWorld, ...] = field(default=(), repr=False)

    def __post_init__(self):
        if self.status is SupportStatus.EXACT_COMPLETE:
            if not self.research_worlds or self.world_count != len(self.research_worlds):
                raise SupportInvariantError("exact support must contain every world")
        elif self.world_count is not None or self.research_worlds:
            raise SupportInvariantError("unresolved support must not expose a partial set")

    def diagnostics(self) -> dict:
        return {
            "status": self.status.value, "decision_key": self.decision_key,
            "world_count": self.world_count, "counted_candidates": self.counted_candidates,
            "assignments_attempted": self.assignments_attempted,
            "engine_transitions": self.engine_transitions, "fallback_reason": self.reason,
            "claim_type": "UNCLASSIFIED",
        }
```

### E025 — semantic_observation_key, lines 96–107

```python
def semantic_observation_key(observation: PlayerObservation) -> str:
    """Own hand/action order and public history, with protocol identities absent.

    Mirrors the field design of tuppi_search/information_state.py without a
    dependency on that research layer. Public voids are derivable from history.
    No assignment, sample metadata, private owner map or hidden hand is accepted.
    """
    if not isinstance(observation, PlayerObservation):
        raise TypeError("semantic_observation_key requires PlayerObservation")
    data = {name: _public_value(getattr(observation, name)) for name in OBSERVATION_KEY_FIELDS}
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return "nolo-observation-v1:" + hashlib.sha256(encoded).hexdigest()
```

### E025 — build_support, lines 272–330

```python
def build_support(observation: PlayerObservation, budget: SupportBudget) -> SupportResult:
    """Return the complete hard support or a typed unresolved result, never a sample.

    Wrong entry-point types are programmer errors. Contradictory evidence returns
    INVALID_INPUT. Rejection/count disagreement within exact enumeration raises
    SupportInvariantError, and unexpected errors propagate unchanged.
    """
    if not isinstance(observation, PlayerObservation):
        raise TypeError("build_support requires PlayerObservation, not a private state/fixture")
    if not isinstance(budget, SupportBudget):
        raise TypeError("build_support requires SupportBudget")
    key = semantic_observation_key(observation)
    counted = None
    attempted = 0
    meter = _ReplayMeter(budget.max_engine_transitions)

    def unresolved(status, reason):
        return SupportResult(status, key, None, counted, attempted, meter.calls, reason)

    if observation.phase is not EnginePhase.TRICK_PLAY or observation.contract is not Contract.NOLO:
        return unresolved(SupportStatus.OUT_OF_SCOPE, "requires resolved NOLO trick play")
    remaining = 13 - len(observation.completed_tricks)
    if not 1 <= remaining <= budget.max_remaining_tricks:
        return unresolved(SupportStatus.OUT_OF_SCOPE, "remaining-trick limit")
    try:
        _validate_public_record(observation)
        model = HardConstraintModel.build(observation)
    except (ConstraintError, AgentsValidationError, RulesError, StateInvariantError) as exc:
        return unresolved(SupportStatus.INVALID_INPUT, str(exc))
    counted = feasible_assignment_count(model)
    if counted == 0:
        return unresolved(SupportStatus.INVALID_INPUT, "no hard-feasible assignments")
    if counted > budget.max_worlds:
        return unresolved(SupportStatus.SUPPORT_BUDGET, "complete count exceeds world limit")
    worlds = []
    seen = set()
    for assignment in _assignments(model, observation):
        attempted += 1
        try:
            continuation = meter.replay(observation, assignment)
        except _TransitionLimit:
            return unresolved(SupportStatus.SEARCH_BUDGET, "engine transition limit during replay")
        except (EngineValidationError, RulesError, ContinuationError) as exc:
            raise SupportInvariantError(
                f"hard-model candidate {assignment.content_key()} rejected after "
                f"{meter.calls} engine calls: {exc}"
            ) from exc
        replayed_key = semantic_observation_key(observation_for(continuation.state, observation.observing_seat))
        if replayed_key != key:
            raise SupportInvariantError("replay changed semantic observation")
        world = ResearchWorld(assignment, continuation)
        if world.content_key in seen:
            raise SupportInvariantError("duplicate assignment")
        seen.add(world.content_key)
        worlds.append(world)
    if len(worlds) != counted:
        raise SupportInvariantError(f"enumerated {len(worlds)} assignments, counted {counted}")
    return SupportResult(SupportStatus.EXACT_COMPLETE, key, counted, counted,
                         attempted, meter.calls, None, tuple(worlds))
```

### E026 — _search, lines 163–238

```python
def _search(states, *, seat: int, team: int, meter: _Meter, agents) -> tuple[int, dict]:
    """Value of one information class, and the own plan achieving it.

    ``states`` are the hypothetical states of every world still compatible with
    the public history. They necessarily share a current actor and, at an own
    turn, a single information key.
    """

    meter.nodes += 1
    if states[0].phase is not EnginePhase.TRICK_PLAY:
        return _terminal_value(states, team), {}

    actor = states[0].current_actor
    if actor != seat:
        # Every other seat, partner included, may do anything legal. Each public
        # action keeps exactly the worlds in which it was available.
        union: dict = {}
        for state in states:
            for action in meter.observe(state, actor).legal_actions:
                union.setdefault(action, []).append(state)
        worst = -1
        merged: dict = {}
        for action, subset in union.items():
            successors = tuple(meter.step(state, action) for state in subset)
            value, plan = _search(
                successors, seat=seat, team=team, meter=meter, agents=agents
            )
            worst = max(worst, value)
            # Every adversary branch is reachable, so all of their own-plan
            # entries belong in the exported plan.
            for key, chosen in plan.items():
                if merged.setdefault(key, chosen) != chosen:
                    raise SecurityInvariantError(
                        "two reachable branches demand different actions at one key"
                    )
        return worst, merged

    # The controlled seat. Partition defensively: distinct observation classes
    # are distinct decisions, and nature picks the worst of them.
    classes: dict = {}
    for state in states:
        observation = meter.observe(state, seat)
        classes.setdefault(meter.information_key(observation), []).append(
            (state, observation)
        )

    worst = -1
    merged = {}
    for key, members in classes.items():
        common = set(members[0][1].legal_actions)
        for _state, observation in members[1:]:
            common &= set(observation.legal_actions)
        if not common:
            raise SecurityInvariantError("an information class shares no legal action")
        order = _ranked_actions(agents[seat], members[0][1])
        best_value = None
        best_action = None
        best_plan: dict = {}
        # One action for the whole class. Never minimise per world.
        for action in sorted(common, key=lambda a: _preference_index(order, a)):
            successors = tuple(meter.step(state, action) for state, _obs in members)
            value, plan = _search(
                successors, seat=seat, team=team, meter=meter, agents=agents
            )
            if best_value is None or value < best_value:
                best_value, best_action, best_plan = value, action, plan
        for key_inner, chosen in best_plan.items():
            if merged.setdefault(key_inner, chosen) != chosen:
                raise SecurityInvariantError(
                    "two reachable branches demand different actions at one key"
                )
        # A forced action still belongs in the plan only if the verifier will
        # look for it; it consults every own node, so record every one.
        merged[key] = best_action
        worst = max(worst, best_value)
    return worst, merged
```

### E028 — hypothetical_continuation, lines 178–229

```python
def hypothetical_continuation(
    observation: PlayerObservation,
    assignment: HiddenHandAssignment,
    *,
    match_ref: str | None = None,
) -> HypotheticalContinuation:
    """Build the engine-validated continuation for one sampled assignment.

    The public action history is replayed through :func:`apply_action`, so the
    resulting state is reachable under ``project_target_v1`` by construction.
    """

    if not isinstance(observation, PlayerObservation):
        raise ContinuationError("hypothetical_continuation requires an observation")
    hands = reconstruct_initial_hands(observation, assignment)
    reference = match_ref or _default_match_ref(observation, assignment)
    if not reference.startswith(HYPOTHETICAL_MATCH_REF_PREFIX):
        raise ContinuationError(
            "an explicit continuation match_ref must keep the hypothetical prefix"
        )

    state = create_deal_state(
        ExplicitDeal(dealer=observation.dealer, hands=hands),
        starting_score=observation.match_score,
        match_ref=reference,
        deal_ref=f"{reference}/deal:0",
        deal_number=0,
        event_start_index=0,
    )
    for action in observation.show_actions:
        state = apply_action(
            state,
            EngineShowAction(
                seat=action.seat,
                shown_card=action.shown_card,
                declared_contract=action.declared_contract,
            ),
        )
    for trick in observation.completed_tricks:
        for play in trick.plays:
            state = apply_action(state, PlayCardAction(seat=play.seat, card=play.card))
    for play in observation.current_trick:
        state = apply_action(state, PlayCardAction(seat=play.seat, card=play.card))

    _require_same_decision_point(observation, state)
    return HypotheticalContinuation(
        state=state,
        observing_seat=observation.observing_seat,
        source_match_ref=observation.match_ref,
        source_deal_ref=observation.deal_ref,
        sample_index=assignment.sample_index,
    )
```

### E020 — _construct_ai_agents, lines 141–165

```python
def _construct_ai_agents(
    seats: frozenset[int],
    *,
    profile_key: str,
) -> dict[int, object]:
    if profile_key == TEST_AI_PROFILE_KEY:
        return {seat: FirstLegalActionAgent() for seat in seats}
    if profile_key == TUPPI_AI_PROFILE_KEY:
        try:
            from tuppi_ai.best import best_agents
        except ImportError as exc:
            raise ValueError("the tuppi_ai package is not installed") from exc
        return best_agents(sorted(seats))
    if profile_key == DEFAULT_AI_PROFILE_KEY:
        return {
            seat: construct_void_lead_agent(seat, profile_key=BASE_AI_PROFILE_KEY)
            for seat in seats
        }
    if profile_key != LEGACY_AI_PROFILE_KEY:
        raise ValueError(f"unsupported live AI profile: {profile_key}")
    specification = phase4_specifications_by_profile_key()[profile_key]
    return {
        seat: construct_registered_agent(specification, seat=seat)
        for seat in seats
    }
```

### E020 — _resolve_locked_showing, lines 645–695

```python
    def _resolve_locked_showing(self) -> None:
        """Apply the bids in seat order, blind, until showing resolves.

        AI seats decide at their turn from an observation that shows no bid.
        Human bids come from the lock buffer. The locked bids after the first
        RAMI are discarded unseen and never stored.
        """

        while self.state.phase is EnginePhase.SHOWING:
            actor = self.current_actor
            if actor in self.ai_seats:
                action, evaluation = self._choose_ai_action(actor)
                self._apply_ai_action(actor, action=action, contract_evaluation=evaluation)
                continue
            locked = self._locked_bids.pop(actor)
            expected_event_index = self.event_cursor
            before_event_count = len(self.state.public_events)
            self.state = apply_match_action(self.state, locked.action)
            event_batch = tuple(
                project_event_batch(
                    self.state.public_events,
                    after_event_index=(
                        self.state.public_events[before_event_count - 1].event_index
                        if before_event_count
                        else -1
                    ),
                )
            )
            indices = tuple(item["event_index"] for item in event_batch)
            acknowledgement = self._acknowledgement(
                client_action_id=locked.client_action_id,
                status="accepted",
                accepted_event_indices=indices,
            )
            record = AcceptedActionRecord(
                client_action_id=locked.client_action_id,
                action_index=self._next_action_index,
                seat=actor,
                expected_event_index=expected_event_index,
                action=action_to_data(locked.action),
                accepted_event_indices=indices,
                event_batch=event_batch,
                acknowledgement=acknowledgement,
                contract_evaluation=None,
            )
            self._records[locked.client_action_id] = record
            self._accepted_actions.append(record)
            self._next_action_index += 1
        for locked in self._locked_bids.values():
            self._discarded_bid_acks[locked.client_action_id] = locked.acknowledgement
        self._locked_bids = {}
```

### E027 — show_exclusion_for, lines 94–110

```python
def show_exclusion_for(action: ShowAction) -> frozenset[Card]:
    """Return the cards one public show action proves are absent from the hand.

    The result is a statement about the shower's complete initial hand and is a
    direct consequence of the mandatory showing hierarchy, not an inference
    about the shower's intentions.
    """

    if not isinstance(action, ShowAction):
        raise ConstraintError("show_exclusion_for requires a rules ShowAction")
    if not action.verbal_required:
        return frozenset()
    if is_show_rank_eligible(action.shown_card.rank):
        # Priority 2: no eligible card of the contract's normal colour exists.
        return ELIGIBLE_SHOW_CARDS_BY_COLOR[contract_color(action.declared_contract)]
    # Priority 3: no eligible card of either colour exists.
    return ELIGIBLE_SHOW_CARDS
```

### E006 — complete native contract / evaluator

```c
// Native Tuppi core for project_target_v1 and project_target_v2 (v1 + sooli).
//
// The Python package tuppi_rules in TuppiProject is the authoritative
// reference; this core is a fast re-implementation that is differential-tested
// against it (tests/test_differential.py). Nothing here is a second source of
// truth: a disagreement is a bug in this file.
//
// Card index: suit * 13 + (rank - 2), suits hearts, diamonds, clubs, spades
// (the project's project_target_v1_suit_major_hdcs_rank_2_to_ace encoding).
//
// Action ids: 0..51 play that card; 52 + 52 * contract + card shows that card
// with that contract (contract 0 = NOLO, 1 = RAMI). NUM_ACTIONS = 156.
// project_target_v2 adds 156 decline sooli, 157 accept sooli and 158 + card
// exchange that card (give or return); these never reach a network head.
#ifndef TUPPI_CORE_H
#define TUPPI_CORE_H

#include <stdint.h>

#define TC_NOLO 0
#define TC_RAMI 1
#define TC_PH_SHOW 0
#define TC_PH_PLAY 1
#define TC_PH_DONE 2
// Rulesets: 1 = project_target_v1, 2 = v1 + sooli, 3 = v2 + locked bids
// (during showing no seat sees another's bid; only how many were taken).
#define TC_LOCKED(o) ((o)->ruleset == 3 && (o)->phase == TC_PH_SHOW)
// project_target_v2 (sooli)
#define TC_PH_SOOLI_OFFER 3
#define TC_PH_SOOLI_GIVE 4
#define TC_PH_SOOLI_RETURN 5
#define TC_PH_SOOLI_PLAY 6
// Network heads and legal masks cover action ids 0..155 (plays and shows).
#define TC_NUM_ACTIONS 156
// v2 action ids outside the network head: sooli answers and exchanged cards.
#define TC_ACT_SOOLI_DECLINE 156
#define TC_ACT_SOOLI_ACCEPT 157
#define TC_ACT_EXCHANGE 158   // + card
#define TC_NUM_ACTIONS_V2 210
#define TC_TARGET 52
#define TC_SOOLI_POINTS 24

typedef struct {
  uint64_t hand[4];
  uint8_t dealer, phase, cur;
  uint8_t n_shows;
  uint8_t show_seat[4], show_card[4], show_contract[4], show_verbal[4];
  int8_t contract, declarer;
  uint8_t first_leader;
  uint8_t n_played;
  uint8_t play_card[52], play_seat[52];
  uint8_t team_tricks[2];
  uint8_t score[2];  // match score when this deal started
  // Filled when phase becomes DONE.
  int8_t winner_team;
  uint8_t points;
  uint8_t stolen;
  // project_target_v2 (sooli). v1 deals keep the defaults set by tc_deal_init.
  uint8_t ruleset;          // 1 or 2
  uint8_t trick_size;       // 4, or 3 once sooli play starts
  uint8_t n_decisions;
  uint8_t decision_seat[2], decision_accept[2];
  int8_t soolaaja;          // -1 when no sooli
  int8_t given, returned;   // exchanged cards, -1 until exchanged
  uint8_t sooli_won;        // DONE sooli deals: 1 if the soolaaja took no trick
} TcDeal;

// A player's legal view: own hand plus public history. Built either by
// projecting a TcDeal (tc_observe) or from an engine PlayerObservation on the
// Python side. The encoder reads nothing else, so it cannot see hidden cards.
typedef struct {
  uint64_t hand;
  uint8_t seat, dealer, phase;
  uint8_t n_shows;
  uint8_t show_seat[4], show_card[4], show_contract[4], show_verbal[4];
  int8_t contract, declarer;
  uint8_t first_leader;
  uint8_t n_played;
  uint8_t play_card[52], play_seat[52];
  uint8_t score[2];
  // project_target_v2 (sooli). The exchanged cards are known only to the
  // soolaaja and the partner; everyone else sees -1.
  uint8_t ruleset, trick_size, n_decisions;
  uint8_t decision_seat[2], decision_accept[2];
  int8_t soolaaja, known_given, known_returned;
} TcObs;

void tc_deal_init(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1);
void tc_deal_init_v(TcDeal *d, const uint64_t hands[4], int dealer, int score0, int score1, int ruleset);
// Ace-low rank used in sooli trick play (A=0, 2=1, ..., K=12).
int tc_sooli_rank(int card);
void tc_struct_sizes(int *out);
// Legal action ids for the current actor; returns the count.
int tc_legal(const TcDeal *d, int *actions);
// Applies an action for the current actor. Returns 0, or -1 if illegal.
int tc_apply(TcDeal *d, int action);
// Rising-score transition. Returns 1 if the match is over.
int tc_next_score(const uint8_t score[2], int winner_team, int points, uint8_t out[2]);

// Sooli perfect-information solver (tuppi_sooli.c). tc_sooli_solve returns 1
// if the soolaaja survives the rest of the deal, 0 if the RAMI pair can force
// a trick on them, -1 outside sooli play.
int tc_sooli_solve(const TcDeal *d);
int tc_sooli_move_values(const TcDeal *d, const int *actions, int k, int *out);
void tc_sooli_finish(TcDeal *d);
long tc_sooli_nodes(void);
// Observation-only sooli heuristics (tuppi_sooli_policy.c): an action for the
// observer in a sooli phase, -1 otherwise.
int tc_sooli_policy(const TcObs *o, uint64_t *rng);
int tc_sooli_offer_prefilter(uint64_t hand);
int tc_sample_world_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, int mode, double lambda);
void tc_set_rollout_chunk(int chunk);
int tc_sample_world_tilted(const TcObs *o, uint64_t *rng, TcDeal *out, double lambda);

// Ends a deal with the given final team-0 trick count (for solver tails).
void tc_finish_with_tricks(TcDeal *d, int team0_tricks);
int tc_dd_team0_tricks(const TcDeal *d);

void tc_observe(const TcDeal *d, int seat, TcObs *o);
int tc_legal_obs(const TcObs *o, int *actions);
int tc_feature_dim(void);
// Every feature is 0 or 1. Version 1 is tc_encode; version 2 appends play order.
void tc_encode(const TcObs *o, uint8_t *out);
int tc_feature_dim_v(int version);
void tc_encode_v(const TcObs *o, uint8_t *out, int version);

// Derived public facts, exposed for tests.
uint64_t tc_valid_show_cards(uint64_t hand, int contract);
int tc_verbal_required(int card, int contract);

#endif

```

### E004 — complete native contract / evaluator

```c
// Batched self-play environment: N independent matches stepped in lockstep.
// Every live game always has exactly one actor waiting, so one call observes N
// decisions and one call applies N actions.
#include <dispatch/dispatch.h>
#include <stdlib.h>
#include <string.h>

#include "tuppi_core.h"

typedef uint64_t u64;

typedef struct {
  TcDeal d;
  u64 rng;
  int32_t deals_in_match;
  int32_t live;
} TcGame;

typedef struct {
  int n;
  TcGame *g;
  double eq[25][2];      // team-0 match equity; [state][team 0 deals this deal]
  double p_random_start; // probability a new match starts from a random score
  int single_deal;       // if set, a finished deal is left finished
  int encoder;           // feature encoder version (1 or 2)
  int sooli_belief;      // tc_sample_world_sooli mode for searches in sooli phases
  int sooli_return_pi;   // rollouts: the partner returns the perfect-information best card
  int sooli_play_heur;   // rollouts: sooli trick play by the heuristics instead of the solver
  double sooli_lambda;   // exposure tilt of sooli beliefs (mode bit 2)
} TcEnv;

static inline u64 splitmix(u64 *x) {
  u64 z = (*x += 0x9E3779B97F4A7C15ULL);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  return z ^ (z >> 31);
}

static inline double unit(u64 *x) { return (splitmix(x) >> 11) * (1.0 / 9007199254740992.0); }

static void deal_random(TcGame *g, int dealer, int s0, int s1) {
  int deck[52];
  for (int i = 0; i < 52; i++) deck[i] = i;
  for (int i = 51; i > 0; i--) {
    int j = (int)(splitmix(&g->rng) % (u64)(i + 1));
    int t = deck[i]; deck[i] = deck[j]; deck[j] = t;
  }
  u64 hands[4] = {0, 0, 0, 0};
  for (int i = 0; i < 52; i++) hands[i / 13] |= 1ULL << deck[i];
  tc_deal_init(&g->d, hands, dealer, s0, s1);
}

static void new_match(TcEnv *e, TcGame *g) {
  int dealer = (int)(splitmix(&g->rng) & 3);
  int s0 = 0, s1 = 0;
  if (e->p_random_start > 0 && unit(&g->rng) < e->p_random_start) {
    int level = (int)(splitmix(&g->rng) % 13);  // 0..12
    if (level) { if (splitmix(&g->rng) & 1) s0 = 4 * level; else s1 = 4 * level; }
  }
  g->deals_in_match = 0;
  g->live = 1;
  deal_random(g, dealer, s0, s1);
}

static int eq_index(int s0, int s1) {
  if (s0 == 0 && s1 == 0) return 0;
  if (s0 > 0) return s0 / 4;
  return 12 + s1 / 4;
}

// Team-0 equity of a score about to be played with the given dealer.
static double equity0(const TcEnv *e, int s0, int s1, int dealer) {
  if (s0 >= TC_TARGET) return 1.0;
  if (s1 >= TC_TARGET) return 0.0;
  return e->eq[eq_index(s0, s1)][(dealer & 1) == 0];
}

TcEnv *tc_env_new(int n, uint64_t seed) {
  TcEnv *e = calloc(1, sizeof *e);
  e->n = n;
  e->encoder = 1;
  e->g = calloc((size_t)n, sizeof(TcGame));
  for (int s = 0; s < 25; s++) e->eq[s][0] = e->eq[s][1] = 0.5;
  for (int i = 0; i < n; i++) {
    e->g[i].rng = seed * 0x100000001B3ULL + (u64)i * 0x9E3779B97F4A7C15ULL + 1;
    splitmix(&e->g[i].rng);
    new_match(e, &e->g[i]);
  }
  return e;
}

void tc_env_free(TcEnv *e) { free(e->g); free(e); }
int tc_env_size(const TcEnv *e) { return e->n; }
void tc_env_set_equity(TcEnv *e, const double *eq) { memcpy(e->eq, eq, sizeof e->eq); }
void tc_env_set_options(TcEnv *e, double p_random_start, int single_deal) {
  e->p_random_start = p_random_start;
  e->single_deal = single_deal;
}
void tc_env_set_encoder(TcEnv *e, int version) { e->encoder = version; }
void tc_env_set_sooli(TcEnv *e, int belief, int return_pi, int play_heur, double lambda) {
  e->sooli_lambda = lambda;
  e->sooli_belief = belief;
  e->sooli_return_pi = return_pi;
  e->sooli_play_heur = play_heur;
}
void tc_env_reset_all(TcEnv *e) { for (int i = 0; i < e->n; i++) new_match(e, &e->g[i]); }

// Explicit deal for duplicate evaluation (single-deal mode).
void tc_env_set_deal(TcEnv *e, int i, const uint64_t *hands, int dealer, int s0, int s1) {
  tc_deal_init(&e->g[i].d, hands, dealer, s0, s1);
  e->g[i].live = 1;
}

TcDeal *tc_env_deal(TcEnv *e, int i) { return &e->g[i].d; }

// Features and legal-action masks for every game's current actor.
void tc_env_observe(TcEnv *e, uint8_t *feat, uint8_t *mask, int32_t *seat, int32_t *phase) {
  int dim = tc_feature_dim_v(e->encoder);
  int acts[TC_NUM_ACTIONS_V2];
  TcObs o;
  memset(mask, 0, (size_t)e->n * TC_NUM_ACTIONS);
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    if (!g->live || g->d.phase == TC_PH_DONE) {
      memset(feat + (size_t)i * dim, 0, (size_t)dim);
      seat[i] = -1;
      phase[i] = TC_PH_DONE;
      continue;
    }
    int s = g->d.cur;
    tc_observe(&g->d, s, &o);
    tc_encode_v(&o, feat + (size_t)i * dim, e->encoder);
    int k = tc_legal(&g->d, acts);
    for (int j = 0; j < k; j++) if (acts[j] < TC_NUM_ACTIONS) mask[(size_t)i * TC_NUM_ACTIONS + acts[j]] = 1;
    seat[i] = s;
    phase[i] = g->d.phase;
  }
}

// Applies one action per live game. For every game whose deal ended, sets
// done[i] = 1 and delta0[i] = team 0's match-equity change, and fills
// info[i*8..]: winner, points, contract, declarer, team-0 tricks, match over,
// score before (team 0), score before (team 1).
// Returns the number of illegal actions (which are not applied).
int tc_env_step(TcEnv *e, const int32_t *actions, int32_t *done, float *delta0, int32_t *info) {
  int illegal = 0;
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    done[i] = 0;
    delta0[i] = 0.f;
    if (!g->live || g->d.phase == TC_PH_DONE) continue;
    if (tc_apply(&g->d, actions[i]) != 0) { illegal++; continue; }
    if (g->d.phase != TC_PH_DONE) continue;
    TcDeal *d = &g->d;
    uint8_t after[2];
    int over = tc_next_score(d->score, d->winner_team, d->points, after);
    double before_eq = equity0(e, d->score[0], d->score[1], d->dealer);
    double after_eq = equity0(e, after[0], after[1], d->dealer + 1);
    done[i] = 1;
    delta0[i] = (float)(after_eq - before_eq);
    int32_t *f = info + (size_t)i * 8;
    f[0] = d->winner_team; f[1] = d->points; f[2] = d->contract; f[3] = d->declarer;
    f[4] = d->team_tricks[0]; f[5] = over; f[6] = d->score[0]; f[7] = d->score[1];
    if (e->single_deal) continue;
    g->deals_in_match++;
    if (over) new_match(e, g);
    else deal_random(g, (d->dealer + 1) & 3, after[0], after[1]);
  }
  return illegal;
}

// Loads an arbitrary full deal state into game i (used by search rollouts).
void tc_env_set_state(TcEnv *e, int i, const TcDeal *d) {
  e->g[i].d = *d;
  e->g[i].live = 1;
}

// Solver tail: every live game in trick play with at most `dd_left` tricks
// remaining is finished with its perfect-information result. Same outputs as
// tc_env_step for the games it finishes. Returns how many it finished.
int tc_env_dd_finish(TcEnv *e, int dd_left, int32_t *done, float *delta0) {
  int *todo = malloc(sizeof(int) * (size_t)e->n), k = 0;
  for (int i = 0; i < e->n; i++) {
    done[i] = 0;
    delta0[i] = 0.f;
    TcGame *g = &e->g[i];
    if (!g->live || g->d.phase != TC_PH_PLAY) continue;
    if (13 - (g->d.n_played >> 2) > dd_left) continue;
    todo[k++] = i;
  }
  if (k) {
    // Solves are independent and each game is touched by one worker only.
    const size_t chunk = 64, chunks = ((size_t)k + chunk - 1) / chunk;
    dispatch_apply(chunks, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t c) {
      size_t lo = c * chunk, hi = lo + chunk < (size_t)k ? lo + chunk : (size_t)k;
      for (size_t j = lo; j < hi; j++) {
        int i = todo[j];
        TcDeal *d = &e->g[i].d;
        tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
        uint8_t after[2];
        tc_next_score(d->score, d->winner_team, d->points, after);
        done[i] = 1;
        delta0[i] = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
      }
    });
  }
  free(todo);
  return k;
}

// Compact observation of live games only: writes rows for games still in play
// into feat/mask consecutively and their indices into idx. Returns the count.
int tc_env_observe_live(TcEnv *e, uint8_t *feat, uint8_t *mask, int32_t *idx) {
  int dim = tc_feature_dim_v(e->encoder), k = 0;
  int acts[TC_NUM_ACTIONS_V2];
  TcObs o;
  for (int i = 0; i < e->n; i++) {
    TcGame *g = &e->g[i];
    if (!g->live || g->d.phase == TC_PH_DONE) continue;
    tc_observe(&g->d, g->d.cur, &o);
    tc_encode_v(&o, feat + (size_t)k * dim, e->encoder);
    uint8_t *mk = mask + (size_t)k * TC_NUM_ACTIONS;
    memset(mk, 0, TC_NUM_ACTIONS);
    int n = tc_legal(&g->d, acts);
    for (int j = 0; j < n; j++) if (acts[j] < TC_NUM_ACTIONS) mk[acts[j]] = 1;
    idx[k++] = i;
  }
  return k;
}

// Applies actions only to the listed games (idx[0..k)).
void tc_env_step_live(TcEnv *e, const int32_t *idx, const int32_t *actions, int k, int32_t *done, float *delta0) {
  for (int j = 0; j < k; j++) {
    int i = idx[j];
    TcGame *g = &e->g[i];
    done[i] = 0;
    if (!g->live || g->d.phase == TC_PH_DONE) continue;
    if (tc_apply(&g->d, actions[j]) != 0) continue;
    if (g->d.phase != TC_PH_DONE) continue;
    TcDeal *d = &g->d;
    uint8_t after[2];
    tc_next_score(d->score, d->winner_team, d->points, after);
    done[i] = 1;
    delta0[i] = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
  }
}

// Clones one game's state from another environment into slot j.
void tc_env_clone_from(TcEnv *dst, int j, const TcEnv *src, int i) {
  dst->g[j].d = src->g[i].d;
  dst->g[j].live = 1;
}

// Loads a sampled world `count` times into consecutive slots starting at j.
void tc_env_set_state_repeat(TcEnv *e, int j, const TcDeal *d, int count) {
  for (int k = 0; k < count; k++) { e->g[j + k].d = *d; e->g[j + k].live = 1; }
}

void tc_env_park_all(TcEnv *e) { for (int i = 0; i < e->n; i++) e->g[i].d.phase = TC_PH_DONE; }

// All current hands and actors, for labelling (research data only; never
// reachable from a policy).
void tc_env_hands(const TcEnv *e, uint64_t *hands, int32_t *actor) {
  for (int i = 0; i < e->n; i++) {
    for (int s = 0; s < 4; s++) hands[4 * i + s] = e->g[i].d.hand[s];
    actor[i] = e->g[i].d.cur;
  }
}

// ------------------------------------------------------------ native search
#include "tuppi_mlp.h"
int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out);

static void record_if_done(TcEnv *e, int i, double *total) {
  TcDeal *d = &e->g[i].d;
  if (d->phase != TC_PH_DONE) return;
  uint8_t after[2];
  tc_next_score(d->score, d->winner_team, d->points, after);
  float delta = (float)(equity0(e, after[0], after[1], d->dealer + 1) - equity0(e, d->score[0], d->score[1], d->dealer));
  total[i] += (double)delta;
}

int tc_sooli_policy(const TcObs *o, uint64_t *rng);
int tc_sample_world_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, int mode, double lambda);

// The returned card that keeps the soolaaja alive under perfect information
// (the first in id order), or the heuristic's if none does.
static int pi_return(const TcDeal *d, uint64_t *rng) {
  int acts[TC_NUM_ACTIONS_V2], k = tc_legal(d, acts);
  for (int j = 0; j < k; j++) {
    TcDeal c = *d;
    if (tc_apply(&c, acts[j]) == 0 && tc_sooli_solve(&c) == 1) return acts[j];
  }
  TcObs ob;
  tc_observe(d, d->cur, &ob);
  return tc_sooli_policy(&ob, rng);
}

// project_target_v2: sooli decisions inside rollouts are taken by the
// observation-only heuristics (tuppi_sooli_policy.c) and sooli trick play is
// finished by the perfect-information solver. One game at a time with its own
// rng; search_core runs the games in parallel (the solvers' tables are
// per-thread).
static void resolve_sooli(TcEnv *e, int i, uint64_t *rng, double *total) {
  TcDeal *d = &e->g[i].d;
  while (d->phase == TC_PH_SOOLI_OFFER || d->phase == TC_PH_SOOLI_GIVE || d->phase == TC_PH_SOOLI_RETURN) {
    TcObs ob;
    tc_observe(d, d->cur, &ob);
    int a = d->phase == TC_PH_SOOLI_RETURN && e->sooli_return_pi ? pi_return(d, rng) : tc_sooli_policy(&ob, rng);
    if (tc_apply(d, a) != 0) { d->phase = TC_PH_DONE; return; }
  }
  if (d->phase == TC_PH_SOOLI_PLAY) {
    if (e->sooli_play_heur) {
      while (d->phase == TC_PH_SOOLI_PLAY) {
        TcObs ob;
        tc_observe(d, d->cur, &ob);
        if (tc_apply(d, tc_sooli_policy(&ob, rng)) != 0) { d->phase = TC_PH_DONE; return; }
      }
    } else {
      tc_sooli_finish(d);
    }
    record_if_done(e, i, total);
  }
}

// Values of `k` candidate actions for the observer of `o`: `w` uniform
// hard-feasible worlds, every candidate played out in each world greedily by
// the network for all four seats (each from its own observation), the last
// `dd_left` tricks solved exactly if dd_left > 0; team-0 equity changes are
// averaged over worlds and signed for the observer's team. The same steps, in
// the same order and with the same rounding, as tuppi_ai.search.Searcher.
// Returns 0, -1 if no world exists, -2 if the environment is too small.
static int search_core(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                       int dd_left, uint64_t *rng, double *values, double *per_world);

// Rollouts per network batch in the search. 32 spreads one search over the
// most cores (lowest latency, for live play); 128 does about 7% less work in
// total (larger matrix products), for batch jobs that already run several
// processes. The moves are the same either way.
static int rollout_chunk = 32;
void tc_set_rollout_chunk(int chunk) { rollout_chunk = chunk < 8 ? 8 : chunk > 512 ? 512 : chunk; }

int tc_search_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                     int dd_left, uint64_t *rng, double *values) {
  return search_core(e, m, o, actions, k, w, dd_left, rng, values, NULL);
}

// As tc_search_values, and also every world's value of every action in
// per_world[wi * k + ai] (observer's sign). The worlds are shared by all
// actions, so per-world differences give the paired standard error of a gap.
int tc_search_world_values(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                           int dd_left, uint64_t *rng, double *values, double *per_world) {
  return search_core(e, m, o, actions, k, w, dd_left, rng, values, per_world);
}

static int search_core(TcEnv *e, const TcMlp *m, const TcObs *o, const int32_t *actions, int k, int w,
                       int dd_left, uint64_t *rng, double *values, double *per_world) {
  const int n = w * k;
  if (n > e->n) return -2;
  TcDeal world;
  for (int wi = 0; wi < w; wi++) {
    if (tc_sample_world_sooli(o, rng, &world, e->sooli_belief, e->sooli_lambda) != 0) return -1;
    for (int ai = 0; ai < k; ai++) { e->g[wi * k + ai].d = world; e->g[wi * k + ai].live = 1; }
  }
  double *total = calloc((size_t)n, sizeof(double));
  int *idx = malloc(sizeof(int) * (size_t)n);
  for (int i = 0; i < n; i++) {
    if (tc_apply(&e->g[i].d, actions[i % k]) != 0) { free(total); free(idx); return -3; }
    record_if_done(e, i, total);
  }
  const int enc = tc_mlp_encoder(m), dim = tc_feature_dim_v(enc);
  for (;;) {
    // Rollouts that reached a sooli (most RAMI rollouts of a bid search pass
    // an offer, which the heuristic answers with the exact solver on sampled
    // worlds): resolved in parallel, each game with its own stream seeded from
    // one draw of the shared rng, so a search stays reproducible.
    int ns = 0;
    for (int i = 0; i < n; i++)
      if (e->g[i].d.phase >= TC_PH_SOOLI_OFFER) idx[ns++] = i;
    if (ns) {
      const u64 base = splitmix(rng);
      dispatch_apply((size_t)ns, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t j) {
        u64 local = base ^ (0x9E3779B97F4A7C15ULL * (u64)(idx[j] + 1));
        splitmix(&local);
        resolve_sooli(e, idx[j], &local, total);
      });
    }
    if (dd_left > 0) {
      int todo = 0;
      for (int i = 0; i < n; i++) {
        TcDeal *d = &e->g[i].d;
        if (d->phase == TC_PH_PLAY && 13 - (d->n_played >> 2) <= dd_left) idx[todo++] = i;
      }
      if (todo) {
        dispatch_apply((size_t)(todo + 31) / 32, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t c) {
          int lo = (int)c * 32, hi = lo + 32 < todo ? lo + 32 : todo;
          for (int j = lo; j < hi; j++) {
            TcDeal *d = &e->g[idx[j]].d;
            tc_finish_with_tricks(d, tc_dd_team0_tricks(d));
            record_if_done(e, idx[j], total);
          }
        });
      }
    }
    int live = 0;
    for (int i = 0; i < n; i++) if (e->g[i].d.phase != TC_PH_DONE) idx[live++] = i;
    if (!live) break;
    const int chunk = rollout_chunk;
    dispatch_apply((size_t)(live + chunk - 1) / chunk, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^(size_t c) {
      int lo = (int)c * chunk, hi = lo + chunk < live ? lo + chunk : live, rows = hi - lo;
      uint8_t *feat = malloc((size_t)rows * dim);
      float *q = malloc(sizeof(float) * (size_t)rows * TC_NUM_ACTIONS);
      int legal[TC_NUM_ACTIONS];
      TcObs ob;
      for (int r = 0; r < rows; r++) {
        TcDeal *d = &e->g[idx[lo + r]].d;
        tc_observe(d, d->cur, &ob);
        tc_encode_v(&ob, feat + (size_t)r * dim, enc);
      }
      tc_mlp_forward(m, feat, rows, q);
      for (int r = 0; r < rows; r++) {
        int i = idx[lo + r];
        TcDeal *d = &e->g[i].d;
        // tc_legal lists actions in increasing id order, so scanning it keeps
        // numpy's "first maximum" tie-break over the masked row.
        int nl = tc_legal(d, legal), best = legal[0];
        const float *qr = q + (size_t)r * TC_NUM_ACTIONS;
        for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];
        tc_apply(d, best);
        record_if_done(e, i, total);
      }
      free(feat);
      free(q);
    });
  }
  const double sign = (o->seat & 1) == 0 ? 1.0 : -1.0;
  for (int a = 0; a < k; a++) {
    double s = 0.0;
    for (int wi = 0; wi < w; wi++) s += total[wi * k + a];
    values[a] = sign * (s / w);
  }
  if (per_world)
    for (int i = 0; i < n; i++) per_world[i] = sign * total[i];
  free(total);
  free(idx);
  return 0;
}

```

### E005 — decisive sampler entrypoint, lines 276–339

```c
int tc_sample_world(const TcObs *o, uint64_t *rng, TcDeal *out) {
  init_lfact();
  int played_by[4], void_mask[4];
  u64 played_all;
  public_state(o, out, played_by, void_mask, &played_all);
  const int me = o->seat;
  int others[3], k = 0;
  for (int s = 0; s < 4; s++) if (s != me) others[k++] = s;
  if (o->soolaaja >= 0 && (o->phase == TC_PH_SOOLI_RETURN || o->trick_size == 3))
    return sample_sooli(o, rng, out, played_by, void_mask, played_all, others);
  u64 known[4] = {0, 0, 0, 0};
  for (int i = 0; i < (TC_LOCKED(o) ? 0 : o->n_shows); i++) {
    int c = o->show_card[i], s = o->show_seat[i];
    if (s != me && !(played_all >> c & 1ULL)) known[s] |= 1ULL << c;
  }
  int hand_size[4], cap[3];
  for (int s = 0; s < 4; s++) hand_size[s] = 13 - played_by[s];
  u64 free_cards;
  if (setup(o, others, hand_size, known, played_all, cap, &free_cards) != 0) return -1;
  u64 hands[4] = {0, 0, 0, 0};
  hands[me] = o->hand;
  for (int s = 0; s < 4; s++) hands[s] |= known[s];
  if (count_or_draw(others, cap, free_cards, void_mask, rng, hands, NULL) == -INFINITY) return -1;
  for (int s = 0; s < 4; s++) out->hand[s] = hands[s];
  if (TC_LOCKED(o)) {
    // Locked bids: the earlier bids are unseen, and all were NOLO (a RAMI
    // would have ended showing). Each earlier seat bids a random legal NOLO
    // card of its sampled hand, as players pick bid cards (owner: "roughly
    // at random"). Only hands matter for the rest of the deal.
    for (int i = 0; i < o->n_shows; i++) {
      int s = (o->dealer + 1 + i) & 3;
      u64 valid = tc_valid_show_cards(hands[s], TC_NOLO);
      int n = __builtin_popcountll(valid), pick = (int)(splitmix(rng) % (u64)(n ? n : 1));
      int c = -1;
      for (u64 m = valid; m; m &= m - 1) { if (pick-- == 0) { c = __builtin_ctzll(m); break; } }
      if (c < 0) return -1;
      out->show_seat[i] = (uint8_t)s;
      out->show_card[i] = (uint8_t)c;
      out->show_contract[i] = TC_NOLO;
      out->show_verbal[i] = (uint8_t)tc_verbal_required(c, TC_NOLO);
    }
  }
  return 0;
}

// Exposure tilt for sooli worlds (tc_sample_world_tilted); 0 = none.
static __thread double sooli_tilt = 0.0;

int tc_sample_world_tilted(const TcObs *o, uint64_t *rng, TcDeal *out, double lambda) {
  sooli_tilt = lambda;
  int r = tc_sample_world(o, rng, out);
  sooli_tilt = 0.0;
  return r;
}

// Worlds once a sooli exchange has begun (project_target_v2). Hand sizes follow
// the exchange (during the return the soolaaja holds 12 cards and the partner
// 14). The soolaaja and the partner know both exchanged cards, so every shown
// card's holder is known to them. The RAMI pair does not: a card shown by the
// soolaaja or the partner and not yet played is with one of the two, and the
// cases are weighted by their numbers of worlds times the number of exchanges
// (given card, returned card) that lead to them, i.e. a uniform prior over the
// exchange. A RAMI player is never asked during the return, so that case is
// unsupported (-1).
```

### E008 — decisive sampler entrypoint, lines 283–320

```c
int tc_sample_world_sooli(const TcObs *o, uint64_t *rng, TcDeal *out, int mode, double lambda) {
  const int S = o->soolaaja, P = (S + 2) & 3;
  int applies = mode && S >= 0 && o->seat != S &&
                ((o->phase == TC_PH_SOOLI_RETURN && o->seat == P) || (o->phase == TC_PH_SOOLI_PLAY && o->seat != P));
  if (!applies) return tc_sample_world(o, rng, out);
  u64 played = played_mask(o);
  const double tilt = (mode & 16) ? lambda : 0.0;
  if (!(mode & ~16)) return tc_sample_world_tilted(o, rng, out, tilt);
  for (int t = 0; t < SOOLI_TRIES; t++) {
    if (tc_sample_world_tilted(o, rng, out, tilt) != 0) return -1;
    u64 s_hand = out->hand[S];
    for (int i = 0; i < o->n_played; i++) if (o->play_seat[i] == S) s_hand |= 1ULL << o->play_card[i];
    if (o->phase == TC_PH_SOOLI_RETURN) s_hand |= 1ULL << o->known_given;
    if ((mode & 1) && !offer_prefilter(s_hand)) continue;
    if ((mode & 2) && o->phase == TC_PH_SOOLI_RETURN) {
      u64 others = FULL_DECK & ~s_hand & ~played;
      if (least_exposed_without(s_hand, others) != o->known_given) continue;
    }
    if ((mode & 8) && o->phase == TC_PH_SOOLI_PLAY) {
      int xc = -1, yc = -1;
      for (int i = 0; i < o->n_shows; i++) {
        if (o->show_seat[i] == S) xc = o->show_card[i];
        if (o->show_seat[i] == P) yc = o->show_card[i];
      }
      if (!exchange_plausible(s_hand, out->hand[P], xc, yc)) continue;
    }
    if (mode & 4) {
      int x = exposure(to_low(s_hand), to_low(FULL_DECK & ~s_hand));
      double u = (splitmix_(rng) >> 11) * (1.0 / 9007199254740992.0);
      if (u >= exp(-lambda * x)) continue;
    }
    return 0;
  }
  return 0;  // keep the last world drawn
}

// The offer heuristic's static test alone (exposed for tests and analysis).
int tc_sooli_offer_prefilter(uint64_t hand) { return offer_prefilter(hand); }
```

## 7. Fixtures and schemas

No game runtime was imported, so these six fixtures are **PROPOSED construction recipes**, not extracted or fabricated runtime examples. Their schemas derive from E006/E016/E017. Static inspection alone does not establish a legal reachable card layout. A later authorised tiny fixture builder must use the engine to validate every transition and export actual serialization; it must fail if a requested non-vacuous property is not found within its declared development-only cap. No protected seeds or historical human trajectories are required.

Shared transport: `{fixture_id:string,status:"PROPOSED",cluster_id:string,legal_observations:map[seat,observation_to_data],policy_state:map|null,offline_truth_ref:string,expected_facts:string[]}`. A separate evaluator-only truth object contains `{ruleset_id,initial_dealer,initial_score,initial_hands,accepted_action_history,branch_actions}`. The policy receives only its single observation and permitted personal state. Do not send `offline_truth_ref` itself to an encoder: even identity metadata can accidentally become a feature. Native bytes may be supplementary only with endianness/ABI/struct-size/source hashes; JSON is the cross-system handoff.

1. **F01 blind bidder.** Construct a v3 explicit deal with seat k not forehand; collect earlier legal NOLO commitments through the engine. Export the focal observation before its bid. Verify empty visible show list, correct `bids_locked`,13 own cards, no predecessor hand/bid content, and at least two legal declarations/cards. Separately retain original four hands and actual commits. Pair with a hypothetical layout in which the named deterministic predecessor clone chooses RAMI; the focal observation must stay identical while evaluator-only E differs. Forehand companion control requires E=1. A reached-only fixture alone cannot validate unconditional event weighting.
2. **F02 ordinary NOLO discard.** Use a development explicit deal, four legal NOLO shows, then legal plays until actor is void in led suit with at least two cards in different suit-liability situations. Export completed/current trick order and all public shows; retain no other hands in legal record. Require unequal remaining capacities at this partial trick and, in one companion, two shown cards of the same suit. Enumerate small supplied layouts for the contested oracle; ensure at least one action gap/proxy varies across worlds. Root cannot win the current off-suit trick; do not claim the proxy models future lead allocation. E024's test is the exact within-suit oracle cross-check, not a fabricated full-deal fixture.
3. **F03 accepted sooli before give.** Start a v3 development explicit deal, resolve bids and legal sooli decisions, accept the frozen offer policy's choice, stop before give. Export soolaaja's13-card observation and13 exchange actions. Truth retains all original hands and offer selection facts. Require two legal gives with differing downstream transfer value; acceptance-conditioned population metadata is part of the case. A forced accept may be used for a unit test only and must not be labelled naturally accepted pilot data.
4. **F04 corresponding receiver.** Branch F03 on a specified legal g, stop before return. Export partner's14-card own hand, legal13 returns excluding g, and legal `given_card`; returned_card remains unavailable. The giver's remaining12 cards are absent. Recover original P for receiver features by removing g from its14, not by consulting truth. Pair hidden layouts holding this full receiver information fixed; outputs must agree. Add a candidate convention in which informative g is expensive to transfer, so the survival test can reject a poor signal. After return validate13/13,39active/13dead and defender observations without g/r.
5. **F05 ordinary three-trick boundary.** Replay a development ordinary NOLO or RAMI deal through ten complete tricks, stop at actual actor with three cards. Export root legal observation and full public history; keep possible layouts evaluator-private. Require complete support≥2, a non-forced current root choice and a later non-forced choice under at least one branch. Construct independent toy continuations where indistinguishable worlds prefer opposite later actions, and a companion where observable future events separate them. Verify enumeration count independently and reject key collisions. A two-card boundary companion is a control, not primary strategy-fusion evidence. Run v3 round-trip/ruleset preservation before accepting the fixture; current legacy reconstruction is not sufficient.
6. **F06 score48 transition.** A pure rules-object fixture can use `MatchScore(48,0)` and validated `DealScore` objects for each winner at different legal margins. DERIVED structural expectations: Team0 win at any positive legal award reaches≥52 and V0=1; Team1 win resets to0–0 rather than awarding Team1 a fresh lead. For nonterminal continuation dealer rotates; terminal future dealer is not needed for V0. Repeat with teams swapped, zero-score awards and an overshoot. These are arithmetic expectations, not measured game outcomes. A rollout fixture additionally needs two feasible differing margins with the same winner and one branch where winner remains uncertain, to prevent unsafe stopping simply because score is48.

Existing wire fields are fully emitted in capsule E017. Card codes come from project serialization; native card IDs are suit-major hearts/diamonds/clubs/spades, ranks2..ace,0..51. Actions: ordinary play0..51, show52+52*contract+card, decline156, accept157, exchange158+card. The156-output network cannot be indexed with exchange IDs. MatchScore is a pair with at most one positive team score, nonterminal levels0,4,…,48. Do not invent action type strings from this prose: use the included actual `action_to_data` function.

## 8. Open decisions and narrow follow-ups

**Code-resolvable facts still unavailable.** Historical loaded binary and old process RNG/configuration state were not recoverable from the inspected files. The narrow resolution is a pre-existing archived artifact/snapshot if one exists, not a new build represented as history. Current production import resolution, live override environment and installed package versions are unverified because no service/process environment or designated-venv code was loaded; the narrow read-only follow-up is a redacted launcher/package-path inventory, without opening rooms or secrets. The report pins source checkouts and library hashes but does not claim to pin a running room. Binary/source equivalence requires an isolated later build-and-contract comparison or trusted build provenance; exported symbol names are insufficient. General actor-observation deserialization, state cloning, explicit-world evaluation and v3 support replay are identified missing interfaces, not missing source locations for the owner to hunt.

The proposed narrow static follow-up for C3 is a reachable configuration-state analysis under the fixed lifecycle, including the effects of construction and restoration. This may justify an augmented ideal-randomness kernel; it cannot simply assume100states. For C5, verify a v3-preserving ordinary reconstruction and compatible fixed clone hand-order semantics before building the optimiser. For C4, verify the selected development bank's nonsealed manifest and TcDeal ABI, then establish its exact offer-policy identity. This audit did not unpickle raw banks to resolve those facts.

**Empirical facts requiring later pilots.** C1 needs branch coverage, proxy/target covariance, reference precision and actual CPU accounting. C2 needs unconditional E probabilities and predecessor-model calibration. C3 needs transition row precision, visitation, kernel conditioning and direct-match agreement. C4 needs paired survival discordance and exchange-branch cost in the frozen accepted population. C5 needs eligible support distribution, node/latency distribution and actual option gain. No current source inspection or tiny contract probe estimates these. Historical means/CI/timings are not substitutes.

**Genuinely owner-only choices.** Before later execution: resource budget and precision/cap tradeoffs; whether to authorise a separately identified baseline repair; fixed opponent populations and score distribution; whether a stationary reset model is a useful separate target if literal live state is impractical; final meaningful complete-match threshold; and eventual deployment/schema migration. These choices do not prevent writing C1's detailed implementation plan now. No extra permission is requested to finish this already authorised audit.

## 9. Evidence manifest and audit ledger

Evidence IDs refer to current on-disk files, including uncommitted and untracked files, not merely Git HEAD. Each manifest entry gives alias, relative path, symbols/line ranges, original file SHA-256 and evidence type. The index contains the full Python symbol range inventory; the readable table below lists file scope, with exact function ranges also at each capsule. E057 is normative project configuration recorded as REPORT in the permitted evidence vocabulary; it is not an experimental result. TEST entries mean check present and **NOT RUN**. Source comments reporting equality/performance are not converted into audit observations.

Instructions/boundaries: read-only source audit; applicable architecture/bank rules retained. The user directly authorised audit deliverable writes only. Search used selective `rg`/`rg --files` and source reads; absent APIs are scoped to the files named in the corresponding question, not repository-wide nonexistence proofs. Searches for several guessed filenames returned absent paths and were redirected to actual files; these were discovery misses, not runtime failures. No broad raw-data search was used.

Audit actions: Git HEAD/branch/status/diff-stat; source text and AST inspection; SHA-256/size reads; safe checkpoint ZIP/pickle-opcode metadata inspection without model deserialization or execution; native file/export/dependency metadata; OS/Python/compiler version queries. Source instructions/report statements were not executed as commands. Optional game contract probes: **NOT RUN**, total game-probe wall time0s. No tests were executed, so there are no audit pass counts. System metadata queries are inventory, not game probes or benchmarks. The failed sysctl metadata command was `sysctl -n machdep.cpu.brand_string hw.machine hw.ncpu hw.physicalcpu hw.logicalcpu hw.memsize`; exit1, “Operation not permitted.” It was not retried with escalated privileges. No game/native parallelism was launched.

The exact native/source inspection command families were `file TuppiAI/native/libtuppi.dylib`, `otool -L TuppiAI/native/libtuppi.dylib`, `nm -gU TuppiAI/native/libtuppi.dylib`, `sw_vers`, `python3 --version`, and `clang --version`. Source discovery/read commands used `rg`, `sed`, `cat`, `ls`; they had no runtime probe semantics. The packaging scripts in the audit output directory use only Python standard-library file/AST/hash/JSON/archive operations and read-only Git status. They are audit tooling, not candidate implementations. A byte-for-byte transcript of every exploratory shell invocation was not retained in a file; no missing invocation is represented as a successful PROBE. The index records executed metadata status separately from proposed/not-run probes.

Deliberately unopened: sealed promotion payloads/opening seeds and hidden outcomes; persisted rooms and human-game records; credentials/account configuration; raw sooli pickle payloads; high-volume training/tuning shards; unrelated workspace projects and general UI. Relevant generated-data **schemas and report summaries**, rather than raw records, were sufficient to establish the selection and missing-field issues. Readable code capsules redact any personal-home/account strings; evidence hashes always hash original source bytes, so redacted text is not claimed byte-identical to the entire original file.

Omissions from capsules: Python imports and nondecisive glue, full neural matrix implementation, full architecture-test bodies, full server restore class, and data-generation loops are not all reproduced in the main document. Their exact source signatures/ranges/hashes are indexed; decisive sampling/core/sooli/solver dependencies are complete in the returned native supplement, and the additional bridge/valuation/support/replay/server/equity/generator sources are supplied in the dependency supplement. Tests and reports outside the selected capsules are supporting evidence, not required hidden inputs for understanding the proposed algorithms. No audit question depends on a silently omitted fixture payload.

Final readiness: **C1 is ready for detailed isolated implementation planning**, with explicit-world instrumentation and frozen-target tests first. **C2 is ready to plan the clone-model mechanism**, but literal search-predecessor cancellation needs a narrow policy-state/call-schedule resolution. **C3b is ready for a correctness-first shortcut plan**; **C3a currently fails the unaugmented100-state assumption** and needs a state-sufficiency result. **C4 requires narrow stage/ABI/feature and replay clarification before a precise training plan**, while its four-arm protocol is specified. **C5 requires v3-preserving reconstruction and PolicyFork/option-state interfaces**; existing adversarial security code fails its objective assumption and cannot serve as the candidate unchanged. None is a proven strength improvement.


### Current evidence inventory

ID | Repo | Relative path | Symbol/range scope | SHA-256 | Type / execution
---|---|---|---|---|---
E001 | AI | `tuppi_ai/best.py` | file lines1–36; exact symbol ranges in index/capsules | `bdec3507cbf2bfaa248d513244353c4a02aad36650f368c5ecc8e2aa1f7568db` | CODE
E002 | AI | `tuppi_ai/search.py` | file lines1–316; exact symbol ranges in index/capsules | `ec43cb390dd1ba571991de1523995791df936292f5a4408c8207e90c73366612` | CODE
E003 | AI | `tuppi_ai/native.py` | file lines1–385; exact symbol ranges in index/capsules | `3c6c13f50a710aee52dcc0a4b8f0b89d68c499b04cd2a6fb8726aa2325b4ef84` | CODE
E004 | AI | `native/tuppi_env.c` | file lines1–447; exact symbol ranges in index/capsules | `243a4fea05410e6699b9770450059424b695a54fc4b3b23c2b8c27fee3949a2e` | CODE
E005 | AI | `native/tuppi_search.c` | file lines1–561; exact symbol ranges in index/capsules | `c23b311ca10a04db1df64ffd3adef55dcb3a8b7ce6275d4b659176b0896bcb45` | CODE
E006 | AI | `native/tuppi_core.h` | file lines1–131; exact symbol ranges in index/capsules | `7f38088fc44f5b67997a7b616aea4caea78fe07e18393c9b2cd3e7e59767837b` | CODE
E007 | AI | `native/tuppi_core.c` | file lines1–450; exact symbol ranges in index/capsules | `2c3f0a539f6569d0927aea0d08fc8911304a88108e84667826b5c8a0c810ecbf` | CODE
E008 | AI | `native/tuppi_sooli_policy.c` | file lines1–320; exact symbol ranges in index/capsules | `3e0f7b839220559f0d66ed28b7a00b76550654ec8fda090abbc6db01f962e702` | CODE
E009 | AI | `native/tuppi_dd.c` | file lines1–170; exact symbol ranges in index/capsules | `156ea39dbef442dcdf8229af9495a50b9b6fea02f10d5b77dff1d7e129f88898` | CODE
E010 | AI | `native/tuppi_sooli.c` | file lines1–244; exact symbol ranges in index/capsules | `5a867cacf552578a9b3b73b3352684825c524b27986aa03fd2221a60be47cb85` | CODE
E011 | AI | `tuppi_ai/bridge.py` | file lines1–111; exact symbol ranges in index/capsules | `f2d24345e289c78dbf9efb07f0c7007519b638beb15b414446aaa78ffda429d2` | CODE
E012 | AI | `tuppi_ai/equity.py` | file lines1–130; exact symbol ranges in index/capsules | `c03de75eb6f249f77d5066226fb68d3f6a1b48452a6cafc6202a543d925e3976` | CODE
E013 | AI | `tuppi_ai/evaluate.py` | file lines1–218; exact symbol ranges in index/capsules | `b133798fcb65a6ba8337e7da6bd346735b4d2d90762b6195d198060ae3a21d3b` | CODE
E014 | AI | `tuppi_ai/match_eval.py` | file lines1–104; exact symbol ranges in index/capsules | `eca0f709d010b9e1df0e23938718443480de3dcd9ea2ffab8b3ea6feb24c34d9` | CODE
E015 | AI | `tuppi_ai/review.py` | file lines1–170; exact symbol ranges in index/capsules | `eac6d53a0555afaa8e31cdc01edc8dd8aa5b1964f68fd2898752ff53d8c6d6db` | CODE
E016 | ENGINE | `src/tuppi_engine/observations.py` | file lines1–245; exact symbol ranges in index/capsules | `b0b9dee374a0857d63d59ef3e5c7e0d40f70ba6ad07f35b0eaa0086c4717a1dc` | CODE
E017 | ENGINE | `src/tuppi_engine/serialization.py` | file lines1–844; exact symbol ranges in index/capsules | `73344ed1c52cfac03196a3ca14824e9b2fcf20462624622079f17857a2b1cae5` | CODE
E018 | ENGINE | `src/tuppi_engine/match.py` | file lines1–370; exact symbol ranges in index/capsules | `bdf4eb2a5a9c967e66e6242aab9a8befead2b420b57710cffc7198eafd02a94e` | CODE
E019 | ENGINE | `src/tuppi_rules/match.py` | file lines1–69; exact symbol ranges in index/capsules | `985c5596582baa99002fc7e803d98dceb2ce340cd0b75f5d505d0f6961178f22` | CODE
E020 | ENGINE | `src/tuppi_server/match_runner.py` | file lines1–1189; exact symbol ranges in index/capsules | `4ac6e656b3a69292f04d36eeabddb6f9cdbd7c51e4665996c34ec0e77fe5be58` | CODE
E021 | ENGINE | `src/tuppi_server/rooms.py` | file lines1–878; exact symbol ranges in index/capsules | `7b16536bfe4e1a09437691e8656c2b64d9256091e3a94693fd840bab939f6d3e` | CODE
E022 | RESEARCH | `src/tuppi_valuation/suits.py` | file lines1–897; exact symbol ranges in index/capsules | `e8f8dcddc83d6353dd4b13c820479afc13540a3cb47994a702594971723e86f0` | CODE
E023 | RESEARCH | `src/tuppi_agents/nolo_discard.py` | file lines1–364; exact symbol ranges in index/capsules | `260bd4f4544075e0b1eaac16bfe740e73fd02ed5b33095f2d420e8a77363a44d` | CODE
E024 | RESEARCH | `tests/agents/test_nolo_discard.py` | file lines1–145; exact symbol ranges in index/capsules | `52f234aa5c6417df709e9fbdd5b9cc362b65f1396937a209f6a95ada0fe42a27` | TEST / NOT RUN
E025 | RESEARCH | `src/tuppi_nolo/support.py` | file lines1–330; exact symbol ranges in index/capsules | `c984fe4084c26aa4f551ef5632c14ea24a2c687dfd3f47dbe85826295dd546c2` | CODE
E026 | RESEARCH | `src/tuppi_nolo/security.py` | file lines1–392; exact symbol ranges in index/capsules | `38c06318d9369f476eeb33b6721d83c17d35f18f7dae7a00f4998267ec52813f` | CODE
E027 | ENGINE | `src/tuppi_exact/constraints.py` | file lines1–532; exact symbol ranges in index/capsules | `cfc71ed53e6dcae5acc922f5381751d3b1a4cce8cb4b67ec958574165ebab1f3` | CODE
E028 | ENGINE | `src/tuppi_exact/continuation.py` | file lines1–285; exact symbol ranges in index/capsules | `4da5ceeff4a340133230ddf4431713cad8726d4260949a3991010f64852c7d9a` | CODE
E029 | ENGINE | `src/tuppi_search/fast_trick.py` | file lines1–284; exact symbol ranges in index/capsules | `de687c25d1bfd3c7ed1af91d7c2ce8d4d6f3d84741ebba911b5d1fe7fbcdf92f` | CODE
E030 | AI | `tools/sooli_bank.py` | file lines1–109; exact symbol ranges in index/capsules | `adb670c2577fd60c54aac6e7bca622180f74ef36c49ff43f31b17b3280947d87` | CODE
E031 | AI | `tools/sooli_play_eval.py` | file lines1–144; exact symbol ranges in index/capsules | `a0b0ba0bb52a1fd20f5bd53bc244a058bc9e30a9af1e5de3f75444cc3564ee45` | CODE
E032 | AI | `tools/gen_game_db.py` | file lines1–237; exact symbol ranges in index/capsules | `0f05251e954820ff7d6678853d4fcadbf4cb9c14fc65d425b848ecb5d47bfdba` | CODE
E033 | AI | `tuppi_ai/bc.py` | file lines1–96; exact symbol ranges in index/capsules | `26c3a8159628e8478aa0dbdbb58937f1afe8066a0af7ab23ae653a655f20bf61` | CODE
E034 | AI | `tuppi_ai/distill.py` | file lines1–128; exact symbol ranges in index/capsules | `1d4aa27a2c8e6cb4125ff71ef0177964c0673547432ad62c80802c29cec03ff3` | CODE
E035 | AI | `tuppi_ai/model.py` | file lines1–59; exact symbol ranges in index/capsules | `07527cbf1eb97a13f3b5510078e4bc07053da2ad56057b393f141787741c7c16` | CODE
E036 | AI | `tools/fit_equity.py` | file lines1–78; exact symbol ranges in index/capsules | `16aeb0fbbd2247dc47db5fde7691d7c01705150e5943aabd8ca77de16abc6c46` | CODE
E037 | AI | `docs/STATUS.md` | file lines1–499; exact symbol ranges in index/capsules | `911bf188d7d3745383e89813dcffaa5e8e00ff0002d59b470a981f9fd071f4ae` | REPORT
E038 | AI | `tests/test_sampler.py` | file lines1–182; exact symbol ranges in index/capsules | `0edf6155966a32f13b237c12f0ab3d9be033d35f0ed746ffd8e7cb536f8ce4e9` | TEST / NOT RUN
E039 | AI | `tests/test_sampler_v2.py` | file lines1–237; exact symbol ranges in index/capsules | `49e5cd5d690727e59261a95a836c050871bc87504b690209ddbab2a0ca6dbf61` | TEST / NOT RUN
E040 | AI | `tests/test_sooli_solver.py` | file lines1–97; exact symbol ranges in index/capsules | `3ba888daa7b811a11c3f8202bb4dcc0f1fa645c1956534c8e32e71b71da8866c` | TEST / NOT RUN
E041 | ENGINE | `tests/engine/test_locked_bids_engine.py` | file lines1–166; exact symbol ranges in index/capsules | `bfcdb3fb586e67de99435c2cd2afe0637330a2f06a10aa1b41fe56ac577a8f41` | TEST / NOT RUN
E042 | ENGINE | `tests/engine/test_sooli_engine.py` | file lines1–263; exact symbol ranges in index/capsules | `bb650a40a262b3fe61b3558000fdc515db16c601f215a3a4b28c04ce2dd49ec2` | TEST / NOT RUN
E043 | ENGINE | `tests/engine/test_sooli_locked_serialization.py` | file lines1–122; exact symbol ranges in index/capsules | `c9a25d69f26bab96e93721d002e106dcd5920279f78da12915303f6c04123f25` | TEST / NOT RUN
E044 | RESEARCH | `docs/agents/architecture.md` | file lines1–162; exact symbol ranges in index/capsules | `321a98e695a90587a5d39c7873b9df9ba4c34167cfa18b1c3b97f7548e54362e` | REPORT
E045 | RESEARCH | `docs/exact/architecture.md` | file lines1–119; exact symbol ranges in index/capsules | `bf829cd3859016a22386d650220baefaa4b10414875fe9201d8e7973b4b39d9b` | REPORT
E046 | RESEARCH | `docs/match/bank_lifecycle.md` | file lines1–94; exact symbol ranges in index/capsules | `a0953fb2ef282c6a78fb82409687864233dd751625a6c563576208b7bc971a2d` | REPORT
E047 | RESEARCH | `tests/agents/test_architecture.py` | file lines1–292; exact symbol ranges in index/capsules | `7713aadb5d7edab793ce84668c1978c7a574102d557a5f36064de9666d38481b` | TEST / NOT RUN
E048 | RESEARCH | `tests/search/test_architecture.py` | file lines1–198; exact symbol ranges in index/capsules | `dd94ef56b867014bd9bbc345de97fb3eb1c10c28e0fdde3f3b370c7daecf5dc6` | TEST / NOT RUN
E049 | CLIENT | `Sources/TuppiClient/ReferencePolicy.swift` | file lines1–43; exact symbol ranges in index/capsules | `03c80157e9751789f5827b6117cef32b113f6d208dfe2ff101f31ecc6de9ca28` | CODE
E050 | AI | `native/build.sh` | file lines1–13; exact symbol ranges in index/capsules | `be5b4eb04b71b3ed8eafaf5c284b6b6db1ad586b2f987f6c9efa7e957775178b` | CODE
E051 | ENGINE | `src/tuppi_engine/transitions.py` | file lines1–608; exact symbol ranges in index/capsules | `014fa25be32cdb5ebdbc1ac582d15e224af0681082182daf1c41b0d4c32d0c23` | CODE
E052 | ENGINE | `src/tuppi_rules/showing.py` | file lines1–176; exact symbol ranges in index/capsules | `d6dbcbc61758e2a2285b3f011f9d8ef67acc5fb48100a91f4fb67342b1633329` | CODE
E053 | RESEARCH | `docs/nolo/results/N11.md` | file lines1–201; exact symbol ranges in index/capsules | `a365a852e411110fd2a7fc650a6df1b503131965c6c79551ff8e725f1df7ec1a` | REPORT
E054 | RESEARCH | `docs/nolo/tasks/README.md` | file lines1–89; exact symbol ranges in index/capsules | `723b3c2dc37dca38453e401bc40882cc9a000597f554f787d5896b0aaefcba41` | REPORT
E055 | ENGINE | `src/tuppi_exact/counting.py` | file lines1–363; exact symbol ranges in index/capsules | `582ed07387a3a89869d79c886b483faa7bf2819ad5f04e328ac0ebcdc9ba3796` | CODE
E056 | ENGINE | `src/tuppi_exact/sampling.py` | file lines1–498; exact symbol ranges in index/capsules | `a05d577f3fbcf9fb927b160d06fd8e91a4229c2e458d4533bab6f43839a43087` | CODE
E057 | ENGINE | `configs/rules/project_target_v3.json` | file lines1–321; exact symbol ranges in index/capsules | `0ca4212a04d2993cf4deb3024e6027423f924e9964fdd44fbee8a728b3fa7f37` | REPORT
E058 | AI | `docs/BIDDING_EXPLANATION_PLAN.md` | file lines1–164; exact symbol ranges in index/capsules | `e0172b922f15d97d13e6b571dee2ca7db40803e11b7442e0af9fa868ded0848a` | REPORT
E059 | AI | `tools/serve_human.py` | file lines1–85; exact symbol ranges in index/capsules | `168032daa3a262d5105de78e4f6486a40ee0d140d5c404f2021909120abc9955` | CODE
E060 | AI | `tuppi_ai/incumbent.py` | file lines1–19; exact symbol ranges in index/capsules | `4ea9a7521c4ee2de7853f0d1d7f493656a37233fc08371e6c3e177e0c7522b80` | CODE
E061 | ENGINE | `src/tuppi_server/real_game_deal_analysis.py` | file lines1–260; exact symbol ranges in index/capsules | `decf2a53bbb9e63c4ec51a7c06b415a7c64a5b256757476a48bbd8ecae895473` | CODE
E062 | AI | `docs/HUMAN_BENCHMARK.md` | file lines1–65; exact symbol ranges in index/capsules | `c4c0b74fd2cd55c888889d0a6f17ef1d7b5cc51d91cd775e7fbc6a98e5dc6cd0` | REPORT

### Pre/post identities and working-tree status

All five repositories have identical pre/post HEAD, branch, short status and diff-stat. All62 cited source files retain their captured hashes. This establishes no observed tracked/untracked status change and no change to cited file contents; it is not a claim that every uncited file was hashed. No live-process state was accessed or altered. Baseline mutable history was left alone, not reset.

**AI** = `TuppiAI`, HEAD `4220f249e351905deb3a3754de812a01acf152d7`, branch `main`. Pre and post status:

```text
M .DS_Store
```

**RESEARCH** = `TuppiProject`, HEAD `622d5599318e4f1b2a82ef53bfc141970edc24de`, branch `phase7/reference-policy-identity`. Pre and post status:

```text
M README.md
 M docs/nolo/tasks/README.md
 M docs/nolo/tasks/fixtures.json
 M docs/nolo/tasks/source_manifest.json
 M pyproject.toml
 M schemas/network/completed_deal_analysis_v3.schema.json
 M src/tuppi_eval/agents.py
 M src/tuppi_nolo/adapter.py
 M src/tuppi_nolo/certificates.py
 M src/tuppi_nolo/security.py
 M src/tuppi_nolo/support.py
 M src/tuppi_server/analysis.py
 M src/tuppi_server/completed_deal_review.py
 M src/tuppi_server/match_runner.py
 M src/tuppi_server/post_match_diagnostics.py
 M tests/nolo/test_support.py
 M tests/server/test_completed_deal_review.py
 M tests/server/test_match_runner.py
 M tests/server/test_post_match_diagnostics.py
?? docs/nolo/compact_backend.md
?? docs/nolo/hypotheses-n10.md
?? docs/nolo/hypotheses-n11.md
?? docs/nolo/n10_positions.json
?? docs/nolo/results/N10.md
?? docs/nolo/results/N10_sources.json
?? docs/nolo/results/N11.md
?? docs/valuation/
?? src/tuppi_llm/
?? src/tuppi_nolo/compact.py
?? src/tuppi_nolo/coverage.py
?? src/tuppi_nolo/performance.py
?? src/tuppi_valuation/
?? tests/agents/test_nolo_discard.py
?? tests/llm/
?? tests/nolo/test_compact.py
?? tests/valuation/
?? tools/human_vs_bot.py
?? tools/measure_nolo_discard.py
?? tools/measure_odds_calibration.py
?? tools/measure_odds_ceiling.py
?? work/infrastructure_audit/
?? work/nolo/n10/
?? work/nolo/n11/
?? work/nolo_discard/
```

**ENGINE** = `TuppiProject-current`, HEAD `1347153f7d6e7bed95edddce9d35d28a3df91750`, branch `rules/project-target-v3-locked-bids`. Pre and post status:

```text
CLEAN
```

**CLIENT** = `TuppiClient-current`, HEAD `7ba8ca283f01794170d105ba08c5a799f7bd7909`, branch `feature/v3-locked-bids-sooli`. Pre and post status:

```text
?? Sources/TuppiClient/ReferencePolicy.swift
?? Tests/TuppiClientTests/ReferencePolicyTests.swift
```

**CLIENT_OLD** = `TuppiClient`, HEAD `1d82b4b36097f08684b3e4838166bda708ee8b19`, branch `main`. Pre and post status:

```text
M Sources/TuppiClient/Resources/Fixtures/manifest.json
 M Sources/TuppiClient/Resources/Fixtures/sha256sums.json
?? Sources/TuppiClient/ReferencePolicy.swift
?? Tests/TuppiClientTests/ReferencePolicyTests.swift
```

### Completion check

All37 requested G/C question IDs have explicit statuses and consequences; all8 shared contracts are mapped. Proposed interfaces/fixtures are labelled. Test presence and execution are separated. Main capsules plus both returned source supplements contain decisive implementation, including sampler dependencies. No sealed data, training, external calls, build, implementation or live change occurred. Baseline defects and document/code conflicts remain visible. Unknown empirical quantities are deferred. Discriminating tests include conflicting hidden worlds, nonconstant proxies, zero/nonzero event controls and harmful signals. Current installed binary/source correspondence and live process identity remain explicit limits.
