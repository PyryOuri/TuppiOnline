# Phase 7 planning measurements

The four scripts that produced the measured figures in
`docs/database/phase7_charter.md` §1. They are planning instruments, not part of
the package, and they write nothing.

Run each from the repository root with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python work/phase7_planning/bench_authoritative.py 20
PYTHONPATH=src python work/phase7_planning/bench_history_growth.py
PYTHONPATH=src python work/phase7_planning/bench_fastpath_gate.py 6
PYTHONPATH=src python work/phase7_planning/bench_match_length.py 200
```

| Script | Question | Result on the development Mac (M3 Max, CPython 3.14.2, one core) |
| --- | --- | --- |
| `bench_authoritative.py` | raw self-play throughput on the authoritative engine | 278-299 actions/s, 54.7 actions/deal |
| `bench_history_growth.py` | is per-action cost constant over a match | no: 1.55 ms at deal 1 -> 2.14 ms at deal 22 |
| `bench_fastpath_gate.py` | what does eliding defensive revalidation buy, and does play change | 12.4x, and all 11 615 checkpoints identical |
| `bench_match_length.py` | match-length distribution, fast-path throughput at scale | mean 33.1 deals, median 22, p99 156, max 245; 3 450 actions/s |

`bench_fastpath_gate.py` is also the shape the **E1** differential gate should
take: run the same streams twice, compare every `(stream, actor, serialised
action)` triple in order plus each match's final score and deal count.

The two scripts that neutralise validation do so by rebinding
`tuppi_engine.match._validate_match_state` and
`tuppi_engine.state._validate_deal_state` in the benchmark process only. That is
a measurement device for establishing the upper bound; it is **not** the proposed
implementation, which is described as E1a/E1b in the charter.

Phase 7 work package **P0** is to re-run all four on the Fedora generation host
and replace the charter's §7.1 assumption table with measurements.
