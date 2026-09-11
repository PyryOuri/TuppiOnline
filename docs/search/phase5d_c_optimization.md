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

## Back-port to the PIMC rollout

The optimization above was applied only to the Phase 5D-B search agents. The
Phase 5C PIMC rollout kept the authoritative path, which is where the cost had
moved: `cProfile` on one `pimc.decide` at W=8 from an opening lead put **85 % of
runtime in `state._validate_deal_state`** (16,160 calls, 16.45 s of 19.27 s) plus
the `build_expected_deal_events` rebuild that check consumes. The policy calls
themselves were 2.22 s. See `docs/search/phase5d_c_profiling.md` for the method.

`rollout.complete_deal` now hands over to `FastTrickState` on reaching trick
play. Two things this required:

- `FastTrickState.from_deal_state`, a second constructor. The rollout already
  holds an authoritative `DealState` — the sampled world with the candidate
  forced — so it needs no observation and no assignment. Unlike
  `from_observation_assignment` it loses nothing: there is no sampler
  canonicalization to undo, so the projection is exact for all four seats and
  keeps `match_ref`/`deal_ref` rather than dropping them.
- `utilities.summary_from_fast_completion`. The five fields a
  `DealOutcomeSummary` needs are exactly the five a `FastTrickState` carries, so
  both completions reduce to one value type scored by one set of adapters. This
  is what keeps that module's stated invariant — that the fast and authoritative
  paths *cannot* disagree about utility semantics — true rather than merely
  tested for.

The authoritative path is not removed. It still plays the showing prefix (at
most 4 of a deal's 56 actions), it still runs whenever an exact tail is
configured because the solver needs a real `DealState`, and it stays reachable
through `_fast_path=False` so the gate below can require agreement.

### Measured

One opening-lead decision, 13 legal actions, `showing_search_enabled=False`,
single process, this host:

| configuration | authoritative | fast | speedup |
|---|---:|---:|---:|
| W=4 (the rejected one) | 3.29 s | **0.50 s** | 6.6x |
| W=8 (largest registered) | 6.64 s | **0.99 s** | 6.7x |
| **W=64 (C3's clearing point)** | 54.45 s | **7.87 s** | **6.9x** |

The authoritative column reproduces the 3.60 / 7.33 / 56.72 s measured
independently before the change. The speedup lands at the pessimistic end of the
5.4-8.3 s range projected from the profile, not the optimistic end implied by the
aggregate 10.47x figure quoted for the UCT path — the rollout retains
`validate_play` and Phase 4 policy execution, so 85 % removable is the right
basis and 10.47x was not.

**W=64 fits the 10 s decision bound, with 2.1 s of margin.** That is not
comfortable single-process, so a deployed opening-lead selector should qualify in
the parallel configuration, as the architecture review recommended.

### Validation gate

`tests/search/test_rollout_differential.py`, 15 checks at three levels:

- **Projection.** `from_deal_state` produces observations byte-identical to
  `observation_for` for all four seats at mid, late and forced positions,
  `match_ref` and `deal_ref` included. It refuses a non-trick-play state.
- **Transitions.** Complete deals walked on both representations from tricks 0,
  4 and 9, comparing after every action: observations, hands, actor, partial
  trick, completed tricks, team totals, phase, deal score, ending score and next
  dealer. Both rollout paths return the same outcome, and
  `actions_already_simulated` survives the handover unchanged.
- **Decisions.** Whole-decision diagnostics identical with the path on and off,
  at mid and late positions, at the 13-arm opening lead, from a showing root
  (which exercises the mid-rollout handover), and under the deal-points adapter
  as well as the match-transition one. Separately confirmed at the real target,
  W=64 at the opening lead: diagnostics byte-identical, 7.87 s against 54.45 s.

Two boundary checks: a configured exact tail keeps the authoritative path and is
still consulted, and a revoking policy is refused with
`IllegalRolloutActionError` rather than repaired. The refusal is raised by
`_choose` before the transition sees the action, because the fast state offers
the same legal set the engine would; `apply` refuses independently too, which
the tests pin separately.

## The incumbent as a rollout continuation

PIMC's value for a candidate is "this action, then reference play". The
reference was necessarily a frozen Phase 4 profile, while deployed play uses
`partner_aware_lead_v2` — so search simulated a continuation nobody would play.
That mismatch was unstated rather than decided.

`SUPPORTED_ROLLOUT_POLICIES` now admits `partner_aware_lead_v2`. The resolution
is `config.rollout_specifications()`, which merges the Phase 4 registry with
`improved_registry` at the point of use, so the incumbent can be *named* without
being *registered* — registering it as a Phase 4 profile would move the frozen
baseline every Phase 4-6 result is quoted against, which
`improved_registry`'s own docstring forbids. Phase 4 keys win on collision, and
`construct_agent` matches an improved specification by identity rather than by
name, so this cannot be used to substitute a forged specification for the
declared one.

**Admitting it does not select it.** `DEVELOPMENT_REFERENCE_POLICY` is unchanged,
every registered agent keeps the continuation it was measured with, and all six
Phase 5C agent identities plus the registry digest are byte-for-byte what they
were before this change — now pinned in
`tests/search/test_rollout_differential.py`, which nothing in the suite did
before. Whether the incumbent continuation actually produces better decisions is
an open empirical question; this only makes it askable by configuration instead
of unaskable.

One related correction: `all_policies_deterministic` returned a bare `True`
justified by "every configured rollout policy is a frozen Phase 4 agent". That
justification stopped holding here even though the conclusion did — both
registries record `determinism` on the specification — so it now reads the
specifications instead of asserting.

`partner_aware_discard_v3` is declared in the same registry and resolves through
the same lookup, and is deliberately left out because nothing has asked for it.

### What this still does not do

It does not change what any registered agent plays. Closing the mismatch in a
deployed configuration remains a separate decision, because a rollout
continuation is part of an agent's identity and changing it makes a new agent.

## Opening-lead-only scoping

The third prerequisite. Its original statement — "no `PimcConfiguration` field
does this" — is right, and the reason is that no field *should*: `hybrid.py`
records that adding a phase-gate field to `PimcConfiguration` would change every
Phase 5C `configuration_id` and therefore every Phase 5C `agent_id`. Scope is
expressed by composition instead, in a separate object carrying its own content
address, and the existing `SearchedPhase` gate is that object.

`SearchedPhase.OPENING_LEAD_ONLY` is a third value. Adding an enum *value* moves
no identity, because the committed gates digest their own `searched_phase.value`
strings and those are untouched — the same reason admitting a rollout policy to a
whitelist was safe.

### The opening lead, defined on the observation alone

`hybrid.is_opening_lead` is true when the phase is trick play, no trick is
completed, and no card has been played into the current one. Consequences worth
stating:

- **Exactly one decision per deal satisfies it**, and only `first_leader` ever
  faces it. A seat that is not the opening leader never searches.
- It is deliberately narrower than "each seat's first card", which would be four
  decisions in three different information states and not what C4 measured.
- It reads only the public observation, so a gate cannot scope itself on
  anything a seat is not entitled to know. Scoping is not a side channel.

Measured on one deal: **1 searched decision out of 54.** That is the entire
affordability argument. At W=64 and 7.87 s per decision, opening-lead scoping
costs about 7.9 s per deal where trick-play-only scoping would cost roughly
seven minutes.

### The predicate moved from phases to decisions

`PhaseGatedConfiguration.searches(phase)` could answer for the two phase-scoped
values. An opening-lead gate searches one trick-play decision and delegates the
rest, so that question has no honest yes or no; the method raises for this scope
and points at `searches_decision(observation)`, which answers for all three. The
gated agent's own `searches(observation)` signature is unchanged, so nothing
downstream had to move.

`to_data()["delegated_phase"]` is recorded in the specification payload and is
therefore digested into gated agent identities. The two committed values keep
their exact strings, `SHOWING` and `TRICK_PLAY`, and the new scope reports
`SHOWING and TRICK_PLAY after the opening lead` rather than falsely claiming a
whole phase.

### Not a registered profile, on purpose

`registry.opening_lead_gate` and `registry.opening_lead_specification` construct
the scope from an explicit `PimcConfiguration`, and it is content-addressed over
that configuration: the same world count and continuation give the same identity,
a different budget or a different continuation gives another. It is **not** in
any registry dict.

Registering a profile would mint an identity asserting *which* world count and
*which* continuation to deploy, and nobody has measured that. C3 puts the
deal-points effect clearing delta only at W=64; the review's recommendation was
to qualify the parallel configuration rather than the single-process one, which
at 7.87 s has 2.1 s of margin. So the world count and the continuation are
arguments an experiment supplies, not claims the repository makes.

`gated_specification` was extracted from `phase5d_a_specification` so both share
one payload builder. That was a pure refactor, and both committed Phase 5D-A
agent identities are pinned in `tests/search/test_phase5d_hybrid.py` to prove it.

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

That paragraph describes the original Phase 5D-C work and still holds for it. The
back-port above changes the rollout's *representation* and the sections above
record the differential evidence that its *semantics* are unchanged; the rollout
policy admitted alongside it changes what a configuration may name, not what any
registered agent plays.

**"Simulations remain serial within one decision" is no longer true, and the
change is deliberate.** `pimc.decide(workers=N)` evaluates a decision's
candidates concurrently, because gate zero found the latency bound and C3's
world-count requirement did not overlap without it — see
`docs/cardplay/results_gate0.md`. What that paragraph rejected is still
rejected: *asynchronous shared-tree* parallelism would change results, which is
why it was refused. Candidate parallelism cannot, because the candidates are
independent, share one deterministically rebuilt world set, and are reassembled
in canonical order before the tie-break; `tests/search/test_pimc_parallel.py`
requires the decision, the `configuration_id` and the `agent_id` to be identical
at every worker count. Worker count stays outside every identity, which is where
`config.py`'s docstring already put it.
