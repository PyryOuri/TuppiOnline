# Phase 5D-C optimization

The optimization preserves the Phase 5D-B search protocol. Existing registered
agent IDs, simulation budgets, exploration constant, action order, information
state key, sampler, rollout policy, utility, normalization, final-action rule,
showing delegation, and strict failure policy are unchanged.

## Implemented optimization

`src/tuppi_search/fast_trick.py` adds an immutable search-local representation for
the already-resolved trick-play suffix of a sampled world. It contains only the
fields consumed by the formal `PlayerObservation`, frozen rollout agents, root
information-state key, and current-deal utility. It omits engine event logs and
the repeated whole-state validation that the authoritative `DealState` performs
on every simulated transition.

The fast projection creates the same formal `PlayerObservation` fields and the
same canonical legal-action order. The fast transition preserves hand order,
follow-suit legality, current-trick winner, next leader, team trick totals,
RAMI/NOLO scoring, rising-score transitions, and terminal state. It does not
implement showing, alter the real match engine, or expose a sampled hand to a
policy. The old authoritative path remains available internally as the
differential reference (`_fast_path=False`).

## Validation gates

- The frozen corpus contains 14 formal-observation positions and three registered
  profiles. The optimized implementation matched all 42 expected semantic
  decisions, diagnostic records, sampled-world identity prefixes, root-node paths,
  and tree-node keys; mismatches: 0.
- Fast and authoritative decisions matched on additional RAMI/NOLO early, middle,
  and late positions for all three profiles.
- A separate authoritative differential run compared 1,000 complete remainder
  simulations and 16,000 individual transitions across RAMI and NOLO. There were
  no discrepancies in observations, hand contents, actors, partial tricks,
  completed tricks, team totals, phases, deal scores, or ending scores.
- The independent tiny exact oracle is unchanged: PIMC chooses A, exact
  information-set evaluation chooses B, and UCT chooses B at budgets 16 and 64.
- The strategy-fusion counterexample and showing delegation remain unchanged.

The large differential summary and semantic conformance records are bulk outputs
under `/Users/pyryouri/Developer/TuppiRuns/phase5d-c/profiles/`; no hidden hands
or true deal states are committed.

## Deliberately rejected or deferred optimizations

Sampler replacement was rejected because sampler construction/draws were a small
fraction of the measured cost and exact indexed world identities must remain
unchanged. A new rollout cache or incremental `PublicInference` implementation
was deferred because it would require changing the frozen Phase 4 policy execution
boundary; rollout feature/inference construction is now the leading remaining
hotspot and is a candidate for a separately validated future optimization.

No asynchronous shared-tree parallelism, native extension, changed rollout,
parameter retuning, exact tail, persistent tree, or new search algorithm was
introduced. Simulations remain serial within one decision. Parallelism remains at
the independent match/pair level.
