# The complete-match duplicate protocol

`src/tuppi_match/` is the definitive complete-match evaluator for
`project_target_v1`. It exists because Phase 4's match mode could not support
strength inference: it capped streams at 40 deals, which sat near the *median*
observed match length, and censored roughly a third of all pairs.

Phase 5A does not add strategy. It adds a measurement instrument, and it
measures the five frozen Phase 4 agents without touching them.

## The unit: one complementary pair

For every independent stream fixture the protocol plays two legs.

| | Seats 0 and 2 | Seats 1 and 3 |
| --- | --- | --- |
| **Leg E** | candidate | opponent |
| **Leg O** | opponent | candidate |

Both legs:

- start at the same score, normally 0-0;
- use the same initial dealer;
- read the **same** extensible deterministic stream;
- rotate the dealer by `project_target_v1`;
- run to **natural termination**: until one partnership reaches at least 52.

The legs may consume different prefix lengths of the stream, and **the longer
leg keeps going**. Nothing is truncated to the shorter one. The shorter leg's
consumed deals are always a prefix of the longer leg's, which the pair record
validates on construction.

A `PairRecord` is the independent statistical unit. A `LegRecord` is not: the
two legs of a pair share their deals by construction and are strongly
correlated, which is the entire point of the duplicate design.

## Extensible deterministic streams

A stream is an unbounded sequence of complete deals addressed by exactly four
values:

```text
deal(protocol_version, root_seed, stream_index, deal_index)
```

`MatchStream.deal(k)` is a pure function of those four values. The property
that carries the protocol is **random access**: recovering deal 500 never
requires generating deals 0 to 499 and never consumes mutable RNG state - the shuffle is a SHA-256 counter Fisher-Yates whose per-swap value is
derived from the index. Three consequences carry the protocol:

- the two legs of a pair read the same deals while running to different
  lengths;
- a stream extends on demand without disturbing its prefix;
- **execution order, worker count, and chunk size cannot change any deal.**

`iter_deals(chunk_size=n)` exists only to bound working memory. The test suite
asserts that chunk sizes 1, 2, 3, 5, 8, 20, and 64 produce identical streams.

Stream identity is a digest over canonical semantic content. Output paths,
timestamps, machine names, and run directories are excluded by construction:
they are never inputs.

A stream supplies **hands only**. The dealer comes from the engine's own
rotation starting at the stream's `initial_dealer`, so a longer leg simply keeps
rotating.

### Sealed fixtures never reach a policy

The engine label handed to `create_match` is `cm-<leg>-<ordinal>`. It is
visible inside every `PlayerObservation`, so it is derived from an ordinal and
never from the stream, the bank, or the seed. A sealed fixture identity cannot
reach an agent through the observation boundary.

## The primary endpoint

For a completed pair, with `Y = +1` when the *even* partnership wins a leg:

```text
D_match = (Y_E - Y_O) / 2
```

| `D_match` | Meaning |
| --- | --- |
| `+1` | the candidate won both orientations |
| `0` | each side won one orientation |
| `-1` | the opponent won both orientations |

The primary endpoint is the candidate's orientation-averaged match win
probability, `(1 + mean(D_match)) / 2`, reported with its advantage over 50 %,
standard error, fixed-horizon paired interval, whole-pair bootstrap interval,
whole-pair sign-flip randomization result, complementary-leg correlation, match
length distributions, and censoring counts.

Legs, deals, transformations, tricks, and decisions are **not** independent
observations and are never counted as such.

## Censoring

A leg that reaches the infrastructure safety cap is
`censored_infrastructure`. It is never a draw, never a policy win, and never a
policy loss. Its pair is `incomplete_censored`, carries no `D_match`, and is
excluded from the primary analysis entirely. The record type enforces this: a
leg that is not complete cannot claim a winner, and a pair with an unfinished
leg cannot carry a pair value.

See `docs/match/censoring.md` for the cap calibration.

## Determinism under parallelism

Every work unit is `(manifest, comparison, pair ordinal)` and is a pure
function of those. `run_experiment` therefore accepts any worker count, and the
test suite runs the same experiment at several worker counts and compares
record identities. Results are reassembled in canonical ordinal order, so even
the ordering of the output is independent of scheduling.

If a worker interpreter cannot start - which happens when the session has no
importable `__main__`, or when the filesystem stalls - the executor finishes
the remaining units serially. The protocol makes the two paths equivalent, so
that changes only how long the run takes.

## Storage and reproducibility

One experiment directory holds:

```text
manifest.json        the resolved immutable manifest
frozen_agents.json   the Phase 4 baseline snapshot used
pairs/<id>.json      every pair record, complete or not
inventory.json       trusted and quarantined work units
report.json          the aggregate report
```

Pairs are checkpointed as a contiguous prefix while the run proceeds, so an
interrupted run resumes instead of replaying. Rerunning an existing semantic
work unit must reproduce the same semantic result or raise
`IntegrityConflictError`. Wall-clock durations are excluded from semantic
identity: a slower machine is not a conflict, a different action is.

### Recommended scratch path

**Do not write experiment output inside a cloud-synced directory.** This
repository lives under an iCloud-synced `Documents` tree, and a Phase 4 run that
wrote several hundred megabytes there caused the sync daemon to stall ordinary
file reads with `ETIMEDOUT` until the directory was removed. Use local scratch:

```bash
PYTHONPATH=src python -m tuppi_match.runner run \
  --design calibration --pairs 256 \
  --output-dir "$TMPDIR/tuppi-phase5a/calibration" --workers 6
```

`reports/phase5a/` holds only the small committed artifacts: the frozen agent
snapshot and the aggregate reports.

## Command line

```bash
# Write or verify the frozen Phase 4 baseline snapshot
python -m tuppi_match.runner freeze --output reports/phase5a/phase4_frozen_agents.json
python -m tuppi_match.runner freeze --verify reports/phase5a/phase4_frozen_agents.json

# Resolve a manifest without running anything
python -m tuppi_match.runner plan --design calibration --pairs 256 --output manifest.json

# Execute, resuming automatically from whatever is already stored
python -m tuppi_match.runner run --design calibration --pairs 256 \
  --output-dir "$TMPDIR/tuppi-phase5a/calibration" --workers 6

# Rebuild a report from stored pairs without running anything
python -m tuppi_match.runner report --design calibration --pairs 256 \
  --output-dir "$TMPDIR/tuppi-phase5a/calibration" --output reports/phase5a/calibration.json

# Sealed-bank lifecycle
python -m tuppi_match.runner seal --action create --seed-file ~/.tuppi/sealed.json \
  --seed "<seed>" --output reports/phase5a/sealed_commitment.json
python -m tuppi_match.runner seal --action open --seed-file ~/.tuppi/sealed.json \
  --reason "<why>" --output opening_record.json
```

## What Phase 5A deliberately does not contain

No perfect-information solving, alpha-beta, PIMC, determinization, ISMCTS,
POMCP, hidden-hand sampling, probabilistic beliefs, particle filters, neural
models, reinforcement learning, self-play, new strategic heuristics, retuning of
Phase 4 profiles, GUI, or networking. The five Phase 4 agents are measured, and
a behaviour digest over their complete action sequences proves they did not
move.
