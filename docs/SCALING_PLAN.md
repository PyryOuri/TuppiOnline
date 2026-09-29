# Scaling self-play: bigger training sets (2026-09-29)

The owner asked for optimisation of the code and the methods with larger
training sets in mind. This file records what the measurements say, what was
built, and what is next, in order of expected value.

## Where the time and the signal go

SP1 spent **86.6M labelled states in 3.7 h**. Its policy scores **+0.0131
[+0.0119, +0.0143]** against the incumbent without search, and it plateaued
from about iteration 36.

| Stage (one 3M-state iteration) | Share of wall time |
| --- | ---: |
| labelling: every legal action played out | 71% |
| self-play: recording states | 17% |
| GPU training (Q net and policy) | 9% |
| evaluation | 3% |

**The binding limit is signal per label, not raw speed.**

- **Held-out advantage R^2 is 0.02-0.05.** Each label is the advantage in one
  deal with its true hidden cards. Only a small share of that is predictable
  from what the player sees, and the rest is noise the net must average away.
- **55% of recorded states are inert** (every action ties) and use 42% of the
  rollouts. Inertness rises from 35-50% early in the deal to 75-93% in the
  last three tricks.
- **Rank-equivalent cards get identical labels 95.7% of the time** and are 24%
  of card-play rollouts.

## Built and measured (branch sp/selfplay)

| Change | Effect | Exactness |
| --- | --- | --- |
| Native actor, labeller and duplicate evaluator | About 100x the labelled decisions per second of `train2.py`; evaluator 9k games/s | Evaluator checked: clone vs clone 0, xi1_small vs clone +0.0020 (vs incumbent +0.0025) |
| Fast sooli offers in self-play | 2.5x real-game self-play | Sooli rate 1.028% vs 1.039% |
| Incremental first layer | +14% labelling, +13% self-play | Labels identical on 56k states |
| Label sharing for rank-equivalent cards | +18% labelling | 0.195% of labels change |
| Importance-weighted recording | Up to 2x recording in informative classes, 0.25x in inert ones | Unbiased by design (rows carry weights) |
| Compact replay | 324 bytes per state instead of about 1,070 (3.3x) | Labels in fp16 (resolution about 2e-4 equity at 0.5) |
| Shards per iteration and `--resume` | Data survives crashes and can be reused by later runs | |
| Q net size independent of the policy net | A large Q costs GPU time only, not rollout time | |
| GPU learner: batch 16,384, fused AdamW, on-device unpacking, `torch.compile` | 0.95M training rows/s for 256x2 | Mixed precision gives nothing on this GPU |

**Tried and rejected:**
- Concurrent engine batches: no gain.
- Dropping the solver tail: labelling was 1.54x *slower* (kept only for
  learning correctness).
- A screen in front of the exact offer heuristic: cannot separate offers.

**Memory for a larger replay.** At 324 bytes per state, 10M states take
3.2 GB of the 36 GB of unified memory, so a 30M-state replay fits.

## Next, by expected value

1. **A larger Q net.** The `--q-width/--q-blocks` option is ready. The Q net
   is where R^2, and so the policy, is limited, and it never runs inside
   rollouts. A 768x4 Q net trains at about 150k rows/s, so 2,000 steps take
   about 3.5 minutes per iteration against about 5 minutes of labelling.
   Test: SP2 (768x4 Q, 256x2 policy), warm-started from SP1's final policy,
   judged by the same duplicate checks. Its data is new states only, because
   SP1's replay was never written to disk.
2. **Lower-noise labels.** Average each recorded state's labels over W worlds
   resampled from the actor's observation, as the search does, in addition
   to the true world. The cost is Wx labelling, the gain is less label noise,
   and the bias is a uniform belief instead of self-play's own. This decides
   how to spend a bigger budget: more states or more worlds per state. Test:
   fixed CPU budget, compare the resulting policies (W = 1 true world, W = 4,
   W = 16).
3. **A larger policy net.** Rollouts cost about the square of the width, so a
   768x4 policy labels about 9x slower. Worth it only once 1 and 2 are spent.
   A middle ground is 384x3.
4. **The solver-tail trade-off.** Labels with the exact 6-trick tail are 1.54x
   faster, but assume perfect endgame play by all four seats. Test with the
   same budget, a tail-labelled run against a no-tail run.
5. **Overlap of the GPU and the CPU.** Label iteration k+1 with pi_k while the
   GPU trains iteration k (a one-iteration-stale policy). That is worth about
   the GPU's share, 9% now and much more with a large Q net (1).
6. **GPU inference for part of the labelling.** A second labeller that runs
   the policy on the GPU in large batches. Estimated +30-50%; it needs a
   Python- or Metal-driven rollout loop, the most engineering of these
   items.
7. **Reuse shards across runs.** Pre-train a new Q net on accumulated shards
   before its first iteration. The labels are for older policies, so the
   older they are, the less they fit.
8. **Product integration.** Rollouts by the SP policy in the search bot
   (being screened), the SP policy as an instant bot for analysis tools, and
   expert iteration on top (search labels over the SP policy).
