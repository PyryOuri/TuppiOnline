# Phase 5F sampler and execution optimization

The production algorithm remains Phase 5E `redeterminizing_ismcts_v1`. Phase
5F changes how the existing exact work is executed; it does not change what a
simulation means. Every observer-local hidden allocation still comes from the
Phase 5B hard-feasible uniform sampler, and the parent simulation world is still
never replaced by an observer-local world.

## Exact indexed sampling

Before Phase 5F, `sample_one(index=i)` implemented the indexed request as
`sample(i + 1)[i]`. That was semantically correct but materialized all earlier
`HiddenHandAssignment` objects. The optimized implementation consumes those
earlier assignments structurally. It performs the same class split selection,
the same combination-rank draw, the same rejection-based
`DeterministicBitSource` calls, and the same source seed, while discarding
ownership materialization. The selected assignment is then materialized by the
existing `_draw` path.

This is not a jump-ahead sampler and it is not a new random-access protocol.
The sequence remains the historical sequential sequence, including its exact
bit consumption and rejection behaviour. The old sequential implementation is
retained in differential tests as the semantic reference.

The exact suffix count path now calls the same memoized `_count_from` recurrence
at its existing class position rather than creating and validating a temporary
suffix `CountingPlan` for every candidate split. Per-sampler immutable context
stores class positions, the canonical counting identity, and suffix sizes.
These fields are representation aids only; they are excluded from sampler
identity and do not contain a hidden-world identifier.

## Pure exact caches

Bounded compositions are memoized by `(total, bounds)` in their original
canonical order. Exact weighted class-split options are memoized by the
canonical counting-plan shape, class position, and residual capacities. The
cache contains integer branch weights and exact tuples; it contains no random
draws. Therefore cache hits cannot alter the indexed source sequence or the
uniform distribution.

Constraint refinement now computes the canonical card order once per model and
skips cards already removed from the working map. Suit ordering uses a fixed
integer table instead of rebuilding an enum list for each card key. The
`PublicInference` refinement path applies the same stable-order technique.
These changes preserve the old loop order and all fixed-point deductions.

The information-state tree receives an already computed observer key when the
same key was needed immediately beforehand to derive the observer sampler seed.
The local projection is still passed to the node for legal-action validation.
The existing Phase 5E invariant—that observer-local projection preserves the
acting observer's formal information state—is tested independently. Stable
action IDs are cached for immutable engine action values.

## Rejected or deferred work

An observer-context cache was considered and measured. In the representative
corrected full-tree decision it would have had zero hits across 1,249 model
builds, so adding broad cache state would increase memory and complexity without
a demonstrated benefit. No approximate sampler, rejection sampler, changed
sampling coordinate, or likelihood weighting was accepted. No rollout policy,
UCT formula, final-action rule, budget, or re-determinization frequency was
changed. FastTrickState was retained; no second transition implementation was
introduced. Native acceleration remains a future option only if a later profile
isolates one stable kernel after these Python optimizations.

## Equivalence evidence

The Phase 5F semantic corpus contains 12 fixed trick-play observations spanning
early, middle, late, and four deterministic streams. All three registered
multi-observer agents produce identical serialized diagnostics before and after
optimization: 36/36 profile-position outputs match. The stored corpus is
privacy-safe and external:
`/Users/pyryouri/Developer/TuppiRuns/phase5f/semantic/phase5e_semantic_corpus_v1.json`,
digest `sha256:664d7efd82dc492652a208a58824effcc903a550df7c80add90fd21d82c1efc9`.
The multi-observer registry digest remains
`sha256:0e58bc6f3445b1b102c2253c282ae9ad95584cbea52768a4efa0acdaff8c0707`.

Focused differential checks cover 10,000 indexed assignments against the
pre-5F sequential reference and 10,000 exact suffix-count comparisons, plus
prefix stability, baseline decision equality, key equality, and the existing
FastTrickState/authoritative-engine checks. The independent tiny
multi-observer oracle and its strategy-fusion counterexample are unchanged.
