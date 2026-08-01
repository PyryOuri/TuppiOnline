# Evaluation architecture

## Scope and boundary

`tuppi_eval` is a deterministic experiment layer above `tuppi_engine`. It
materializes deals, assigns immutable agent specifications to seats, runs a
finite schedule through the public engine agent protocol, retains research
results, and computes block-level summaries. It does not alter engine
transitions or substitute actions. An illegal action is a failed game.

The package deliberately contains no search, training, neural model, belief
model, expert heuristic, GUI, network, human-input loop, or legacy-agent port.
The included agents are mechanical evaluator fixtures only.

The dependency direction is:

```text
tuppi_rules <- tuppi_engine <- tuppi_eval
     ^              ^              |
     |              |              +-- deal banks, schedules, records, statistics
     |              +-- observations, actions, explicit deals, canonical results
     +-- cards, seats, contracts, score transitions
```

Neither the engine nor evaluator imports `tuppi_legacy`.

## Immutable inputs

An evaluation is fixed by a strict configuration, immutable agent registry,
two partnership specifications, a content-addressed deal bank, and a
content-addressed schedule. Unknown JSON fields are rejected. Every setting
that can affect outcomes—including statistical replicate counts and all three
seed roots—is explicit. Output paths and operational timestamps are not part
of semantic identities.

Team specifications support identical or different component agent IDs.
`shared_instances` is present for protocol clarity but must be `false` in
Phase 3. The arena constructs four fresh Python objects for every schedule row,
including homogeneous teams.

## Deal-level and match-level modes

Deal mode starts every transformed game from the explicit score stored in the
base deal. One independent base deal produces one eight-game duplicate block.
This is the default and preferred Phase 3 mode because pairing removes much of
the card/seat nuisance variation.

Match mode groups an explicit, ordered base-deal sequence into one independent
unit. Every transformed row uses the corresponding transformed common
sequence, preserves score transitions and dealer rotation, and must reach 52.
Match mode therefore requires the round-robin dealer policy; digest-derived
dealers are valid for independent deal-mode banks but cannot describe a match's
mandatory next dealer.
If the configured sequence ends first, the row is an
`insufficient_match_deals` failure. Match utility is ±1; it is never pooled
with point-valued deal utility. Terminal-deal contract fields remain useful as
diagnostics but are not a substitute for per-deal match histories retained in
the raw engine result.

## Finite arena lifecycle

For each canonical schedule entry the serial arena:

1. derives independent per-seat agent seeds from the agent root seed and entry
   identity;
2. constructs four fresh agent objects;
3. transforms the already-materialized deal or sequence;
4. executes it through `PlayerObservation` and the engine action boundary;
5. validates and writes the complete raw research result atomically;
6. writes one canonical game-record shard atomically; and
7. quarantines a structured failure instead of manufacturing an outcome.

Existing shards are strictly reloaded and matched to their schedule entries.
A successful shard also requires its raw result and digest. Resume therefore
does not replay completed entries. Final ordering is by canonical schedule
position, so future process sharding can merge without changing semantics.
Phase 3 intentionally uses one serial worker.

## Failure handling and limits

Configuration and deal-bank failures stop before execution. Per-entry failures
classify agent construction, illegal action, agent protocol, engine invariant,
timeout, serialization, insufficient match material, and unexpected failures.
The explicit policy either continues after writing the failed shard or aborts.
Failed rows have no winner, points, utility, or contract and invalidate their
entire duplicate block for paired inference.

Per-action, per-deal, and per-match wall limits are explicit. Phase 3 agents
run as trusted same-process Python code. The action limit is checked when an
agent call returns; it is diagnostic protection, not preemptive sandboxing.
Aggressive process isolation is deferred.

## Raw and public outputs

Raw files use the engine research-result format and intentionally retain full
hands for reproducible offline research. Public summaries contain aggregates,
stable IDs, seat roles, contracts, scores, and failures but no hands. Agents
are invoked only by the engine with immutable player observations; the
evaluator never supplies private engine state to an agent.

## Deferred work

Formal sequential testing is deferred. The only accepted protocol is fixed
sample with no interim checkpoints or stopping boundaries, which explicitly
prohibits favorable-result stopping. Process parallelism and optional ratings
are also deferred. Ratings, when added, must not replace paired block results
or combine deal and match modes.

## Diagnostic performance smoke

On 2026-08-01, Python 3.14.3 on macOS arm64 ran 20 base deals / 160
transformed games with the trivial first/low/high agents in 23.106 seconds
(6.92 games/second), with zero failures. Fifty in-memory serializations of the
complete evaluation result took 0.269 seconds total (about 5.39 ms each), and a
full shard reload plus summary rebuild took 0.133 seconds. A separate
eight-game `tracemalloc` sample peaked at approximately 0.50 MB of traced
Python allocations. This is a diagnostic snapshot from
`examples/evaluation/benchmark_smoke.py`, not a CI threshold or capacity claim;
filesystem, tracing, and machine load affect it.
