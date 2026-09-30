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
