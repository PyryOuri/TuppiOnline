# Validation and provenance

This delivery documents the codebase and proposes work. It does not claim a new playing-strength result or a measured efficiency gain. The saved [validation record](VALIDATION.json) contains actual navigation, metadata and source-hash checks. The [main report](REPORT.md) distinguishes current source settings from a running process's loaded configuration.

## Checks actually performed

| Check | Observed result | What it establishes |
|---|---|---|
| Explicit-tree source inventory and Python AST parsing | Earlier 1,906 files; ending 1,908 files; no recorded Python syntax errors | Selected source parses; no imports, native execution or semantic validation |
| Four source-body probes with dependency stubs | All four triggers reproduced; exact file hashes in `SOURCE_PROBES.json` | Python control flow for F01–F04; not full native/game impact |
| Prepared infrastructure standard-library suite | **63 tests, 228.393 seconds, OK, exit 0** | Covered configuration, paired-result, censoring, policy-prior/replay logic, process fixtures and queue accounting |
| Review script AST parsing | Recorded in `VALIDATION.json` | Syntax of the three delivered review tools |
| Markdown destinations, source paths and discovery pointer | **193 local links checked, none broken; workspace README pointer present** | Linked artifacts exist; does not attest external websites, anchor rendering or source semantics |
| Probe hashes versus ending inventory/current files | Recorded in `VALIDATION.json` | Reproduced findings refer to the saved source and unchanged checked files at verification |

The standard-library suite was run from `TuppiAI-prior` with:

```bash
python3 -B -m unittest discover -s tests -p 'test_*_stdlib.py' -v
```

Its test process completed successfully during this review. The observed result is retained in [STDLIB_CHECK.json](STDLIB_CHECK.json), with the ending checkout identity and inventoried test-file hashes. That record is a transcription of the observed tool result, not an independently signed CI log. Some process tests use dummy child processes; they do not validate production native-worker cleanup or real queue throughput. Tests use temporary fixtures rather than active run directories. No repeat suite was launched after success.

The suite covers more prepared work than the earlier 24-check policy-prior report because the separate queue/provenance implementation grew during this review. Passing small tests does not establish native/Torch parity, training throughput, model export correctness or game strength.

## Source changes during review

The earlier inventory completed at **06:14:06 UTC** on 2 October. The ending inventory ran from **07:31:39 to 07:50:30 UTC**. Both are sequential collections on a busy workspace, **not atomic filesystem snapshots**. Git metadata and individual file reads can occur at different times. The ending snapshot's duration should not be treated as standalone inventory performance. The inventory tool was refined to prune excluded trees and prevent overwriting an existing snapshot. The retained inventories and their explicit scopes are the evidence, rather than a claim that the whole workspace remained frozen. A further factory change after the ending inventory added `RAMI_MARGIN=0.0`; the final source probes record those exact newer bytes separately and recheck all four triggers.

| Checkout | Earlier HEAD | Ending HEAD | Ending dirty entries |
|---|---|---|---:|
| `TuppiAI` | `decd7e8` | `8ced46d` | 6 |
| `TuppiAI-prior` | `319e121` | `0799508` | 0 |
| `TuppiAI-sp` | `ca031fc` | `ca031fc` | 0 |
| `TuppiAI-vn` | `c581279` | `c581279` | 0 |
| `TuppiAI-perf` | `da299a3` | `da299a3` | 0 |
| `TuppiProject-current` | `dc554c4` | `dc554c4` | 2 |
| `TuppiProject` | `622d559` | `622d559` | 44 |
| `TuppiClient-current` | `7ba8ca2` | `7ba8ca2` | 2 |
| `TuppiClient` | `1d82b4b` | `1d82b4b` | 4 |

Full identities, dirty paths and selected source changes are in the JSON record. Main's adaptive/RAMI-bonus logic changed; the final documents qualify its allocation risk separately. The prior branch acquired checked paired results and frozen resumable queues, superseding its earlier registered implementation snapshot. The review did not make those production changes. Its own changes are confined to this output directory and one discovery section in the workspace `README.md`; that README pointer was added after the ending inventory.

## Coverage and exclusions

Manual review followed representative critical paths: rules and observation boundaries; native sampling/rollouts/solvers/model lifetime; current factory and action flow; duplicate and match evaluation; self-play and VRPO collection/labels/updates/checkpointing; prepared policy-prior/queue infrastructure; server and client transport/review; older search/belief/imitation and dirty NOLO/LLM capabilities; returned C0–C5, CVR/JRPL and self-play handoffs/results. Existing documents were reused rather than replaced.

The inventory covers explicit source/tests/docs/tools trees in nine checkouts, selected execution source trees and root discovery documents. It excludes credentials, private rooms/trajectories, saved user data, model directories, run data, archives, symlink targets and most build caches. Source copies under native research builds remain counted. A file count, AST import list or docstring flag does not mean that file's behavior was manually checked. The generated index is a navigation aid, not exhaustive developer API documentation.

The review performed **no native build/load, Torch training, game benchmark, client build/GUI test, server restart, private-room inspection, deployment or external headless-LLM invocation**. Existing local numerical results are reported with their source/evaluator; they were not reproduced. No scientific conclusion is drawn from a stub, syntax check or small contract test. No active job, installed library, model or immutable handoff was altered.

## Reproduce the review checks

From this directory:

```bash
python3 -B tools/source_probes.py --out SOURCE_PROBES_LATER.json
python3 -B tools/validate_review.py
```

The first command creates a new probe diagnostic against current source and may fail after repairs; it refuses to overwrite an existing filename. The second regenerates navigation from the saved ending inventory and checks current destinations against the original/final saved probe hashes. A source change can correctly cause it to fail; retain the existing evidence and record later work separately.

To take a **new** scoped inventory without overwriting either existing snapshot:

```bash
python3 -B tools/inventory.py --out SOURCE_SNAPSHOT_LATER.json
```

This is read-only on the repositories but can take time on a busy machine. It publishes exclusively to a new filename. For future production work, use the isolated implementation reports' deferred native/Torch commands after freezing source, models, equity table, library, engine, lifecycle and evaluation design. Those runtime gates remain outstanding.
