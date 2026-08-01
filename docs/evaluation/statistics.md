# Paired evaluation statistics

## Primary utility

For deal row `j` in base-deal block `i`, define signed game utility

```text
g_ij = +deal points  if Team A wins
       -deal points  if Team B wins
```

The independent paired value is

```text
U_i = (1/8) * sum(j=1..8, g_ij)
```

Positive values favor Team A, negative values favor Team B, and zero is a tie.
Only complete eight-row blocks produce `U_i`. In match mode the row utility is
+1 or -1 for the match winner before the same eight-row average; deal and match
statistics remain separately labeled.

## Reported inference

For the `n` complete independent blocks, the implementation reports the mean
and median of `U_i`, sample standard error `s/sqrt(n)`, a two-sided normal
confidence interval at the configured level (normally 95%), and Cohen's paired
`d_z = mean(U)/s` when sample variance is nonzero.

It also reports a deterministic percentile paired bootstrap interval. Each
bootstrap draw is indexed by SHA-256 from the explicit analysis seed,
replicate, and draw position. This is separate from deal and agent randomness.

The exact two-sided sign test discards ties and uses the binomial distribution.
The paired sign-flip permutation test enumerates all `2^n` assignments for
`n <= 16`; above that it uses the explicitly configured number of deterministic
Monte Carlo sign flips with a plus-one correction. P-values accompany, but do
not replace, the confidence interval, mean effect magnitude, standardized
effect, and win/tie/loss block counts.

With fewer than two complete blocks the standard error and normal interval are
unavailable. With fewer than ten blocks the report warns that uncertainty is
unstable. Empty and incomplete inputs remain explicit rather than becoming
zeros.

## Secondary metrics

Descriptive transformed-game metrics include Team A/B deal-win rates, reset
rate, winning deal points by team, RAMI and NOLO rates, successful/stolen RAMI,
mean tricks, match win rate in match mode, decision-failure rate, and mean/p50/
p95 execution times. These correlated game counts are not the sample size for
primary inference.

Diagnostics are stratified by contract, declaring team, successful/stolen
RAMI, dealer, forehand, partnership assignment, transformation, exact starting
score, Team A up/down/0-0 status, contract × score status, point magnitude,
declarer, and first leader. Strata with fewer than ten represented base deals
are marked small and descriptive—not causal. Initial-hand strength descriptors
are deliberately deferred rather than implying causal adjustment.

## Sequential use

Phase 3 implements fixed-sample analysis only. Configuration validation rejects
interim checkpoints and stopping boundaries. Users must not inspect interim
results and stop when favorable; a future sequential protocol must predeclare
its maximum, looks, and statistically valid alpha spending or confidence
sequence before it is accepted.
