# Running the corpus on the Fedora host

The operational half of `docs/database/phase7_charter.md`, for the primary
generation host of decision D6: **Intel i7-6700K, 4 physical cores / 4 threads,
48 GB RAM, fast SSD, GTX 1070, no wall-clock limit.**

**There is a second machine, and for generation it is the better one.** The M3
Max MacBook Pro (14 cores, 36 GB, no CUDA) ran the T0 pilot at a measured **556
deals/s on 12 workers**, so 10M deals takes **~5 hours** there against ~37 on
this box. Every command below works unchanged on it - substitute the venv path
and use `--workers 12`. Two reasons this document still targets Fedora: it has
no wall-clock limit and does not belong to anybody's working day, and it holds
the only CUDA device. The natural division of labour is **generate on the Mac,
train on the 1070**; §6 is the only part that must run here.

Everything below is a command you can run and a number you should compare
against. Where a figure is an assumption rather than a measurement, it says so.

---

## 0. Before anything: calibrate (work package P1)

The charter's throughput table is an *assumption* - that a 6700K core delivers
0.35-0.50x of the M3 Max core the measurements were taken on. Replace it with a
measurement first, because everything downstream is sized from it.

```bash
cd /path/to/TuppiProject
python -m venv ~/.venvs/tuppi && ~/.venvs/tuppi/bin/pip install -e '.[dev]'

PYTHONPATH=src ~/.venvs/tuppi/bin/python work/phase7_planning/bench_authoritative.py 20
PYTHONPATH=src ~/.venvs/tuppi/bin/python work/phase7_planning/bench_history_growth.py
PYTHONPATH=src ~/.venvs/tuppi/bin/python work/phase7_planning/bench_fastpath_gate.py 6
PYTHONPATH=src ~/.venvs/tuppi/bin/python work/phase7_planning/bench_match_length.py 200
```

Reference values from the development Mac (M3 Max, CPython 3.14.2, one core):

| Measurement | Mac | Expect on the 6700K |
| --- | ---: | --- |
| authoritative engine | 278 actions/s | 100-140 actions/s |
| trusted mode, `partner_aware_lead_v2` | 2 588 actions/s, 47.3 deals/s | 17-24 deals/s |
| speedup | 11.1x | should hold - it is a work reduction, not a hardware effect |
| deals per match | mean 33.1, median 22, p99 156 | identical; it is a property of the rules |

**The gate is `bench_fastpath_gate.py`**: it must print `identical play: True`.
That is the differential check the trusted mode owes its callers, and a
`False` on this host means stop and investigate rather than proceed.

Also record, because the charter's calendar depends on them:

```bash
nproc; lscpu | grep -E 'Model name|Thread|Core'
free -g | head -2
df -h /var/lib
python -c "import sys; print(sys.version)"
```

**Hyper-threading.** The 6700K is a 4-core/8-thread part and the host reports 4
threads, so HT appears to be off. This workload is memory-latency-bound and
usually gains 15-30% from it. If it can be enabled in the firmware, measure 4
workers against 8 (§2) before committing to a setting - it is free throughput if
it holds up.

---

## 1. Sanity: the tests, on this host

```bash
PYTHONPATH=src ~/.venvs/tuppi/bin/python -m pytest tests/corpus tests/engine -q
```

Expect all green. The full suite takes ~17-25 minutes here and has one known
pre-existing failure,
`tests/learning/test_boundaries_and_schemas.py::test_product_package_increment_does_not_change_frozen_learning_layer`,
which pins `version = "0.13.0"` against a committed `0.13.1`. It predates this
work and belongs to whoever owns that packet.

---

## 2. The T0 pilot (work package P4 gate)

Never launch T1 without a full T0 pass. The pilot costs about half an hour here
and has caught three real defects already - a discarded final deal, an epsilon
branch that never fired in half its streams, and an unconstructible score
schedule.

```bash
CORPUS=/var/lib/tuppi-corpus          # any local path on the SSD; NOT in the repo
export PYTHONPATH=src OMP_NUM_THREADS=1

# What the manifest asks for, before generating anything.
~/.venvs/tuppi/bin/python -m tuppi_corpus.runner plan --stream-stop 5000 --shard-streams 250

# Generate.  --workers changes wall-clock time and nothing else.
time ~/.venvs/tuppi/bin/python -m tuppi_corpus.runner generate \
  --output $CORPUS/t0-pilot --stream-stop 5000 --shard-streams 250 --workers 4

# The gate: digests, a byte-identical rebuild in a fresh process, and
# authoritative replay of a sample.
~/.venvs/tuppi/bin/python -m tuppi_corpus.runner verify --output $CORPUS/t0-pilot --sample 200

~/.venvs/tuppi/bin/python -m tuppi_corpus.runner stats --output $CORPUS/t0-pilot
```

Measured on the Mac with 12 workers, for comparison:

| | Mac, 12 workers |
| --- | ---: |
| deals | 141 601 (5 728 matches) |
| wall time | 254.6 s |
| throughput | **556 deals/s** (46 per worker) |
| on disk | 9.2 MB, **68 bytes per deal** |
| deals per match | 24.7 |
| RAMI share | 0.781 (the Phase 5F evaluation independently reported 0.784) |

**T0 passes only if all four hold:**

1. `verify` prints `digests and row counts agree`, a rebuild that `reproduced
   its digest exactly`, and the sampled deals `agreed`;
2. `stats` shows every stratum present, with match-share and deal-share close to
   the plan's stream-share (they differ by design - paired strata make two
   matches per stream, and softening lengthens matches);
3. the RAMI share lands near 0.78;
4. `flagged deals` shows nonzero `forced_contract`, `forced_play`,
   `epsilon_branch`, `softened` **and** `revalidated`. A zero anywhere means a
   stratum silently produced ordinary play, which is exactly the class of defect
   the pilot exists to catch.

Then throw the pilot away. It is a cache of a pure function; the manifest is the
artifact.

---

## 3. P5 before P6, on this host especially

On four cores the optimisation work is the difference between a ~37-hour run and
plausibly under 12. **It stops being a gate if T1 runs on the Mac instead**,
where the same corpus takes ~5 hours - so treat this section as required only if
you generate here. Measured shares of the *trusted* path on the Mac:

| Target | Share of trusted runtime | What it is |
| --- | ---: | --- |
| **E2** deal-boundary revalidation | ~35% | `_validate_match_state` still rebuilds the whole match history at each deal boundary, and the history grows |
| **E3** `public_inference.build` | ~27% | rebuilt from scratch once per decision, scanning the deal history each time |
| **E5** PyPy | unmeasured | the generator has no C dependency, so this is a pure measurement question |

E5 is the cheapest to settle and possibly the largest:

```bash
# PyPy 3.11 satisfies the project's >=3.11,<3.15 range.
pypy3 -m venv ~/.venvs/tuppi-pypy && ~/.venvs/tuppi-pypy/bin/pip install -e '.[dev]'
PYTHONPATH=src ~/.venvs/tuppi-pypy/bin/pypy3 work/phase7_planning/bench_fastpath_gate.py 6
```

Two conditions on adopting it: `identical play: True`, and a T0 pilot whose
shard digests match the CPython ones exactly. If digests diverge, something in
the generator is interpreter-dependent and that is a defect to find, not a
tolerance to accept. Note that `compression.zstd` is CPython 3.14; PyPy 3.11
will fall back to zlib, which changes the *file* but not the payload digest -
that is why the digest covers the uncompressed payload.

---

## 4. T1: the 10M-deal run (work package P6)

Sizing from the pilot: 24.7 deals per match, ~28 deals per stream across the
mixture. **10M deals needs roughly 355 000 streams**; the invocation below uses
400 000, which overshoots to ~11.3M and is the safer direction to err in.

On the Mac, use `--workers 12` and expect ~5 hours.

```bash
CORPUS=/var/lib/tuppi-corpus
export PYTHONPATH=src OMP_NUM_THREADS=1

nohup ~/.venvs/tuppi/bin/python -m tuppi_corpus.runner generate \
  --output $CORPUS/t1 \
  --root-seed tuppi-corpus-t1-v1 \
  --stream-stop 400000 \
  --shard-streams 2000 \
  --workers 4 \
  > $CORPUS/t1/generate.log 2>&1 &
```

200 shards of 2 000 streams each. Shard size is a trade: larger shards mean
less catalogue overhead, smaller ones mean less lost work on interruption. At
2 000 streams a shard is ~50 000 deals and ~20 minutes of one core here, which
is a reasonable amount to lose to a power cut.

**It is resumable.** Re-run the identical command and it regenerates only the
shards absent from the catalogue. The manifest is written on first use and the
run refuses to continue if the requested parameters would produce a different
`run_id`, so a resumed run cannot quietly mix two configurations.

Expected, at the assumed 20 deals/s per worker:

| | 4 workers |
| --- | ---: |
| throughput | ~80 deals/s |
| 10M deals | ~35 hours |
| on disk | ~700 MB |

Monitor with:

```bash
tail -f $CORPUS/t1/generate.log
wc -l $CORPUS/t1/catalog.jsonl        # shards completed, out of 200
du -sh $CORPUS/t1/shards
```

Then verify, and this time verify properly:

```bash
~/.venvs/tuppi/bin/python -m tuppi_corpus.runner verify --output $CORPUS/t1 --sample 2000
~/.venvs/tuppi/bin/python -m tuppi_corpus.runner stats  --output $CORPUS/t1
```

---

## 5. Storage discipline

- The corpus goes on a **plain local filesystem outside the repository**, and
  never inside iCloud or any synced folder - the README already records a
  synced-tree failure, and these are hundreds of megabytes of research-private
  deals.
- `deals` carry **complete hidden hands**. Treat the directory as
  research-private. Do not copy it anywhere a policy could read it, and derive
  model inputs only through `tuppi_corpus.replay`.
- Keep the `manifest.json` and `catalog.jsonl` even if you delete the shards.
  Those two files plus the pinned source digests *are* the corpus.

---

## 6. The GPU, when you get to training

Generation never touches it. Before planning any training around the 1070:

```bash
~/.venvs/tuppi/bin/pip install '.[learning]'
~/.venvs/tuppi/bin/python -c "import torch; print(torch.__version__, torch.cuda.is_available()); print(torch.cuda.get_arch_list())"
```

`sm_61` must appear in the arch list. Recent PyTorch wheels have been dropping
Pascal; if it is missing, pin an older wheel/CUDA pair or build from source.
`pyproject.toml` currently asks for `torch>=2.13,<2.14`, which needs confirming
against this card specifically.

Do not expect mixed precision to help: GP104's fp16 throughput is a small
fraction of its fp32 throughput. Train fp32. 8 GB and ~6.5 fp32 TFLOPS are
ample for the 1-20M parameter range, which is the right size class - Phase 6's
actor had 41 900 parameters, and part of why it had nothing to learn from was
that there was nothing to learn *with*.

The realistic bottleneck is the input pipeline. Replay measured **16 481
decisions/s on one core**, so a handful of loader processes saturate this card
comfortably; pre-materialise memory-mapped tensor caches per encoder version
rather than replaying inside the training loop.

---

## 7. Two pyproject lines that are not committed yet

`pyproject.toml` carries another author's pending edits (an `llm` extra and the
`tuppi-valuation` entry point), so only the corpus's own two lines were
committed. Nothing here depends on them - `python -m tuppi_corpus.runner` is the
invocation used throughout this document - but `tuppi-corpus` as a console
script arrives when that file is next committed.
