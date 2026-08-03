# The Phase 5B exact layer

`src/tuppi_exact/` adds five exact capabilities on top of Phase 4's hard public
inference, plus the frozen-baseline gate and the rule diagnosis those
capabilities make possible.

Everything in the package is **exact or an error**. No function in it returns an
estimate, and none degrades gracefully: a request outside budget raises
`SolverBudgetError` rather than answering approximately. That rule exists because
an exact answer carries authority, and a heuristic that inherits the interface of
an exact one keeps the authority while losing the property that earned it.

## The dependency direction is one-way, and checked

```text
tuppi_rules -> tuppi_engine -> tuppi_eval -> tuppi_agents -> tuppi_match
                                                                  |
                                                                  v
                                                            tuppi_exact
```

`tuppi_exact` reads all five earlier packages. **None of them may reference it.**
`tuppi_exact.integrity.capability_containment` parses their source and fails if
any does, and `tests/exact/test_integrity_and_variants.py` asserts it.

The reason is not tidiness. Phase 4's agents are frozen references whose
specifications record `search`, `belief_model`, `endgame_solver`,
`hidden_hand_sampling`, `learning`, and `rollout_budget` as `null`. If a Phase 4
module could import a solver, every Phase 4 and Phase 5A result would become
retroactively search-assisted and no earlier claim would still mean what it said.
The containment check is what makes that impossible rather than merely
discouraged.

## The five capabilities

| Module | Question it answers exactly |
| --- | --- |
| `constraints` | Which seats may still hold this card? |
| `counting` | How many hidden-hand assignments does public information permit, and what fraction place this card at this seat? |
| `sampling` | Draw one of those assignments, exactly uniformly. |
| `continuation` | Turn a sampled assignment into a playable engine state. |
| `solver` | What is optimal play here under perfect information? |

They compose in that order. A determinizing search agent would use all five:
build the model, count it, sample worlds, construct continuations, solve or roll
out each. Phase 5B builds the pieces and uses them to diagnose Phase 4's
rising-score rules; it does **not** ship a search agent.

## What Phase 4's inference was missing

`PublicInference` derives exclusions from five facts: own hand, played cards,
shown cards, failure to follow suit, and remaining capacity. Phase 5B adds a
sixth, and it is not a refinement of degree.

**A show action constrains the shower's entire initial hand.**
`project_target_v1` derives `verbal_required` from the complete 13-card hand
through a mandatory three-level hierarchy, so the public tuple
`(seat, shown_card, declared_contract, verbal_required)` is a hard statement
about cards the shower does not hold:

| Public show action | Exact deduction |
| --- | --- |
| `verbal_required` false | Priority 1. Nothing new excluded. |
| `verbal_required`, shown rank 3-9 | Priority 2. **No eligible card of the contract's normal colour** - 14 cards excluded. |
| `verbal_required`, shown rank ineligible | Priority 3. **No eligible card of either colour** - all 28 excluded. |

Priority 3 cannot show an eligible card, because under priority 3 the hand holds
none. That is why the shown card's rank separates the two fallback levels with
certainty rather than by guess.

This is not an optional improvement. Without it the sampler produces assignments
that contradict a public show action, and the engine rejects them when a
continuation is built - see `docs/exact/continuation.md`. Phase 4 did not need
the deduction because Phase 4 never reconstructed a hand.

## Exactness aids, not approximations

Three techniques make the exact answers cheap. Each is exact; none is a
heuristic cut.

**Equivalence classes over allowed-seat sets.** Two unknown cards with the same
allowed-seat set are interchangeable for every feasibility, counting, and
uniform-sampling question, so the constraint system collapses to a transportation
problem over at most fifteen classes and at most three open seats.

**Hall / Gale-Hoffman propagation.** With at most three unknown seats, checking
every seat subset is a *complete* feasibility test, so infeasibility is detected
rather than discovered later.

**Equivalent-card reduction in the solver.** Two cards of one suit in one hand
are interchangeable when no card that can still matter lies between them. "Can
still matter" includes cards in the **current trick**, not just cards in other
hands - a card of the led suit sitting between two of the actor's cards means one
beats the trick and the other does not. Omitting that was a real defect, caught
by the brute-force cross-check; `tests/exact/test_solver.py` keeps a named
regression test for it.

## Storage and privacy

The solver and the continuation constructor both read **all four hands**. They
are research-private by construction: no observation carries them, no policy is
handed one, and a hypothetical continuation is labelled
`research_private_hypothetical` with a `hypothetical:` match reference.

Nothing in this package writes high-volume output. Census and ablation artifacts
belong on a plain local filesystem outside the repository;
`integrity --report` warns when the working tree itself looks cloud-synced,
because a cloud-synced tree was the reproducible cause of a stalled subprocess
test before the tree was relocated.

## Documentation map

- Constraints and the show deduction: `docs/exact/constraint_model.md`
- Counting and exactly uniform sampling: `docs/exact/counting_and_sampling.md`
- Hypothetical continuations: `docs/exact/continuation.md`
- The exact solver and the monotonicity theorem: `docs/exact/solver.md`
- The frozen-baseline gate: `docs/exact/integrity.md`
- The match-aware rule diagnosis and its results: `docs/exact/phase5b_results.md`
- Strict schemas: `schemas/exact/`
