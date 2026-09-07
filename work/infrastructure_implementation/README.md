# INF-01 to INF-03 implementation evidence

Scratch evidence for the three bounded efficiency tasks of
[`docs/engine/efficiency_plan.md`](../../docs/engine/efficiency_plan.md).
The results and gate verdicts are written up in
[`docs/engine/efficiency_results.md`](../../docs/engine/efficiency_results.md).

`harness.py` takes a `--src` tree, so one workload measures two revisions in
separate processes. It calls only public entry points plus the same private
live-server helpers the read-only audit used, and never patches production code
for speed.

| File | What it is |
| --- | --- |
| `harness.py` | the workload: `--mode correctness`, `counts` or `timing` |
| `paired.py` | runs `harness.py --mode timing` for two trees in `ABBAABBAABBA` order |
| `analyse.py` | turns a paired file into the gate verdicts |
| `compare.py` | first structural difference between two correctness captures |
| `manifest.py` | reduces a 24 MB correctness capture to a committable manifest |
| `source_hashes_before.json` / `_after.json` | all 362 `src`/`tests` Python files; exactly 8 differ |
| `baseline_correctness_manifest.json` / `current_…` | per-section digests; identical apart from the capture file's own size and hash |
| `baseline_counts.json` / `current_counts.json` | validation, catalogue-build, reconnect and projection counts per operation |
| `inf01-paired.json` / `inf02-` / `inf03-` | each task measured alone against the same baseline |
| `all-paired.json` | all three together, and the no-regression check |
| `*-summary.txt` | `analyse.py` output for each of the above |

The full 24 MB correctness captures are deliberately not committed; regenerate
them with the commands in the results document. Re-running any of this
overwrites these outputs, so a follow-up task must freeze its own baseline
first.
