# Censoring policy and the safety cap

## Censoring is an infrastructure outcome

A match leg that reaches the configured maximum deal count is recorded as
`censored_infrastructure`. That status means one thing only: *the harness gave
up before the rules did.*

It is **never**:

- a draw,
- a policy win,
- a policy loss,
- an observation of any kind about either agent.

The record types enforce this rather than trusting a convention. A `LegRecord`
whose status is not `complete` cannot carry `winning_engine_team`,
`even_partnership_won`, or `candidate_won` - construction raises
`RecordError: an unfinished leg must not claim ...; censoring is never a policy
outcome`. A `PairRecord` with an unfinished leg is `incomplete_censored`, has
`d_match = None`, and reports `analysable = False`.

Censored pairs stay in the raw records and in the inventory as quarantined work.
They are counted and reported (`censored_pair_count`, `censoring_rate_pairs`)
and they are excluded from the primary analysis entirely. **Formal promotion is
impossible while required primary pairs are censored.**

## Why the Phase 4 cap failed

Phase 4 capped match streams at 40 deals. Measured over 2 560 completed legs on
the Phase 5A calibration bank, the distribution of match length against the
frozen Phase 4 agents is:

| statistic | deals |
| --- | --- |
| minimum | 2 |
| median | 23 |
| mean | 32.6 |
| p90 | 70 |
| p95 | 97 |
| p99 | 134 |
| maximum | **227** |

**27.1 % of individual legs run longer than 40 deals.** A pair censors if
*either* leg exceeds the cap, which is how Phase 4 arrived at roughly a third of
pairs lost. The cap was not conservative; it sat just above the median.

The distribution is heavy-tailed for a structural reason: a deal win by the
non-rising partnership resets the score to 0-0, so a match between
closely-matched policies can restart repeatedly. Any cap chosen without looking
at that tail will censor, and it will censor *selectively* - the streams that
run long are exactly the streams where the two policies are hardest to separate,
so the surviving sample is biased toward agreement.

## How the cap is chosen now

The cap is an infrastructure safeguard, so it is placed beyond the longest match
anyone has actually seen rather than at a quantile of the sample. A quantile
would censor by design at exactly the rate it names.

```text
cap = max(floor, ceil(longest_observed * headroom) rounded up to a multiple of 64)
headroom = 3.0, floor = 256
```

Applied to the calibration data: `longest_observed = 227`, so the calibrated
recommendation is **704**, and zero observed legs come near it.

The Phase 5A calibration run itself used **512**, chosen before the data existed
from a 16-match pilot whose longest match was 125. It produced **zero censored
pairs out of 1 280**, so it was adequate; 704 is the recommendation carried
forward for future runs against these agents.

Both the cap and the reason for it are required fields in the resolved
manifest - `MatchManifest` rejects a cap with a reason shorter than twenty
characters - so a future reader can always see what the safeguard was and why.

## Recalibrating for a new agent

A stronger or more decisive agent shortens matches; a more evenly matched pair
lengthens them. When either side of a comparison changes, re-derive the cap:

1. run a pilot of 16 to 32 pairs at a generous cap;
2. pool the completed leg lengths;
3. call `calibrate_safety_cap(lengths)`;
4. use the proposed cap for the full run and record it in the manifest;
5. after the run, confirm `censored_pair_count == 0`. If it is not, the cap was
   too low for these agents and the run must be repeated, not patched.

## Censoring-aware estimators

Survival or censoring models may be reported *exploratorily*. They are not a
substitute for completing matches that are reasonably executable, and the
primary endpoint always requires completed pairs. Phase 5A needed no such model:
the repaired protocol censored nothing.
