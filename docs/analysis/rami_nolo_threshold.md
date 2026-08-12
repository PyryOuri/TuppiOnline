# RAMI versus NOLO showing threshold

This is a research-only counterfactual experiment over the frozen `partner_aware_v1` policy. It does **not** modify or register a new production agent, and it directly generates deterministic deals without opening or reading any fixture bank. `sealed_bank_opened` is `false` in every result manifest.

## Current production decision rule

`partner_aware_v1` uses:

```text
RAMI score = HCP + 0.5*aces + 0.25*control_cards + 0.5*max(0, longest_suit_length-4)
NOLO score = 1.5*low_card_count + 3*void_count + 2*singleton_count + doubleton_count - top_five_count - 0.5*honour_count
choose RAMI iff RAMI score >= 15.0
                 and NOLO score <= 2.0
```

HCP is A=4, K=3, Q=2, J=1; controls are aces plus kings. Low cards are ranks 2–4, top-five cards are 10–A, and honours are J–A. The second comparison is an independent NOLO-suitability veto, so the production rule is not a single unconstrained scalar threshold.

Match score does not affect this profile (`match_state_enabled=false`). The experiment nevertheless cycles through table, up, down, and near-target match scores to verify that conclusion in context.

Both contracts are always legally expressible under the authoritative fallback hierarchy. Ranks 3–9 of the contract colour are preferred (red for RAMI, black for NOLO); otherwise an eligible off-colour 3–9 is shown verbally, and if none exists any hand card may be shown verbally. Conditional on a contract, the policy chooses the lowest eligible rank and then HDCS suit precedence. A RAMI declaration ends showing immediately; NOLO passes showing clockwise until another player declares RAMI or all four declare NOLO.

## Design and corpus

Each decision record starts both forced branches from the same immutable, private-state digest and preserves deal, seat, dealer, partnership, public showing history, hand, and match score. The forced action is the policy's own best-ranked legal action for that contract (the lowest eligible rank under this profile). Four ordinary frozen `partner_aware_v1` policies complete showing and trick play. A forced NOLO can therefore lead to a later player's RAMI, which is part of the real value of choosing NOLO now.

The estimand is the local contract choice at production-reachable showing states. Thresholds are applied to the same focal-decision corpus, while every later showing/play decision remains the frozen production policy, exactly as specified for the counterfactual comparison.

The primary utility is signed production deal points for the acting partnership: points won minus points conceded. This retains the real scoring asymmetry: made RAMI is `4 × (declaring tricks − 6)` while stolen RAMI is `8 × (defender tricks − 6)`. Trick count is secondary.

- Tuning: **4096 decisions from 1501 generated source deals** (`rami-nolo-threshold-tuning-v1`).
- Fresh held-out validation: **4096 decisions from 1491 generated source deals** (`rami-nolo-threshold-validation-v1`).
- Statistical cluster: source deal; confidence intervals resample whole source deals because one deal can contribute multiple decisions.
- Validation discipline: the candidate was frozen from tuning before validation; validation compares only that candidate with production. The full validation threshold curve was not inspected.

## Tuning threshold sweep

The sweep covers every 0.25 point across the observed RAMI-score range plus two points at each tail, holds the production NOLO veto at 2, includes threshold 15, and adds explicit always-RAMI and always-NOLO controls. The complete dense table is in `/Users/pyryouri/Developer/TuppiRuns/rami-nolo-threshold/tuning_threshold_sweep.csv` and the curve is in `/Users/pyryouri/Developer/TuppiRuns/rami-nolo-threshold/threshold_curve.svg`.

| Threshold/control | Mean utility | RAMI frequency | RAMI success | Stolen RAMI | Points scored | Points conceded |
|---|---:|---:|---:|---:|---:|---:|
| -2.00 | -0.117 | 83.4% | 62.0% | 38.0% | 5.988 | 6.105 |
| 11.50 | 0.973 | 53.7% | 70.5% | 29.5% | 6.215 | 5.242 |
| 11.75 | 1.052 | 50.7% | 71.1% | 28.9% | 6.228 | 5.176 |
| 12.25 | 1.102 | 47.0% | 71.8% | 28.2% | 6.239 | 5.138 |
| 12.50 | 1.085 | 46.1% | 72.0% | 28.0% | 6.224 | 5.139 |
| 13.00 | 1.058 | 43.1% | 72.5% | 27.5% | 6.209 | 5.151 |
| 13.50 | 0.952 | 39.2% | 72.8% | 27.2% | 6.172 | 5.220 |
| 15.00 | 0.818 | 28.8% | 76.2% | 23.8% | 6.081 | 5.263 |
| 32.00 | -1.697 | 0.0% | — | — | 4.824 | 6.521 |
| ALWAYS NOLO | -1.697 | 0.0% | — | — | 4.824 | 6.521 |
| ALWAYS RAMI | -1.137 | 100.0% | 58.8% | 41.2% | 5.684 | 6.820 |

- Numerical tuning maximum: **12.25** (mean utility 1.102).
- Prespecified one-SE near-optimal interval: **11.75 to 13.00**.
- Tuning-selected central candidate: **12.50**.
- Production threshold 15 in plateau: **false**.

## Fresh held-out comparison

| Policy | Mean utility | Deal-win probability | Expected tricks | RAMI frequency | RAMI success | Stolen RAMI | Points scored | Points conceded |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Current 15.00 | 0.750 | 53.7% | 6.711 | 28.4% | 76.7% | 23.3% | 6.103 | 5.353 |
| Candidate 12.50 | 1.057 | 57.2% | 6.772 | 47.3% | 72.4% | 27.6% | 6.270 | 5.213 |

- Mean paired utility difference, candidate minus current: **0.307 points per decision**.
- Source-deal-cluster bootstrap 95% CI: **[0.108, 0.516]** (5000 replicates).
- Decisions choosing a different contract: **775 / 4096**, across **573 source deals**.
- Decision-level win/tie/loss across all decisions: **{'loss': 304, 'tie': 3433, 'win': 359}**; among the 775 changed choices: **{'loss': 304, 'tie': 112, 'win': 359}**.
- Source-deal-level win/tie/loss across all source deals: **{'loss': 251, 'tie': 999, 'win': 241}**; among the 573 affected deals: **{'loss': 251, 'tie': 81, 'win': 241}**.

## Success probability and payoff around the threshold

| RAMI score | n | RAMI succeeds | RAMI stolen | RAMI − NOLO utility | Veto-pass n | Veto-pass success | Veto-pass RAMI − NOLO |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 9.75 | 65 | 46.2% | 53.8% | -6.154 | 61 | 45.9% | -6.361 |
| 10.00 | 94 | 54.3% | 45.7% | -4.128 | 67 | 55.2% | -3.881 |
| 10.25 | 42 | 50.0% | 50.0% | -2.762 | 39 | 53.8% | -2.564 |
| 10.50 | 104 | 57.7% | 42.3% | -0.500 | 84 | 61.9% | 0.381 |
| 10.75 | 32 | 59.4% | 40.6% | -3.000 | 32 | 59.4% | -3.000 |
| 11.00 | 128 | 56.2% | 43.8% | -1.250 | 103 | 57.3% | -1.553 |
| 11.25 | 46 | 67.4% | 32.6% | -1.217 | 40 | 67.5% | -0.400 |
| 11.50 | 149 | 59.7% | 40.3% | -1.181 | 129 | 61.2% | -0.465 |
| 11.75 | 38 | 52.6% | 47.4% | -5.895 | 29 | 55.2% | -4.828 |
| 12.00 | 124 | 58.9% | 41.1% | -0.645 | 112 | 58.0% | -0.036 |
| 12.25 | 39 | 71.8% | 28.2% | 0.103 | 33 | 72.7% | 1.576 |
| 12.50 | 121 | 62.0% | 38.0% | 1.322 | 109 | 63.3% | 1.431 |
| 12.75 | 71 | 66.2% | 33.8% | -0.563 | 61 | 68.9% | -0.525 |
| 13.00 | 90 | 66.7% | 33.3% | 1.111 | 85 | 67.1% | 1.694 |
| 13.25 | 66 | 60.6% | 39.4% | -0.424 | 56 | 66.1% | 0.857 |
| 13.50 | 106 | 58.5% | 41.5% | -1.057 | 100 | 58.0% | -0.560 |
| 13.75 | 73 | 64.4% | 35.6% | -0.603 | 64 | 70.3% | 1.125 |
| 14.00 | 58 | 65.5% | 34.5% | 3.586 | 58 | 65.5% | 3.586 |
| 14.25 | 82 | 69.5% | 30.5% | 5.756 | 76 | 73.7% | 7.000 |
| 14.50 | 64 | 65.6% | 34.4% | 0.625 | 61 | 65.6% | -0.197 |
| 14.75 | 110 | 68.2% | 31.8% | 1.745 | 105 | 66.7% | 1.867 |
| 15.00 | 40 | 77.5% | 22.5% | 2.500 | 39 | 76.9% | 2.769 |
| 15.25 | 110 | 66.4% | 33.6% | 0.327 | 106 | 66.0% | 0.566 |
| 15.50 | 28 | 82.1% | 17.9% | 6.857 | 28 | 82.1% | 6.857 |
| 15.75 | 95 | 74.7% | 25.3% | 4.084 | 91 | 75.8% | 4.615 |
| 16.00 | 32 | 65.6% | 34.4% | 3.375 | 31 | 64.5% | 3.742 |
| 16.25 | 84 | 72.6% | 27.4% | 5.238 | 83 | 72.3% | 5.542 |
| 16.50 | 35 | 77.1% | 22.9% | 5.714 | 35 | 77.1% | 5.714 |
| 16.75 | 72 | 80.6% | 19.4% | 6.444 | 69 | 79.7% | 6.493 |
| 17.00 | 37 | 64.9% | 35.1% | 8.000 | 36 | 63.9% | 8.000 |

Within one RAMI-score point of the tuning plateau (and only where the production NOLO veto passes), RAMI succeeded in **62.8%** of 1011 held-out decisions. Mean successful RAMI points were **9.398** and mean stolen-RAMI points conceded were **15.191**. Combining those empirical RAMI payoffs with the observed NOLO utility gives an approximate break-even RAMI success probability of **62.3%**. The first adequately populated exact score bin with non-negative veto-pass RAMI-minus-NOLO utility was **10.50**, at an empirical RAMI success probability of **61.9%**. Exact quarter-point bins are visibly noisy and non-monotone, so candidate selection uses the tuning plateau rather than this first crossing. These are environment-specific empirical estimates, not assumed 50% or 60% cutoffs.

## Stratified findings

The prespecified boundary subset contains **1011** held-out veto-passing decisions. Full strata are in `/Users/pyryouri/Developer/TuppiRuns/rami-nolo-threshold/stratified_analysis.json`.

| Dimension | Most NOLO-favouring stratum | Most RAMI-favouring stratum |
|---|---:|---:|
| Hand HCP | 7-9: -0.435 (n=46) | 13-15: 6.250 (n=32) |
| Longest suit | 6: -0.542 (n=155) | 5: 0.769 (n=458) |
| Suit shape | 4-4-4-1: -6.667 (n=33) | 6-3-2-2: 2.400 (n=55) |
| Shown-card rank | 7: -2.340 (n=53) | 6: 1.684 (n=95) |
| Dealer/forehand position | forehand: -0.275 (n=363) | dealer: 0.773 (n=150) |
| Previous NOLO shows | 0: -0.275 (n=363) | 3: 0.773 (n=150) |
| Match-score category | table: -0.527 (n=220) | down: 0.898 (n=401) |

Global-threshold adequacy: **appears adequate at the tested resolution** — no supported boundary-region sign reversal in the prespecified strata. Some small cells have large descriptive effects, but cells below the prespecified `n >= 100` evidence rule are hypothesis-generating only. The experiment does not implement a context-dependent replacement.

## Reproduction and artifacts

From the repository root:

```bash
PYTHONPATH=src python3 tools/run_rami_nolo_threshold.py --output-root /Users/pyryouri/Developer/TuppiRuns/rami-nolo-threshold --report docs/analysis/rami_nolo_threshold.md --tuning-decisions 4096 --validation-decisions 4096 --bootstrap-replicates 5000 --workers 8 --tuning-seed rami-nolo-threshold-tuning-v1 --validation-seed rami-nolo-threshold-validation-v1 --analysis-seed rami-nolo-threshold-analysis-v1
```

Machine-readable records, sweep tables, the paired comparison, score-conditional probabilities, stratification, summary, hashes, and plot are under `/Users/pyryouri/Developer/TuppiRuns/rami-nolo-threshold`. The decision JSONL files contain the exact acting hand and public history plus a full private-state digest; complete deals can be regenerated from the declared split seed and source-deal index.

Decision-gate reason: fresh held-out cluster-bootstrap interval excludes zero in favour of the candidate.

CHANGE SUPPORTED
