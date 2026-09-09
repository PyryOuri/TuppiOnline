# S1b: the same question with a gate that can actually fire

**Status: pre-registered 2026-09-09, before the instrument was modified and
before any S1b data existed.** Nothing below may be revised after seeing a
result.

S1 ([results_s1.md](results_s1.md)) returned INCONCLUSIVE because one of its two
gates was unreachable by construction: its upper bound on legal headroom carried
a Monte Carlo noise allowance ten times the threshold it had to fall below. That
was a design error, not a property of the game.

S1b asks the identical question with a statistic that is powered at the same
budget. **It is a confirmatory replication, not a discovery**: S1's post-hoc
analysis already predicts the answer, and this document states that prediction
so the test can fail.

Everything not restated here is inherited unchanged from
[hypotheses_s1.md](hypotheses_s1.md): the question, the two executable arms and
their declared card selector, the endpoint, the design, the clustering, the
deployment normalisation, δ, and §8's invalidation conditions.

---

## 1. What changes

**Fresh data.** Root seed `tuppi-s1b-headroom-v1`, which draws different forehand
hands *and* different completions from S1's `tuppi-s1-headroom-v1`. S1's
shrinkage estimate was computed after seeing S1's result, so re-using S1's hands
would make this pre-registration nominal. Same design, new seeds.

**A new primary statistic.** In place of
`G_legal_upper = E_o[max(0, Δ̄ + z·se)]`, which measured the noise floor:

```
var_signal = max(0, Var_o(Δ̄) − mean_o(se²))
w(o)       = var_signal / (var_signal + se(o)²)
shrunk(o)  = grand_mean + w(o) · (Δ̄(o) − grand_mean)
G_legal_eb = seat_share · E_o[ max(0, shrunk(o)) ]
```

This is a James–Stein shrinkage of each observation's noisy mean toward the grand
mean by its own noise share, and it estimates what a selector that knew
`E[Δ|o]` **exactly** would gain — an achievability estimate rather than a
confidence envelope. It is powered because the variance decomposition separates
signal from noise at the observation level instead of paying `z·se` per
observation.

The bootstrap must **re-fit `var_signal` and every `w(o)` inside each
replicate**. Holding the weights fixed at their full-sample values would
understate the interval.

## 2. Gates, fixed now

δ = 0.001 equity per evaluated deal, unchanged.

| Outcome | Condition |
| --- | --- |
| **PASS** | the cross-fitted `G_deploy`'s one-sided 97.5% lower bound exceeds δ |
| **SCIENTIFIC KILL** | `G_legal_eb`'s one-sided 97.5% **upper** bound falls below δ |
| **DEGENERATE** | the signal share `var_signal / Var_o(Δ̄)` falls below **0.25** |
| **INCONCLUSIVE** | none of the above |

`G_deploy` and its gate are carried over verbatim so that a positive result
cannot be missed by the change of statistic.

**The DEGENERATE guard exists because the new estimator has a failure mode the
old one did not.** If between-hand variance were entirely noise, `var_signal`
collapses to zero, every weight goes to zero, `shrunk(o)` becomes the grand mean
for every observation, and `G_legal_eb` becomes `max(0, grand mean)` — which is
0 here, firing the kill for the wrong reason. S1 measured an 89.4% signal share,
so this guard should not trigger; if it does, the estimator had no discriminating
power and no kill may be claimed from it.

## 3. The prediction, stated so it can be wrong

From S1's 512 observations: `G_legal_eb = +0.000217`, 95% CI
[+0.000115, +0.000337], signal share 89.4%.

**S1b is therefore expected to return SCIENTIFIC KILL**, with `G_legal_eb`
between roughly +0.0001 and +0.0004 and an upper bound comfortably below δ.

Three ways this prediction could fail, all of which would be informative:

- `G_legal_eb`'s upper bound lands **above** δ — S1's estimate was optimistic
  about its own precision, or its hand sample was unrepresentative. Result:
  INCONCLUSIVE, and the question is open at a budget that cannot settle it.
- `G_deploy`'s lower bound exceeds δ — a deployable selector does reach the
  threshold on fresh hands, which would contradict S1 outright and demand
  explanation before anything is built on either run.
- the signal share collapses below 0.25 — S1's variance decomposition does not
  replicate, and neither run's post-hoc reasoning can be trusted.

## 4. What a kill means, and what it does not

A SCIENTIFIC KILL here means: **at the forehand's first showing decision, with
the alternative card chosen by the declared lowest-eligible-rank selector, and
against the frozen reference at 0-0, a perfect observation-compatible selector is
worth about a fifth of the funding threshold.** Experiment 2 is not funded on
this scope.

It does not mean, and may not be reported as meaning:

- that card play has no headroom — 95.3% of decisions are untouched here;
- that a **freely chosen** alternative card has no headroom — the alternative arm
  is one declared policy, not the best of the 26 legal showing actions the rules
  permit;
- that later showing seats, non-zero scores, or other opponent families behave
  this way;
- that no learned Tuppi player is possible.

Each of those is a separate experiment needing its own pre-registration.

## 5. Budget

131 072 rollouts, identical to S1: about 3 minutes on the development Mac and
11 minutes on the Fedora box. No increase over the run that returned
inconclusive.
