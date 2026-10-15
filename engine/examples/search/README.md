# Phase 5C search examples

Small, fast, reproducible. Every command below is deterministic: the same inputs and
seeds produce the same decision, the same candidate values, and the same diagnostics.

Write bulk output outside the repository. These examples write nothing large.

## List the registered agents and the utility adapters

```bash
python -m tuppi_search.runner agents
python -m tuppi_search.runner utilities
```

`trick_split_v1` reports `registerable=False`: it ignores the 6/7 boundary that
decides who wins the deal, so it is available for ablation only.

## Run the boundary gate

```bash
python -m tuppi_search.runner validate
```

Checks that no earlier package imports the search layer, that the frozen Phase 4
agents still disclaim search, that `match_aware_v1` is not retuned, that
`development_reference_v1` still resolves to the committed `partner_aware_v1`, that no
excluded technique family is present, and that the sealed bank is unopened.

## One trick-play decision, with action-value diagnostics

```bash
python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_smoke_v1 \
  --seat 1 --tricks 9
```

Prints one line per legal action with its mean utility, spread, and root-team deal-win
count, then the selection gap. A gap of exactly `0.000000` means the sample could not
separate the top actions and the canonical order broke the tie.

## One showing decision

```bash
python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_smoke_v1 \
  --seat 1 --tricks 0
```

Showing candidates are `(contract, card)` pairs. Expect several cards of one contract
to score identically: the shown card is public but changes no contract, leader, or
trick, so it usually moves nothing.

## Exact tail on versus off

```bash
python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_standard_v1 --seat 1 --tricks 9 \
  --output "$TMPDIR/tail-off.json"

python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_exact_tail_v1 --seat 1 --tricks 9 \
  --output "$TMPDIR/tail-on.json"
```

Compare `simulation_counts.solver_calls` (zero versus positive) and
`exact_tail.max_tricks_remaining`. The two may choose different actions, and that is
expected rather than a defect: the tail changes the estimand, not the currency. See
`docs/search/exact_tail_integration.md`.

## Deterministic replay

Re-running any `explain` command reproduces the decision exactly. The seed is derived
from the policy seed and the **information state**, so two different real deals that
present the same observation also produce the same worlds:

```bash
python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_smoke_v1 --seat 1 --tricks 9 \
  --output "$TMPDIR/first.json"

python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_smoke_v1 --seat 1 --tricks 9 \
  --output "$TMPDIR/second.json"

# Identical apart from operational_timing, which is not part of the decision.
diff <(python -c "import json,sys;d=json.load(open('$TMPDIR/first.json'));d.pop('operational_timing');print(json.dumps(d,indent=1,sort_keys=True))") \
     <(python -c "import json,sys;d=json.load(open('$TMPDIR/second.json'));d.pop('operational_timing');print(json.dumps(d,indent=1,sort_keys=True))")
```

## A CI-sized match comparison

PIMC is expensive: about 20 minutes per complete-match pair per worker at the
four-world budget. Start small and read the measured throughput first.

```bash
python -m tuppi_search.runner benchmark --streams 1

python -m tuppi_search.runner compare \
  --candidate uniform_feasible_pimc_smoke_v1 \
  --opponent partner_aware_v1 \
  --pairs 2 --workers 2 \
  --output "$HOME/TuppiRuns/phase5c/example-compare.json"
```

Two pairs resolves nothing statistically. It proves the protocol runs, that no leg was
censored, and that no decision failed.

## Deal-level screening

Roughly thirty times cheaper than a complete match, and the right instrument for
ablations:

```bash
python -m tuppi_search.runner ablate \
  --candidate uniform_feasible_pimc_smoke_v1 \
  --opponent partner_aware_v1 \
  --deals 4 \
  --output "$HOME/TuppiRuns/phase5c/example-ablation.json"
```

Deal-level results screen for behavioural differences. Phase 5A established that
signed deal value is blind to match safety, so they never support a match-strength
claim.
