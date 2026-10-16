# Tuppi Self-Play Strength-Maximisation Research Packet

**Prepared:** 29 September 2026  
**Purpose:** Handoff for the next LLM/engineer whose objective is to make the Tuppi bot as strong as possible using self-play.  
**Status:** Research and experiment plan. No training, source edits, deployment, or new benchmark run is claimed here.

---

## 0. Mission

The objective is not to find the simplest self-play method or the method with the cleanest theoretical story.

The objective is:

> **Produce the strongest possible Tuppi bot, using self-play as the main learning mechanism, while measuring strength on the actual game and final deployment configuration.**

This packet updates the earlier `SELFPLAY_NEXT_METHODS_HANDOFF.md`. The existing SP1 pipeline remains a serious baseline because it is already producing positive screening results. However, the primary new algorithmic branch should now be **variance-reduced policy-gradient self-play with a privileged centralised action-value critic**, i.e. a Tuppi adaptation of the 2026 VRPO/Q-boosting idea.

The recommended research programme is therefore:

1. Freeze and independently verify the best current SP1 checkpoint.
2. Repair the known methodological weaknesses in SP1.
3. Build a compact **privileged-Q VRPO** learner.
4. Compare repaired SP1 and VRPO at matched end-to-end compute.
5. Align training increasingly closely with actual **complete-match winning**.
6. Integrate the strongest learned actor with the existing determinisation search.
7. Add **selective search distillation** where it produces useful policy improvements per unit compute.
8. Introduce population/partner diversity only if cross-play demonstrates a real robustness problem.
9. Scale architecture and total training only after the learning mechanism has been shown to keep producing strength.

---

# 1. Verified starting point

## 1.1 Game and deployment constraints

The authoritative game is `project_target_v3`.

Key properties:

- Four seats.
- Opposite seats are permanent partners.
- 13 cards per player.
- No trumps.
- RAMI: seek tricks.
- NOLO: avoid tricks.
- Bidding is simultaneous/private until reveal logic resolves.
- Bid legality depends on rank and red/black colour.
- Sooli includes a private exchange, dead partner hand, three-player play, ace-low handling, and a 24-point result.
- Matches use rising team scores and finish at 52 or more.

This is an imperfect-information **team game**. A deployed actor may use:

- its own private hand;
- public history;
- public score/contract information;
- any other information legally available to that seat.

It may **not** access partner or opponent private cards at inference.

A full-information critic is acceptable **only during training**.

---

## 1.2 Existing search comparator

The main search bot is a determinisation-based rollout search:

1. sample hidden hands consistent with observations;
2. compare legal actions through rollout;
3. use a six-trick double-dummy tail.

The Python default is W128. The project also uses larger live settings, historically including W1024/adaptive search.

The rollout policy already has public-history encoding. A recurrent actor is therefore not automatically required merely to represent previous play.

Search remains a deployment option even if self-play produces a strong standalone actor.

---

## 1.3 Current SP1 mechanism

SP1 is approximately a form of policy iteration:

```text
Initial policy = behavioural clone

For each iteration:
    generate self-play deals
    play the current policy on all four seats
    record selected non-forced decisions

    for each recorded full state:
        branch every legal action
        finish each branch with current policy continuation

    regress an observation-only Q network
        on realised full-state branch returns

    use Q + conservative retain-old-action margin
        to select an improved action

    distil selected actions into a policy network

    evaluate new policy against:
        clone
        previous policy
```

Current SP1 return target is based on change in a fixed incumbent match-equity table.

Important distinction:

> All legal branches for a recorded state share the same actual hidden deal.  
> This reduces paired noise, but one full-state branch outcome is still **not** the true information-set action value.

Hidden-hand × action interaction remains.

---

# 2. Current SP1 evidence

The inspected `sp1` run contained four completed iterations:

| Iteration | Recorded states | Equity vs clone | Logged 95% half-width | Advantage R² |
|---|---:|---:|---:|---:|
| 1 | 2,016,984 | +0.002225 | 0.000405 | 0.0332 |
| 2 | 2,012,306 | +0.003144 | 0.000410 | 0.0193 |
| 3 | 2,022,964 | +0.005011 | 0.000415 | 0.0239 |
| 4 | 2,025,432 | +0.005905 | 0.000404 | 0.0240 |

Iteration 4 has a nominal interval of approximately:

```text
+0.005501 to +0.006310 equity/deal
```

This is promising evidence.

It is **not yet** proof of:

- complete-match superiority;
- authoritative-engine transfer;
- W128/W1024 search superiority;
- mixed-partner robustness;
- improved human-partner play;
- a completed/verified 100M accounting unit.

The low advantage R² should not be interpreted as evidence of failure. The policy is improving despite the low aggregate R².

---

# 3. Negative evidence that must not be forgotten

Do not restart these failed or weak mechanisms under cosmetic new names.

| Prior approach | Existing evidence | Implication |
|---|---|---|
| Plain DMC from scratch | ~−0.047 after 1.6M deals | Do not restart from random; warm start and better credit assignment |
| Paired branches from scratch | Poor signal under near-random continuation | Competent continuation is important |
| Greedy learned Q over blueprint | ~−0.020, excess RAMI | Raw Q regression + greedy argmax can fail badly |
| Historical expert iteration | Small standalone gain; rollout replacement did not help | Strong actor ≠ good opponent/rollout model |
| Behavioural belief weighting | Worse than uniform | Better card prediction alone does not prove better decision selection |
| C1/C2/C5 pilots | No validated useful gain | Do not repackage identical mechanisms |
| VN1/VN2 value-leaf work | Little speed benefit / no clear strength gain | Leaf replacement and training critic are different hypotheses |
| Original CVR | Baseline sampler incompatible with engine | Failure was legality/infrastructure, not informative strength evidence |
| Corrected CVR | Screen did not meet investment gate | New teacher ideas must beat this history |
| JRPL | No supported gain over initial control | Partnership learning needs a proper control |

---

# 4. Primary algorithmic branch: privileged-Q VRPO

## 4.1 Why VRPO is now the highest-priority new method

A 2026 paper by Fan and Farina, **“GAE Falls Short in Imperfect-Information Self-Play Reinforcement Learning”**, identifies a specific variance source in PPO self-play for imperfect-information games.

Standard PPO commonly uses:

```text
actor + V(s) critic + GAE
```

In a stochastic imperfect-information equilibrium, future actions are themselves sampled. This introduces action-sampling variance into multi-step GAE targets even when the state critic is accurate.

The paper proposes:

- a centralised action-value critic `Q(s,a)`;
- Expected-SARSA-style multi-step targets;
- a Q-boosted advantage estimator;
- PPO-style clipped policy updates.

The resulting method is called **VRPO**.

Primary source:

- https://arxiv.org/abs/2605.19235

This is unusually relevant to Tuppi because:

- Tuppi is imperfect-information.
- Useful policies may need stochasticity.
- SP1 already shows that action-value discrimination is a central bottleneck.
- Tuppi has only 156 global action outputs, so summing policy-weighted Q values over legal actions is cheap.

The paper does **not** prove VRPO will beat SP1 in Tuppi. This is a high-priority hypothesis to test.

---

## 4.2 Actor

Use the existing compact observation representation unless a controlled architecture experiment later proves it insufficient.

Initial recommendation:

```text
Actor:
    observation-only
    legal-action mask
    256–512 hidden width initially
    residual MLP trunk acceptable
    outputs logits over 156 actions
```

Initialise from:

1. strongest independently confirmed SP1 checkpoint, preferably;
2. otherwise the behavioural clone.

Do **not** initialise from random unless specifically running an ablation.

The actor must not receive:

- other private hands;
- truth-only belief information;
- critic outputs dependent on hidden cards;
- illegal training-only teammate identifiers.

---

## 4.3 Privileged Q critic

The critic may use the complete simulator state during training.

Recommended critic inputs:

- all four hands;
- full public action history;
- contract;
- score;
- acting seat;
- team perspective;
- shown/played cards;
- legal-action mask;
- current deal/match context;
- Sooli state where applicable.

Recommended output:

```text
Q(s, a) for all 156 actions
```

Possible initial architecture:

```text
width: 512–1024
residual blocks: 3–6
```

The critic can be much larger than the actor because it is discarded at deployment.

The critic estimates the return of the **actual decentralised continuation policy**. It must not turn into a clairvoyant optimal-control teacher.

---

## 4.4 Expected action value

For each actor observation/state pair:

\[
V(s)=\sum_{a \in A_\mathrm{legal}} \pi(a\mid o)\,Q(s,a)
\]

This expectation is computationally cheap in Tuppi because the global action space is small.

The policy advantage is then derived from the Q critic rather than from a conventional V-only GAE pipeline.

Implement the VRPO/Q-boosting estimator according to the primary paper rather than improvising an approximate variant.

---

## 4.5 Team perspective

Reward/sign handling must be explicit.

If critic values are expressed from Team 0 perspective:

\[
A_i(s,a)=
\begin{cases}
Q_0(s,a)-V_0(s), & i\in Team\ 0\\
-\left(Q_0(s,a)-V_0(s)\right), & i\in Team\ 1
\end{cases}
\]

Equivalent team-relative encodings are acceptable.

Test reward/sign logic with small deterministic fixtures before any expensive training.

This is an infrastructure gate, not a performance hypothesis.

---

## 4.6 PPO/VRPO update

Start conservatively:

- masked stochastic policy;
- PPO clipped objective;
- measured KL;
- modest number of epochs per fresh batch;
- moderate entropy regularisation;
- gradient clipping;
- current-policy data;
- logged behaviour-policy version;
- stored action log probabilities.

Do not blindly copy entropy coefficients or PPO hyperparameters from Dou Dizhu.

Reward scale and action structure differ.

---

# 5. Why VRPO is preferred over vanilla PPO as the first new build

Vanilla privileged-critic PPO remains a valid control.

However, if implementing a new on-policy learner from scratch, the stronger scientific comparison is:

```text
SP1
vs
PPO + privileged V critic
vs
VRPO + privileged Q critic
```

If implementation cost forces only one new method, prioritise VRPO.

Reason:

- it preserves the strongest current empirical case for policy gradients;
- it directly addresses stochastic future-action variance;
- Tuppi's small legal action set makes expected-Q computation attractive;
- a large critic can exploit training-only truth without leaking it into the deployed actor.

The 2025/2026 imperfect-information policy-gradient benchmark also supports taking generic policy-gradient methods seriously rather than immediately rebuilding around CFR/PSRO-style machinery:

- https://arxiv.org/abs/2502.08938

A 2026 Big 2 self-play study further reports PPO outperforming several value-based baselines under matched experimental conditions and finds moderate entropy plus current-policy self-play useful:

- https://arxiv.org/abs/2605.28863

These are supporting results from different games, not guarantees for Tuppi.

---

# 6. Keep repaired SP1 as a full competitor

SP1 is already improving. It should not become merely an ablation.

Repair it.

## 6.1 Independent parent-deal splitting

Current held-out Q evaluation can contain states from the same original deal on both sides of the split.

Required change:

```text
deal generation
    ↓
assign parent deal ID
    ↓
split parent deals
    ↓
only then branch / augment / replay
```

Maintain:

- training parents;
- development/selection parents;
- untouched confirmation parents.

---

## 6.2 Label policy version

Replay currently mixes labels generated under different continuation policies.

Every label should include:

```text
policy_version
parent_deal_id
acting_seat
phase
score
contract
legal_action_count
```

Compare:

1. fresh latest-policy labels only;
2. short replay;
3. policy-conditioned replay;
4. limited relabelling of retained states.

Do not assume more replay is always better.

---

## 6.3 Diagnose Q selection rather than only Q MSE/R²

Measure:

- action-ranking accuracy;
- top-1 agreement;
- regret of changed decisions;
- calibration by predicted action gap;
- performance by bid/play;
- early versus late RAMI;
- early versus late NOLO;
- score state;
- legal-action count.

Most importantly:

> Evaluate the composite Q-improved policy before distillation.

Then compare:

```text
base actor
→ composite Q policy
→ distilled actor
```

If composite improves and distilled policy loses the gain, the bottleneck is distillation, not self-play data.

---

## 6.4 Replace brittle hard improvement where justified

The current retain-old-action margin is not a statistical confidence bound.

A useful candidate target is:

\[
p_{\mathrm{target}}(a\mid o)
\propto
p_{\mathrm{reference}}(a\mid o)
\exp\left(A(o,a)/\tau\right)
\]

over legal actions.

This yields a regularised soft improvement rather than hard winner-take-all Q argmax.

Treat this as an experiment, not an assumed improvement.

Possible controls:

- hard argmax + margin;
- soft advantage target;
- KL-constrained policy update;
- Q ensemble uncertainty gate.

---

# 7. Optimise the real objective: complete-match winning

This is a major strategic priority.

SP1 currently uses a fixed incumbent match-equity table.

That is useful for dense credit assignment, but if the policy changes substantially, the old table may cease to represent the true value of score states.

The final objective is:

\[
P(\text{win complete Tuppi match})
\]

not:

\[
\text{equity/deal against historical B0}
\]

---

## 7.1 Learn a contemporary match-value model

Generate complete self-play matches under contemporary policies.

Fit:

\[
M(x)=P(\text{eventual match win}\mid x)
\]

where `x` contains at minimum the score state and any genuinely relevant public match context.

Then use potential-style dense reward:

\[
r_t = M(x_{t+1})-M(x_t)
\]

while retaining the true terminal match result as the anchor.

This gives:

- dense per-deal learning;
- direct alignment with complete-match outcome;
- automatic adaptation when stronger agents change score-transition dynamics.

---

## 7.2 Do not immediately trust a learned match table

Validate calibration separately.

Report:

- predicted versus empirical win probability;
- score-state coverage;
- calibration by policy generation;
- naturally visited versus artificially sampled score states.

A bad match-value model can silently optimise the wrong thing.

Maintain terminal match win/loss as the final truth metric.

---

# 8. Self-play opponent curriculum

## 8.1 Start simple

Primary training should initially use mostly:

```text
current policy vs current policy
```

Suggested starting fraction:

```text
80–100% current-policy self-play
```

Why:

- strongest direct pressure for continual improvement;
- avoids spending much compute on obsolete policies;
- recent four-player card-game evidence supports current-policy self-play as a strong finite-budget baseline.

Do not start with a giant league.

---

## 8.2 Continuously measure cross-play

Retain strategically important checkpoints.

Construct payoff/cross-play matrices:

\[
P_{ij}=\text{performance of checkpoint }i\text{ against checkpoint }j
\]

Also test mixed partners.

Look specifically for:

- catastrophic forgetting;
- strategic cycles;
- convention lock-in;
- strong homogeneous pair but weak heterogeneous pair.

Example cycle:

```text
A beats B
B beats C
C beats A
```

If cycles are real and persistent, current-only self-play is inadequate.

---

## 8.3 Add population training only when needed

First population should be small and meaningful:

- clone;
- strongest early SP1;
- strongest late SP1;
- strongest VRPO/PPO seed;
- search-distilled actor if it becomes distinct.

Sample partners and opponents separately.

Only escalate to PSRO-style machinery if the measured payoff matrix demonstrates that simpler mixtures are insufficient.

---

# 9. Preserve stochastic policies

Do not assume argmax is the correct final deployment.

Imperfect-information strategies can benefit from randomisation.

Evaluate at least:

1. greedy argmax;
2. full policy sampling;
3. low-temperature sampling;
4. controlled probability floor or entropy-preserving deployment where appropriate.

Report:

- complete-match performance;
- exploitability proxy / cross-play robustness;
- search compatibility;
- mixed-partner performance.

A deterministic version can outperform average opponents while becoming easier to exploit.

Do not collapse stochasticity until measured.

---

# 10. Use the existing search as a strength amplifier

The strongest final bot is likely not necessarily policy-only.

Candidate final structure:

```text
strong self-play actor
        +
determinisation/search
        +
appropriate continuation models
```

The actor used to choose our move and the policy used to model other players need not be the same network.

---

## 10.1 Mandatory rollout-model factorial

For each strong actor, compare:

| Own-team continuation | Opponent continuation |
|---|---|
| clone | clone |
| learned | clone |
| clone | learned |
| learned | learned |

Do this first at W128 for economical screening.

Then confirm the best configuration at intended live settings, e.g. W1024/adaptive.

Prior project evidence already shows:

> A stronger standalone actor does not automatically make a better rollout/opponent model.

This must remain an explicit experimental dimension.

---

## 10.2 Same-world versus same-latency comparisons

Both are useful.

### Same search budget

Hold number of sampled worlds fixed.

Answers:

> Is the new policy/model intrinsically better under the same search workload?

### Same practical latency

Hold wall-clock decision latency fixed.

Answers:

> Which final agent is stronger in actual deployment?

Report both if practical.

---

# 11. Selective search distillation

Once the self-play actor is strong, use the existing expensive search selectively rather than uniformly.

Prioritise states with:

- high actor entropy;
- small critic action gaps;
- critic ensemble disagreement;
- disagreement between actor and W128/W1024;
- high estimated match-value leverage;
- bidding and early-play decisions where errors propagate;
- states repeatedly implicated by loss analysis.

For teacher-labelled states retain:

- search action distribution where possible;
- action values;
- number of sampled worlds;
- uncertainty/standard error;
- sampler identity;
- search configuration;
- teacher policy/model version.

Do not store only a hard winner.

---

## 11.1 Proposed loop

```text
self-play actor
    ↓
collect difficult / consequential states
    ↓
search teacher
    ↓
confirm close decisions on independent worlds
    ↓
distil
    ↓
resume self-play
    ↓
repeat only while independent strength improves
```

This is the preferred way to exploit W1024-level computation without paying it on every self-play decision.

---

# 12. Architecture scaling

Do not immediately solve every problem with a larger actor.

Suggested order:

```text
actor width 256
→ 512
→ 768/1024 only after validated learning saturation
```

Keep the training method fixed during capacity tests.

The critic deserves earlier scaling because:

- it is training-only;
- it receives full state;
- higher capacity may improve advantage estimation without deployment cost.

Example initial capacity study:

```text
Actor:
    256 vs 512

Critic:
    512 vs 1024
    3–6 residual blocks
```

Do not simultaneously change:

- architecture;
- reward;
- self-play population;
- Sooli model;
- optimiser;
- search teacher.

Otherwise attribution becomes impossible.

---

# 13. Sooli and other simulator-transfer issues

Current learned policy does not fully learn the complete Sooli decision process.

This is a possible ceiling.

Do not immediately rebuild the whole pipeline around Sooli.

Instead measure:

1. frequency of Sooli in important match states;
2. outcome sensitivity to Sooli decisions;
3. discrepancy between native approximation and authoritative engine;
4. strength delta if exact Sooli handling is used.

If Sooli contributes materially to remaining error, make it learnable or improve the simulator.

If not, spend compute elsewhere.

---

# 14. Experimental programme

## Stage 0 — Freeze reality

Before new learning:

- obtain final completed large-run result;
- define exactly what “100M” counted;
- record policy hashes;
- record native binary hash;
- record engine hash;
- record config;
- record sampler identity;
- record Sooli configuration;
- record whether branch sharing/weighted recording was enabled;
- preserve every selected and failed checkpoint.

Run an independent authoritative-engine confirmation of the strongest SP1 checkpoint.

Do not select on this confirmation set.

---

## Stage 1 — Diagnose SP1

On fixed development panels:

1. base actor vs Q composite;
2. Q composite vs distilled actor;
3. fresh labels vs replay labels;
4. current-policy replay vs mixed-policy replay;
5. native vs authoritative engine;
6. phase/contract/score breakdown;
7. changed-decision regret;
8. action-gap calibration.

This determines whether more SP1 scaling is rational.

---

## Stage 2 — Build the policy-gradient family

Minimum controlled variants:

### A. PPO-V

```text
actor: observation-only
critic: privileged V(s)
advantage: GAE
```

### B. VRPO-Q

```text
actor: observation-only
critic: privileged Q(s,a)
advantage: Q-boosting / Expected-SARSA-lambda
```

Warm-start both from the same actor.

Use the same:

- data-generation budget;
- actor architecture;
- reward;
- self-play opponent distribution;
- optimiser family where possible;
- evaluation stream.

This isolates the advantage-estimation mechanism.

---

## Stage 3 — Matched-compute comparison

Primary contestants:

1. repaired SP1;
2. PPO-V;
3. VRPO-Q.

Primary comparison should be **matched end-to-end compute**, not simply equal deal count.

Track separately:

- original independent deals;
- recorded decisions;
- branch completions;
- environment actions;
- optimiser updates;
- replay reuse;
- teacher/search calls;
- CPU core-hours;
- accelerator time;
- wall time;
- peak memory;
- actor inference p50/p95 latency.

A method that uses half the simulations but 10× the training compute is not “half the cost”.

---

## Stage 4 — Match-objective alignment

Take the strongest two algorithms.

Compare:

1. historical fixed match-equity reward;
2. recalibrated match-value reward;
3. direct terminal match reward with bootstrapping;
4. hybrid dense + terminal objective if needed.

The outcome is complete-match strength.

---

## Stage 5 — Search integration

For each finalist:

- W128 rollout factorial;
- same-world comparison;
- same-latency comparison;
- opponent-model controls.

Promote only configurations that transfer.

---

## Stage 6 — Selective ExIt/search distillation

Use the strongest search only on selected high-information states.

Measure:

```text
confirmed independent strength gained
--------------------------------------
teacher CPU/GPU/wall cost
```

Stop if useful gain per compute collapses.

---

## Stage 7 — Population hardening

Only if cross-play justifies it:

- historical checkpoint mixture;
- independent seeds;
- partner diversity;
- explicit best responses;
- eventually PSRO if genuine cycles remain.

Do not pay league-training cost before a league problem exists.

---

## Stage 8 — Scale

Only now increase:

- total self-play volume;
- actor size;
- critic size;
- number of seeds;
- search teacher budget.

Scale the recipe that has already demonstrated a positive learning curve.

---

# 15. Evaluation hierarchy

Do not allow one proxy to become the entire project objective.

## Level 1 — learning diagnostics

- critic/Q loss;
- R²;
- policy entropy;
- KL;
- clip fraction;
- value/Q calibration;
- action gap;
- gradient statistics.

Useful for debugging only.

---

## Level 2 — standalone policy strength

Against:

- clone;
- previous checkpoint;
- strong historical checkpoints;
- independent seed;
- fixed panel.

Use fresh independent games.

---

## Level 3 — cross-play

Measure:

- policy cycles;
- mixed partners;
- convention dependence;
- opponent dependence.

---

## Level 4 — search integration

Measure:

- W128;
- W1024/adaptive;
- same worlds;
- same latency.

---

## Level 5 — complete-match performance

This is the most important endpoint.

Use:

- complementary team/seat assignments;
- independent original match seeds;
- clustered inference at the correct independent unit;
- confidence intervals;
- prespecified confirmation sets.

A policy that gains per-deal equity but fails to gain complete-match win probability has not achieved the final objective.

---

# 16. Seed policy

For early engineering pilots:

```text
1 seed is acceptable
```

For method selection:

```text
>= 3 independent training seeds if compute permits
```

For final claims:

- report seed variability;
- do not report only the best seed;
- keep the selected best deployed checkpoint separate from the scientific average effect.

---

# 17. Stop rules

Stop or pause a recipe when one of the following is demonstrated:

### Harm

A sufficiently precise independent evaluation shows a meaningful negative effect.

### Excluded useful gain

The confidence interval becomes narrow enough to exclude the minimum useful improvement.

### Learning saturation

Strength improvement per unit compute has flattened over multiple independent checkpoints.

### Transfer failure

Native gain repeatedly disappears in authoritative engine or complete matches.

### Search incompatibility

Standalone gain cannot be converted into search/deployment gain despite controlled rollout-model tests.

Do **not** label these as algorithm failure:

- crashed training;
- illegal sampler;
- underpowered evaluation;
- broken reward sign;
- resource exhaustion;
- one small null pilot;
- evaluation leakage.

---

# 18. Compute allocation recommendation

Initial research effort allocation:

```text
45%  privileged-Q VRPO
25%  repaired / continued SP1
15%  evaluation + match-objective calibration
10%  selective search / ExIt integration
 5%  population / cross-play work
```

This allocation should change if evidence changes.

Examples:

### If SP1 continues climbing strongly

Shift more compute to:

- repaired SP1;
- match calibration;
- search integration.

### If SP1 Q ranking saturates but VRPO learns

Shift heavily to VRPO.

### If VRPO actor improves standalone but search gets worse

Invest in:

- rollout-model separation;
- selective search;
- opponent modelling controls.

### If all homogeneous self-play methods cycle

Increase population training.

---

# 19. Highest-value ablations

In approximate priority order:

1. **SP1 vs VRPO at matched end-to-end compute**
2. **VRPO-Q vs ordinary PPO-V**
3. **SP1 composite Q vs SP1 distilled actor**
4. **current-policy labels vs mixed-version replay**
5. **fixed equity table vs recalibrated match value**
6. **greedy vs stochastic VRPO deployment**
7. **learned own-team rollout vs learned opponent rollout**
8. **actor 256 vs 512**
9. **critic 512 vs 1024**
10. **current-only vs small historical opponent mixture**
11. **uniform self-play data vs selective search distillation**

Do not run all combinations factorially unless evidence justifies the compute.

---

# 20. Implementation correctness tests before long VRPO runs

Before performance testing, construct deterministic unit/integration tests for:

- team reward sign;
- acting-seat perspective;
- terminal reward;
- match reset;
- deal reset;
- legal masked probabilities sum to 1;
- illegal actions have zero probability;
- stored old log-prob reproduces behaviour policy;
- policy-version tracking;
- critic sees privileged information;
- actor provably does not;
- Expected-SARSA policy expectation;
- lambda return;
- bootstrapping at terminal states;
- Sooli transitions;
- bidding legality;
- RAMI/NOLO reward orientation.

Any error here can produce a convincing but meaningless learning curve.

---

# 21. Information leakage audit

This deserves a formal checklist.

At actor inference, inspect the actual tensor.

Verify that no feature can encode:

- opponent cards;
- partner cards;
- hidden Sooli information;
- true sampled determinisation identity;
- critic latent state;
- full-state action value;
- future event information.

The critic may contain all of these where appropriate during training.

Shared network code is acceptable. Shared hidden information at runtime is not.

---

# 22. Long-term target system

The strongest plausible development path is:

```text
behavioural clone / SP1 checkpoint
            ↓
privileged-Q VRPO self-play
            ↓
contemporary match-value optimisation
            ↓
strong observation-only stochastic actor
            ↓
selective high-quality search distillation
            ↓
cross-play / population hardening when needed
            ↓
search-integrated final bot
            ↓
authoritative-engine complete-match confirmation
```

Expanded:

\[
\boxed{
\text{BC/SP1 warm start}
\rightarrow
\text{VRPO self-play}
\rightarrow
\text{match alignment}
\rightarrow
\text{selective ExIt}
\rightarrow
\text{population hardening}
\rightarrow
\text{search-integrated deployment}
}
\]

This is the current preferred route.

It is not a claim that VRPO has already been shown to be best for Tuppi.

---

# 23. What not to do

Do not:

- interpret low Q R² as proof SP1 failed;
- abandon a +0.0059 screening checkpoint before proper confirmation;
- run another arbitrary 100M block without identifying what should improve;
- copy PPO/entropy coefficients from another card game blindly;
- let privileged critic information leak into actor inference;
- confuse full-state Q labels with information-set optimal action values;
- replace all rollout models with the newest actor without factorial testing;
- start full PSRO before demonstrating cycles;
- evaluate only against the immediately preceding checkpoint;
- choose the best checkpoint on the same data used for final confirmation;
- optimise only per-deal equity while ignoring complete matches;
- report one seed as evidence of algorithm superiority;
- count only simulator deals while ignoring branch/search/training compute;
- call an infrastructure failure an algorithmic negative result.

---

# 24. Immediate next execution sequence

If taking over the project now, execute in this order.

### Task 1 — Freeze SP1

Produce a manifest containing:

```text
checkpoint
git hashes
native binary hash
engine hash
config
sampler
self-play accounting units
runtime flags
final run metrics
```

### Task 2 — Confirm best SP1 independently

Use:

- authoritative engine;
- fresh seeds/deals;
- complementary seats/teams;
- complete-match endpoint as well as per-deal metrics.

### Task 3 — Repair SP1 scientific instrumentation

Add:

- parent IDs;
- policy versions;
- clean splits;
- composite-policy evaluation;
- changed-decision regret.

### Task 4 — Implement PPO-V reference

This validates the actor/critic/on-policy infrastructure.

### Task 5 — Implement VRPO-Q

Follow the primary algorithm closely.

### Task 6 — Tiny correctness run

Purpose:

- catch bugs;
- check signs;
- inspect entropy/KL;
- verify critic learning;
- confirm no illegal actions.

Do not make strength conclusions.

### Task 7 — Medium matched-compute pilot

Compare:

```text
SP1
PPO-V
VRPO-Q
```

Use common initial policy and evaluation streams.

### Task 8 — Select the strongest learning mechanism

Use independent strength and compute efficiency, not training loss.

### Task 9 — Align to match value

Recalibrate dense reward using contemporary complete matches.

### Task 10 — Integrate with search

Run own-team/opponent-rollout factorial.

### Task 11 — Selective teacher loop

Spend W1024/search compute only where it changes important decisions.

### Task 12 — Scale

Only after the above produces a demonstrably improving recipe.

---

# 25. Decision table

| Observation | Response |
|---|---|
| SP1 keeps improving and confirms in matches | Preserve and scale SP1; still run bounded VRPO comparison |
| SP1 composite improves but distilled actor does not | Fix distillation, not simulation volume |
| SP1 Q rankings remain noisy and saturation appears | Shift toward VRPO |
| PPO-V improves but VRPO-Q does not | Debug VRPO estimator/critic before rejecting policy gradients |
| VRPO-Q clearly beats PPO-V | Use VRPO as main learner |
| Standalone actor improves but search worsens | Separate own/opponent rollout models |
| Learned rollout helps own team only | Use asymmetric continuation adapter |
| Current-only self-play cycles | Add historical population |
| Homogeneous pair strong, mixed partner weak | Add partner-diversity training |
| Per-deal gain does not improve matches | Recalibrate match-value objective |
| Native gain disappears in authoritative engine | Fix simulator/reward/rules transfer before scaling |
| Search teacher gives high-value corrections | Expand selective distillation |
| Search teacher adds no independent strength | Stop buying more teacher labels |
| Larger actor adds no strength | Keep smaller deployed actor; spend capacity on critic/search |
| All methods plateau | Consider deeper game-theoretic methods only after bottlenecks are characterised |

---

# 26. Deferred methods

These remain research options, not first-line implementations:

- PSRO
- Deep CFR
- ReBeL
- Student of Games-style solver
- R-NaD / DeepNash-style regularised dynamics
- team-public-information conversion methods
- learned attacker / exploitability approximations
- reduced-deck exact solving

They become rational when a specific measured failure calls for them.

Examples:

- persistent non-transitive cycles → PSRO;
- policy-gradient plateau with evidence of strategic exploitation → regret/game-theoretic methods;
- determinisation pathology → public-belief/subgame methods;
- human-partner incompatibility → explicit cross-play/partner-diversity methods.

---

# 27. Primary external references

### VRPO / Q-boosting

Zhiyuan Fan, Gabriele Farina.  
**GAE Falls Short in Imperfect-Information Self-Play Reinforcement Learning.**  
2026.  
https://arxiv.org/abs/2605.19235

Key relevance:

- explains action-sampling variance in GAE under stochastic imperfect-information self-play;
- proposes centralised `Q(s,a)` critic;
- Expected-SARSA-style multi-step target;
- PPO-style on-policy actor;
- strongest direct methodological inspiration for the new Tuppi branch.

### Policy-gradient comparison in imperfect-information games

**Reevaluating Policy Gradient Methods for Imperfect-Information Games.**  
https://arxiv.org/abs/2502.08938

Key relevance:

- large comparative study;
- generic policy-gradient methods remain strong baselines;
- specialised FP/DO/CFR-derived deep-RL methods do not automatically dominate.

### Four-player card-game PPO evidence

Aalok Patwa.  
**Self-Play Reinforcement Learning under Imperfect Information in Big 2.**  
2026.  
https://arxiv.org/abs/2605.28863

Key relevance:

- four-player hidden-information card game;
- PPO compared with value-based alternatives;
- moderate entropy useful;
- current-policy self-play useful under finite budget.

### Existing project references retained from previous handoff

- PerfectDou: https://arxiv.org/abs/2203.16406
- MAPPO: https://arxiv.org/abs/2103.01955
- Expert Iteration: https://arxiv.org/abs/1705.08439
- Other-Play: https://arxiv.org/abs/2003.02979
- Fictitious Co-Play: https://arxiv.org/abs/2110.08176
- PSRO: https://arxiv.org/abs/1711.00832
- ReBeL: https://arxiv.org/abs/2007.13544
- Deep CFR: https://proceedings.mlr.press/v97/brown19b.html
- R-NaD / DeepNash: https://arxiv.org/abs/2206.15378
- Student of Games: https://pmc.ncbi.nlm.nih.gov/articles/PMC10651118/
- team-public-information conversion: https://arxiv.org/abs/2206.09161

---

# 28. Instructions to the next LLM/engineer

Use this packet as a dated research plan, not as evidence that the proposed methods already work.

Your job is to maximise actual Tuppi strength.

You must:

1. Preserve the verified SP1 evidence.
2. Refresh final run results before making a scale decision.
3. Keep evidence, inference and hypotheses separate.
4. Implement legal observation-only deployment actors.
5. Treat privileged information as critic-only.
6. Compare repaired SP1 and VRPO fairly.
7. Price total compute, not just generated deals.
8. Evaluate complete matches and search transfer.
9. Preserve failed experiments as negative evidence.
10. Introduce complexity only when a measured bottleneck justifies it.

The highest-priority new hypothesis is:

> **A warm-started observation-only stochastic actor trained by VRPO/Q-boosting with a full-information training-only Q critic will produce stronger and/or more compute-efficient self-play improvement than the current SP1 branch-regression/distillation pipeline.**

The highest-priority existing competing hypothesis is:

> **SP1 is already on a productive improvement trajectory, and correcting its split/replay/distillation/evaluation weaknesses may outperform replacing it.**

These hypotheses should be tested directly.

The desired final result is not “a successful RL experiment”.

It is:

> **the strongest validated Tuppi bot that can be produced, with the self-play system feeding a deployment configuration that wins the actual game.**
