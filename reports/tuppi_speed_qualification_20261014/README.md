# Qualified Tuppi computation baseline

The selected `compact128` baseline combines reward buckets, shared immutable VRPO1 rollout weights, chunk 128 and forced-row compaction. W1024, margins, models, equity and controller lifecycle stay fixed. It saved a median paired 34.6% serial CPU on the two-deal technical timing bank, with exact action/value/RNG traces. Read [REPORT.md](REPORT.md) for the native-parallel latency results and exact validation boundaries.

The original [prepared package](../tuppi_cheap_wins_preparation_20261014/README.md) and [additional probes](../tuppi_additional_exact_wins_20261014/REPORT.md) remain immutable. The product and installed native library were not replaced.

## Verify and preview

Run from this directory. The launcher uses the recorded product Python executable and selects the frozen sources explicitly.

```bash
python3 -B launch_analysis.py verify
python3 -B launch_analysis.py preview configs/strength_costing.json
python3 -B launch_analysis.py preview configs/heuristic_guard_costing.json
python3 -B launch_analysis.py preview configs/match_costing.json
```

`run` without `--execute` also previews. The proposed costing budgets are 3,600 CPU seconds for the six-job strong-panel plan, 1,800 for the three-job heuristic guard and 600 for the capped match pair. These are reservation ceilings, not expected durations or powered strength doses. Each duplicate job has two parent bundles, with all eight indexed games required per parent.

When a bounded costing run is assigned, use a new result directory:

```bash
python3 -B launch_analysis.py run configs/strength_costing.json --out analysis_runs/strong_costing_01 --execute
python3 -B launch_analysis.py run configs/heuristic_guard_costing.json --out analysis_runs/guard_costing_01 --execute
python3 -B launch_analysis.py run configs/match_costing.json --out analysis_runs/match_costing_01 --execute
```

These plans were prepared, not executed. There is no automatic retry, continuation after a failed cap or automatic confirmation sizing. Compare complete, compatible parent bundles using the preceding strict statistics tool:

```bash
python3 -B ../tuppi_cheap_wins_preparation_20261014/launch.py compare analysis_runs/strong_costing_01/hard_anchor_vs_baseline/result.json analysis_runs/strong_costing_01/baseline_vs_baseline/result.json --out analysis_runs/strong_costing_01/hard_anchor_comparison.json
```

The result context identifies this qualified package, the original frozen snapshot and the common speed variant. All searched arms and searched opponents receive the same selected speed settings. Statistical design and promotion gates remain in the preceding [protocol](../tuppi_cheap_wins_preparation_20261014/PROTOCOL.md); the new package supersedes its chunk/native-baseline choice for these new costing plans, without changing its hypothesis definitions or outcomes.

## Qualification files

| File | Purpose |
|---|---|
| [QUALIFIED_BASELINE.json](QUALIFIED_BASELINE.json) | Selected native binary and exact settings |
| [SUMMARY.json](SUMMARY.json) | Paired technical repetitions and selection |
| [GATES.json](GATES.json) | Engineering thresholds recorded before W1024 timing |
| [BUILD.json](BUILD.json) | Private compiler/source/native identities |
| [PLAN.json](PLAN.json) | Original finite qualification dose and code hashes |
| [bindings.py](bindings.py) | Shared implementation for all prepared searched arms |
| [FACTORY_CHECK.json](FACTORY_CHECK.json) | Baseline/hard-anchor/ensemble factory wiring |
| [WRAPPER_CHECK.json](WRAPPER_CHECK.json) | W4 identity-control evaluation pipeline |
| [PACKAGE.json](PACKAGE.json) | Sealed implementation, configurations and evidence |
| [VALIDATION.json](VALIDATION.json) | Final integrity, CLI and document checks |

Qualification outputs are under `runs`; future scientific attempts stay under `analysis_runs`. Preserve existing files and hashes. A change to models, source, parameters, study design or selected baseline requires a new version.
