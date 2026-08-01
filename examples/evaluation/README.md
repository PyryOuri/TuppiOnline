# Evaluation examples

These are deliberately small Phase 3 fixtures, not evidence that any baseline
agent is strategically strong. Regenerate them from the repository root with:

```bash
PYTHONPATH=src python examples/evaluation/generate_examples.py
```

`small_deal_bank.json` and `baseline_comparison.json` can be passed to
`python -m tuppi_eval.runner compare`. `baseline_crossplay.json` is the
cross-play request. The other files exercise team composition, block-level
inference, failure quarantine semantics, resume identity, synthetic statistics,
matrix orientation, and the future promotion-decision schema.

`benchmark_smoke.py` runs 160 transformed games with trivial agents and reports
diagnostic throughput, serialization/summary time, and traced Python memory.
It intentionally asserts no performance threshold.
