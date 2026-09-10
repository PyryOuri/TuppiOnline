# C1: observation-compatible headroom at the opening card play

**Pre-registration. Fixed before the instrument exists.** Nothing in
`work/cardplay/c1_headroom.py` may deviate from this document; if the design has
to change, that is a new pre-registration with a new name, not an edit here.

Scoping evidence: `/Users/pyryouri/Developer/tuppi_e7_cardplay_scope_20260910/`
(`SCOPE.md`, `out/feasibility.json`, `out/power.json`).

## 1. Why

S1b killed the showing intervention and recorded that it establishes *"nothing
about card play, which is 95.3% of decisions and untouched here."* Three
subsequent attempts to take rules from a blinded expert review and validate them
(E4, E5, E6) all failed, and all three mined **hindsight** loss. Hindsight does not
bound achievable improvement: S1b measured a perfect observation-compatible
selector capturing **3.9%** of the oracle gap at showing, and E6 priced a rule
built on a 3× hindsight association whose counterfactual netted **−4.08 points per
deal**.

This measures the quantity that actually decides whether card-play rule work is
fundable, at the decision carrying the most loss.

## 2. The decision and the estimand

The **opening card play**: the first trick-play decision of a deal, at 0–0. E1/E2
place **52.8%** of hindsight loss in the 9–12 cards-left band, and E6's only
positive band was the opening play.

An **observation** *o* is the acting seat's own hand plus the public show history.
For each legal opening lead *a*, `V(a|o)` is the mean over completions of
per-deal frozen-continuation match equity for the acting partnership. `p(o)` is
the reference's own choice. All K legal leads are arms; at the opening lead
**K = 13**.

Endpoint: `tuppi_valuation.equity`. **δ = 0.001**, the threshold S1/S1b used. The
signed-deal-points bar of 1.0 declared elsewhere in this repository is a
candidate-screening rule on a different endpoint and does **not** apply here.

## 3. Conditioning — both variants, reported separately

At the first show the public history is empty, so uniform dealing is the exact
conditional. Card play sits behind a show history and that no longer holds.
Measured acceptance over 40 observations × 400 trials:

- **HARD** — pin each shown card into the seat that showed it, deal the remaining
  cards uniformly, force the recorded show sequence, and require each forced show
  to be legal in the resampled hand. Acceptance **97.6%**. Discards behavioural
  information, which the reference does not use: the T0–T3 audit found its hard
  ownership exclusions sound and the behavioural deduction unimplemented.
- **POLICY** — additionally require the reference's show policy to *choose* those
  shows. Acceptance **13.85%**, about 7 draws per usable world. This is the exact
  conditional under the assumption that opponents show like the reference.

Both are run. The difference between them is the value of the behavioural
inference the reference does not perform, and reporting one alone would leave that
unmeasured.

## 4. The estimator, fixed now

Per observation *o*, arm sample means `m_a` with standard errors `s_a` over M
completions. Let `mbar` be the mean of `m_a` across arms and

```
noise    = mean_a(s_a^2)
v_obs    = Var_a(m_a)
signal   = max(v_obs - noise, 0)
lambda   = signal / (signal + noise)
m_hat_a  = mbar + lambda * (m_a - mbar)
g_hat(o) = max_a m_hat_a - m_hat_{p(o)}
```

- **`G_legal_eb` = mean over observations of `g_hat(o)`.** What a selector knowing
  `E[V(a|o)]` exactly would gain. This is the reported bound.
- **`G_deploy`**, cross-fitted: split the M completions in half, take
  `argmax_a` on one half, score `V(s(o)) - V(p(o))` on the other, average over both
  split directions. With 13 arms the max of noisy means is badly biased upward, so
  cross-fitting is load-bearing rather than a refinement.
- **`G_foresight`**, per-completion `max_a value(a) - value(p)`. Reported for
  comparison with the charter's foresight framing **only**, never as a bound.

**The naive bound `E_o[max(0, g + z*se)]` is deliberately NOT used.** The power
check measured per-completion sd **0.05115**, so `z*se` at M = 128 is about
0.0089, nearly **nine times δ**. That gate could not fire, which is exactly the
defect that cost S1 a run. Declaring the shrinkage estimator in advance is the
correction S1's own §8 recommended.

**Deployment normalisation.** Figures are multiplied by the measured share of
deals in which the evaluated partnership holds the opening lead, so they are what
a deployed candidate gains across all deals rather than conditional on leading.
Both conditional and normalised figures are reported; the gates apply to the
normalised ones, as in S1.

## 5. Power, already measured

24 observations × 48 completions × 13 arms, 14,976 rollouts:

| Quantity | Value | Prior runs |
|---|---|---|
| Per-completion sd | 0.05115 | S1 at showing: 0.0586 |
| Signal share | **0.9178** | S1 0.894, S1b 0.902 |
| Completions for `z*se < δ` | 10,050 | S1's trap was ~13,200 |

Signal variance is positive and the share reproduces both prior runs, so the
shrinkage estimator has real between-hand signal and is not measuring its own
noise floor. **The EB gate is reachable; the naive gate is not.**

## 6. Budget, seeds and stopping rule

- **N = 512 observations, M = 128 completions, K = 13**, mirroring S1b, per
  conditioning variant. 851,968 rollouts each; measured 85 rollouts/s single
  process with `trusted_transitions`, so about 17 minutes per variant at 10
  workers.
- Root seeds: `tuppi-c1-hard-v1` and `tuppi-c1-policy-v1`. Bootstrap seed
  `tuppi-c1-bootstrap-v1`, 5,000 replicates over observations.
- **One run per variant.** Inconclusive stops the branch at this budget. This is
  not licence to escalate completions until something appears.

## 7. Gates

Bootstrap over observations, one-sided 97.5% bounds, on the deployment-normalised
figures.

> **SCIENTIFIC KILL** if the upper bound of `G_legal_eb` is below δ = 0.001.
> **PASS** if the lower bound of `G_deploy` is above δ.
> **INCONCLUSIVE** otherwise.

Gates are evaluated per conditioning variant. A kill requires **both** variants to
kill; if they disagree, the result is inconclusive and the disagreement is the
finding.

Endpoint controls must pass before anything is priced, as in S1: the symmetric
model must give `V(0-0) = 0.500000` exactly, and the fitted equity range must lie
inside the equal-strength bounds plus the measured dealer asymmetry.

## 8. Predicted outcome, recorded in advance

**A kill.** Per-completion sd and signal share both land where showing did, and
S1b's finding that 96% of the oracle gap is irreducible hidden-layout variance is
a property of hidden information, which does not shrink because the decision
moved. Stating this now so that a kill cannot later be presented as a surprise,
and so that a PASS would be a genuine update.

## 9. What this will not establish

- Nothing about **later tricks**. This is the opening lead only.
- Nothing about **non-zero scores**. Equity is convex in the score; this is 0–0.
- Nothing about **transfer**: every other seat is the frozen reference.
- Nothing about **opponent-model rules**, which self-play cannot value at all.
- Nothing about whether a learned Tuppi player is possible.
- A kill closes card-play *rule* work at this decision on this endpoint. It does
  not close card play.
