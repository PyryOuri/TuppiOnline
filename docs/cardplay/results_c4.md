# C4 results: the signal is opening-lead-specific, and the opening lead is where the decision matters

**Status: COMPLETE. Outcome: OPENING_LEAD_SPECIFIC.**

Pre-registration: [hypotheses_c4.md](hypotheses_c4.md), committed as `0674854`
before `work/cardplay/c4_depth.py` existed. Run 2026-09-10, 256 observations,
780,416 rollouts, 818 s at ten workers (954 rollouts/s aggregate). Artifacts under
`/Users/pyryouri/Developer/tuppi_c4_depth_20260910/`.

## 1. Instrument gates — all three pass

| Gate | Result |
| --- | --- |
| **I1** `G_deploy <= G_foresight` at every depth | **pass** |
| **I2** depth 12 replicates C3 | **pass** — [+0.001073, +0.001716] overlaps C3's [+0.001226, +0.001717] |
| **I3** at least 128 feasible worlds per included decision | **pass** — 19 decisions correctly skipped |

I2 is the one that mattered. C3's hand-rolled dealing was replaced by
`tuppi_exact.UniformFeasibleSampler`, and depth 12 is the same estimand, so this
is a **cross-instrument replication on a fresh seed**: +0.001387 here against
C3's +0.001470 and C1's +0.001441. Three independent measurements of the same
quantity, two different samplers, within 6% of each other.

## 2. The result

| depth | usable | arms | on lead | `G_deploy` | 95% CI | `G_foresight` | clears δ |
| ---: | ---: | ---: | ---: | ---: | --- | ---: | :---: |
| **12** | 256 | 13.0 | 100% | **+0.001387** | [+0.001073, +0.001716] | 0.016371 | **yes** |
| 9 | 216 | 5.0 | 13% | +0.000398 | [+0.000209, +0.000613] | 0.003590 | no |
| 6 | 212 | 4.9 | 23% | +0.000634 | [+0.000411, +0.000875] | 0.003268 | no |
| 3 | 181 | 3.6 | 27% | +0.000591 | [+0.000372, +0.000838] | 0.001433 | no |

Paired per-deal differences against depth 12 are negative at every depth:
`9` −0.001005, `6` −0.000712, `3` −0.000575.

Only the opening lead clears δ. §7 predicted "clearing δ at 12 and 9 … verdict
GENERALISES". **Wrong.** That is three predictions in three runs — C1's
direction, C3's threshold location, and now C4's generalisation. My priors about
this game are not good, which is worth weighing against any recommendation I make.

## 3. The finding underneath the verdict

The gain does not decay smoothly with depth: 9 (+0.000398) is *lower* than 6
(+0.000634) and 3 (+0.000591). It collapses immediately after the opening lead
and then sits flat.

The reason is visible in the foresight column. **The available gain collapses, not
the selector's share of it:**

| depth | `G_deploy / G_foresight` |
| ---: | ---: |
| 12 | 8.5% |
| 9 | 11.1% |
| 6 | 19.4% |
| 3 | 41.2% |

The selector captures a *larger* fraction of what is there as the deal closes.
There is simply an order of magnitude less to have: foresight at the opening lead
is **4.6×** the next depth measured and **11×** the last.

**The opening lead is where the decision matters.** That is a statement about the
game, not about the policy, and it is the most reusable thing in this run.

## 4. A confound I did not anticipate, and it cuts in the reported direction

Depth is entangled with lead-versus-follow. The deal's opening leader does not
lead every trick, so at depths 9, 6 and 3 the evaluated seat is on lead only 13%,
23% and 27% of the time and holds ~5 legal cards rather than 13. "Later decisions"
therefore largely means "following suit with a handful of options".

§4 of the pre-registration did not foresee this and no gate covers it. I added
`share_on_lead` as a descriptive field after the smoke test and before the run —
recorded here because it was a change made with partial knowledge, even though it
touched no estimand and no gate.

It does not rescue the null: it *explains* it, and it sharpens the headline rather
than undermining it. The opening lead is special partly **because** it is a free
choice among thirteen cards with no play history. Whether a selector helps a
*later lead* specifically is unmeasured — 13% to 27% of these decisions were
leads, too few to split out at this N.

## 5. The practical consequence, which is favourable

C3 measured 1.08 s per decision on ten cores and worried about paying it
repeatedly. C4 says you would not: the only decision that clears δ is the
**first** one. That is **one invocation per deal**, not twenty-six.

Against a mean match length of 32.6 deals, a candidate would spend roughly 35 s of
ten-core compute per match, once per deal, at a decision where the player is not
under time pressure from a partner waiting on a trick in progress.

This does not qualify anything. The ten-second requirement still covers showing,
encoding, transfers, synchronisation and first-move lazy initialisation under a
watchdog on a loaded machine, and none of that is measured. But the cost shape is
much better than C3 alone implied.

## 6. What this establishes and what it forecloses

**Establishes:**

- The above-δ signal is **specific to the opening lead** at this measurement, with
  three later depths measured and none clearing.
- Depth 12 replicated across two samplers and three seeds.
- The available gain, not the selector's efficiency, is what collapses after the
  opening lead — an order-of-magnitude property of the game.
- A production selector would need to fire once per deal, not per decision.

**Does not establish:**

- Anything about later *leads* specifically, which this design under-sampled.
- Any whole-deal or per-match gain. §6 of the pre-registration forbids aggregating
  across depths and E6 is why: per-decision counterfactuals are not additive.
- Anything about non-zero scores, transfer beyond the frozen reference, or
  opponent-model play.
- Any candidate. Nothing was modified or promoted.

## 7. Cost

| | Rollouts | Wall clock |
| --- | ---: | ---: |
| C4 | 780,416 | 14 min at 10 workers |
| C3 | 850,304 | 18 min |
| C1 both variants | 1,657,344 | 40 min |
| S1 + S1b | 262,144 | 6.2 min |

Fourteen minutes narrowed a promising branch from twenty-six decisions to one, and
replicated its only positive result through a second, independently validated
sampler.
