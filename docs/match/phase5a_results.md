# Phase 5A results and baseline-ladder reassessment

All numbers here come from the **calibration** and **development** banks. None
of them is a promotion claim, and none designates a champion. The
promotion-sealed bank exists, is committed by digest, and has never been opened.

Source artifacts: `reports/phase5a/calibration_report.json`,
`reports/phase5a/score_state_diagnostics.json`,
`reports/phase5a/match_length_calibration.json`.

## The protocol repair worked

| | Phase 4 match mode | Phase 5A |
| --- | --- | --- |
| Stream | fixed 40-deal bank slice | extensible, random-access |
| Cap | 40 deals | 512 (calibrated recommendation 704) |
| Censored pairs | 92 of 256 games, 13 of 32 blocks lost | **0 of 1 280** |
| Usable pairs | 19 | 256 per comparison |
| Endpoint | signed deal points | match win probability |

Across 1 280 calibration pairs and 576 diagnostic pairs - 3 712 complete matches
- **not one leg was censored and not one failed.** The longest match observed was
227 deals; 27.1 % of legs exceeded the old 40-deal cap, which is precisely why
Phase 4 lost a third of its pairs.

## Primary results: the ladder over complete matches

256 complete complementary pairs per comparison, from 0-0, safety cap 512.
`p_win` is the candidate's orientation-averaged match win probability.

| Step | Candidate | Opponent | `p_win` | 95 % CI | sign-flip p | W / T / L |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `reactive_contract_v1` | `legacy_heuristic_port_v1` | **0.896** | [0.872, 0.921] | 0.0001 | 203 / 53 / 0 |
| 2 | `public_counting_v1` | `reactive_contract_v1` | **0.621** | [0.587, 0.655] | 0.0001 | 78 / 162 / 16 |
| 3 | `partner_aware_v1` | `public_counting_v1` | **0.557** | [0.530, 0.584] | 0.0002 | 41 / 203 / 12 |
| 4 | `match_aware_v1` | `partner_aware_v1` | 0.498 | [0.481, 0.515] | 1.000 | 9 / 237 / 10 |

### Does the data support each ladder step?

- **Reactive over legacy port: yes, decisively.** 0.896, and the opponent won
  *zero* pairs out of 256. Phase 4's deal-level finding survives the change of
  endpoint intact.
- **Counting over reactive: yes.** 0.621 with a tight interval well clear of
  0.5. Hard public inference is worth roughly twelve percentage points of match
  win probability against the rung below it.
- **Partner-aware over counting: yes, but smaller.** 0.557, interval [0.530,
  0.584]. Real, and about half the size of the counting step.
- **Match-aware over partner-aware: no.** 0.498 with an interval that is almost
  centred on 0.5 and a randomization p-value of 1.000. There is no detectable
  benefit.

Monotonicity is not forced. The first three steps are supported; the fourth is
not, and the ladder is reported as it measured.

## The match-aware ablation: the first valid measurement

Phase 4 could not measure the rising-score rules. Its deal-level bank started
every deal at 0-0, where the rules are inert, and its 48-0 bank scored them in
deal points - a currency the rules deliberately spend. Phase 5A measures them on
match wins.

`match_aware_v1` versus `match_aware_no_match_features_v1` (the identical policy
with every `match.*` rule switched off) over 256 pairs from 0-0:

**`p_win` = 0.498, CI [0.481, 0.515], sign-flip p = 1.000, 237 of 256 pairs
tied.**

The two agents produce a different pair outcome in only 19 of 256 pairs, and
those 19 split 9 wins to 10 losses.

### Conditional match equity at explicit score states

64 pairs per state, complementary assignments, each leg run to natural
termination. Secondary diagnostics; they never replace the 0-0 endpoint.

| Start | `p_win` | 95 % CI | sign-flip p | mean deals | immediate completions |
| --- | --- | --- | --- | --- | --- |
| 48-0 | 0.484 | [0.441, 0.528] | 0.733 | 16.1 | 52.3 % |
| 44-0 | 0.484 | [0.447, 0.522] | 0.682 | 16.7 | 42.2 % |
| 32-0 | 0.500 | [0.469, 0.531] | 1.000 | 25.6 | 7.8 % |
| 16-0 | 0.492 | [0.466, 0.519] | 1.000 | 28.9 | 0.0 % |
| 0-0 | 0.500 | [0.478, 0.522] | 1.000 | 24.5 | 0.0 % |
| 0-16 | 0.500 | [0.478, 0.522] | 1.000 | 25.6 | 0.0 % |
| 0-32 | 0.500 | [0.478, 0.522] | 1.000 | 23.1 | 4.7 % |
| 0-44 | 0.492 | [0.466, 0.519] | 1.000 | 16.4 | 39.8 % |
| 0-48 | 0.477 | [0.443, 0.511] | 0.378 | 17.5 | 42.2 % |

**The rules never help at any score state.** At the mid scores they are
literally inert - `p_win` is exactly 0.500 because the two agents make identical
decisions. At 44-0, 48-0, 0-44, and 0-48, where the protect and pressure
overlays actually fire, the point estimate is consistently *below* 0.5 (0.477 to
0.484), though every interval still contains 0.5.

### Conclusion on the match-aware features

The honest reading, stated plainly: **the Phase 4 rising-score rules provide no
measurable benefit, and the weak trend where they fire is unfavourable.**

Three separate observations support it rather than one:

1. they change the pair outcome in only 7.4 % of matches from 0-0;
2. those changes split evenly (9-10);
3. at every score state where they are active the point estimate is below 0.5.

This is now a measurement, not a suspicion. Phase 4 reported the value of these
rules as *unestablished*; Phase 5A establishes that it is *not positive* at this
sample size.

What it does **not** license: silently editing `match_aware_v1` and re-running
against the same bank. A changed profile is a new agent identity and belongs to
a later experiment on different fixtures. The diagnosis - which of the three
rules is responsible, and whether the protect threshold is simply mis-set -
belongs to Phase 5B with a fresh design.

## Development reference

`partner_aware_v1` is designated **`development_reference_v1`**: the strongest
rung the complete-match data supports, and the natural opponent for the first
search agent.

The designation is bookkeeping for later comparisons, not a promotion:

- it rests on a calibration bank that was visible during development;
- `match_aware_v1` is *not* worse than it (0.498 is a tie, not a loss), so the
  choice between them is a coin flip on this evidence; `partner_aware_v1` is
  preferred only because it is the simpler agent that achieves the same result;
- the sealed bank has never been opened, so no champion exists.

## Secondary behaviour

Descriptive only; these cannot override a primary result.

| | closely-matched pairings | reactive vs legacy port |
| --- | --- | --- |
| resets per match (mean) | 11.3 | 7.5 |
| RAMI share of deals | 0.77 | 0.57 |
| stolen RAMI share of RAMI | 0.23 | 0.19 |

Resets per match: median 7, p95 34, maximum 83. That tail is the mechanism
behind the long matches - two closely-matched partnerships can reset each other
repeatedly before either survives to 52.

## Throughput

| | |
| --- | --- |
| Deals per second | ≈ 14 at six workers (≈ 4.6 single-threaded) |
| Complete matches per second | ≈ 0.34 |
| Pairs per second | ≈ 0.17 (5.9 s per pair) |
| Calibration run | 1 280 pairs, 2 560 matches, ≈ 83 000 deals in 125 min |
| Diagnostics run | 576 pairs in 32 min |
| Storage per pair | ≈ 4 KB (compact leg records; no per-deal hands retained) |
| Total experiment storage | ≈ 8 MB for 1 856 pairs |

Serialization is a negligible share: pair records are compact by design, which
is what keeps a 3 700-match experiment inside 8 MB and off a synced filesystem.

## Limitations

- **Every number here is from an unsealed bank.** They are descriptive.
- **256 pairs resolves large effects only.** Detecting a one-point edge in match
  win probability needs roughly 1 500 to 3 000 pairs; see
  `docs/match/calibration.md`.
- **The null on the match-aware features is a null, not a proof of harm.** Every
  interval contains 0.5.
- **All comparisons use one initial dealer (seat 0).** Dealer rotation inside a
  match is exercised continuously, but the *initial* dealer is not varied across
  streams, so any initial-dealer effect is unmeasured. The duplicate design makes
  this benign for the primary contrast, since both legs share it.
- **Match lengths are specific to these agents.** A more decisive agent will
  shorten them and change the required cap and sample size.
- **Only one candidate-opponent pairing per ladder step was run.** There is no
  full cross-play at the match level; that would multiply the cost by the number
  of pairs of agents.

## Deferred to Phase 5B

1. Open nothing sealed until a candidate is frozen.
2. Diagnose the match-aware null: per-rule ablations, and whether the protect
   threshold at distance 4 is simply mis-set.
3. Build the belief layer on top of `PublicInference` as a hard constraint set.
4. Add PIMC or ISMCTS using the Phase 4 rungs as rollout policies, with
   `partner_aware_v1` as the development reference opponent.
5. Re-estimate match length and `sd(D)` for the search agent before sizing its
   evaluation; a search agent will change both.
6. Only then open the sealed bank, once, with a recorded reason.
