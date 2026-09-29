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
