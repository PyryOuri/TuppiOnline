# Tuppi after the first large self-play run: research handoff

Prepared 29 September 2026; run-record snapshot cutoff 16:12:03 UTC. This file is self-contained for a planning LLM without repository access. It combines a read-only inspection of the current implementation and logs with a targeted primary-literature review through this date. Recommendations are hypotheses for Tuppi, not measured improvements. No training, experiments, source edits or deployment were performed for this handoff.

## Recommendation

Keep the first large SP1 run as a useful baseline. Do not interpret an insufficient gain as evidence that self-play has failed. First identify whether the bottleneck is action-value estimation, policy distillation, changing opponents, search integration, or the training environment. The most credible next algorithmic comparison is **a compact, clone-initialised, regularised PPO actor with a full-information critic used only during training**. Compare it with a repaired SP1 and selective search distillation at equal end-to-end compute.

Train against a small, diverse, frozen collection of opponents and partners if cross-play exposes fragility. Add a full PSRO league only if simpler population sampling leaves a measurable problem. ReBeL, Deep CFR, R-NaD and Student of Games belong on the longer-term research list; none is an efficient drop-in replacement for this four-seat partnership system.

This ranking is an engineering and scientific judgement based on the local evidence and the literature below. It is not a claim that one paper establishes the optimal Tuppi algorithm.

## 1. What game and objective are we solving?

The authoritative game is `project_target_v3`, defined by the v1, v2 and v3 rule documents in `TuppiProject-current/docs/rules/`. Four seats hold 13 cards each; opposite seats are permanent partners. There are no trumps. In RAMI teams seek tricks; in NOLO they avoid tricks. Bids consist of a declaration and an eligible card, chosen without seeing other bids. Reveals stop at the first RAMI. Bid legality depends on card rank and red/black colour, including fallback rules. Sooli adds a private exchange, a dead partner hand, three-player trick play with ace low, and a 24-point outcome. Matches use rising scores and end at 52 or more.

Two teams do not make this an ordinary two-player perfect-recall game: partners have different private hands. A deployed actor must use its own legal observation/history. Shared parameters are allowed; sharing private hands at inference changes the game.

Separate three objectives:

1. A strong inexpensive standalone policy.
2. A policy or model that improves the existing search at an acceptable latency.
3. Strong complete-match performance, including playing with an unfamiliar or human partner.

Success at one does not establish the others. The earlier broad-strength programme aimed at roughly 60% complete-match wins against its frozen B0, with a lower bound above 55%. SP1 instead uses per-deal equity screens. Neither threshold should silently replace the other. There is no established conversion from +0.005 equity/deal to a particular match win rate.

## 2. Current implementation, not just its name

Workspace roles:

| Path relative to `/Users/pyryouri/Developer` | Role |
|---|---|
| `TuppiAI-sp/` | Active self-play worktree inspected here |
| `TuppiAI/` | Main bot/search checkout |
| `TuppiAI-perf/` | Concurrent optimisation checkout; not edited |
| `TuppiAI-vn/` | Value-network worktree |
| `TuppiProject-current/` | Authoritative v3 engine |
| `TuppiProject/` | Separate older research checkout with concurrent work; do not conflate |

At inspection, SP HEAD was `f6463cecd0ccce49e2d8b61982b632186f732b64`, AI HEAD `da299a3f2789325d304b79713208169e9815027a`, and engine HEAD `1347153f7d6e7bed95edddce9d35d28a3df91750`. SP had uncommitted changes in `native/tuppi_env.c` and `tuppi_ai/native.py`. Source and log observations are a moving snapshot, not proof of the binary loaded by a running process. The adjacent `SOURCE_SNAPSHOT.json` records exact file hashes and copied run records; it is supplementary, not required to understand this file.

### The live search comparator

`TuppiAI/tuppi_ai/best.py` defines a clone-driven determinization search: sample hidden hands consistent with observations; compare legal actions through rollouts; use a six-trick double-dummy tail. The Python default is W128. The workspace README reports W1024 for live play; E7 adaptive bid allocation is configured above W128. Server restart/loaded binary was not verified here. Use explicit settings and binary hashes in a future comparison.

The small rollout network has encoder 2, a 256-wide trunk with two residual blocks, and 156 action outputs. Encoder 2 represents the public play sequence, in addition to hand, score, contract, shown cards and other features. A recurrent network is therefore not automatically needed merely to add history.

### SP1 is approximate policy iteration

Source: `TuppiAI-sp/tuppi_ai/selfplay.py`, native actor/labeller in `native/tuppi_env.c`, and `docs/SELFPLAY_PLAN.md`.

```text
Initial policy = bc_small behaviour clone
For each iteration:
  generate v3 deals with random start scores
  play the policy on all four seats, with some random exploration
  record a subset of unforced bid/card decisions
  for each recorded full state, branch every legal action
  finish each branch with the current observation-only policy
  regress observation-only Q on full-state realised branch returns
  train on absolute Q error plus 4 × centred-advantage error
  choose action by argmax(Q + margin for retaining old action)
  distil chosen actions into one policy with cross-entropy
  evaluate new policy pair versus clone pair and preceding-policy pair
```

Returns are the acting team's change in a fixed incumbent match-equity table. SP1 uses no solver tail. Sooli is resolved by heuristics with a fast offer model; the learned 156-action policy does not learn the complete sooli decision process. AdamW training uses MPS when available, packed feature storage and optional compilation. A three-iteration replay buffer mixes previously generated Q labels. Held-out advantage R² chooses Q weights every 200 steps.

All actions at a recorded state share the actual hidden cards. This reduces paired-difference noise; it does **not** remove uncertainty about hidden cards. Action-by-hidden-hand interactions remain, and one full-state branch outcome is not the conditional action value of an information set. Actor-local continuations distinguish this from a full-information optimal-action teacher.

### Written plan and actual runs differ

| Setting | `Config` default / written plan | `runs/selfplay/sp1/config.json` |
|---|---|---|
| Recorded states/iteration | 400,000 in code | 2,000,000 |
| Retain-old-action margin | 0.003 | 0.006 |
| Minimum advantage R² for update | 0.20 in code | 0.01 |
| Q / policy update steps | 2,000 / 1,500 | 2,000 / 1,000 |
| Native evaluation base deals | plan 20,000; code 8,192 | 8,192 |
| Replay / batch / random probability | 3 / 16,384 / 0.03 | same |

The separate `scale1` configuration records 3M states/iteration, margin 0.003, minimum R² −9, and 800/800 updates. Do not merge these runs into a single unchanged preregistration. This handoff does not establish when or why the settings changed.

The written SP1 criteria are: continue if periodic policies improve on the clone beyond their 95% intervals; stop the recipe if no policy reaches +0.005 equity/deal within 24 loop hours; require search integration to pass non-inferiority with lower 95% bound above −0.0010, and claim a +0.0020 gain only with a positive lower bound. These are existing project gates, not universally adequate sample sizes. The inspected Python loop does not automatically enforce all these scientific gates: its loop limits are hours/iterations, with an R² check inside learning. Do not assume a stopped or continuing process proves a gate decision.

### Observed preliminary results

At the final snapshot cutoff, the `sp1` log contained four complete iterations:

| Iteration | Recorded states | Equity versus clone | Logged 95% half-width | Advantage R² | Total seconds |
|---|---:|---:|---:|---:|---:|
| 1 | 2,016,984 | +0.002225 | 0.000405 | 0.0332 | 292.2 |
| 2 | 2,012,306 | +0.003144 | 0.000410 | 0.0193 | 282.9 |
| 3 | 2,022,964 | +0.005011 | 0.000415 | 0.0239 | 298.0 |
| 4 | 2,025,432 | +0.005905 | 0.000404 | 0.0240 | 327.5 |

These are logged native duplicate screens of paired networks, using eight games per base deal and default start score 0–0. They are not authoritative-engine confirmation, a search comparison, a cross-partner test, or a match-win measurement. Iteration 4's nominal interval is approximately [+0.005501, +0.006310], above +0.005, whereas iteration 3's interval straddles that threshold. Repeated checkpoint inspection affects selection claims; retain this as promising screening evidence pending independent confirmation. Low R² alone clearly cannot establish failure: the logged policy improves despite explaining little raw branch-advantage variance.

The user describes the first 100M self-play run as ongoing. The inspected logs do not count completed original games, branch rollouts or total environment steps, so they do not verify 100M completion or even its accounting unit. The separate status estimate of about one hour for 100M deals is an actor-throughput estimate, not the full learning loop. In SP1 iteration 3, labels cost 181.0 of 223.5 collection seconds, and training cost 62.7 seconds. Branch generation, not only optimiser throughput, matters substantially.

## 3. Existing negative evidence to preserve

These are project-reported results, inspected but not rerun. Populations, rules versions and comparators differ; do not pool the numbers.

| Attempt | Local evidence | Consequence for next work |
|---|---|---|
| Plain DMC from scratch, `dmc1` | −0.047 after 1.6M deals; weak action separation | Warm start and improve credit assignment; not proof DMC can never work |
| Paired branches from scratch, `pair1` | Uninformative differences under near-random continuation | A competent continuation is useful; raw scale alone may be wasteful |
| Greedy learned Q over blueprint, `pi1` | −0.020; excess RAMI; margin was neutral | Measure selection bias and action rankings, not just MSE |
| Expert iteration `xi1_small` | Standalone +0.0025 in its historical test; rollout replacement did not help | A stronger actor is not necessarily a better model of other players |
| Behavioural belief weighting | Worse than uniform; model mismatch and particle collapse | Better card prediction does not itself prove better action selection |
| C1/C2/C5 pilots | Insufficient cost opportunity / no useful validated gain / opponent-model mismatch | Do not restart these identical mechanisms under new names |
| VN1 / VN2 | VN1 bid leaf non-inferior but only 1.09× total speed-up; VN2 −0.00039 [−0.00126,+0.00048], excess RAMI | Leaf replacement failure is not a training-critic failure; separate their uses |
| Original CVR | `BASELINE_SAMPLE_INCOMPATIBLE_WITH_ENGINE` | A legality failure, not an informative negative strength trial |
| Corrected-sampler CVR | 256 teacher parents; `SCREEN_DID_NOT_MEET_INVESTMENT_GATE` | Explicitly compare any new teacher proposal with this attempted correction |
| JRPL after extension | `NO_SUPPORTED_LEARNING_GAIN_OVER_INITIAL_CONTROL` | New partnership learning must beat its untrained/initial-policy control |

Sources: `TuppiAI/docs/STATUS.md`, `TuppiAI-sp/docs/STATUS.md`, `TuppiAI-sp/docs/VALUE_NET_PLAN.md`, `audit_deliverables/tuppi_implementation_return/RETURN_TO_PLANNER.md`, `tuppi_execution_12h/RESULTS.md`, `tuppi_execution_sampler_v1/RESULTS.md`. Earlier `tuppi_execution_v2_output/RESULTS.md` was commissioning-only and is superseded by later execution results for trial status.

## 4. Diagnose SP1 before replacing it

The following are source-derived concerns and proposed diagnostics, not demonstrated causes of the current run's performance.

**Distinguish prediction noise from decision failure.** Measure held-out advantage error by bids, early/late NOLO and RAMI, score and legal-action count. Measure the realised value of the composite Q policy separately from its distilled policy. Report agreement and regret on changed decisions. A low aggregate R² may reflect irreducible hidden-state noise; a high one can coexist with bad argmax choices.

**Separate original deals in validation.** The learner holds out the first 10% of recorded rows, without parent-deal identifiers in its returned dataset. Multiple states from the same deal can therefore cross the split. Native recording order can also reflect batching. Preserve deal IDs and split before branching, augmentation or replay. Use a separate selection set and untouched confirmation stream. The present held-out R² is a development metric, not a clean proof of generalisation to independent deals.

**Treat replay as changing-policy data.** Three iterations' labels estimate returns under three continuation policies; unconditioned regression learns a mixture, not exactly Q of the latest policy. Compare one-iteration replay, policy-version conditioning, or limited relabelling on retained states. Reusing labels is not wrong by definition, but its bias must be priced against its data efficiency.

**Separate actor from opponent model.** Test own-team rollout replacement, opponent rollout replacement and both. A clone may remain useful as the opponent model even after the acting policy improves. Evaluate against the intended opponent population. Existing search takes a single rollout net; seat-specific continuation policies require an explicit adapter, not merely a different model path.

**Check objective and simulator transfer.** Native learning uses approximate sooli offers, no double-dummy tail and random start scores. The live policy uses search and different continuation assumptions. Test shortlisted policies in the authoritative engine with exact project handling. Audit score-table calibration against complete-match outcomes before assuming the fixed incumbent equity table remains accurate for stronger agents. Keep score-mixture diagnostics distinct from naturally visited match states.

**Preserve approximate-engine identity.** Dirty native code includes optional branch sharing and class-weighted recording. Neither appears enabled by the inspected `selfplay.py`, but runtime flags were not verified. Adjacent cards are not necessarily equivalent under a policy that reads exact ranks or signals; the code itself reports only 95.7% identical labels for a class of shared pairs. Validate decision/outcome effects, not merely throughput or logits. Do not attribute these concurrent changes to the frozen SP1 results without binary evidence.

**Use valid symmetries.** No trumps does not imply that all 24 suit permutations preserve the full game. Red/black bid eligibility matters. Colour-preserving suit permutations are candidates, with hands, masks, bids, history and action IDs transformed together. Any wider augmentation requires a demonstrated rule- and observation-preserving mapping. Existing policy conventions can also make a rule symmetry different from a fixed-policy-value symmetry.

## 5. Ranked methods and why

### A. First algorithmic alternative: regularised PPO with a training-only privileged critic

PerfectDou provides a relevant precedent: an observation-only actor, a critic with extra information during training, and PPO/GAE in a mixed cooperative/competitive card game. Its paper evaluates DouDizhu card play, not Tuppi bidding, and its reported distributed setup uses 880 CPU cores and eight GPUs. Transfer the mechanism, not its performance or training-time claims. See §3.1 and Appendix D.1 of [PerfectDou, 2022](https://arxiv.org/html/2203.16406v3).

A more recent comparison is directly relevant to algorithm choice: the ICLR 2026 study compares policy-gradient and specialised game-learning methods over five two-player games and more than 7,000 runs. Generic policy-gradient methods remain competitive; entropy regularisation is consequential. The games are not partnership Tuppi, and the paper's total compute is not a suggested local budget. See §§4–6 and Appendix E of [Reevaluating Policy Gradient Methods for Imperfect-Information Games](https://arxiv.org/html/2502.08938v4). Do not copy its entropy coefficients without matching reward scale.

**Proposed Tuppi design:** retain the fast compact actor and legal mask; initialise from the clone or a validated SP1 policy. Sample actions from a masked distribution during training. Fit a separate critic to full-state information and the relevant history/acting-team perspective. Estimate team-return advantages, with correct sign changes across opposing seats and correct terminal/reset handling. Apply PPO clipping or a measured KL limit, entropy regularisation, and modest update epochs. Start synchronously; log behaviour-policy versions and action log probabilities. Preserve an actor-only inference interface.

The critic predicts returns of the actual decentralised continuation. It must not secretly replace that continuation with a clairvoyant optimal policy. Full-information action argmax labels averaged after selection are not interchangeable with expected information-set action values. No hidden-hand features, critic outputs dependent on truth, or training-only teammate identifiers may leak into the actor at deployment.

This can avoid branching every legal action and avoid a separate noisy Q argmax/distillation loop. Whether it is more sample-efficient locally is an empirical question: bootstrapping adds bias, and PPO can waste data through excessive epochs. Compare both simulations consumed and total wall time. Test sampled versus greedy inference explicitly; argmax can destroy a strategy that depends on randomisation.

A controlled version should compare observation-only and privileged critics with the same actor, data budget and optimiser family. A small amount of clone regularisation may stabilise early learning; anneal and measure it rather than fixing imitation as a permanent ceiling. [MAPPO's cooperative experiments](https://arxiv.org/abs/2103.01955) support careful PPO baselines, but do not supply competitive-team convergence guarantees.

### B. Low-disruption alternative: repair conservative policy improvement and distillation

Keep the native SP1 data path. First fix parent splits and label-version accounting. Replace hard all-or-nothing action labels with a measured, regularised distribution if winner's-curse diagnostics implicate argmax. One candidate is

```text
p_target(a | o) proportional to p_reference(a | o) * exp(advantage(o,a) / temperature)
```

over legal actions, with a nonzero-support reference and controlled KL. This is a proposed regularised improvement step, not an assertion that SP1 implements MMD. Bound the actual policy update; a fixed 0.006 prediction margin is not a statistical confidence bound. A small independently trained Q ensemble can diagnose unstable choices, but correlated ensemble errors must not be reported as calibrated intervals.

Allocate labels by decision relevance: retain random coverage, add bid and early-play strata, and spend extra independent continuations/worlds where action selection is uncertain and consequential. Record selection probabilities and correct training weights when targeting the original distribution. Shared hidden cards remove common difficulty, not every component of variance. Repeating deterministic continuation on the identical full state buys no new information.

Use a small fixed audit panel to estimate label reliability and information-set action gaps. Any hidden-world resampling must satisfy bid legality and use a justified belief distribution; uniform legally consistent worlds are not automatically the behavioural posterior. The prior CVR legality failure makes this a concrete requirement.

### C. Efficient use of the existing strong teacher: selective expert iteration

ExIt alternates planning and policy learning; see [Thinking Fast and Slow with Deep Learning and Tree Search, 2017](https://arxiv.org/abs/1705.08439). Tuppi already has an expensive teacher and a historically successful first distilled actor, so selective teaching has a lower integration burden than replacing the entire search architecture.

Proposed application: use the current search on a mixture of random states and states where the learner disagrees or has uncertain high-impact choices. Retain action values, world counts and uncertainty, not only a hard winner. Confirm close action gaps on independent worlds. Distil into the compact deployed actor; if a larger offline teacher helps, pay its cost only during training. Collect teacher labels on learner-visited states to reduce distribution shift.

The search is an approximate teacher, not ground truth. Keep its model and sampler identity explicit. Do not launch nested W1024 search over every self-play decision. Measure useful confirmed teacher improvements per CPU-hour, including label generation. If the student reproduces the teacher but no longer improves, buying more imitation data alone cannot establish a better teacher. This differs from restarting CVR: the immediate target is the existing policy's useful decisions, not the previously unsuccessful learned leaf correction.

### D. Robustness: small partner/opponent populations before full PSRO

Self-play can develop conventions that fail with unfamiliar partners. [Other-Play, 2020](https://arxiv.org/abs/2003.02979) demonstrates this issue and a symmetry-based response in Hanabi. [Fictitious Co-Play, 2021](https://arxiv.org/abs/2110.08176) trains against diverse partners and their earlier checkpoints, with human-coordination evidence in Overcooked. These motivate cross-play, not a claim of measured human-Tuppi gains.

Proposed first population: frozen clone, search-distilled policy, selected early/late SP1 policies, and at least one independent training seed when available. Keep partner and opponent sampling separate. For the pure strong-pair objective, retain coherent jointly trained pairs as population entries; for human-compatible play, explicitly train and evaluate mixed pairs. Checkpoint age alone is a weak proxy for strategic diversity.

Measure a cross-play payoff matrix. If genuine cycles persist, train approximate best responses to a population mixture, as in [PSRO, 2017](https://arxiv.org/abs/1711.00832). Sample entire legal policies/pairs without introducing hidden communication. A mixture over a limited population is not a certificate of low full-game exploitability.

The 2026 [Joint Experience Best Response paper](https://arxiv.org/html/2602.06599v1) reuses shared trajectories to reduce PSRO sampling cost and addresses offline coverage with conservative, exploratory and hybrid variants. Its §6 acknowledges substantial remaining sample and population costs. Treat it as a later efficiency extension if a league is justified, not the default replacement for SP1. Off-policy reuse must account for which other policies generated the data.

### E. Longer-term methods, conditional on a demonstrated remaining bottleneck

| Method | Evidence and useful idea | Why not first here |
|---|---|---|
| [ReBeL, 2020](https://arxiv.org/abs/2007.13544) | Public-belief-state learning and search; two-player zero-sum result | Needs beliefs/ranges and a sound team information model; not ordinary determinization plus a value net |
| [Student of Games, 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10651118/) | Combines search, learning and game-theoretic reasoning across perfect/imperfect-information games | Substantial new solver and value interfaces; partnership transfer and cost unestablished |
| [DeepNash / R-NaD, 2022](https://arxiv.org/abs/2206.15378) | Search-free Stratego self-play using regularised game-learning dynamics | Stratego evidence does not establish a fast local Tuppi implementation or team convergence |
| [Deep CFR, 2019](https://proceedings.mlr.press/v97/brown19b.html) | Neural approximation of counterfactual regret; strong poker results | Current branch regression is not CFR; traversal, reach weighting and average strategy add substantial work |
| [Team-public-information conversion, 2022](https://arxiv.org/abs/2206.09161) | Coordinator prescribes actions using common information, respecting private states | Useful theoretical foundation for team solving; not permission to merge partners' hands into a runtime player |

A bounded reduced-deck Tuppi problem could test information-set algorithms and exact best responses before a full rebuild. That is a separate research investment. A learned attacker against the full game can reveal weaknesses but provides no upper bound on exploitability.

### Recent adjacent evidence screened

[Outer-Learning for Skat, December 2025](https://arxiv.org/html/2512.15435v1) bootstraps statistics for early-game choices. Its reported 30M AI-game generation required more than a month on 16 cores, although table fitting was cheap. It supports attention to early decisions, not a claim that the whole method is cheap or directly superior to SP1.

[A Gold-Standard Study of Lightweight Game-Playing Agents, August 2026 revision](https://arxiv.org/html/2607.06854v2) reports Gin Rummy improvements from trust-region updates, curricula and checkpoint selection, with limited benefit from larger encoders. This is a recent preprint and supporting evidence only; its scope and benchmark cannot establish a Tuppi ranking.

[DouZero, ICML 2021](https://proceedings.mlr.press/v139/zha21a.html) remains a useful counterexample to declaring Monte Carlo learning inherently inadequate: it produced strong DouDizhu play with neural action encoding and parallel actors. Its four-GPU, multi-day result is not a runtime forecast for this Mac. Recency alone does not make a method more applicable than an older, simpler baseline.

## 6. What to do for each observed outcome

| Outcome after a frozen SP1 checkpoint | Next decision |
|---|---|
| Better standalone and better in search | Preserve recipe, test independent seed and complete matches; scale only while useful gains per hour continue |
| Better standalone, search flat/worse | Diagnose continuation-model mismatch; separate own-team/opponent roles; consider policy-guided selective search rather than discard actor |
| Composite Q policy better, distilled actor worse | Repair distillation and measure changed-state regret before new simulation |
| Q action ranking weak and extra data saturates | Compare privileged-critic PPO and selective search targets; inspect label noise by phase |
| Beats latest checkpoint but loses to earlier policies/panel | Add population training, regularisation and checkpoint retention; evaluate cycles explicitly |
| Strong same-policy pair, weak mixed pair | Partner diversity/cross-play branch; keep this distinct from pure pair-strength objective |
| Native gain disappears in reference engine | Resolve legality, information, sooli and reward/simulator differences before further scaling |
| Evaluation too imprecise for the desired gain | Call it unresolved; collect independent evaluation units if worthwhile, not another arbitrary 100M training block |
| Strong per-deal screens, insufficient match wins | Revisit match-value calibration and score distribution, then test the actual match objective |

## 7. Efficient comparison programme for the next planning LLM

This is a proposed experimental design, not authorisation or a fixed compute commitment.

**Stage 0: freeze and establish meaning.** Obtain the completed 100M run manifest, its accounting units, policy/binary hashes, exact settings and final logs. Select checkpoints on development data. Preserve unselected and failed checkpoints. Add a clean independent authoritative-engine screen and the initial-policy control. Do not silently overwrite current SP1 criteria based on observed results.

**Stage 1: inexpensive failure localisation.** On a fixed development panel compare composite versus distilled actions; native versus reference transitions; clone versus selected policy; fresh versus mixed-version labels; and performance by phase/score. Price data generation, branching, training, evaluation and memory separately. Reuse valid frozen data where possible. Decide which one or two mechanisms deserve training.

**Stage 2: bounded algorithm comparison.** Recommended candidates are repaired SP1 and compact privileged-critic PPO, with selective expert iteration as a targeted comparator if teacher evidence is positive. Use a small prespecified hyperparameter set focused on update size, entropy and data reuse. Do not confound a new algorithm, larger architecture, changed sooli model and richer opponents in one comparison. Use three independent training seeds for shortlisted recipes if the budget permits; a single seed remains a pilot.

Measure:

- Independent original deals, recorded decision rows, branch completions, environment actions, optimiser updates, replay reuse and training seeds separately.
- CPU core-hours, accelerator/wall hours, peak memory and inference p50/p95 latency on the same hardware.
- Performance at matched total compute as the primary efficiency comparison; learning curves by sample count as a secondary one. Include teacher-generation and hyperparameter-selection cost.
- Against the clone, the preceding policy, retained diverse policies, and the frozen current search. A 50% win rate against an identical self-play copy says nothing about absolute strength.

**Stage 3: product transfer.** Use W128 for economical screening under explicit fixed search settings; confirm the chosen integration at intended W1024/adaptive settings and equal practical latency. Same-world-count and same-latency comparisons answer different questions; report both if resources allow. Preserve clone opponent modelling as a control. Check both bot-pair and mixed-partner settings.

**Stage 4: confirmation.** Use fresh complete-match pairs with complementary seat/team assignments, clustered at the original independent pair. Reuse the existing anytime-valid machinery only if its assumptions and utility bounds match the new endpoint; otherwise freeze a fixed sample size before testing. Use pilot variance to calculate precision rather than assume 512 deals suffice. Correct or isolate checkpoint/method selection. Report effect intervals and seed variability, not only the winning checkpoint. If pursuing the historical major-gain goal, measure its actual match-win target.

Stop a recipe for a validated harmful effect, an excluded useful effect after adequate precision, or a clearly saturated learning curve within its budget. Keep resource exhaustion, underexposure, broken execution and scientific failure separate. A null small pilot is not a universal theorem about the method.

## 8. Constraints and questions the next LLM must resolve

1. What precisely did “100M” count, and what was the final run outcome? Logs inspected here cannot answer.
2. Which target dominates: best homogeneous bot pair, human-compatible partner, or lowest-latency strong standalone agent? Default to live search strength while reporting the others separately.
3. What total future compute and latency are available? Literature cluster runtimes are not portable estimates.
4. Which sampler, sooli configuration and binary define the new baseline? Original B0 and corrected B0-S1 are separate evidence populations.
5. Was branch sharing or weighted recording actually enabled in the running optimiser programme? Preserve its independent attribution.
6. Can the proposed PPO interface correctly handle per-team rewards, asynchronous turns, policy versions and legal masked log probabilities? Test these before performance conclusions.

The targeted review inspected primary paper text or primary abstracts; full technical sections were consulted for PerfectDou, the 2026 policy-gradient comparison, JBR, and the recent Skat/Rummy candidates. It is not an exhaustive systematic review, and reported paper results were not reproduced. Abstract-level review supports the high-level descriptions of deferred methods, not implementation readiness.

## 9. Ready-to-paste instruction for the next LLM

> Use this handoff as the dated starting snapshot. First distinguish verified local evidence, paper evidence and proposed adaptations. Refresh the completed SP1/100M result and active binary/configuration identity. Diagnose the limiting step before recommending more scale. Produce a concrete, compute-priced comparison of repaired SP1, compact regularised PPO with a training-only privileged critic, and selective expert iteration where justified. Add diverse partner/opponent training only against a measured robustness need. Account explicitly for CVR/JRPL, belief, rollout-replacement and value-leaf negative evidence. Keep actor information legal, preserve independent parent splits, and evaluate actual search and match transfer. Challenge the ranking if stronger primary evidence or the completed SP1 results warrant it. Return an experiment plan with controls, discriminating outcomes and stop rules; do not assume this document authorises training or deployment.
