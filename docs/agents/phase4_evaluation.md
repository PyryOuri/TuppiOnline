# Phase 4 baseline evaluation

Phase 4 does not introduce a second evaluator. It contributes agents and
immutable manifests and runs the Phase 3 arena unchanged: content-addressed deal
banks, the eight-game `balanced_duplicate_8_v1` schedule, the independently
generated base deal as the unit of inference, atomic resumable shards, and
structured failures.

## Committed inputs

| Artifact | Contents |
| --- | --- |
| `banks/phase4_development_deal_v1.json` | 64 base deals, seed `phase4-development-deal-v1`, round-robin dealer, 0-0. |
| `banks/phase4_development_deal_up_v1.json` | 64 base deals, seed `phase4-development-deal-up-v1`, starting from 48-0. |
| `banks/phase4_crossplay_v1.json` | 8 base deals, seed `phase4-crossplay-v1`. Deliberately small. |
| `banks/phase4_development_match_v1.json` | 1280 base deals = 32 blocks of 40, seed `phase4-development-match-v1`. |
| `manifests/phase4/*.json` | One immutable `EvaluationConfiguration` per comparison, plus the cross-play request and an index. |
| `reports/phase4/baseline_report.json` | The frozen report, validated by `schemas/agents/baseline_report.schema.json`. |

Every manifest is reproducible from code: `tests/agents/test_schemas.py`
rebuilds each configuration from its `ComparisonSpec` and requires the committed
`evaluation_id` and `configuration_digest` to match. Regenerate with:

```bash
PYTHONPATH=src python -m tuppi_agents.runner write-banks --output-dir banks
PYTHONPATH=src python -m tuppi_agents.runner write-manifests \
  --bank-dir banks --output-dir manifests/phase4
```

## Benchmark-bank status and reuse restrictions

These banks are **development banks**. They were visible while the agents were
written, so their numbers are descriptive: they show that the pipeline runs, that
the rungs differ, and roughly in which direction. They are **not** sealed
promotion evidence and must never be quoted as a strength benchmark. The
restriction is recorded inside each bank's creation metadata and in the report's
`interpretation` block, not only here.

A sealed promotion bank - generated after the agents are frozen, kept out of the
development loop, and used once - is a Phase 5 deliverable. Until then, the only
defensible claims are relative and provisional.

## Result classes

The report keeps three classes apart and labels every comparison:

- `development` - deal-level and match-level comparisons on the development
  banks;
- `protocol_control` - comparisons against the non-strategic Phase 3 fixtures,
  which establish a floor, not a ranking among strategic agents;
- `ablation` - the same deals and the same schedule with exactly one capability
  changed.

## A. Deal-level protocol validation

64 independently generated base deals, each played as the canonical eight-game
duplicate block, giving 512 transformed games per comparison and 64 independent
observations for inference. Five comparisons walk the ladder and add a control
floor. The sample is sized to exercise the statistical pipeline; it is not large
enough to claim precise strength, and the intervals in the report show that.

### Why a second deal-level bank exists

The first run exposed a flaw in this protocol, and the flaw is worth recording
rather than quietly fixing. Every deal in `phase4_development_deal_v1` starts at
0-0, where **every rising-score rule is inert by construction**: the protect
overlay needs an up partnership near 52, the pressure overlay needs a down one,
and coasting needs margin that cannot move the match. Run only on that bank, the
partner-aware-versus-match-aware comparison and the match-state ablation both
returned a mean paired utility of exactly `0.00` over all 64 blocks - not
evidence of no effect, but evidence that nothing was being measured.

`phase4_development_deal_up_v1` starts every deal at 48-0, so one partnership is
four points from the target and the other can only reset. That is precisely
where the match-aware rules fire, and the reset rate on that bank is 0.41 rather
than 0.00. The 0-0 comparisons are kept in the report as the negative control
that documents the inertness.

## B. Complete-match baseline comparison

Complete explicit deal streams from 0-0, with complementary partnership
assignments supplied by the canonical schedule. 32 independent match streams of
up to 40 deals each, eight orientations per stream.

Match lengths are unequal by nature: a deal win by the non-rising partnership
resets the score to 0-0, so a match can run long. A stream that does not reach 52
within its 40 deals is **censored**, and the arena records it as a structured
`insufficient_match_deals` failure rather than silently truncating it. The report
carries a `censored_games` count per comparison, and censored games are excluded
from outcome metrics by the Phase 3 quarantine rule.

## C. Cross-play

Eleven teams over the 8-deal cross-play bank, every unordered pair, 66 cells:

- four protocol controls (first legal, lowest legal, highest legal, seeded
  random);
- the five ladder rungs as homogeneous clone partnerships;
- two heterogeneous partnerships (match-aware with reactive, match-aware with a
  first-legal control).

Eight base deals per cell is a deliberately small sample chosen so the whole
matrix stays reproducible on a laptop. Cross-play is **descriptive**: it shows
that every pairing runs, that identities are recorded, and roughly how the cells
fall. It does not support a ranking.

## Ablations

The required ablations, all on the same deals and the same schedule as their
comparison partner:

| Ablation | Manifest | Isolates |
| --- | --- | --- |
| Reactive vs public counting | `deal_reactive_vs_counting` | Hard public inference. |
| Counting vs partner awareness | `deal_counting_vs_partner_aware` | Explicit partnership rules. |
| Partner awareness vs match awareness | `deal_partner_aware_vs_match_aware` (0-0), `..._from_48` | Deterministic rising-score rules. |
| Legacy vs simple showing | `ablate_showing_legacy_vs_simple` | The showing profile, with identical trick play. |
| Legacy convention on/off | `ablate_legacy_convention_on_off` | The optional legacy showing convention. |
| Match-state features on/off | `ablate_match_state_on_off` (0-0), `..._from_48` | Every `match.*` rule at once. |
| Diagnostics on/off | measured, not an arena run | See below. |

The first three are *structural*: the two profiles differ by a capability, not by
a tuned number, so the comparison isolates the capability.

The diagnostics ablation is not an arena comparison because it must not be one:
`choose_action` never builds a diagnostics record and `decide` computes the same
ranking either way, so play is provably identical. That identity is asserted for
every registered agent over a complete deal in
`tests/agents/test_conformance.py`, and the *cost* of diagnostics is measured in
the performance section instead.

The match-state ablation has a matching structural property:
`match_aware_no_match_features_v1` is required by test to choose exactly the same
actions as `partner_aware_v1` at 0-0, 48-0, and 0-48, which is what makes the
comparison a clean measurement of the rising-score rules alone.

## What the report contains

Per comparison: paired utility (mean, median, normal and bootstrap intervals,
sign-test and permutation p-values, Cohen's dz), independent base deals,
transformed games, censored games, deal win rate for both sides, mean tricks,
mean conditional deal points, reset rate, RAMI declaration rate, successful and
stolen RAMI counts, NOLO rate, match win rate where the mode provides it, action
and game latency percentiles, failure counts, and diagnostic strata by contract,
score state, RAMI outcome, partnership assignment, and up/down status.

Small strata carry the Phase 3 warning `small diagnostic stratum; descriptive,
not causal`. That warning is part of the data, not decoration.

## Interpretation rules

The objective is to establish a ladder, not to force an expected ranking.

- Each rung is a strictly larger **capability** set than the one below. That is a
  statement about the code, not about strength.
- If a more sophisticated agent performs worse, the result is **preserved**. It
  is diagnosed by ablation, not deleted, and the ladder is not reordered by
  preference.
- Nothing is tuned on this bank until a desired answer appears. The thresholds
  committed here are the ones the agents were written with.
- Development-bank findings, protocol-control results, and future sealed
  promotion claims are reported separately and must stay separate.
- No result in this report supports an expert-strength claim, and none is
  offered.

## What the frozen run actually found

Four findings are worth stating plainly, including the two that are unfavourable
to the top of the ladder.

**1. Hard public inference helps, and partnership rules help a little.**
Public counting beats reactive by 1.50 deal points per base deal
(95% CI [0.34, 2.66], permutation p = 0.018) and partner awareness beats counting
by 0.50 (CI [0.01, 0.99], p = 0.069). Both are small, both are on a development
bank, and neither is a strength claim - but the direction is consistent and the
mechanism is the one the rules were written for.

**2. The transparent reactive baseline beats the legacy port.** Reactive beats
`legacy_heuristic_port_v1` by 2.75 (CI [0.80, 4.70], p = 0.008), and the showing
ablation attributes most of that to showing: simple showing beats legacy showing
by 2.38 (CI [0.65, 4.10], p = 0.013) with trick play held identical. The frozen
legacy expected-value thresholds are uncalibrated for this ruleset, which is
exactly what the port's documentation says about them.

**3. Match awareness measures *worse*, not better, on the deal-level metric.**
On the 48-0 bank the rising-score rules cost 1.03 deal points per base deal
(CI [-2.16, 0.10], p = 0.105). This result is preserved and the ladder is not
reordered. The diagnosis is a metric mismatch rather than a defect in the rules:
the primary metric is *signed deal points*, and the whole point of the protect
rule is to trade deal margin for match safety. A partnership that is down scores
zero for any win, so a metric denominated in deal points cannot see the thing the
rule optimises. The rule may still be wrong - the interval includes zero and
crosses well past it - but this comparison cannot settle that, and it would be
dishonest to tune the threshold until the sign flips.

**4. The complete-match comparison is uninformative because of censoring.**
92 of 256 match games (36%) failed to reach 52 within their 40-deal stream and
were recorded as structured `insufficient_match_deals` failures, leaving 19 of 32
blocks complete. Those 19 blocks return a paired utility of exactly 0.00, which
almost certainly reflects a censoring bias rather than equality: streams in which
the two policies diverged are also the streams whose lengths diverged, so they are
the ones most likely to have lost a game to censoring. Against a protocol control
the same design is decisive (match win rate 1.000 over 256 completed games), so
the pipeline works; the sample design does not. Phase 5 should lengthen the
streams, adopt a censoring-aware estimator, or score matches by a statistic that
survives truncation.

The honest summary: rungs 2 to 4 form a weak but consistent ordering on this
bank, rung 1 sits below them mainly through its showing thresholds, and rung 5's
value is **not established** by any measurement in this report.

## Performance

Measured by `tuppi_agents.benchmark` on fixed deals with no CI threshold. Action
latency distribution, deals per second, feature-extraction cost, diagnostics
overhead, peak traced memory, and throughput relative to the first-legal control
on the same deals in the same process.

The headline structural finding is that the agents are cheap: the engine
revalidates the entire deal state on every accepted action, so it dominates the
measurement, and the ladder adds a small fraction on top. The relative column,
not the absolute wall-clock, is the meaningful comparison, and it is what
supports using these policies later as rollout policies or opponent models.

## Reproducing the frozen report

```bash
PYTHONPATH=src python -m tuppi_agents.runner run-suite \
  --bank-dir banks \
  --output-dir runs/phase4 \
  --report reports/phase4/baseline_report.json \
  --only all
```

`runs/` holds the raw per-game shards and is git-ignored; the committed artifact
is the report. The run is resumable at two levels: completed atomic shards are
reused inside a comparison, and `--resume-report` reuses whole comparison blocks
from an earlier report whose manifest identity still matches, so adding one new
comparison does not replay the others.

**Choose an output directory outside any cloud-synced tree.** The full suite
writes several hundred megabytes of raw shards. Producing that inside a folder
synced by iCloud Drive, Dropbox, or similar makes the sync daemon reconcile every
shard, which in this checkout stalled ordinary file reads with `ETIMEDOUT` until
the directory was removed and the daemon settled. Point `--output-dir` at local
scratch storage:

```bash
PYTHONPATH=src python -m tuppi_agents.runner run-suite \
  --bank-dir banks --output-dir "$TMPDIR/tuppi-phase4" \
  --report reports/phase4/baseline_report.json --only all
```

<!-- BEGIN GENERATED RESULTS -->
## Frozen results

Generated from `reports/phase4/baseline_report.json` by `examples/agents/render_report.py`. Paired utility is signed deal points per independently generated base deal, positive for Team A. These are development-bank numbers: descriptive, not sealed.

### Ladder and development comparisons

| Comparison | Team A | Team B | n | Mean paired utility (A - B) | 95% CI | Bootstrap CI | Sign p | Perm p | A deal win rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `deal_legacy_port_vs_reactive` | reactive_contract_v1 | legacy_heuristic_port_v1 | 64 | 2.75 | [0.80, 4.70] | [0.84, 4.72] | 0.008 | 0.008 | 0.586 |
| `match_partner_aware_vs_match_aware` | match_aware_v1 | partner_aware_v1 | 19 | 0.00 | [0.00, 0.00] | [0.00, 0.00] | n/a | 1.000 | 0.488 |

### Ablations

| Comparison | Team A | Team B | n | Mean paired utility (A - B) | 95% CI | Bootstrap CI | Sign p | Perm p | A deal win rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `deal_reactive_vs_counting` | public_counting_v1 | reactive_contract_v1 | 64 | 1.50 | [0.34, 2.66] | [0.44, 2.69] | 0.065 | 0.018 | 0.555 |
| `deal_counting_vs_partner_aware` | partner_aware_v1 | public_counting_v1 | 64 | 0.50 | [0.01, 0.99] | [0.06, 1.03] | 0.057 | 0.069 | 0.516 |
| `deal_partner_aware_vs_match_aware` | match_aware_v1 | partner_aware_v1 | 64 | 0.00 | [0.00, 0.00] | [0.00, 0.00] | n/a | 1.000 | 0.500 |
| `ablate_showing_legacy_vs_simple` | reactive_contract_v1 | reactive_contract_legacy_show_v1 | 64 | 2.38 | [0.65, 4.10] | [0.72, 4.09] | 0.011 | 0.013 | 0.594 |
| `ablate_legacy_convention_on_off` | partner_aware_v1 | partner_aware_legacy_convention_v1 | 64 | -0.09 | [-0.28, 0.09] | [-0.28, 0.00] | 1.000 | 1.000 | 0.492 |
| `ablate_match_state_on_off` | match_aware_v1 | match_aware_no_match_features_v1 | 64 | 0.00 | [0.00, 0.00] | [0.00, 0.00] | n/a | 1.000 | 0.500 |
| `deal_partner_aware_vs_match_aware_from_48` | match_aware_v1 | partner_aware_v1 | 64 | -1.03 | [-2.16, 0.10] | [-2.12, 0.06] | 0.034 | 0.105 | 0.500 |
| `ablate_match_state_on_off_from_48` | match_aware_v1 | match_aware_no_match_features_v1 | 64 | -1.03 | [-2.16, 0.10] | [-2.12, 0.06] | 0.034 | 0.105 | 0.500 |

### Protocol-control floor

| Comparison | Team A | Team B | n | Mean paired utility (A - B) | 95% CI | Bootstrap CI | Sign p | Perm p | A deal win rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `deal_match_aware_vs_control` | match_aware_v1 | control_first_legal | 64 | 13.72 | [11.95, 15.49] | [11.97, 15.38] | 0.000 | 0.000 | 0.906 |
| `match_match_aware_vs_control` | match_aware_v1 | control_first_legal | 32 | 1.00 | [1.00, 1.00] | [1.00, 1.00] | 0.000 | 0.000 | 1.000 |

### Declaration and outcome behaviour

| Comparison | RAMI rate | Stolen RAMI given RAMI | Reset rate | Mean tricks A | Mean tricks B | Failed games | Censored |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `deal_legacy_port_vs_reactive` | 0.500 | 0.234 | 0.000 | 6.58 | 6.42 | 0 | 0 |
| `deal_reactive_vs_counting` | 0.719 | 0.261 | 0.000 | 6.90 | 6.10 | 0 | 0 |
| `deal_counting_vs_partner_aware` | 0.719 | 0.250 | 0.000 | 6.51 | 6.49 | 0 | 0 |
| `deal_partner_aware_vs_match_aware` | 0.719 | 0.239 | 0.000 | 6.50 | 6.50 | 0 | 0 |
| `deal_match_aware_vs_control` | 0.391 | 0.120 | 0.000 | 5.77 | 7.23 | 0 | 0 |
| `ablate_showing_legacy_vs_simple` | 0.500 | 0.234 | 0.000 | 6.48 | 6.52 | 0 | 0 |
| `ablate_legacy_convention_on_off` | 0.719 | 0.239 | 0.000 | 6.52 | 6.48 | 0 | 0 |
| `ablate_match_state_on_off` | 0.719 | 0.239 | 0.000 | 6.50 | 6.50 | 0 | 0 |
| `deal_partner_aware_vs_match_aware_from_48` | 0.766 | 0.337 | 0.406 | 6.32 | 6.68 | 0 | 0 |
| `ablate_match_state_on_off_from_48` | 0.766 | 0.337 | 0.406 | 6.32 | 6.68 | 0 | 0 |
| `match_partner_aware_vs_match_aware` | 0.878 | 0.139 | 0.000 | 6.15 | 6.85 | 92 | 92 |
| `match_match_aware_vs_control` | 0.297 | 0.000 | 0.000 | 5.25 | 7.75 | 0 | 0 |

### Complete-match results

| Comparison | Streams | Completed games | Censored | Match win rate A |
| --- | --- | --- | --- | --- |
| `match_partner_aware_vs_match_aware` | 19 | 164 | 92 | 0.488 |
| `match_match_aware_vs_control` | 32 | 256 | 0 | 1.000 |

### Cross-play (8 base deals per cell, descriptive)

| Row team | Column team | Mean paired utility (row orientation) | n | Failures |
| --- | --- | --- | --- | --- |
| control_lowest_legal_card | partner_aware_v1 | -11.75 | 8 | 0 |
| control_lowest_legal_card | control_highest_legal_card | -0.50 | 8 | 0 |
| control_lowest_legal_card | control_seeded_random_legal | 0.81 | 8 | 0 |
| control_lowest_legal_card | public_counting_v1 | -11.75 | 8 | 0 |
| control_lowest_legal_card | heterogeneous_match_aware_with_reactive | -11.50 | 8 | 0 |
| control_lowest_legal_card | control_first_legal | 0.50 | 8 | 0 |
| control_lowest_legal_card | reactive_contract_v1 | -10.25 | 8 | 0 |
| control_lowest_legal_card | match_aware_v1 | -11.75 | 8 | 0 |
| control_lowest_legal_card | legacy_heuristic_port_v1 | -9.50 | 8 | 0 |
| control_lowest_legal_card | heterogeneous_match_aware_with_control | -6.38 | 8 | 0 |
| partner_aware_v1 | control_highest_legal_card | 13.50 | 8 | 0 |
| partner_aware_v1 | control_seeded_random_legal | 13.25 | 8 | 0 |
| partner_aware_v1 | public_counting_v1 | 1.00 | 8 | 0 |
| partner_aware_v1 | heterogeneous_match_aware_with_reactive | 1.25 | 8 | 0 |
| partner_aware_v1 | control_first_legal | 14.00 | 8 | 0 |
| partner_aware_v1 | reactive_contract_v1 | 1.50 | 8 | 0 |
| partner_aware_v1 | match_aware_v1 | 0.00 | 8 | 0 |
| partner_aware_v1 | legacy_heuristic_port_v1 | 3.75 | 8 | 0 |
| partner_aware_v1 | heterogeneous_match_aware_with_control | 6.12 | 8 | 0 |
| control_highest_legal_card | control_seeded_random_legal | 0.75 | 8 | 0 |
| control_highest_legal_card | public_counting_v1 | -14.25 | 8 | 0 |
| control_highest_legal_card | heterogeneous_match_aware_with_reactive | -13.12 | 8 | 0 |
| control_highest_legal_card | control_first_legal | -1.00 | 8 | 0 |
| control_highest_legal_card | reactive_contract_v1 | -12.75 | 8 | 0 |
| control_highest_legal_card | match_aware_v1 | -13.50 | 8 | 0 |
| control_highest_legal_card | legacy_heuristic_port_v1 | -12.50 | 8 | 0 |
| control_highest_legal_card | heterogeneous_match_aware_with_control | -9.88 | 8 | 0 |
| control_seeded_random_legal | public_counting_v1 | -14.44 | 8 | 0 |
| control_seeded_random_legal | heterogeneous_match_aware_with_reactive | -14.50 | 8 | 0 |
| control_seeded_random_legal | control_first_legal | -2.19 | 8 | 0 |
| control_seeded_random_legal | reactive_contract_v1 | -13.19 | 8 | 0 |
| control_seeded_random_legal | match_aware_v1 | -16.69 | 8 | 0 |
| control_seeded_random_legal | legacy_heuristic_port_v1 | -13.62 | 8 | 0 |
| control_seeded_random_legal | heterogeneous_match_aware_with_control | -8.50 | 8 | 0 |
| public_counting_v1 | heterogeneous_match_aware_with_reactive | 0.00 | 8 | 0 |
| public_counting_v1 | control_first_legal | 14.50 | 8 | 0 |
| public_counting_v1 | reactive_contract_v1 | -0.25 | 8 | 0 |
| public_counting_v1 | match_aware_v1 | -1.00 | 8 | 0 |
| public_counting_v1 | legacy_heuristic_port_v1 | 2.75 | 8 | 0 |
| public_counting_v1 | heterogeneous_match_aware_with_control | 5.25 | 8 | 0 |
| heterogeneous_match_aware_with_reactive | control_first_legal | 14.75 | 8 | 0 |
| heterogeneous_match_aware_with_reactive | reactive_contract_v1 | 0.00 | 8 | 0 |
| heterogeneous_match_aware_with_reactive | match_aware_v1 | -1.25 | 8 | 0 |
| heterogeneous_match_aware_with_reactive | legacy_heuristic_port_v1 | 3.00 | 8 | 0 |
| heterogeneous_match_aware_with_reactive | heterogeneous_match_aware_with_control | 5.50 | 8 | 0 |
| control_first_legal | reactive_contract_v1 | -15.00 | 8 | 0 |
| control_first_legal | match_aware_v1 | -14.00 | 8 | 0 |
| control_first_legal | legacy_heuristic_port_v1 | -13.50 | 8 | 0 |
| control_first_legal | heterogeneous_match_aware_with_control | -7.12 | 8 | 0 |
| reactive_contract_v1 | match_aware_v1 | -1.50 | 8 | 0 |
| reactive_contract_v1 | legacy_heuristic_port_v1 | 3.00 | 8 | 0 |
| reactive_contract_v1 | heterogeneous_match_aware_with_control | 4.62 | 8 | 0 |
| match_aware_v1 | legacy_heuristic_port_v1 | 3.75 | 8 | 0 |
| match_aware_v1 | heterogeneous_match_aware_with_control | 6.12 | 8 | 0 |
| legacy_heuristic_port_v1 | heterogeneous_match_aware_with_control | 5.38 | 8 | 0 |

### Performance

| Agent | Deals/s | Mean action latency (ms) | p95 (ms) | Relative wall clock |
| --- | --- | --- | --- | --- |
| `control:first_legal` | 6.91 | 0.000 | 0.000 | 1.000 |
| `legacy_heuristic_port_v1` | 6.38 | 0.087 | 0.222 | 1.084 |
| `reactive_contract_v1` | 6.61 | 0.073 | 0.111 | 1.045 |
| `public_counting_v1` | 6.36 | 0.184 | 0.285 | 1.086 |
| `partner_aware_v1` | 6.29 | 0.190 | 0.297 | 1.098 |
| `match_aware_v1` | 6.22 | 0.194 | 0.298 | 1.111 |

Diagnostics overhead ratio for `match_aware_v1`: 1.007 wall clock, with provably identical play.

Wall-clock values are hardware dependent. The engine revalidates the whole deal state on every accepted action, so it dominates the measurement; the relative column is the meaningful comparison.
<!-- END GENERATED RESULTS -->
