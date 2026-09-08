# S1: is there observation-compatible headroom at the first show?

**Status: pre-registered 2026-09-08, before any measurement.** Written to be
falsifiable and then left alone. Nothing below may be revised after seeing a
result; if the design turns out to be wrong, this document records that it was
wrong rather than being edited into having been right.

This is Experiment 1 of the programme in
`work/phase7_planning/nn_architecture_review.md`, adopted as charter decision
D7. It is the smallest experiment that can kill that programme.

---

## 1. The question

`docs/database/phase7_charter.md` §1.7 records that on the RAMI declaration the
reference captures **30.6%** of a perfect-foresight ceiling, the best
hand-descriptor rule **33.8%**, and eight descriptors explain **R² = 0.106**.
That was read as a 3.3x headroom.

It is not. Perfect foresight sees the hidden layout. Write `Δ` for the realised
gain of an intervention on a particular deal. An oracle collects

```
G_foresight = E[ max(0, Δ) ]
```

while anything that must decide from the observation alone collects at most

```
G_legal = E_o[ max(0, E[Δ | o]) ]   ≤   G_foresight
```

and the gap can be total. If `Δ = -1 + ε` with `ε` independently ±20, every deal
is changed by the intervention and foresight profits on half of them, yet no
observation-only policy should ever override.

**So the question this experiment answers is:**

> Can information legally available at the forehand's first showing decision
> identify profitable deviations from the reference, when every consequence is
> evaluated under an executable, correctly-matched continuation?

If the answer is no, no network architecture rescues it, and the programme stops
here having spent a few minutes rather than a corpus.

## 2. Why the first show and nowhere else

The first showing decision is the only decision in this game with all of these
properties at once:

- **no earlier action to invert** — the public history is empty, so nothing about
  the measurement depends on modelling how a previous actor chose;
- **the decider cannot have changed its own input distribution** — the
  distribution-shift mechanism that is the leading explanation of the cloning
  failure cannot operate;
- **exactly one intervention** — no compounding;
- **the partner in the labels is the partner in deployment** — the continuation
  mismatch that broke every search family cannot operate;
- **hidden completions can be sampled without conditioning on behaviour** — with
  no public history, the conditional distribution over the other three hands
  given the forehand's own hand is exactly uniform over the remaining 39 cards.

That last point matters: it means this experiment needs no belief model, no
particle weighting, and no policy assumption. It is the one place in the game
where the exact conditional is free.

## 3. The intervention, stated as two executable policies

Not "RAMI versus NOLO". A show is a `(card, contract)` pair, and the shown card
is public information that changes the rest of the deal, so an intervention that
did not fix the card would not be executable.

| Arm | Action |
| --- | --- |
| **B** (baseline) | exactly what the reference plays, unchanged |
| **A** (alternative) | the **other declaration**, with the card chosen by a fixed declared selector: **lowest eligible rank, ties broken by the engine's legal-action order** |

The selector is declared here, before measurement, and is deliberately *not* the
reference's own ranking — the review's point is that a comparison must be between
two policies we could actually ship, and the alternative branch must not inherit
whatever the reference's card preference happens to be.

A forehand NOLO declaration **passes showing on**: later seats show normally and
may declare RAMI. Forcing the forehand's declaration and forcing the deal's
contract are different interventions; this is the former.

All four seats, in both arms, are the frozen reference
`partner_aware_lead_v2` (`agent:sha256:252fe227b01900e3…`), receiving only their
own formal observations, for every remaining showing and card-play decision.

## 4. The utility

**Primary endpoint: per-deal frozen-continuation match equity**, from
`src/tuppi_valuation/equity.py`.

Signed deal points are a surrogate and a misleading one: at 48-0 every winning
margin is identical, so pricing margin there is wrong. Equity prices a deal by
the match state it produces, solving the absorbing Markov chain over the coarse
score space — every award being a multiple of four leaves only 25 nonterminal
score configurations.

The deal model that chain needs is estimated from **reference self-play deals
only**. The reference is score-independent (`match_state_enabled = false`), so
its deal-outcome distribution is identical at every score, and one distribution
over `(dealer's team won, points)` suffices.

The utility of a completed deal, to the forehand's partnership, is the equity
delta that partnership realises across the deal. The label for one paired
observation is

```
Δ(o, completion) = U_A(o, completion) − U_B(o, completion)
```

Secondary, diagnostic only, never promoted to primary after the fact: signed
deal points, team tricks, deal-win rate, RAMI declaration rate.

**Starting score is 0-0** for the primary run. Equity is strongly convex in the
score, so the value of an intervention is score-dependent; that is a later
experiment, not this one.

## 5. Design

- **512** first-showing observations, each a distinct forehand hand drawn from
  the deal stream.
- **128** independent hidden completions per observation: the forehand's 13 cards
  are held fixed and the remaining 39 are dealt uniformly among the other three
  seats.
- **2** arms per completion, sharing that completion exactly.

Total **131 072** completed-deal rollouts.

**Cross-fitting.** For each observation, split its 128 completions into two
halves. Use half 1 to decide whether the alternative beats the baseline, and
half 2 to value that decision; then swap and average. This is what stops the
selector from exploiting the same noise it is evaluated on — the reason a naive
"take the max of two sample means" would manufacture headroom out of Monte Carlo
error.

**Clustering.** The unit is the **observation**, not the completion and not the
deal. All 128 completions and both arms of one observation are one cluster.
Confidence intervals resample observations.

## 6. The estimand, normalised for deployment

A candidate that acts only at the forehand's first show is idle in most deals.
Reporting its gain *conditional on overriding* would overstate it by the reciprocal
of the override rate. So the primary quantity is the **deployment-normalised
per-deal equity gain**:

```
G_deploy = seat_share × E_o[ 1{selector overrides} · Δ̄(o) ]
```

with `seat_share = 1/2`, because under complementary team assignment the
candidate partnership holds the forehand in exactly half of legs and can
intervene in no others.

Two further quantities are reported and must not be confused with it:

- **`G_legal_upper`** — a conservative upper bound on observation-compatible
  headroom, `E_o[ max(0, Δ̄(o) + z·se(Δ̄(o))) ]`, deployment-normalised. This is
  the quantity the scientific kill criterion tests. It is *deliberately
  optimistic*: it credits every observation whose noisy mean could plausibly be
  positive.
- **`G_foresight`** — the per-deal oracle gain, for comparison with §1.7's
  framing only. It is not achievable and is never a target.

## 7. Gates, fixed now

Minimum worthwhile gain, adopted from the review as a funding threshold rather
than a measured property of the game:

```
δ = 0.001 equity per evaluated deal
```

For scale: the reference's entire equity contribution on this decision is
+0.00652 and perfect foresight is +0.02126, so δ is about 15% of the former and
5% of the latter.

| Outcome | Condition |
| --- | --- |
| **PASS** | the cross-fitted selector's one-sided 97.5% lower bound on `G_deploy` exceeds **δ** |
| **SCIENTIFIC KILL** | the one-sided 97.5% **upper** bound on `G_legal_upper` falls below **δ** |
| **INCONCLUSIVE / BUDGET KILL** | neither of the above at the fixed 131 072-rollout budget |

An inconclusive result **stops this programme** at this budget. It is not
licence to escalate completions until something appears, and it is not evidence
that no learned Tuppi player is possible — only that this particularly
favourable and diagnosable test did not resolve.

A PASS does **not** authorise a network. It authorises Experiment 2, whose job is
to amortise a decision procedure that has already been shown to work.

## 8. What would invalidate the measurement rather than answer it

Any of these stops the run and is reported as a defect, not a result:

- an arm whose forced action is not a legal member of the engine's legal tuple;
- a continuation agent receiving anything but its own formal observation;
- the two arms of a pair not sharing an identical hidden completion;
- the equity table failing its own model-free bound — equity outside
  `[1/4, 3/4]` under a symmetric deal model, or `V(0-0) ≠ 1/2` by symmetry;
- a reference-delegating wrapper that does not reproduce the reference's actions
  exactly.

## 9. What this cannot establish

- **Nothing about card play.** 95.3% of decisions are trick play and this
  experiment touches none of them.
- **Nothing about transfer.** Every seat is the reference. A gain here is a
  measured best response to one policy family, not evidence of general strength,
  and certainly not evidence against a competent human.
- **Nothing about later showing seats.** The forehand is the only seat with an
  empty public history; seats 2-4 decide after observing passes, which is
  precisely the policy-dependent inference this design avoids.
- **Nothing at non-zero scores.** Equity is convex in the score and this is
  measured at 0-0 only.
