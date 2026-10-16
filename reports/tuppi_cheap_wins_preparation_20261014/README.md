# Prepared Tuppi cheap improvements analyses

The four candidate arms are implemented in an isolated package, with the current engine, models, equity table and native comparator frozen by hash. The live app and other author's checkouts are unchanged. Start with [the analysis protocol](PROTOCOL.md) for exact interventions, controller lifecycles, proposed budgets and promotion gates; the preceding [critical assessment](../tuppi_cheap_wins_assessment_20261014/REPORT.md) supplies their rationale.

Preparation checks passed: 11 candidate/statistics tests, 14 native root comparisons including W1024 solver tails, and 16 authoritative W4 games forming two baseline identity-control bundles. The rebuilt library, reward-bucket library with its option disabled/enabled, and identical-model arm matched the checked reference root values and RNG. All four plans passed preview and default-run checks without creating execution output.

One complete W1024 deal also matched every action/value/RNG fingerprint for both speed arms across 58 decisions: four bids, two sooli offers and 52 plays. The [reward-bucket check](checks/w1024_qualification/comparison.json) used about 22.5% less CPU; the [identical-model check](checks/w1024_qualification/same_net_comparison.json) used about 10.6% less. These are single-deal observations, without repeated timing or separate construction accounting. Broader contract coverage, accepted/forced-sooli histories, repeated speed measurements and scientific strength comparisons remain pending.

## Commands

Run from this directory. The launcher uses the recorded product interpreter and explicit frozen source paths.

```bash
python3 -B launch.py verify
python3 -B launch.py preview configs/strength_costing.json
python3 -B launch.py preview configs/speed_validation.json
python3 -B launch.py preview configs/match_costing.json
python3 -B launch.py preview configs/heuristic_guard_costing.json
```

`run` is also a preview unless `--execute` is supplied. When the next bounded analysis is assigned and compute is available, use a new directory:

```bash
python3 -B launch.py run configs/strength_costing.json --out runs/strength_costing_01 --execute
python3 -B launch.py run configs/speed_validation.json --out runs/speed_validation_01 --execute
python3 -B launch.py run configs/match_costing.json --out runs/match_costing_01 --execute
python3 -B launch.py run configs/heuristic_guard_costing.json --out runs/heuristic_guard_costing_01 --execute
```

Each plan is independent. Run the initial speed qualification before adopting either speed change; price strength jobs before increasing their sample size. The strength-costing and guard plans contain compatible reference jobs. A successful run publishes results under its named job directory. Compare a candidate with its matching reference:

```bash
python3 -B launch.py compare runs/strength_costing_01/hard_anchor_vs_baseline/result.json runs/strength_costing_01/baseline_vs_baseline/result.json --out runs/strength_costing_01/hard_anchor_comparison.json
python3 -B launch.py compare runs/strength_costing_01/suit_ensemble_vs_baseline/result.json runs/strength_costing_01/baseline_vs_baseline/result.json --out runs/strength_costing_01/ensemble_comparison.json
python3 -B launch.py compare_traces runs/speed_validation_01/reward_bucket/result.json runs/speed_validation_01/baseline_before/result.json --out runs/speed_validation_01/reward_bucket_comparison.json
python3 -B launch.py compare_traces runs/speed_validation_01/same_net/result.json runs/speed_validation_01/baseline_after/result.json --out runs/speed_validation_01/same_net_comparison.json
```

No confirmation is automatically scheduled or sized. Two-parent costing outputs do not support an efficacy conclusion. All published reports are exclusive writes; failed attempts stay recorded and a later attempt requires a new run directory. This first package has no partial-job resume or automatic retry.

## Files

| File | Purpose |
|---|---|
| [FROZEN.json](FROZEN.json) | Captured source/model/native identity and original checkout state |
| [candidates.py](candidates.py) | Current-margin hard anchor, root suit ensemble, identical-model factory and diagnostics |
| [build_native.py](build_native.py) | Private baseline/reward-bucket builds and reviewable source patches |
| [NATIVE_BUILD.json](NATIVE_BUILD.json) | Compiler commands, binary and C source hashes |
| [worker.py](worker.py) | Fresh duplicate bundles, retained full-deal traces and censored match costing |
| [launch.py](launch.py) | Hash checks, dry-run preview, finite caps and attempt publication |
| [statistics_tools.py](statistics_tools.py) | Strict parent/game pairing, trace comparisons and unknown-match bounds |
| [PREPARATION_CHECKS.json](PREPARATION_CHECKS.json) | Exact scope and results of completed preparation checks |
| [PACKAGE.json](PACKAGE.json) | Sealed code, configurations, protocol and preparation evidence |

The `frozen` sources are evidence and should remain immutable. The runtime's optional loader and MLP hook are explicit in `freeze.py`. Private build source patches are under `builds/reward_bucket`; the installed native library was not replaced. To change source, parameters, identities or the study design, prepare a new version and preserve this package and its attempts.
