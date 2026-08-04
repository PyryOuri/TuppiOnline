# Determinism and the seed hierarchy

Phase 5C is deterministic. The same observation, configuration, and policy seed
always produce the same action, the same candidate values, and the same diagnostics.

## No ambient randomness

Nothing in `src/tuppi_search/` uses a module-global RNG, a mutable shared stream, a
process identifier, worker completion order, wall-clock time, or Python's `hash()` -
which is salted per process and would silently make a run irreproducible.
`tests/search/test_pimc_core.py` greps the package for `import random`,
`random.random`, `random.shuffle`, and `numpy.random`.

## The coordinate namespace

Every random quantity is derived from a canonical JSON object over named
coordinates:

```text
pimc_protocol        the search protocol version
information_state    digest of the acting seat's complete information set
decision_seed        the caller's explicit per-decision seed
domain               which quantity is being drawn
sample_index         which sampled world
candidate_action     which root action        (rollout domains only)
rollout_replica      which replica            (stochastic policies only)
acting_seat          which simulated seat
decision_index       which simulated decision inside a rollout
```

## World sampling never sees the candidate

This is the rule the whole design rests on. `SeedDomain.HIDDEN_WORLD_SAMPLING` is not
in `CANDIDATE_DEPENDENT_DOMAINS`, and passing a `candidate_action_id` for it **raises**
rather than being ignored - so a typo that made the world set depend on the action
fails loudly instead of quietly confounding every comparison.

Rollout domains *may* depend on the candidate, because different root actions produce
genuinely different histories and coupling them to one stream would tie unrelated
decisions together. Phase 5C's registered agents use deterministic rollout policies,
so no rollout randomness is drawn at all; the coordinates exist so a later stochastic
policy has a documented place to sit rather than an improvised one.

## One seed for the whole world set

The sampler receives a single seed for the entire indexed set, not one per index. The
Phase 5B sampler is already an indexed deterministic stream, and re-seeding per index
would destroy its prefix-stability guarantee - the property that makes a larger budget
reuse a smaller one's worlds *exactly*.

That is what makes the action-stability study meaningful: the first 4 worlds of an
8-world budget are literally the 4-world budget's worlds, so a change of action
between budgets is a genuine change of opinion rather than a different sample.
`tests/search/test_worlds_and_seeds.py` asserts the nesting directly.

## Information-state identity

`information_state_digest` covers the *whole* observation: the observing seat's own
hand, the public showing and play history, the contract, the declarer, the match
score, the seating, the legal action set, and the public `match_ref`/`deal_ref` -
which the complete-match protocol derives from an ordinal precisely so they carry no
fixture identity.

Two different real deals presenting the same observation therefore produce the same
digest, the same seeds, the same worlds, the same values, and the same action.
`tests/search/test_information_set_invariance.py` builds genuine alternative *real*
deals - engine-validated, with the original public labels - and asserts all of that.

That test caught a real subtlety during development. An earlier version built its
alternatives with Phase 5B's `hypothetical_continuation`, which deliberately re-labels
its `match_ref` so a hypothetical can never be filed as a dealt deal. Because
`match_ref` is a genuine public field, the alternatives differed *inside* the
information set and the test was proving the wrong thing.

## Common random numbers

Within one decision, every candidate shares:

- the same sampled world indices;
- the same rollout policy versions;
- the same replica count;
- the same resource budget;
- the same deterministic action rules.

**Limitation, stated:** once histories diverge, action-by-action random-number
coupling stops being meaningful. Two candidates lead to different positions, so the
"same" simulated decision index is not the same decision. Coupling is exact at the
level of *worlds*, which is where it matters most, and approximate below that. With
deterministic rollout policies the question does not arise at all.

## Replicas and deterministic policies

`rollout_replicas > 1` is **refused** while every configured policy is deterministic:
replaying the same world with the same policies reproduces the same rollout, so extra
replicas would spend N times the compute to average N identical numbers. Raise
`world_count` instead. The field exists for a later stochastic policy.

## Deterministic budgets, not wall-clock

The semantic definition of a Phase 5C agent is a fixed amount of *work*: a world
count, a replica count, and an exact-tail threshold. Wall-clock stopping is
deliberately not part of any agent definition - a time-limited agent plays differently
on a loaded machine, so its results would not be reproducible and its identity would
be a fiction. Timing is measured separately and recorded as operational data.

## What does not change a decision

Verified by test: requesting diagnostics, the output path, logging verbosity, worker
count, and the order in which evaluations complete. Candidate aggregation is a
function of the multiset of utilities, so completion order cannot affect it.
