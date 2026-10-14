# Hosted native backend

This isolated branch retains the frozen VRPO1/VRPO3/equity models and the current
controller parameters. It adds platform-aware `.dylib`/`.so` loading and atomic
native builds. `TUPPI_NATIVE_LIBRARY` can explicitly select a qualified library.

The compact128 integration adds exact ordinary reward buckets, batches of 128
and forced-row compaction. Settings belong to each native environment rather
than a process-wide switch. `best_agents` shares one immutable native VRPO1 model
when both rollout roles use that same file; each seat retains its own environment
and RNG. `speedups=False` constructs the reference configuration for checks.
Models, W1024, keep margins, adaptive bids and the six-trick tail are unchanged.
The browser adapter uses the same native sources and per-environment settings.
Qualification is recorded separately under
`audit_deliverables/tuppi_compact128_integration_20261014/`; the earlier hosted
and research records remain historical baselines.

- `native/build.sh` keeps the macOS Accelerate/dispatch build.
- `native/build.sh --portable` uses explicit float32 SIMD (NEON/SSE2/WASM) and
  serial native scheduling; accumulation order stays explicit.
- `native/build.sh --blas` keeps portable state/search and transposed weights,
  but uses Accelerate on macOS or OpenBLAS on Linux for matrix multiplication.

The browser build is unchanged. The hosted image uses `--blas` with one BLAS
thread and must pass frozen reference comparisons before deployment. Both
portable and optimised macOS variants matched the complete frozen W128 and
W1024 reference files exactly. This is finite synthetic equivalence, not a
strength result or universal mathematical equivalence between BLAS libraries.

A spawned-process screen of the same 12 W1024 positions preserved root actions
and RNG cursors. The observed maximum search decreased from 18.73 to 3.58 seconds
with optimised matrix multiplication; both bot processes peaked near 316 MB RSS.
These are macOS observations, not Linux capacity guarantees.

`models/hosted-models.json` pins only the three production model/table files.
Training and research packages are not activated. Actual Linux build/load,
reference comparisons, process qualification and hosted match capacity remain
required before an online release.
