# Concluded findings

**Generated from `index.json` by `tuppi_research.findings`. Do not edit by hand.**

Check this before proposing a hypothesis. Every negative row carries its scope limits, because every mistake this index exists to prevent was a correctly scoped negative result read too broadly.

Query: `python -m tuppi_research.findings <term>` — 25 findings.

| date | id | verdict | question |
|---|---|---|---|
| 2026-09-05 | `pimc-small-rejected` | **rejected** | Does the registered uniform-feasible PIMC configuration beat the development reference? |
| 2026-09-06 | `phase5dc-search-fast-path` | **measured** | Can search-local state remove engine revalidation cost without changing search semantics? |
| 2026-09-08 | `s1-showing-headroom` | **inconclusive** | What observation-compatible headroom exists at the forehand's first show? |
| 2026-09-09 | `decision-leverage-v1` | **measured** | How many of the reference's decisions can change the deal outcome at all? |
| 2026-09-09 | `e1-loss-map` | **measured** | Where does the incumbent's hindsight loss sit, and is it concentrated? |
| 2026-09-09 | `e2-intensity-replication` | **confirmed** | Does E1's post-hoc intensity gradient replicate on fresh seeds with bars fixed in advance? |
| 2026-09-09 | `e3-endpoint-direction` | **confirmed** | Does the signed-deal-points surrogate point the same way as match outcomes? |
| 2026-09-09 | `s1b-showing-kill` | **killed** | Repeat S1 with the shrinkage estimator declared in advance: is there fundable headroom at the first show? |
| 2026-09-09 | `t0-ablation-surface` | **measured** | How much of the reference's strategy can be tested by single-rule ablation? |
| 2026-09-09 | `t1-hard-exclusions-sound` | **confirmed** | Are the reference's public-inference deductions sound? |
| 2026-09-09 | `t2-rule-ablation-closed` | **refuted** | Does disabling any single ablatable rule of the reference improve it? |
| 2026-09-09 | `t3-trick12-ceiling` | **inconclusive** | Is there exploitable headroom at the evaluated partnership's first turn in trick 12? |
| 2026-09-10 | `c1-opening-lead-headroom` | **void** | What observation-compatible headroom exists at the opening card play? |
| 2026-09-10 | `c3-world-count` | **measured** | How many sampled worlds does the opening-lead selector need to clear delta, and what does it cost? |
| 2026-09-10 | `c4-opening-lead-specific` | **measured** | Does the opening-lead selector's gain generalise to later decisions? |
| 2026-09-10 | `e4-duck-denial` | **refuted** | Should the incumbent decline to overtake its partner when an opponent can duck and preserve an honour? |
| 2026-09-10 | `e5-lead-exit` | **inconclusive** | Is winning a trick a liability when no safe lead remains afterwards? |
| 2026-09-10 | `e6-capture-timing` | **refuted** | Should the incumbent hold a certain winner to promote its lower cards in that suit? |
| 2026-09-10 | `q3-blinded-review` | **inconclusive** | Can one expert, blinded, beat the incumbent on hindsight-flagged decisions, and does their reasoning name rules the catalogue lacks? |
| 2026-09-10 | `trusted-transitions-policy-prohibition` | **constraint** | May a policy use the engine's revalidation-elision device to meet the latency budget? |
| 2026-09-11 | `ablation-fallback-decision` | **measured** | What does a policy do when a strategic rule is disabled, and how much of the incumbent is testable? |
| 2026-09-11 | `c2-reachable-headroom` | **measured** | How much of the opening lead's perfect-information gain is reachable from the observation alone? |
| 2026-09-11 | `c5-deployment-inconclusive` | **inconclusive** | Does the measured opening-lead headroom appear when the selector actually plays? |
| 2026-09-11 | `gate0-latency` | **measured** | Can an opening-lead PIMC selector run inside the decision bound? |
| 2026-09-12 | `crossplay-descriptive-only` | **constraint** | Does the existing cross-play record say anything about whether the incumbent's advantage transfers? |

## `pimc-small-rejected` — rejected

*2026-09-05* · tags: `pimc`, `search`, `rejected`, `negative`, `world-count`

**Question.** Does the registered uniform-feasible PIMC configuration beat the development reference?

**Scope.** uniform_feasible_pimc_small_v1 with world_count=4, showing search enabled, rollout policy partner_aware_v1, match_transition utility; 32 complementary complete-match pairs from 0-0 against development_reference_v1.

**Numbers.** world_count = 4; p_win = 0.156; interval = [0.075, 0.238]; sign_flip_p = 0.0001; record = 0 wins / 10 ties / 22 losses; censored_legs = 0; failed_decisions = 0

**Does not establish.**
- The registry states it explicitly: no strength claim is made or implied about PIMC designs in general. ONE CONFIGURATION was measured, not a family.
- Every registered configuration ever evaluated used world_count <= 8. See c3-world-count: delta is cleared only at 64, and 4 is slightly NEGATIVE.
- It searched every trick-play decision; see c4-opening-lead-specific for where headroom actually is.
- Its rollout policy was partner_aware_v1, not the incumbent partner_aware_lead_v2, which is not a supported rollout policy.

**Evidence.** `src/tuppi_search/registry.py`, `docs/search/phase5c_evaluation.md`, `reports/phase5c/phase5c_evaluation.json`

## `phase5dc-search-fast-path` — measured

*2026-09-06* · tags: `search`, `performance`, `pimc`, `fast-path`, `engineering`

**Question.** Can search-local state remove engine revalidation cost without changing search semantics?

**Scope.** Phase 5D-B search semantics only. fast_trick search-local trick-play state, differential-tested against the authoritative engine.

**Numbers.** aggregate_speedup = 10.47x; range = 8.04x to 15.67x; conformance_records_matched = 42; differential_simulations = 1000; differential_transitions = 16000

**Does not establish.**
- It was NOT applied to the Phase 5C PIMC rollout path: rollout.py does not use fast_trick, while multi_observer.py and root_info_uct.py do.
- The speedups are for 5D-B semantics; the magnitude on other search families is an estimate until measured.

**Evidence.** `docs/search/phase5d_c_results.md`, `src/tuppi_search/fast_trick.py`, `tests/search/test_phase5d_c_optimization.py`

## `s1-showing-headroom` — inconclusive

*2026-09-08* · tags: `showing`, `headroom`, `estimator-defect`, `preregistration`

**Question.** What observation-compatible headroom exists at the forehand's first show?

**Scope.** 512 forehand hands x 128 exact conditional completions x 2 arms; alternative arm is a declared lowest-eligible-rank selector; frozen reference continuation; 0-0; equity endpoint, delta 0.001.

**Numbers.** G_deploy = 9.6e-05; G_legal_upper = 0.001184; G_foresight = 0.006223; foresight_gap = 65x; signal_share = 0.894; rollouts = 131072

**Does not establish.**
- INCONCLUSIVE ONLY BECAUSE OF A PRE-REGISTRATION DEFECT: the declared bound's noise allowance was 10x delta, so its gate could never fire. This is not evidence about the game.
- Nothing about card play, which is 95.3% of decisions.
- Nothing about a freely chosen alternative card, later showing seats, non-zero scores, or transfer to other policies.

**Superseded by.** `s1b-showing-kill`

**Evidence.** `docs/showing/results_s1.md`, `docs/showing/hypotheses_s1.md`, `work/showing/s1_headroom.py`

## `decision-leverage-v1` — measured

*2026-09-09* · tags: `leverage`, `decision-classes`, `instrument`

**Question.** How many of the reference's decisions can change the deal outcome at all?

**Scope.** Reference self-play, frozen continuation, decisions across whole deals.

**Numbers.** decisions_that_cannot_change_the_outcome = 61%

**Evidence.** `work/showing/decision_leverage.py`, `docs/audit/results_t0_t3.md`

## `e1-loss-map` — measured

*2026-09-09* · tags: `hindsight`, `loss-map`, `card-play`, `instrument`

**Question.** Where does the incumbent's hindsight loss sit, and is it concentrated?

**Scope.** 96 deals, 2613 evaluated-partnership decisions, hindsight loss = best legal action minus chosen, own continuation, all four seats the incumbent.

**Numbers.** mistake_rate = 15.35%; mean_max_single_decision_loss_per_deal = 9.38; loss_mass_first_four_decisions = 52.8%; concentration = DIFFUSE

**Does not establish.**
- Hindsight loss is an UPPER BOUND on addressable loss: the best action is identified using the actual hidden hands. See s1b-showing-kill for a measured 65x gap at showing.
- Self-play blind spot: a flaw both partnerships share is invisible.
- The pre-registered concentration criterion was share-based and could not fire for a small intense class.

**Evidence.** `/Users/pyryouri/Developer/tuppi_e1_decision_quality_20260909/RESULTS.md`, `/Users/pyryouri/Developer/tuppi_e1_decision_quality_20260909/PREREGISTRATION.md`

## `e2-intensity-replication` — confirmed

*2026-09-09* · tags: `hindsight`, `replication`, `showing`, `card-play`

**Question.** Does E1's post-hoc intensity gradient replicate on fresh seeds with bars fixed in advance?

**Scope.** 192 fresh-seed deals, 5264 decisions, cluster bootstrap by deal, three hypotheses with bars declared before the run.

**Numbers.** showing_intensity = 2.0; showing_interval = [1.55, 2.55]; nolo_intensity = 1.16; declarer_partner_intensity = 0.65; mistake_rate = 17.34%

**Does not establish.**
- Showing being a high-hindsight-intensity class does NOT make it a target: s1b-showing-kill had already killed the showing intervention, and the 96%-irreducible finding explains the intensity.
- NOLO did not replicate and is not a licensed target.
- Hindsight metric, so the same upper-bound caveat as e1-loss-map.

**Evidence.** `/Users/pyryouri/Developer/tuppi_e2_intensity_20260909/RESULTS.md`, `/Users/pyryouri/Developer/tuppi_e2_intensity_20260909/PREREGISTRATION.md`

## `e3-endpoint-direction` — confirmed

*2026-09-09* · tags: `endpoint`, `surrogate`, `match-mode`, `instrument`

**Question.** Does the signed-deal-points surrogate point the same way as match outcomes?

**Scope.** Three contrasts at zero, moderate and extreme effect; deal mode 96 units, match mode 24 units, supply 256, both endpoints on independent banks.

**Numbers.** identity_at_zero = held on both endpoints; moderate_contrast_deal = 1.4375; moderate_contrast_match = 0.3333; match_endpoint_cost_ratio = ~110x; match_units_for_0.05_win_rate = 1274

**Does not establish.**
- Directional agreement only. RANK agreement - whether the surrogate orders candidates the same way - is unestablished and is what acceptance decisions need.
- No conversion factor between the endpoints is asserted.
- The two endpoints were measured on independent banks, so this is a sign comparison, not a paired one.

**Evidence.** `/Users/pyryouri/Developer/tuppi_e3_endpoint_20260909/RESULTS.md`, `/Users/pyryouri/Developer/tuppi_e3_endpoint_20260909/PREREGISTRATION.md`

## `s1b-showing-kill` — killed

*2026-09-09* · tags: `showing`, `headroom`, `kill`, `negative`

**Question.** Repeat S1 with the shrinkage estimator declared in advance: is there fundable headroom at the first show?

**Scope.** Fresh seeds, same design as S1: forehand's FIRST show, alternative card chosen by a declared lowest-eligible-rank selector, frozen reference in all other seats, 0-0, equity endpoint, delta 0.001.

**Numbers.** G_legal_eb = 0.000233; interval = [+0.000141, +0.000340]; G_deploy = 0.000131; G_foresight = 0.00594; perfect_legal_share_of_oracle = 3.9%; signal_share = 0.902

**Does not establish.**
- Nothing about card play, 95.3% of decisions and untouched.
- Nothing about a FREELY CHOSEN alternative card; the rules permit up to 26 legal showing actions and only one alternative was tested.
- Nothing about later showing seats, which decide after observing passes.
- Nothing about non-zero scores; equity is convex in the score and this is 0-0 only.
- Nothing about transfer: every seat was the reference.
- Nothing about whether a learned player is possible.
- It does NOT bound a joint showing/play policy: this is a marginal test under reference continuation.

**Supersedes.** `s1-showing-headroom`

**Evidence.** `docs/showing/results_s1b.md`, `docs/showing/hypotheses_s1b.md`

## `t0-ablation-surface` — measured

*2026-09-09* · tags: `ablation`, `rules`, `tooling-limit`, `instrument`

**Question.** How much of the reference's strategy can be tested by single-rule ablation?

**Scope.** The reference's own HeuristicProfile switch surface, established before any performance measurement.

**Numbers.** catalogued_rules = 38; implemented_by_reference = 24; mechanical_out_of_scope = 8; strategic_and_unvalidated = 16; of_those_ablatable = 4; unvalidated_with_no_switch = 12

**Evidence.** `docs/audit/results_t0_t3.md`

## `t1-hard-exclusions-sound` — confirmed

*2026-09-09* · tags: `inference`, `rules`, `soundness`

**Question.** Are the reference's public-inference deductions sound?

**Scope.** Hard ownership exclusions, checked against true deals. Also tested a behavioural ducking deduction.

**Numbers.** hard_exclusion_checks = 202800; violations = 0; behavioural_ducking_violation_rate_nolo = 16.6%

**Does not establish.**
- The behavioural ducking deduction is NOT sound and the reference does not implement it; soundness applies only to the hard exclusions.

**Evidence.** `docs/audit/results_t0_t3.md`

## `t2-rule-ablation-closed` — refuted

*2026-09-09* · tags: `ablation`, `rules`, `local-search`, `negative`

**Question.** Does disabling any single ablatable rule of the reference improve it?

**Scope.** 2000 control deals, the 4 ablatable rules plus one compound control, equity endpoint, delta 0.001, exploratory one-sided 95%.

**Numbers.** qualifying_variants = 0; inert_rules_of_four = 3; inert_action_divergence = 0.0%; V2_effect = -0.0002; V2_action_divergence = 5.2%; V5_positive_control = -0.00574; V5_interval = [-0.00652, -0.00498]

**Does not establish.**
- Nothing about the 12 unvalidated strategic rules that have no ablation switch, which is three quarters of the reference's unvalidated strategy.
- Nothing about rule ADDITIONS or modifications, only about disabling existing ones.
- Nothing about compound or multi-rule changes beyond the single V5 control.

**Evidence.** `docs/audit/results_t0_t3.md`

## `t3-trick12-ceiling` — inconclusive

*2026-09-09* · tags: `late-game`, `oracle`, `headroom`, `trick-12`

**Question.** Is there exploitable headroom at the evaluated partnership's first turn in trick 12?

**Scope.** 2000 control deals, every legal action replayed on the ACTUAL hidden deal with the frozen reference continuing. Hidden state used offline only.

**Numbers.** mean_oracle_gain = 0.000846; one_sided_95 = [+0.000698, +0.001004]; delta = 0.001; straddle = 4e-6 on the upper side; assignments_with_any_gain = 3.5%

**Does not establish.**
- Neither proceeds nor kills: the lower bound does not exceed delta and the upper bound does not fall below it.
- This is an ORACLE gain using hidden state, not observation-compatible headroom.
- Nothing about other tricks or other decision classes.

**Evidence.** `docs/audit/results_t0_t3.md`

## `c1-opening-lead-headroom` — void

*2026-09-10* · tags: `opening-lead`, `headroom`, `estimator-defect`, `world-sampling`

**Question.** What observation-compatible headroom exists at the opening card play?

**Scope.** 512 observations x 128 completions x 13 arms, two conditioning models (hard-constraint and policy-dependent), equity endpoint, delta 0.001.

**Numbers.** G_deploy_hard = 0.001441; G_deploy_policy = 0.00152; G_legal_eb_hard = 0.00057; G_foresight_hard = 0.015884; rollouts = 1657344

**Does not establish.**
- VOID: G_deploy exceeded G_legal_eb by 2 to 2.5x with disjoint intervals, which is impossible, from two estimator defects - noise treated as independent across arms priced on the same completions, and shrinkage applied across arms rather than across observations.
- NO HEADROOM BOUND is claimed by this run. That was its purpose and it failed.
- The cross-fitted G_deploy is unaffected by both defects and is the number that carries forward.

**Superseded by.** `c3-world-count`

**Evidence.** `docs/cardplay/results_c1.md`, `docs/cardplay/hypotheses_c1.md`, `work/cardplay/c1_headroom.py`

## `c3-world-count` — measured

*2026-09-10* · tags: `opening-lead`, `world-count`, `world-sampling`, `latency`, `pimc`

**Question.** How many sampled worlds does the opening-lead selector need to clear delta, and what does it cost?

**Scope.** 511 observations, hard-constraint conditioning, W in {1,2,4,8,16,32,64}, cross-fitted G_deploy, equity endpoint, delta 0.001. All three instrument gates passed.

**Numbers.** W1 = -0.000794; W4 = -0.000148; W8 = 0.000382; W32 = 0.001255; W64 = 0.00147; W64_interval = [+0.001226, +0.001717]; rollouts_per_decision_at_64 = 832; share_of_foresight = 8.5%

**Does not establish.**
- Only W=64 clears delta; W=1 is actively HARMFUL and W<=4 is negative to negligible.
- It is NOT a headroom bound. G_deploy <= G_legal, so 8.5% of foresight is a LOWER bound on legal headroom, not an upper bound on it. The ceiling at the opening lead remains unmeasured.
- The curve was still rising at W=64 (32->64 increment +0.000215), so 64 is not the asymptote.
- Cost was derived from aggregate batch throughput, not a timed single-decision request latency.
- Both arms continue with the frozen reference: this is opening-lead selection, not search play.

**Supersedes.** `c1-opening-lead-headroom`

**Evidence.** `docs/cardplay/results_c3.md`, `docs/cardplay/hypotheses_c3.md`, `work/cardplay/c3_worlds.py`

## `c4-opening-lead-specific` — measured

*2026-09-10* · tags: `opening-lead`, `depth`, `world-sampling`, `generalisation`

**Question.** Does the opening-lead selector's gain generalise to later decisions?

**Scope.** 256 observations, same seat followed through the deal at cards_left 12/9/6/3, W=64, worlds from the validated feasible sampler. All three instrument gates passed, including cross-instrument replication at depth 12.

**Numbers.** depth12 = 0.001387; depth9 = 0.000398; depth6 = 0.000634; depth3 = 0.000591; foresight_by_depth = 0.0164 / 0.0036 / 0.0033 / 0.0014; selector_share_of_foresight = 8.5% / 11.1% / 19.4% / 41.2%; verdict = OPENING_LEAD_SPECIFIC

**Does not establish.**
- Only the opening lead clears delta; depths 9, 6 and 3 are all well below it.
- Depth is CONFOUNDED with lead-versus-follow: at later depths the seat was on lead only 13-27% of the time with about five legal cards instead of thirteen. Whether a later LEAD benefits is unmeasured.
- No aggregate across depths may be computed: per-decision counterfactuals are not additive (see e6-capture-timing).
- Nothing about non-zero scores or transfer beyond the frozen reference.

**Evidence.** `docs/cardplay/results_c4.md`, `docs/cardplay/hypotheses_c4.md`, `work/cardplay/c4_depth.py`

## `e4-duck-denial` — refuted

*2026-09-10* · tags: `card-play`, `rules`, `negative`, `hindsight`, `partner`

**Question.** Should the incumbent decline to overtake its partner when an opponent can duck and preserve an honour?

**Scope.** Observational, 192 deals, RAMI trick-play decisions where the partner held the trick and overtaking was legally possible; hindsight loss; stratified by duck availability.

**Numbers.** overtook_mean_loss = 0.416; declined_mean_loss = 1.931; duckable_overtook = 1.156; duckable_declined = 2.4; non_duckable_overtook = 0.0; non_duckable_n = 80; large_errors = 2 of 125 overtakes

**Does not establish.**
- Observational and confounded: the policy chooses when to overtake, so the groups differ systematically. Enough to refuse the hypothesis, not to endorse the rule.
- The catalogued rule it questions, partner.rami.overtake_when_partner_beatable.v1, remains unvalidated (provenance generic_trick_taking_hypothesis).

**Evidence.** `/Users/pyryouri/Developer/tuppi_e4_overtake_20260910/RESULTS.md`

## `e5-lead-exit` — inconclusive

*2026-09-10* · tags: `card-play`, `negative`, `proxy-defect`, `hindsight`

**Question.** Is winning a trick a liability when no safe lead remains afterwards?

**Scope.** 192 deals; 'no safe exit' operationalised as every remaining card being a certain winner; stratified by cards remaining.

**Numbers.** no_safe_exit_share_of_decisions = 7.1%; no_safe_exit_share_of_loss = 1.0%; mean_cards_left_when_triggered = 1.72; mean_cards_left_otherwise = 6.32; loss_mass_9_to_12_cards = 52.8%

**Does not establish.**
- NOT REFUTED, UNMEASURED: the proxy matched only 1 of the 3 positions that motivated it and collapses into the endgame, where nothing is left to decide.
- A forward-looking squeeze measure was never tested; the 1% loss ceiling argues against building one.
- The concept as the reviewer stated it - anticipating a future squeeze - remains untested.

**Evidence.** `/Users/pyryouri/Developer/tuppi_e5_leadexit_20260910/RESULTS.md`

## `e6-capture-timing` — refuted

*2026-09-10* · tags: `card-play`, `rules`, `negative`, `selection-bias`, `hindsight`

**Question.** Should the incumbent hold a certain winner to promote its lower cards in that suit?

**Scope.** 192 deals, RAMI decisions played into a promotion structure; proxy validated against both motivating positions first; then the actual substitution priced by counterfactual.

**Numbers.** association_spent_vs_kept_9to12 = 6.634 vs 1.969; best_is_same_suit_lower = 71 of 172 (41.3%); policy_already_best = 56.3%; net_per_substitution = -1.99; net_per_deal = -4.083; opening_play_band = +1.524 (n=63)

**Does not establish.**
- The 41.3% figure was SELECTION ON THE OUTCOME: computed among decisions that already carried loss, while the rule fires on the whole population including the 56.3% where the policy was already right.
- Three converging signals - a 3x association, the named alternative being hindsight-best, and expert reasoning - all pointed the wrong way. Only pricing the counterfactual caught it.
- One band (opening play, n=63) was positive and is recorded as a possible narrow hypothesis, not a finding.

**Evidence.** `/Users/pyryouri/Developer/tuppi_e6_capture_20260910/RESULTS.md`

## `q3-blinded-review` — inconclusive

*2026-09-10* · tags: `human-review`, `hypothesis-generation`, `blinded`, `card-play`

**Question.** Can one expert, blinded, beat the incumbent on hindsight-flagged decisions, and does their reasoning name rules the catalogue lacks?

**Scope.** 24 trick-play positions, 12 hindsight-flagged and 12 matched zero-loss controls, three-way blinded, formal observation only, one reviewer.

**Numbers.** flagged_hits = 6 of 12; preregistered_bar = 8; monte_carlo_p = 0.295; control_hits = 12 of 12; control_chance_expectation = 10.92; factual_claims_verified = 6 of 6

**Does not establish.**
- NOT DETECTED on the efficacy question, but the control arm was near-automatic (91% by chance) so it could not confirm reviewer competence; that was recovered post-hoc.
- The flagged arm needed 8 of 12, a bar 71% above chance, so it can only detect a large signal.
- Positions were selected by hindsight loss, which is 65x inflated at showing and 91.5%-plus hidden-information-dominated at the opening lead. The seed was pointed at irreducible positions.
- The four concepts it named absent from the catalogue are hypotheses, not validated rules.

**Evidence.** `/Users/pyryouri/Developer/tuppi_q3_blinded_review_20260910/RESULTS.md`, `/Users/pyryouri/Developer/tuppi_q3_blinded_review_20260910/PREREGISTRATION.md`

## `trusted-transitions-policy-prohibition` — constraint

*2026-09-10* · tags: `constraint`, `latency`, `policy-boundary`, `search`

**Question.** May a policy use the engine's revalidation-elision device to meet the latency budget?

**Scope.** Architectural constraint stated in the module docstring and enforced by a test.

**Numbers.** self_play_generation_share_in_validation = 81%; measured_generation_speedup = 12.4x

**Does not establish.**
- No policy may enter trusted_transitions; tests/agents/test_architecture.py fails if any agent module imports it. It is a generation and research device, not a runtime performance switch.
- Research instruments and generators MAY use it, as the committed S1 instrument does.
- The sanctioned route for a search policy is a validated search-local state, differential-tested; see phase5dc-search-fast-path.

**Evidence.** `src/tuppi_engine/trusted.py`, `tests/agents/test_architecture.py`

## `ablation-fallback-decision` — measured

*2026-09-11* · tags: `assumptions`, `ablation`, `governance`, `supersedes-t0`

**Question.** What does a policy do when a strategic rule is disabled, and how much of the incumbent is testable?

**Scope.** The incumbent's 24 catalogued rules; T0-T3's 16 unvalidated strategic ones.

**Numbers.** ablatable_before = 4 of 16; ablatable_after = 6 of 16; counting_nolo_action_divergence = 3.8% and 1.0%; flag_is_identity_safe = 29 rules flipped in memory, zero agent ids moved

**Does not establish.**
- That the seven Class B rules are testable yet; they share score components under disjoint conditions and need per-rule condition-scoped neutralisation.
- That the three Class C showing thresholds are ablatable at all; removing a threshold has no neutral meaning and they are better varied than removed.
- That any unblocked rule is harmful. Ablation can only find harmful rules, and T2 found none qualified.

**Evidence.** `docs/audit/ablation_fallbacks.md`, `src/tuppi_agents/counting.py`, `tests/agents/test_architecture.py`

## `c2-reachable-headroom` — measured

*2026-09-11* · tags: `cardplay`, `opening-lead`, `headroom`, `supersedes-c1`

**Question.** How much of the opening lead's perfect-information gain is reachable from the observation alone?

**Scope.** Opening lead, HARD conditioning, incumbent continuing every other seat, all deals at score 0-0.

**Numbers.** G_legal_lower_bound_95 = +0.001702; reachable_fraction_of_foresight = >=10.6%; G_deploy_256 = +0.001860; G_foresight = +0.016015

**Does not establish.**
- A ceiling. The increment series is not decaying and the curve had not converged at W=256; the extrapolated plateau adds 63% of the measured value and is unusable.
- Irreducibility. G_foresight minus G_legal is the value of hidden information, not an error floor of any policy.
- Anything about the incumbent's distance from G_legal; this measures the far end of that interval.
- Anything at non-zero score states, which were never varied.

**Evidence.** `work/cardplay/c2_headroom.py`, `docs/cardplay/results_c2.md`, `docs/cardplay/hypotheses_c2.md`

## `c5-deployment-inconclusive` — inconclusive

*2026-09-11* · tags: `cardplay`, `opening-lead`, `deployment`, `underpowered`, `variance-pilot`

**Question.** Does the measured opening-lead headroom appear when the selector actually plays?

**Scope.** Deployed W=128 opening-lead selector, incumbent delegate and continuation, duplicate design, score states drawn from the match-visit distribution.

**Numbers.** mean_equity_difference = -0.000225; ci95 = [-0.002053, +0.001525]; realised_per_base_deal_sd = 0.0146; base_deals_needed_to_clear_delta = 1994

**Does not establish.**
- That the effect is absent. The campaign was underpowered by a knowable factor and could not have detected C2's effect.
- That the effect is present.
- Score-state dependence: the instrument discarded the per-block scores, so its own prediction P3 could not be evaluated.

**Evidence.** `work/cardplay/c5_deployed.py`, `docs/cardplay/results_c5.md`, `docs/cardplay/hypotheses_c5.md`

## `gate0-latency` — measured

*2026-09-11* · tags: `instrument-gate`, `latency`, `parallelism`, `opening-lead`

**Question.** Can an opening-lead PIMC selector run inside the decision bound?

**Scope.** Cold maximum over 12 fresh deals, single host, 13 legal actions.

**Numbers.** W64_serial_incumbent = 11.92 s; W64_parallel_8_incumbent = 2.24 s; W128_parallel_8_incumbent = 4.35 s; W256_parallel_8_incumbent = 8.58 s; largest_admissible_serial = W=32

**Does not establish.**
- The ten-second production requirement, which includes showing, encoding, transfers and synchronisation under a watchdog.
- Anything about other hosts.
- Any claim about strength.

**Evidence.** `work/cardplay/gate0_latency.py`, `docs/cardplay/results_gate0.md`, `docs/search/phase5d_c_optimization.md`

## `crossplay-descriptive-only` — constraint

*2026-09-12* · tags: `transfer`, `crossplay`, `retrieval`, `machinery-exists`

**Question.** Does the existing cross-play record say anything about whether the incumbent's advantage transfers?

**Scope.** reports/phase4/baseline_report.json, 11 teams, 66 cells.

**Numbers.** independent_base_deals_per_cell = 8; cells = 66; incumbent_present = no

**Does not establish.**
- Anything about transfer. The report states cross-play uses a deliberately small shared bank and is descriptive only.
- Anything about partner_aware_lead_v2, which post-dates this matrix and is absent from it.

**Evidence.** `reports/phase4/baseline_report.json`, `manifests/phase4/crossplay_request.json`, `src/tuppi_eval/crossplay.py`
