# Phase 5C evaluation: budgets, and a decisive negative result

Every number here comes from **development banks** created for Phase 5C with root
seeds no earlier phase used. None is a promotion claim, none designates a champion,
and the promotion-sealed bank has still never been opened.

Source artifacts: `reports/phase5c/`.

## The headline, first

**The uniform-feasible PIMC baseline loses decisively to `development_reference_v1`
over complete matches.**

| | |
| --- | --- |
| Candidate | `uniform_feasible_pimc_small_v1` (4 worlds, `partner_aware_v1` rollout, match-transition utility) |
| Opponent | `partner_aware_v1` = `development_reference_v1` |
| Pairs | 32 complementary pairs from 0-0, safety cap 704 |
| `p_win` | **0.156** |
| 95 % CI | [0.075, 0.238] |
| Sign-flip p | 0.0001 |
| Pair W / T / L | **0 / 10 / 22** |
| mean `D_match` | -0.688 |
| Censored / failed legs | 0 / 0 |

Thirty-two pairs is a small design, but the effect is not small: the interval
excludes 0.5 by a wide margin and PIMC won **zero** of 32 pairs. This is a solid
negative result, not an underpowered one.

It is preserved exactly as measured. Nothing was retuned against this bank, and every
diagnostic below was run either on a different bank or as a decision-level census.

## Budgets, chosen from measurement

Budgets were not assumed. The cost model was measured first, and it is what makes the
evaluation design what it is.

**Rollout** dominates. `apply_action` revalidates the whole deal state on every
transition, so a rollout is O(remaining actions x history):

| Tricks remaining | 13 | 10 | 7 | 4 | 1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Median rollout | 87.5 ms | 75.4 ms | 58.1 ms | 36.5 ms | 10.4 ms |

About 6.8 ms per remaining trick; 513 simulated actions per second.

**World construction** is cheap by comparison: constraint model 0.32 ms median, exact
feasible count 0.038 ms, and 15.0 ms per world - the last dominated by replaying the
public history to build each hypothetical, which is again engine validation.

**Legal actions**: mean 3.76 in trick play, 6.71 at showing, and **24.0 % of
trick-play decisions are forced** (one legal action) and are answered without any
sampling at all.

**Decision latency**, median / p95:

| Worlds | Tail off | Tail on (threshold 4) |
| ---: | ---: | ---: |
| 2 | 624 / 2 024 ms | 354 / 1 192 ms |
| 4 | 1 265 / 4 046 ms | 699 / 2 332 ms |
| 8 | 2 494 / 7 999 ms | 1 403 / 4 818 ms |

**Match throughput** with PIMC on two seats at four worlds: 0.050 deals/s, 26.5 search
decisions per deal.

### What that arithmetic forced

At 0.050 deals/s and a Phase 5A mean leg of ~30 deals, one complete-match pair costs
roughly 20 worker-minutes. So:

- 128 pairs at six workers ≈ **7 hours**;
- 32 pairs at six workers ≈ 1.8 hours predicted, **5.5 hours actual** (legs ran longer
  than the benchmark's two-deal sample implied, and showing roots with 8+ candidates
  are the most expensive decisions in a deal).

So **128 pairs was not computationally practical** in this phase, and the stated
condition for that target - "if computationally practical" - is not met. The design
was sized to what fits and the arithmetic is reported rather than hidden. Because the
observed effect is large, 32 pairs was enough to resolve it.

### Registered budgets

| Profile | Worlds | Tail | Purpose |
| --- | ---: | --- | --- |
| `uniform_feasible_pimc_smoke_v1` | 2 | off | CI/smoke; exercises the whole path in seconds |
| `uniform_feasible_pimc_small_v1` | 4 | off | **Phase 5C primary**; largest budget whose match comparison finishes |
| `uniform_feasible_pimc_standard_v1` | 8 | off | world-count contrast |
| `uniform_feasible_pimc_exact_tail_v1` | 8 | 4 tricks | continuation-policy contrast |
| `uniform_feasible_pimc_counting_rollout_v1` | 4 | off | rollout-policy contrast |
| `uniform_feasible_pimc_deal_utility_v1` | 4 | off | utility contrast |

The primary profile and its utility were frozen **before** the primary evaluation ran.

## Protocol smoke: the implementation is sound

Before any comparison: 8 deal pairs with PIMC against the reference produced **zero
illegal actions, zero rollout failures, zero world-construction failures, zero
censored legs**, and byte-identical repeat runs. The 32-pair comparison then completed
2 048 legs with 0 censored and 0 failed.

So the loss is not a defect in the harness. PIMC plays legal, reproducible Tuppi and
loses.

## Action stability across nested budgets

Sample prefixes nest exactly - the first 4 worlds of an 8-world budget *are* the
4-world budget's worlds - so a change of action between budgets is a genuine change of
opinion.

| Budget change | Agreement |
| --- | ---: |
| 2 → 4 worlds | 0.667 (16/24) |
| 4 → 8 worlds | 0.833 (20/24) |

Opinions are still moving at four worlds. One decision in six changes when the budget
doubles from 4 to 8, so the primary budget is *not* converged. That is a real
limitation of the primary agent and it is stated as one.

## The mechanism: what the diagnostics say, and what they rule out

Two secondary metrics from the 32-pair comparison stand out against Phase 5A's figures
for Phase 4 pairings:

| | Phase 5A (closely-matched Phase 4 pairs) | Phase 5C (PIMC vs reference) |
| --- | ---: | ---: |
| RAMI share of deals | 0.77 | **0.900** |
| Stolen-RAMI share of RAMI | 0.23 | **0.361** |
| Resets per match (mean) | 11.3 | 6.81 |

More RAMI contracts, and a much larger share of them stolen - which is the expensive
way to lose, since ramin ryöstö pays the opponents 8 per trick above six.

**Attribution limit, stated:** both metrics are deal-level and do not record which
partnership declared. Declarer seat share was near-uniform ([0.231, 0.220, 0.242,
0.207]), so PIMC declared roughly half the contracts, but the aggregate alone cannot
prove PIMC's own declarations were the stolen ones.

### The hypothesis that was tested and refuted

The natural first explanation is **selection optimism**: the chosen action is the
argmax of a handful of noisy per-world means, taking a maximum over noisy estimates is
biased upward, and RAMI's value distribution is far wider than NOLO's - so the noisier
contract is systematically flattered. That mechanism predicts the RAMI rate falls as
the world count rises.

A dedicated showing census (24 deals, forehand's first showing decision only, one
observation per deal) measured it:

| | RAMI declaration rate |
| --- | ---: |
| `partner_aware_v1` (reference) | 0.417 |
| PIMC, 2 worlds | 0.458 |
| PIMC, 4 worlds | 0.458 |
| PIMC, 8 worlds | 0.542 |
| PIMC, 16 worlds | **0.583** |

The rate rises with the budget and moves *further* from the reference. So
small-sample optimism is not the mechanism - more worlds make PIMC declare RAMI more
often, not less. Whatever PIMC is converging to, it prefers RAMI more than the
reference policy does.

### The explanation that survives

Two structural biases fit, and both are documented rather than newly invented:

**Policy mismatch, self-referential.** PIMC estimates an action's value assuming
**reference play by all four seats afterwards**, including its own partner. In the
real match both candidate seats play PIMC. So every value it computes is optimistic
about its own partnership's continuation by exactly the margin by which PIMC is worse
than the reference - and the comparison says that margin is large. This is not random
error; it is a systematic overestimate of its own side, and it is largest for
high-variance choices like declaring RAMI, whose payoff depends most on how well the
declaring side actually plays.

**Root strategy fusion.** The averaging step still combines worlds, and the root action
is chosen as if the agent could tailor its choice per world. PIMC's rollout is
observation-only, which removes continuation clairvoyance - each simulated seat sees
only its own hand - so the classical form of fusion is *weakened* here. What remains is
fusion at the root, and it does not vanish with more samples.

Together these predict what was measured: a policy that over-commits to contracts
whose value depends on strong declarer play, converging *away* from the reference as
the budget grows.

### The utility is not the explanation either

The same showing census was run under both registerable utility adapters. The RAMI
declaration rates are **identical** at every budget:

| Utility | reference | 2 w | 4 w | 8 w | 16 w |
| --- | ---: | ---: | ---: | ---: | ---: |
| `match_transition_v1` | 0.417 | 0.458 | 0.458 | 0.542 | 0.583 |
| `deal_result_v1` | 0.417 | 0.458 | 0.458 | 0.542 | 0.583 |

That is expected rather than surprising, and the reason is provable. **From 0-0 the
two adapters are exactly ordinally equivalent.** For a nonterminal result the winner's
rise equals the deal points, so `match_transition_v1` is `±points/52` against
`deal_result_v1`'s `±points/56` - the same ranking up to a positive scale. The one case
that could have broken it, a 56-point stolen RAMI, ends the match immediately and maps
to `±1.0` under *both* adapters, which is each one's extreme. Exhaustive check over
every contract, declarer, and trick split from 0-0: **zero ordering disagreements**,
pinned by `test_the_two_registerable_utilities_agree_ordinally_from_zero_zero`.

So a utility ablation conducted from 0-0 **cannot** separate these adapters, and this
one did not. The adapters diverge only where the rising score does something the deal
points cannot see - a down-team reset, or a win that reaches the target - so a
meaningful utility contrast has to start from a nonzero score state. That was not
run.

## Heterogeneous partnership diagnostic

Diagnostic only, 6 deals per design, single orientation - so not paired, not
complementary, and carrying seat and dealer effects the duplicate design removes.
These numbers have essentially no inferential weight and are reported for direction
only.

| Design | Mean candidate utility |
| --- | ---: |
| PIMC + reference, versus a pure reference pair | +0.179 |
| Pure PIMC pair, versus PIMC + reference | -0.103 |

Both signs point the same way: PIMC does *less badly* when it has a reference partner
than when it has a PIMC partner. That is the direction the policy-mismatch hypothesis
predicts - two PIMC seats compound the error each one makes about its partner - but at
six unpaired deals it is a hint about where to look, not evidence.

## Deal-level ablations

Deal-level screening is roughly thirty times cheaper than a complete match and is the
instrument Phase 5C uses for ablations. It is **screening only**: Phase 5A established
that signed deal value is blind to match safety, so a deal-level result may show that
two agents differ and may never be read as a match-strength claim.

| Contrast | Deal pairs | Mean paired utility | SE | Ahead / tied / behind |
| --- | ---: | ---: | ---: | --- |
| PIMC small vs `partner_aware_v1` | 8 | +0.005 | 0.062 | 3 / 2 / 3 |
| PIMC 8 worlds vs PIMC 4 worlds | 6 | -0.058 | 0.078 | 4 / 0 / 2 |

Both are inconclusive at these sizes - each standard error is larger than its point
estimate - and both are reported for completeness rather than as findings. The first is
consistent with the match-level loss without confirming it: a single deal cannot see the
compounding that a 30-deal match exposes.

### The ablations that were not run, and why

The exact-tail contrast, the rollout-policy contrast, and a nonzero-score utility
contrast were **not** completed. They were started and abandoned on cost grounds: a
deal-level ablation between two PIMC agents puts search on all four seats, so at eight
worlds it runs about 3 minutes per deal, and the four planned contrasts projected to
roughly four more hours. They are listed here rather than quietly dropped, and the
world-count contrast above is the one that fits.

Nothing was inferred about the exact tail's playing strength. Its measured effect in
Phase 5C is a 1.8x speedup and a documented bias direction, and nothing more.

## What is established, and what is not

**Established:**

- the implementation is sound: zero illegal actions, zero failures, zero censoring
  across 2 048 legs, and exact reproducibility;
- information-set invariance holds: two different real deals presenting the same
  observation produce identical constraints, worlds, values, diagnostics, and action;
- PIMC values equal an independent hand-rolled enumeration exactly on small feasible
  sets;
- **this PIMC baseline is decisively weaker than `partner_aware_v1` over complete
  matches** at the four-world budget;
- the four-world budget is not converged (one decision in six changes at eight worlds);
- selection optimism from small samples is **not** the mechanism.

**Not established:**

- that PIMC is weaker at *every* budget. Only four worlds was measured at the match
  level; eight and sixteen were measured only at the decision level.
- that PIMC would lose against a weaker opponent. The reference is the strongest rung
  Phase 5A's data supports.
- which of the two named biases dominates. Both fit; neither was isolated.
- anything about the exact tail at the match level. Its contrast was run at the deal
  level only.
- that the stolen RAMI contracts were PIMC's own, for the attribution reason above.

## What was deliberately not done

Not tuned. The result stands as measured, on a bank that will not be reused for a
retry. No Phase 4 profile was touched, `match_aware_v1` was not retuned, and no
behaviour change was made to chase the number. Any change would produce a new agent
identity and belong to a later experiment on fresh fixtures - which is exactly the rule
Phase 5A wrote after its own null result.

## Recommended Phase 5D decision

The negative result is *informative*, and it points somewhere specific.

1. **Fix the policy mismatch before adding tree search.** The cheapest principled
   change is to roll out the candidate partnership's future turns with a policy that
   approximates PIMC rather than the reference - or to accept one-ply PIMC only as a
   *component*. Either is a new agent identity.
2. **Then ISMCTS, which is the structural answer.** An information-set searcher chooses
   one strategy per information set rather than averaging world-specific choices, which
   is precisely the root fusion that survived Phase 5C's observation-only rollout.
   Phase 5C's sampler, hypothetical world, rollout boundary, utility, and seed
   hierarchy are all reusable as-is.
3. **Keep the exact tail out of the critical path** until the root problem is fixed. It
   is a 1.8x speedup and a bias amplifier; both matter, and the second matters more.
4. **Re-measure match length and pair variance for any new agent** before sizing its
   evaluation. PIMC's legs averaged 21.75 deals against the reference's ~30, so a
   decisive agent changes the cost model.
5. **The sealed bank stays closed.** Nothing in Phase 5C is promotion evidence.

## Reproduction

```bash
source "$HOME/.venvs/tuppi-research/bin/activate"
cd "$HOME/Developer/TuppiProject"

python -m tuppi_search.runner validate
python -m tuppi_search.runner benchmark --streams 2 \
  --output "$HOME/TuppiRuns/phase5c/benchmark.json"
python -m tuppi_search.runner stability --streams 3 --decisions 24 \
  --output "$HOME/TuppiRuns/phase5c/action_stability.json"
python -m tuppi_search.runner showing-sensitivity --deals 24 \
  --output "$HOME/TuppiRuns/phase5c/showing_sensitivity.json"

# The headline: about 5.5 hours at six workers.
python -m tuppi_search.runner compare \
  --candidate uniform_feasible_pimc_small_v1 --opponent partner_aware_v1 \
  --pairs 32 --safety-cap 704 --workers 6 \
  --output "$HOME/TuppiRuns/phase5c/match_comparison_32.json"
```

Write experiment output outside the repository and outside any cloud-synced directory.
