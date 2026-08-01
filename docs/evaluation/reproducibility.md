# Evaluation reproducibility

## Identity and canonical data

Semantic artifacts use compact UTF-8 JSON with sorted keys, no NaN/infinity,
and duplicate-key rejection on input. IDs are SHA-256 digests of canonical
content, never Python reprs, memory addresses, file paths, or wall timestamps.

Deal-bank identity includes the ordered complete deals, ruleset, generator and
shuffle versions, root seed, and dealer policy. Human creation metadata is
retained but excluded from identity. Agent IDs include implementation,
compatibility, determinism/seed policy, parameters, optional checkpoint/search
budget, and partner convention. Descriptions are retained display metadata.

Game and evaluation semantic IDs exclude measured durations. Operational files
still retain durations and timestamps. This separation allows two machines to
agree on results without pretending their clocks and throughput are identical.

## Seed separation

The seed hierarchy has three mandatory roots:

- the deal root derives each `(index, shuffle step)` independently;
- the agent root derives each `(schedule entry, seat, agent ID)` independently;
- the analysis root derives bootstrap and permutation replicates.

No mutable global RNG stream is used. Generating deals out of order, resuming
rows, or changing future worker count therefore cannot move another deal or
agent's random stream. The deterministic shuffle is
`sha256_counter_fisher_yates_modulo_v1`: a descending Fisher–Yates pass whose
choice at every step is the SHA-256-derived integer modulo the current prefix.
Its exact generator version is stored in every bank.

## Atomic shards and resume

Every JSON artifact is written to a temporary regular file, flushed, and
atomically replaced. A schedule entry has one filename derived from its
position and stable ID. Resume strictly validates that shard, its evaluation
and entry IDs, and—on success—the retained raw result digest. Completed entries
are not rerun. Failed rows remain quarantined and continue to invalidate their
blocks.

The manifest records configuration, registry, bank and schedule digests; git
commit and dirty status; ruleset and engine identity; installed package
version; Python and platform; all seed roots; analysis seed; worker count;
failure count; start/completion timestamps; result ID; and output artifact
digests. Timestamps and performance measurements are not in semantic result
digests.

## Installed distribution name

The distribution is named `tuppi-research`, while the legacy command and
archive installation paths retain their existing compatibility names. The
neutral distribution name reflects that the wheel now contains authoritative
rules, the clean engine, and evaluation—not merely the frozen legacy archive.
The rename was performed before the Phase 2 commit and did not alter imports,
console compatibility, archive bytes, or rules/engine identities.

## Reproduction checklist

1. Check out the manifest commit and verify dirty status expectations.
2. Install the recorded `tuppi-research` version on a compatible Python.
3. Validate the bank, config, and schedule through their strict loaders.
4. Run `python -m tuppi_eval.runner compare` into any new output directory.
5. Compare semantic result IDs and raw-result digests; assess timing separately.

Same-process Python agents are trusted code in Phase 3. OS resource isolation,
distributed execution, and preemptive timeouts are deferred.
