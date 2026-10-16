# Tuppi final assessment of cheap improvements

Four inexpensive opportunities remain worth considering: make adaptive bidding obey the policy anchor while allocating worlds, average the root actor over lawful suit swaps, solve only the endgame distinctions that affect equity, and remove redundant processing of identical rollout models. The first two could improve decisions. The latter two could reduce computation at the existing strength. **None has a confirmed game-strength gain in the current W1024 bot.**

The strongest fresh evidence is an isolated endgame prototype: identical float rewards on 256 synthetic positions with 42.5% fewer solver nodes. The most interesting new strength hypothesis is a four-view suit ensemble at the root: the existing actor makes materially different choices under suit swaps that preserve the rules, and four native actor forwards cost about 0.20–0.21 ms in small per-root calls on this Mac. Both findings justify small tests, without justifying a new large training programme.

Assessment date: 14 October 2026. Evidence and executable probes are in [PROBES.json](PROBES.json), [probe.py](probe.py), [build_probe.py](build_probe.py) and [BUILD.json](BUILD.json). All new files are confined to this assessment directory. Production source, models, installed native library, running server and app were left unchanged. The source files hashed by the probes remained unchanged during their execution.

## Current bot and evidence

The current product is the v3 game with blind locked bids, NOLO/RAMI and sooli. [PRODUCT.md](../../PRODUCT.md) and the [maintenance report](../tuppi_maturity_implementation_20261013/REPORT.md) define the product and validation boundaries. `TuppiProject-current` is the authoritative current engine/server; `TuppiAI` is the bot. The unfinished `TuppiProject` and `TuppiClient` trees belong to concurrent work. `TuppiAI-prior` contains prepared research infrastructure, and `TuppiAI-mature`/`TuppiBrowser` contain the portable browser work. These roles are distinct.

The current [factory](../../TuppiAI/tuppi_ai/best.py) uses VRPO1 for both rollout teams, VRPO3 for the root policy anchor, a six-trick exact ordinary tail, the showing-fallback sampler repair and the incumbent-derived equity table. The factory default is W128; the [live server source](../../TuppiProject-current/src/tuppi_server/match_runner.py) requests W1024. Above W128, bids use adaptive batches of 128 with z=2.5 and delta=0.005. The anchor margins are 0.003 for play and 0.03 for bids. This describes current source, not an attestation of the server's loaded process.

The bot has a substantial record of measured improvements and negative results. The [results ledger](../../TuppiAI/docs/STATUS.md) records the exact speedups, E7 adaptive bidding, learned policies, stronger rollouts and successful policy anchoring. The [robustness study](../../TuppiAI/docs/ROBUSTNESS_PLAN.md) then changed the opponents' rollout model from the heuristic clone to VRPO1. That gained +0.00701 ± 0.00271 equity per deal on its W128 strong-opponent panel and cost −0.00224 ± 0.00196 against the heuristic in the powered guard. The owner selected the strong-opponent objective and deployed it; the W1024 bot-versus-bot confirmation was stopped before a result.

Consequently, the project has demonstrated diminishing returns on several methods, but has not established a general strength ceiling for the final configuration. Old W128 gains, earlier W1024 gains against heuristic opponents, and sum-of-gains narratives cannot substitute for a fresh comparison of the final W1024 controller against strong opponents.

## Ranked opportunities

| Priority | Change | Main benefit | Evidence now | Next decision |
|---|---|---|---|---|
| 1 | Integrate the existing hard anchor into bid allocation | Better use of worlds; possible strength and latency benefit | Actual-method counterexample; implementation already prepared in the isolated prior checkout | Validate and screen one hard-anchor arm at W1024 |
| 2 | Average the root VRPO3 policy over four colour-preserving suit permutations | Possible strength gain with very little added inference | Lawful transition checks, substantial actor inconsistency, small inference cost | Screen a root-only ensemble with unchanged rollout policies and margins |
| 3 | Endgame search over exact equity buckets | Reduce exact-tail work without changing its valuation target | 256 identical rewards; 42.5% fewer nodes | Integrate privately and check complete root value/action/RNG parity |
| 4 | Use one batch and shared immutable weights when rollout models are identical | Reduce copying, allocation and split inference | Source-confirmed redundancy after the VRPO1 opponent-model change | Profile and fingerprint a narrow native/factory change |

### Make bid allocation answer the final decision question

[Searcher.adaptive_values](../../TuppiAI/tuppi_ai/search.py) eliminates actions using raw searched equity. Only afterward does `_keep_blueprint` keep VRPO3's action unless another beats it by 0.03. An anchor can therefore disappear from allocation while still being eligible for the final decision. Its value can have 128 samples while the challenger has 1024, and the final comparison uses those unequal estimates.

The probe executes the current method's AST with controlled paired returns. It produces sample counts **1024, 128, 1024**. The returned challenger mean is 0.04625 and the anchor's stale mean is 0.008, so the current post-search keep rule chooses the challenger. Pricing the same predetermined returns for all 1024 worlds gives an anchor mean of 0.036; with the existing 0.03 keep margin, the final choice is the anchor. This demonstrates the mismatch. It does not estimate its frequency or damage in actual games.

For fixed fully priced values, the current keep rule is equivalent to selecting `Q(a) + keep * 1(a == anchor)`, with the anchor winning an exact score tie. Apply that deterministic offset during leadership, elimination and stopping, and retain raw Q separately for diagnostics. Track action sample counts and never choose an eliminated action from its stale mean. This avoids spending worlds on distinctions the final rule will ignore and protects distinctions the final rule still needs.

This is **already prepared**, as `keep_adaptive=1`, in [TuppiAI-prior](../../TuppiAI-prior/docs/POLICY_PRIOR_INFRASTRUCTURE.md). It is not a new implementation claim or an invitation to merge that entire branch. Its runtime validation remains deferred, and its snapshot predates the final strong opponent model. Use the current VRPO1/VRPO1/VRPO3 identities explicitly when validating it.

Start with the hard-anchor integration alone. A soft log-policy prior or uncertainty-dependent keep margin adds another policy choice and should follow only if the simpler arm is useful. E7's z=2.5 heuristic is not automatically an anytime, family-wide error guarantee; sequential best-arm methods require a joint design of sampling, stopping and recommendation. [Garivier and Kaufmann](https://proceedings.mlr.press/v49/garivier16a.html) establish that distinction in their bandit setting, not a guarantee for this Tuppi implementation.

### Average the root actor over lawful suit swaps

The actor uses suit-indexed input features and action heads. The VRPO training path does not enforce equivariance. A rule symmetry therefore need not be a symmetry of the learned policy.

The safe full-game group here has four views: identity, hearts↔diamonds, clubs↔spades, and both swaps. All preserve the red/black showing rules, ranks, contracts and verbal fallback conditions. **Do not use all 24 suit permutations for this full-game actor intervention:** swapping a red and black suit can change showing legality. The value-net's older 24-suit augmentation belongs to a different full-information, post-bidding target.

The probes transform complete native state and public history, re-encode each actor's own view, remap legal action outputs, and check that a legal transition commutes with the transformation. Across two diagnostic corpora, 2,016 such checks passed.

| Diagnostic population | Card-play positions | Positions with any remapped actor disagreement | Four-view probability ensemble changes the action | Ensemble changes outside rank equivalence |
|---|---:|---:|---:|---:|
| Random legal ordinary trajectories | 128 | 57 | 22 | 15 |
| VRPO3-greedy ordinary trajectories | 128 | 75 | 29 | 19 |

The second corpus uses the native VRPO3 greedy policy and declines all sooli offers. It is closer to actor play, but neither corpus is current searched-bot self-play. Multiple observations share a parent deal, so these are descriptive counts, not confidence intervals. In its 128 bid positions, the ensemble changes the bid card/action 42 times but changes the contract only four times. Much of the bid inconsistency concerns signalling-card choice.

The proposed candidate averages **legal softmax probabilities**, remapped to original actions, across the four views. Consult this ensemble only for the root anchor; keep VRPO1 rollouts, sampled worlds, margins and all sooli mechanisms unchanged. Four native forwards took median 0.20–0.21 ms versus 0.053–0.057 ms for one view in 32 small calls per phase. Those timings exclude state/feature transformations and controller/search overhead.

This is the best novel low-cost strength hypothesis found in this assessment. Removing arbitrary suit dependence may reduce actor errors without retraining. It may also average away useful learned coordination, change signalling, or replace a good action with a worse one. The E6 result warns that adjacent-card choices can matter. Do not collapse actions, alias learned-policy cache entries across symmetries, or describe the ensemble as an exact optimization. Test both teammates adopting it together, and check mixed adoption if it is intended for human partnerships.

### Solve the equity distinction instead of the exact trick count

The [ordinary DD solver](../../TuppiAI/native/tuppi_dd.c) binary-searches the exact final trick count. Search then maps that count through scoring, rising-score transitions, match equity and float32 reward rounding. Several trick totals can yield the same reward: losing while ahead resets to 0–0 regardless of the penalty size; high-score wins can all end the match; other score transitions create further plateaus.

For each solver-tail row, compute its exact float32 payoff for the conservative range `team0_done ... team0_done + remaining_tricks`. Identify only the boundaries where that payoff changes. Use the existing null-window solver at those boundaries until the exact reward bucket is known. Monotonicity of scoring/equity with the ordinary trick split makes this sufficient. If the range is completely flat, no solver probe is required.

In the 256-position synthetic probe:

| Measure | Exact trick count | Exact reward bucket |
|---|---:|---:|
| Solver nodes | 220,247 | 126,676 |
| Null-window calls | 584 | 373 |
| Float reward mismatches | Reference | 0 |

The copied full solver also matched the installed solver's trick count on every position. Forty-five ranges were flat; the median range had three distinct reward buckets. The measured solver calls took only milliseconds, so the raw timing ratio is too fragile to be a general speed claim. **42.5% fewer nodes is an algorithmic observation on this corpus, not a 42.5% full-bot saving.** Payoff construction and any production lookup-table overhead need measurement.

This extends, rather than rediscovers, the [C3b utility certificate](../tuppi_implementation_plan/IMPLEMENTATION_SPEC.md) and [existing implementation](../../TuppiAI/tuppi_ai/research/c3_utility_stop.py). C3b checks whether the whole conservative range already has one value; its contract report found no eligible rows on one as-is six-trick-tail case. The new mechanism operates **inside the exact tail and also helps when multiple reward buckets remain**. It changes no rollout-policy batch shapes before that tail.

Integrate it only in evaluator-private ordinary DD tails. A bucket representative is not an actual final trick count or authoritative game result. Preserve the real game, research callers requiring exact tricks, and terminal statistics. Return an abstract utility result and accumulate it exactly once, preserving the current float32 delta then float64 aggregation. Use the actual loaded equity table. Whole root values, actions and RNG must still pass fingerprints across both contracts, declarer teams, partial tricks, resets and match-ending states.

An additional probe canonicalized suit names inside the DD transposition key. It preserved results and reduced nodes by 9.3% alone, but its extra canonicalization work made this short-tail microbenchmark slower. Combining it with reward buckets visited 47.8% fewer nodes than the original solver but was also slower than buckets alone. **Do not prioritize that additional optimization:** this is a useful negative result showing why node count alone is insufficient.

### Remove redundant separation of identical rollout policies

`best.OPPONENT_ROLLOUT` and `best.TEAM_ROLLOUT` now name the same VRPO1 file. However, [best_agents](../../TuppiAI/tuppi_ai/best.py) loads it twice, and [the native rollout loop](../../TuppiAI/native/tuppi_env.c) still allocates team/opponent feature and output arrays, copies rows into two groups, performs two forwards and copies them back. Each seat also exports separate native MLP weight objects.

When model configuration and weights are identical, use one inference batch and share immutable native weights within the factory. Keep separate seat environments, RNGs, diagnostics and lifetimes. Retain the existing split path for genuinely different team/opponent models. This opportunity became more concrete after the October opponent-model change; the earlier audit's weight-sharing idea predates that equality.

The mathematical rollout policy is unchanged, but altered BLAS batch sizes can alter float rounding and near-tie argmax choices. Require exact root fingerprints; if they differ, quantify the effect and treat the result as a numerical/policy variant. There is no measured speed estimate for this change yet.

## Small repairs and lower priority leads

The previously documented [v3 sooli-setting persistence](../tuppi_codebase_review_20261002/FINDINGS.md) remains: ordinary rollout options reset only when `ruleset == 2`, while sooli calls mutate them in v3. A retained controller can price later bids differently according to which sooli phases it previously visited. A one-line-looking repair can change the bidding model; the owner previously chose to retain it. Reopening it should therefore create a separately frozen comparison, not silently alter the historical bot or the browser's captured parity target. It is a correctness/model-consistency lead, with no established positive strength effect.

The showing-fallback sampler rebuilds its card-by-capacity DP per world in [showing_constraints.h](../../TuppiAI/native/showing_constraints.h), whereas the ordinary suit-split sampler already caches its tables. Caching the exact fallback table per observation is another narrow speed lead. Preserve all forbidden-placement, capacity and free-card keys and the RNG draw order. Its population benefit is unknown; do not spend a large profiling campaign on this rare branch before the four priorities above.

A mixture opponent model is cheap to propose but changes the strategic target. The strong-model deployment knowingly traded heuristic exploitation for strong-opponent play. Recovering the heuristic score is not necessarily an improvement under the owner's objective. It is secondary to validating the final W1024 configuration and the existing allocation mismatch.

## Ideas that do not justify another cheap win claim

| Idea | Existing evidence and reason to defer |
|---|---|
| Increase worlds everywhere | Earlier W1024 gained about +0.00107 over W128 at 7.6× CPU; the product already uses W1024. More sampling does not remove model bias. |
| Extend NOLO DD from six to seven tricks | Earlier test gave −0.00018, with 17% more CPU. No new mechanism addresses that failure. |
| Search one card per equivalent rank group | E6 saved 9% CPU but failed its non-inferiority gate; signalling choices affected real continuation. |
| Add a learned belief net or sharpen policy likelihoods | Multiple attempts lost strength or collapsed effective samples. A new calibrated strong-play inference model is substantial research. |
| Replace rollouts with a value net | VN1 bid leaves met a strength guard but saved only 1.09× whole-deal CPU after E7; play leaves and VN2 failed. Changed browser costs could warrant a new product-specific test, not reuse of old claims. |
| Bigger Q nets or more search-labelled iteration | SP2/SP2b did not break the plateau; SP3 improved label fit but lost in games. These require a changed target or information model. |
| More VRPO training | Earlier runs gained modestly, but another many-hour training run is outside this assessment's meaning of cheap. |
| Force RAMI using five supported cards | The [five-legs study](../rami_five_legs_20261004/REPORT.md) found −0.00273 equity/deal for the sufficient-trigger intervention. |
| Revive C2/C5 unchanged | [C2](../tuppi_implementation_output/research/c2_screen_stage2_results.md) showed no conditional-sampling gain at equal effective sample; [C5](../tuppi_implementation_output/research/c5_screen_stage1_results.md) rarely followed its plan against searching opponents. |
| Treat CVR/JRPL stops as proof of no headroom | [Earlier execution](../../tuppi_execution_12h/RESULTS.md), [corrected-sampler CVR](../../tuppi_execution_sampler_v1/RESULTS.md) and [v2 commissioning](../../tuppi_execution_v2_output/RESULTS.md) have different failure/cost boundaries. They do not establish universal impossibility, and they are not cheap continuations. |

Determinized search also retains an information-structure limitation. More perfect-information solving does not automatically produce a better implementable hidden-information strategy; [Frank, Basin and Matsubara](https://cdn.aaai.org/AAAI/1998/AAAI98-071.pdf) demonstrate the broader problem in imperfect-information games. That supports keeping the policy/search combination and testing complete trajectories, not importing an expensive equilibrium solver as a cheap fix.

## Recommended final round

1. Freeze the current W1024 baseline with explicit source, model, native, equity and controller-lifecycle identities. Keep the as-is sooli state policy. Use fresh indexed duplicate bundles and fresh retained controllers per complete-match leg; do not score censored matches as draws or mix incompatible process-global sampler settings. The earlier [findings](../tuppi_codebase_review_20261002/FINDINGS.md) and [prepared checked evaluator tools](../tuppi_experiment_tools_20261002/IMPLEMENTATION_REPORT.md) explain those requirements.
2. Develop the reward-bucket tail and identical-model batching independently in an isolated checkout. Require root value/action/RNG fingerprints and measure both CPU and wall time on representative bids, RAMI, NOLO and sooli paths. Keep an exact-tricks fallback. Do not bundle saved time with more worlds and call that the same optimization.
3. Screen **two strength arms only**: existing hard-anchor allocation, then four-view root actor averaging. Keep margins and model identities fixed initially. Use current searched opponents and VRPO3, with the heuristic as a secondary guard. First record per-action sample counts, changed-decision frequency, paired base-deal variance and actual cost; choose confirmation size from those measurements and an agreed meaningful effect. Saved root values may screen hypotheses, but complete changed trajectories decide adoption.
4. Confirm a useful arm on fresh W1024 deals and completed matches before calling it a strength gain. Keep this record separate from the original planning packages. If neither cheap strength arm transfers, close the final cheap round and retain the exact speed work that passes its gates.

My recommendation is to spend the next small implementation effort on the exact reward-bucket tail, and the next bounded strength experiment on hard-anchor allocation. The suit ensemble deserves the second strength slot because it uses the existing strong actor, exposes a concrete inconsistency, and adds very little inference cost. There is no present evidence for another large cheap strength jump; there are credible opportunities for better integration and less wasted computation.
