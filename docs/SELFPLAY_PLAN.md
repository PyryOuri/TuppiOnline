# Self-play learning programme SP1 (pre-registered 2026-09-29)

The owner asked for a self-play programme at a scale the earlier attempts
never reached, with the GPU training optimised and the self-play engine's
three remaining levers done. Everything below was fixed before any training
run.

## Why the earlier attempts failed, and what changes

| Attempt (docs/STATUS.md) | Failure | SP1's answer |
| --- | --- | --- |
| `dmc1`, plain Monte Carlo from scratch, 1.6M deals | The target variance is dominated by the hidden cards, so the net learned state value, not card choice | Paired branch targets: every legal action is played out from the same full state, so differences carry no hidden-card noise |
| `pair1`, branching from scratch | Under a near-random continuation, one changed card sends the deal down an unrelated path, so differences measure chaos | Start from the behaviour clone (incumbent-level play), so continuations are sensible from iteration 0 |
| `pi1`, greedy on learned Q over a blueprint | Taking the best of 13-26 noisy estimates over-declares RAMI (84% vs 75%) and loses 0.020 | Conservative improvement: leave the current policy's action only when the learned advantage exceeds a margin; distil the result into one policy net |
| All of them | Python-driven, about 500 deals/s plus 900 branches/s | Native actor and labeller, about 100x the labelled decisions per second |

## The loop (approximate policy iteration)

Iteration k, current policy pi_k (a network; pi_0 = `runs/bc_small.pt`):

1. **States.** Self-play games under project_target_v3, with random start
   scores. All four seats play pi_k, sooli decisions come from the heuristics
   with the fast offer model, and there is no solver tail (the policy plays
   every trick). At random unforced decisions (bids and card play) the full
   state is recorded. For state diversity, a small share of non-recorded
   moves is played uniformly at random.
2. **Labels.** From each recorded full state, every legal action is played
   out to the end of the deal with pi_k on all seats. Q^pi_k(s, a) is the
   acting team's match-equity change. The same hidden cards are shared by all
   of a state's actions.
3. **Q net.** Q_theta(observation, a) is regressed on those labels: the level
   of all legal actions plus the centred differences (advantages), as in
   `train2.py`. This uses the observation only, so it learns
   E[Q | observation] under self-play's own distribution of hidden cards. It
   is warm-started from the previous iteration.
4. **Policy.** pi_{k+1}(obs) = argmax_a [Q_theta(obs, a) + margin * 1(a =
   pi_k(obs))]. This composite is distilled into one policy net on the
   iteration's states (cross-entropy) and becomes the next iteration's actor
   and rollout policy.
5. **Quick check.** A native duplicate evaluation (`native_eval`) of
   pi_{k+1} against pi_0 (the clone, at parity with the incumbent) and
   against pi_k.

## Criteria (fixed in advance)

**Measurement.** Iteration checks use `native_eval.duplicate` on 20,000 base
deals (network against network, 8 games per base deal, seeds unused in
training). Claims against the incumbent use `tuppi_ai.evaluate` in the
authoritative engine. The screening protocol applies (W=128 first).

- **Continue** while the best pi_k improves on pi_0 by more than its 95%
  interval every 3 iterations.
- **Kill SP1** if, within 24 hours of loop wall time, no pi_k beats the clone
  by at least **+0.005** equity per deal without search. For scale:
  expert iteration round 1 reached +0.0027; the search bot is +0.015.
- **Product relevance.** It only counts if a passing policy also helps the
  search bot. `search:<pi_k>` (as rollout policy) against the current best
  agent at W=128 on 512 fresh deals must pass non-inferiority (lower 95%
  bound above -0.0010), with a gain of +0.0020 claimed only if the lower
  bound is above 0. Earlier stronger rollout nets did not help, because the
  rollouts must model the incumbent opponent. So the programme also reports
  the policy against a panel: the clone, `xi1_small`, `bc_v1` and earlier
  iterations.

## Engineering tasks, measured separately

- **Native actor and labeller** (`tc_selfplay_states`, `tc_branch_values`).
- **GPU learner.** The dataset lives on the GPU in packed bits and is
  unpacked on the device, with fused AdamW. Batch size and mixed precision
  are chosen by measured rows per second at equal loss.
- **Engine levers:**
  1. Incremental first layer in self-play rollouts (inexact; logits within
     float tolerance, argmax agreement reported).
  2. Concurrent engine batches to fill idle cores.
  3. No solver tail.

  Each is measured in deals per second on the same workload.

## SP2 (pre-registered 2026-09-30, before its run)

**What SP1's diagnostics showed** (`docs/SP1_MANIFEST.json`, `docs/STATUS.md`):
- SP1 plateaued because its Q net stopped finding improvements beyond label
  noise. At iteration 43, the composite policy's changed decisions gain
  +0.0005 ± 0.0021 per change on fresh labels.
- Distillation costs at most about 0.0005 (composite minus distilled, against
  the incumbent: +0.00048 [-0.00001, +0.00096]).
- Clean held-out R^2 on fresh deals is 0.051, the same as logged, so the leak
  between rows of one deal was negligible.

**SP2 therefore targets advantage estimation and label efficiency**, starting
from SP1's final policy:
- **The Q net:** 768x4 instead of 256x2, trained from scratch with a zero
  head. It never runs in rollouts, so it costs GPU time only.
- **Labels:** one rollout per run of rank-equivalent cards (95.7% identical
  labels) and importance-weighted recording by measured non-inert rate.
- **Held-out rows:** every 10th self-play batch (whole deals).
- **Unchanged from SP1:** 2M states per iteration, replay of 3 iterations,
  margin 0.006, gate R^2 >= 0.01, 2,000 Q steps and 1,000 policy steps per
  iteration, no solver tail, fast sooli offers.

**Criteria:**
- **The result** is the final iteration's distilled policy. No checkpoint is
  selected on evaluation data; the composite is reported alongside.
- **Loop budget:** at most 8 h of wall time. Stop early after iteration 12 if
  the native check against SP1's final policy has not exceeded its 95%
  interval in any of the last 8 iterations.
- **Primary test:** authoritative engine, no search, 1,024 fresh deals (seed
  sp2-confirm-v1), paired against SP1's final policy on the same deals.
  - **Improvement:** at least +0.0020 with the lower bound above 0.
  - **Non-inferior:** the lower bound above -0.0010.
  - **Otherwise:** worse.
- **Product test**, only if it improves: search with SP2 rollouts against
  search with SP1 rollouts, W=128, 1,024 fresh deals, the same
  non-inferiority and gain rules.
- **Attribution:** SP2 changes the Q size and the labelling efficiency
  together. A gain is credited to the combination; separating them would be
  a follow-up ablation.

**Deviation (recorded 2026-09-30 08:10, before the restarted run).**
- **Failure.** SP2's first iteration regressed badly: -0.0083 against SP1's
  final policy (vs the clone +0.0031, from +0.0126). The fresh 768x4 Q net
  (held-out R^2 0.022) passed the R^2 gate (0.01), and its noise beat the
  0.006 margin on 24.7% of decisions. That was harmless from the clone in SP1
  but harmful from a strong policy. The failed run is kept in
  `runs/selfplay/sp2_failed_iter1`.
- **Repair: a held-out improvement gate.** On the held-out deals, measure the
  composite's one-step gain: label of its action minus label of pi_k's
  action, under pi_k continuations, importance-weighted. The policy changes
  only if that gain exceeds 2 standard errors, for the best margin of the
  grid 0.006, 0.01, 0.02, 0.04 (chosen on the held-out deals, never on
  evaluation data).
  - Checked from the clone: margin 0.003 changed 45% of decisions for
    -0.00018; the gate chose 0.02 (+0.00021 ± 0.00010).
- **SP2 restarts with this gate.** Every other setting, the criteria and the
  8 h budget are unchanged, counted from the restart.

## SP2b (pre-registered 2026-09-30, before its run; used only if SP2 stops without improvement)

**The problem SP2 showed.** A 768x4 Q net trained from scratch climbs
slowly: held-out R^2 was 0.021, 0.023, 0.028, 0.029 and 0.029 over
iterations 1-5. It overfits the noisy labels within about 200 steps per
iteration, and its proposed changes lose on held-out deals at every margin,
so the gate keeps SP1's policy.

**The repair.** The same as SP2 except:
- the 768x4 Q net is warm-started by distilling SP1's final Q net
  (`runs/selfplay/sp1/q_latest.pt`, 3,000 steps on the first iteration's
  replay). The smoke test reached held-out R^2 0.041 after 600 steps.
- Q weight decay is 1e-4 instead of 1e-5.

**Hypothesis.** Starting from SP1's advantage estimates, the larger net can
learn beyond them as data accumulates, and open the gate.

**Criteria:** those of SP2, with the same primary test (seed sp2-confirm-v1).
- **Budget:** at most 6 h.
- **Stop** after iteration 10 if the gate has not opened in any of the last
  8 iterations.
- If SP2b also plateaus at SP1's level, that is the conclusion: a larger Q
  net with true-world labels does not break SP1's plateau. The next lever
  then is lower-noise labels (averaged over sampled worlds, or search
  distillation), not Q capacity.

## Live rollout roles: confirmation at W=1024 (pre-registered 2026-09-30 11:00)

**The candidate:** the live configuration (W=1024, E7 adaptive bids, 6-trick
tail) with the SP1 policy (`models/sp1_policy_043.pt`) as the rollout model
of the searching team's own seats, and the clone for the opponents.

**The screen that motivated it:** W=128, 1,024 deals: +0.00132 [+0.00041,
+0.00222] against clone/clone rollouts.

**The test:**
- 512 deals, seed perf-e7-v1, rs=1, paired with the stored reference arm
  (the same live configuration with clone rollouts,
  `b_e7.json`: +0.01608).
- Those deals were used for E7, VN1 and VN2 tests, never for anything
  involving SP1.

**Deploy if:** the lower 95% bound of variant minus reference is above
-0.0010 **and** the point estimate is above 0. **Otherwise** it stays at
W=128 evidence and is not deployed.

## VRPO1 (pre-registered 2026-09-30 23:15, before its run)

**Method** (`tuppi_ai/vrpo.py`; Fan and Farina 2026, arXiv 2605.19235):
- PPO on the SP1 policy.
- The advantages are Q-boosted and come from a privileged critic Q(s, a).
  - The critic is a 512x4 network, trained from scratch.
  - Its input is the actor's observation plus the three hidden hands.
  - V(s) = sum_a pi(a|o) Q(s, a).
- An Expected SARSA(lambda) trace runs over each deal, with the sign flipped
  whenever the other team acts.
  - Q_target = Q + G and A = Q - V + G.
  - lambda = 0.95, gamma = 1.
- Why it could beat SP1's approach: the critic sees the full state, so it
  can learn what the hidden cards contribute, which the observation-only Q
  net cannot. The noise that stopped SP2 and SP2b is then explained rather
  than averaged away.

**Settings:**
- 16,384 sampled self-play deals per iteration (temperature 1); every
  network decision of all four seats is a row, about 0.9M rows.
- 4 critic epochs and 4 actor epochs per batch; minibatch 16,384; PPO clip
  0.2.
- The actor epochs stop early if the mean KL exceeds 0.02.
- Entropy bonus 0.001; actor learning rate 3e-5, critic 3e-4.
- The first 6 iterations train the critic only.
- Sooli phases are played by the heuristics with the fast offer model.
- Every 3rd iteration, a native duplicate check (8,192 base deals, greedy)
  runs against SP1's final policy and the clone, plus a sampled-play check
  against SP1.

**Checked before the run:**
- The trace equals a per-deal reference loop.
- lambda = 1 with a zero critic gives the Monte Carlo return.
- In the trajectories, the behaviour log-probabilities equal the network's
  softmax, the legal masks contain the actions, and the hidden hands are
  disjoint (`tests/test_vrpo.py`).
- SP1's sampled play at temperature 1 has entropy 0.13 nats per decision.

**Criteria:**
- **The result** is the final iteration's actor, played greedily. No
  checkpoint is selected on evaluation data; the best checkpoint is only
  reported.
- **Budget:** at most 5 h of wall time.
- **Stop early** for divergence if three consecutive checks against SP1 have
  an upper bound below 0.
- **Stop early** for a plateau after iteration 60 if no check in the last 30
  iterations had its lower bound above 0.
- **Primary test:** authoritative engine, no search, 1,024 fresh deals (seed
  vrpo-confirm-v1), paired against SP1's final policy on the same deals.
  - **Improvement:** at least +0.0020 with the lower bound above 0.
  - **Non-inferior:** the lower bound above -0.0010.
  - **Otherwise:** worse.
- **Product test**, only if it improves: search with VRPO own-team rollouts
  against search with SP1 own-team rollouts, W=128, 1,024 fresh deals.

## SP3: search labels (pre-registered 2026-09-30 23:31, before its run)

**Why.** SP2 and SP2b showed that single true-world labels limit SP1's
policy iteration, not Q capacity. SP3 trains Q on search results instead.

**Labels.** Each recorded state gets labels from 16 worlds with
`tc_world_values`: the true world plus 15 worlds drawn by the search's
sampler, which honours the showing-fallback restrictions (B0-S1) in
self-play.
- In each world, every legal action is played out with pi_k, and the last 6
  tricks are solved exactly, as the live search does.
- The label is the mean over the 16 worlds: a W=16 search value.
- The true-world value is stored separately.

**Measured before the run** (40k states, from SP1, not evaluation data):

| Labels | Held-out advantage R^2 after 200 Q steps | Label rate |
| --- | --- | --- |
| 16 worlds, 6-trick tail | 0.18 | 990 states/s |
| 16 worlds, no tail | 0.08 | 860 states/s |
| SP1 (single true world) | about 0.05 at best | |

**The gate stays on the true-world labels.** The sampler ignores what play
reveals about the hidden cards, so a Q net fitted to sampled-world values
can prefer moves that fail under the real distribution of hands. The
composite's one-step gain is measured on the held-out states' true-world
labels (which include the solver tail), as in SP2.

**Settings:**
- Start from SP1's final policy. The Q net has the policy's shape and is
  warm-started from it, with a zero head.
- 1M states per iteration. Every 5th self-play batch is held out (about
  20%), for a sharper gate.
- Margin grid 0.006, 0.01, 0.02, 0.04, gate z = 2, replay of 3 iterations.
- 2,000 Q steps with early stopping, 1,000 policy steps.
- Label sharing and importance weighting are on, as in SP2.

**Criteria:**
- **The result** is the final iteration's distilled policy. No checkpoint is
  selected on evaluation data.
- **Budget:** at most 6 h of wall time. VRPO1 runs at the same time on the
  same machine.
- **Stop** after iteration 8 if the gate has not opened in any of the last 6
  iterations.
- **Primary test:** authoritative engine, no search, 1,024 fresh deals (seed
  sp3-confirm-v1), paired against SP1's final policy.
  - **Improvement:** at least +0.0020 with the lower bound above 0.
  - **Non-inferior:** the lower bound above -0.0010.
- **Product test**, only if it improves: search with SP3 own-team rollouts
  against search with SP1 own-team rollouts (the live setting), W=128, 1,024
  fresh deals.

## Sampler fix B0-S1: strength screen (pre-registered 2026-09-30 23:33)

**The fix.** When a showing fallback is on record, the search's world
sampler honours what it implies about the original hands (`sf=1`,
`tc_set_showing_fix`). Before the fix, 69% of the worlds drawn at such
decisions were illegal. Such decisions are 2.9% of card-play decisions.

**The test** (W=128, the live rollout setting):
- 1,024 deals, seed sp1-search-v2, rs=1, paired with the stored arm without
  the fix (`fact_ownSP_oppCL.json`: +0.01643).
- Those deals were used for the rollout-role grid, never for anything
  involving the sampler.

**Adopt if:** the lower bound of variant minus reference is above -0.0010.
It is a correctness fix, so non-inferiority suffices at W=128, as for exact
changes that alter moves. Adoption means the live default is switched on
after this screen.

## VRPO2: continuation (pre-registered 2026-10-01 02:05, before VRPO1 ended; run only if VRPO1 passes its improvement test)

**Why.** VRPO1's native check against SP1 was still climbing near the end of
its budget (+0.0039 at iteration 276), with a stable KL and entropy.

**The change.** The same settings as VRPO1, starting from VRPO1's final
actor and its critic (`critic_init`), with no critic-only warm-up.
- The KL, clip and learning rates are unchanged.
- The reference of the native checks stays SP1.

**Criteria:**
- **The result** is the final actor.
- **Budget:** at most 6 h.
- **Stop early** for divergence (three consecutive checks below VRPO1's
  final result, measured as vs SP1 upper bound below VRPO1's final vs SP1
  point) or for a plateau: after iteration 150, no check in the last 90
  iterations beyond the best earlier check by more than its interval.
- **Primary test:** authoritative engine, no search, 1,024 fresh deals (seed
  vrpo2-confirm-v1), paired against VRPO1's final actor.
  - **Improvement:** at least +0.0010 with the lower bound above 0. The bar
    is lower than SP2's +0.0020, because this is a continuation.

## NOLO solver tail of 7 tricks (pre-registered 2026-10-01 05:35; item 4)

**Why.** The no-search policies lose 0.005-0.008 per decision against the
robust double-dummy action in NOLO with 4-6 tricks left; SP1 and VRPO1 both
do (`tools/dd_consensus.py`). In the search, those tricks are reached by the
rollout policy before the 6-trick exact tail. NOLO solves are fast at 7
tricks (median 0.94 ms).

**The candidate.** The rollouts' exact tail starts one trick earlier in NOLO
contracts (`ddn=1`, `tc_set_dd_extra_nolo`). RAMI is unchanged. With the
switch off, the move fingerprint is unchanged.

**The screen** (W=128, live rollout setting: own team SP1, opponents clone):
- 1,024 deals, seed vrpo1-search-v1, rs=1, paired with that seed's arm
  without the switch.
- That arm is the SP1 reference of the VRPO1 product test, so the two
  variants share their reference.

**Criteria:**
- **Pass:** the point estimate is above 0, the lower bound is above -0.0010,
  and the CPU per deal is at most 1.5x.
- A pass goes on to a W=1024 confirmation before live use (same rule as the
  rollout roles).
- A gain is claimed only if the lower bound is above 0.

## VRPO1 own-team rollouts: W=1024 confirmation (pre-registered 2026-10-01 09:10)

**The screen** (W=128, 1,024 deals, seed vrpo1-search-v1): search with VRPO1
own-team rollouts against search with SP1 own-team rollouts:
+0.00065 [-0.00009, +0.00138], with equal CPU. Non-inferior; no gain
claimed.

**The test:**
- The live configuration (W=1024, E7, 6-trick tail) with VRPO1
  (`models/vrpo1_actor_0504.pt`) as the own-team rollout model.
- 512 deals, seed perf-e7-v1, rs=1, paired with the stored arm with SP1
  own-team rollouts (`b_teamsp1.json`, +0.01666).
- Neither arm uses the sampler fix, so they differ only in the rollout model.
- Those deals were never used for anything involving VRPO.

**Deploy if:** the lower bound is above -0.0010 and the point estimate is
above 0 (the same rule as SP1's rollouts). It would be deployed together
with the sampler fix, which is already live.

## Policy-anchored search (pre-registered 2026-10-01 09:25)

**What motivated it.** On the deals of seed vrpo1-search-v1, VRPO1 without
search scored +0.01756. Search (W=128, VRPO1 own-team rollouts) scored
+0.01689: search minus policy -0.00067 [-0.00195, +0.00062]. At W=128 the
determinised search no longer improves on the policy.

**The candidate.** The same search, but the agent keeps VRPO1's action unless
the searched value of another action exceeds it by more than 0.003 equity
(`keep=0.003:bp=models/vrpo1_actor_0504.pt`). It applies at every searched
decision (bids and card play).

**The test:** W=128, the same 1,024 deals (seed vrpo1-search-v1, rs=1).
- **Primary:** against the plain search arm (`s_vrpo1.json`).
- **Secondary:** against VRPO1 without search (`n_vrpo1.json`).
- The margin was chosen before any hybrid result. It is not tuned on these
  deals; a second margin would need fresh deals.

**Pass:** the primary lower bound is above -0.0010 and the point estimate is
above 0. A gain is claimed only if the lower bound is above 0. A pass goes
to W=1024 before live use.

## VRPO3: a 512x4 actor (pre-registered 2026-10-01 10:47)

**Why.** VRPO2 added only +0.00066 over VRPO1 (not confirmed), although
its native check kept creeping up. The 256x2 actor (0.8M parameters) looks
near its capacity. The critic already explains 0.87-0.88 of the variance.

**The start.**
- VRPO2's actor (`models/vrpo2_actor_0447.pt`) is distilled into a 512x4
  net (3.2M parameters) with `tools/distil_policy.py`: 24 rounds of 16,384
  self-play deals, KL to the teacher's softmax.
- **Condition:** the native duplicate check of student against teacher
  (8,192 base deals) must have its lower bound above -0.0010. Otherwise the
  distillation is extended (same tool, more rounds) before VRPO3 starts.

**The run.**
- VRPO with the student as the actor and VRPO2's critic as a warm start,
  with 2 critic-only warm-up iterations.
- Every other setting as in VRPO1; the reference of the native checks is
  VRPO2's actor.

**Criteria:**
- **The result** is the final actor.
- **Budget:** at most 8 h.
- **Stop early** for a plateau: after iteration 150, no check in the last 90
  iterations beyond the best earlier check by more than its interval.
- **Primary test:** no search, 1,024 fresh deals (seed vrpo3-confirm-v1),
  paired against VRPO2's actor.
  - **Improvement:** at least +0.0010 with the lower bound above 0.
- **Attribution:** a gain is credited to the larger actor plus continued
  training. VRPO2's own continuation rate (about +0.0013 native per 450
  iterations) is the comparison point.

## Policy-anchored search: W=1024 confirmation (pre-registered 2026-10-01 11:55)

**The W=128 result** (the pre-registered screen above, seed vrpo1-search-v1):
- against plain search: **+0.00305 [+0.00234, +0.00377]**;
- against VRPO1 without search: +0.00239 [+0.00121, +0.00357].

It passes, with a gain claimed (the lower bound is above 0).

**A code change for W=1024.**
- `keep` used to bypass E7's adaptive bid search; now it is applied after
  it. When a dropped action is the policy's, its value is its mean over the
  worlds it saw.
- At W=128 nothing changes, because adaptive allocation is off at 128
  worlds or fewer.

**The test:**
- The live configuration (W=1024, E7, VRPO1 own-team rollouts) with
  `keep=0.003:bp=models/vrpo1_actor_0504.pt`.
- 512 deals, seed perf-e7-v1, rs=1, paired with the stored live arm without
  keep (`b_teamvrpo1.json`, +0.01707).
- Neither arm uses the sampler fix.
- CPU per deal is reported.

**Deploy if:** the lower bound is above -0.0010 and the point estimate is
above 0.

## Anchor margin grid (pre-registered 2026-10-01 13:35)

**The question.** Whether a different `keep` margin than the live 0.003 is
better. 0.003 was fixed without tuning.

**The test** (W=128, the live configuration otherwise: VRPO1 own-team
rollouts, sampler fix, anchor on VRPO1):
- Three arms: keep = 0.0015, 0.003 (the reference) and 0.006.
- 1,024 fresh deals, seed keep-grid-v1, rs=1.

**Adopt another margin only if** its paired difference against 0.003 has
its lower bound above 0. This is two comparisons, so no Holm correction is
applied, but the bar is a full gain, not non-inferiority. A change would be
confirmed at W=1024 before going live.

**Grid 1 result (seed keep-grid-v1), against keep 0.003 (+0.02007):**

| keep | Difference |
| --- | --- |
| 0.0015 | -0.00093 [-0.00154, -0.00032] |
| 0.006 | +0.00057 [-0.00010, +0.00123] |

Neither margin is adopted: 0.006's lower bound is not above 0.

## Anchor margin grid 2 (pre-registered 2026-10-01 14:55)

**Why.** Grid 1 is monotone, and the larger margin looks better.

**The test:** keep = 0.003 (the reference), 0.006 and 0.012, on 1,024 fresh
deals (seed keep-grid-v2), otherwise as grid 1.

**Decision:**
- 0.006 against 0.003 is pooled over grids 1 and 2 (2,048 deals);
  0.012 against 0.003 uses grid 2 only.
- Among the margins whose lower bound is above 0, the one with the highest
  point estimate is adopted.
- A change is confirmed at W=1024 before going live.

**Grid 2 result (seed keep-grid-v2), against keep 0.003 (+0.02011):**

| keep | Difference |
| --- | --- |
| 0.006 | +0.00076 [+0.00008, +0.00143] |
| 0.006, pooled with grid 1 (2,048 deals) | +0.00066 [+0.00019, +0.00113] |
| 0.012 | **+0.00116 [+0.00017, +0.00214]** (CPU +5%) |

By the rule, 0.012 is adopted, pending W=1024.

## keep 0.012 at W=1024 (pre-registered 2026-10-01 16:40)

**The test:**
- The live configuration (W=1024, E7, VRPO1 own-team rollouts) with
  keep=0.012.
- 512 deals, seed perf-e7-v1, rs=1, paired with the stored keep=0.003 arm
  (`b_keep.json`, +0.01974). Neither arm uses the sampler fix.

**Deploy if:** the lower bound is above -0.0010 and the point estimate is
above 0.

**Note.** The grid is still monotone at 0.012. Pure policy (an infinite
margin) was worse than keep=0.003 by 0.0024, so an optimum lies somewhere
above 0.012. A further grid (0.012 against 0.024) on fresh deals may follow.
