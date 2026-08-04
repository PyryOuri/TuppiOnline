# The Phase 5C search layer

`src/tuppi_search/` is the first search-based Tuppi baseline: **classical root
Perfect-Information Monte Carlo** over the exactly uniform hard-feasible worlds
Phase 5B provides.

For one decision:

1. build the Phase 5B hard constraint set from the acting seat's observation;
2. sample an indexed set of uniformly feasible hidden-hand assignments;
3. construct one engine-validated hypothetical world per sample;
4. force **each** legal root action into **every** world of that one common set;
5. complete each deal with observation-only rollout policies, optionally handing
   the endgame to the Phase 5B exact solver;
6. average root-team-oriented utility and select deterministically.

## The dependency direction is one-way, and checked

```text
tuppi_rules -> tuppi_engine -> tuppi_eval -> tuppi_agents -> tuppi_match -> tuppi_exact
                                                                                 |
                                                                                 v
                                                                           tuppi_search
```

`tuppi_search` reads all six earlier packages. **None of them may reference it.**
`tuppi_search.validation.dependency_direction_problems` parses their source and
fails if any does.

The reason is the same one Phase 5B gave for its own boundary, one layer further
out. Phase 4's agents are frozen references whose specifications record `search`,
`belief_model`, `endgame_solver`, `hidden_hand_sampling`, `learning`, and
`rollout_budget` as `null`. If a Phase 4 module could import PIMC, every Phase 4,
5A, and 5B result would become retroactively search-assisted and no earlier claim
would still mean what it said.

## Modules

| Module | Responsibility |
| --- | --- |
| `random` | Domain-separated seed derivation and the information-state digest. |
| `utilities` | Three versioned root-team-oriented utility adapters over one shared outcome type. |
| `config` | The immutable, content-addressed PIMC configuration. |
| `worlds` | The indexed, candidate-independent sampled-world set. |
| `rollout` | Observation-only continuation of a hypothetical world. |
| `exact_tail` | Optional Phase 5B exact endgame, with an explicit threshold. |
| `pimc` | The root search, candidate aggregation, and deterministic selection. |
| `agents` | The deployable agent; engine `Agent` protocol, nothing more. |
| `registry` | Immutable Phase 5C agent identities. |
| `diagnostics` | Strict, privacy-safe decision records. |
| `validation` | The boundary gate. |
| `oracle` | Restricted perfect-information diagnostics. **Not an agent.** |
| `evaluation` | Deal-level screening and complete-match comparison. |
| `benchmark` | Performance measurement and action-stability study. |
| `runner` | The finite noninteractive CLI. |

## What Phase 5C is not

A **baseline**, not an equilibrium solver, and never to be described as optimal
imperfect-information play. See `docs/search/uniform_feasible_pimc.md` for the
strategy-fusion argument in full.

Phase 5C deliberately contains no information-set tree search (ISMCTS, MO-ISMCTS,
RIS-MCTS, POMCP), no persistent search tree or tree reuse, no neural policy or
value model, no learned or heuristic hidden-hand likelihood weighting, no particle
filter, no Bayesian belief model, no counterfactual regret minimization, no
reinforcement learning, no self-play or population training, and no search
distillation. `tuppi_search.validation.excluded_technique_problems` scans for those
families rather than trusting this paragraph - though it is a source scan, so it
catches an accident rather than a determined re-implementation.

## Why ISMCTS is deferred

Three reasons, in order of weight.

**A baseline has to exist first.** ISMCTS is judged against something. Until a
deterministic PIMC agent with a fixed budget and a reproducible identity exists,
there is nothing to compare an information-set searcher *to*, and no way to tell
whether a difference came from the algorithm or from the sampler, the utility, or
the rollout policy.

**Everything ISMCTS needs is built here, and is separately testable.** The exact
sampler, the engine-validated hypothetical world, the observation-only rollout, the
root-team utility, and the deterministic seed hierarchy are all Phase 5C
components. Building them under PIMC's simpler control flow means each was tested
in isolation before a tree was layered on top.

**PIMC's failure modes are the argument for ISMCTS**, and they should be *measured*
rather than asserted. Phase 5C's own evaluation found this baseline losing
decisively to the frozen reference agent; the value of that result is that it is a
measurement with a named mechanism, which is exactly the motivation an
information-set searcher needs. See `docs/search/phase5c_evaluation.md`.

## Storage and privacy

The deployable agent reads only a `PlayerObservation`. Rollout policies read only
their own seat's projected observation. Hypothetical worlds are labelled
`research_private_hypothetical` by Phase 5B and are never serialized into a
committed artifact - `tests/search/test_architecture.py` checks the committed
reports for that directly.

Bulk output belongs on a plain local filesystem outside the repository. Phase 5C
run artifacts live under `~/TuppiRuns/phase5c`; only compact summaries are
committed under `reports/phase5c/`.

## Documentation map

- The algorithm and strategy fusion: `docs/search/uniform_feasible_pimc.md`
- The rollout boundary: `docs/search/rollout_security.md`
- The exact tail and its bias: `docs/search/exact_tail_integration.md`
- The utility adapters: `docs/search/utilities.md`
- Determinism and the seed hierarchy: `docs/search/determinism.md`
- Budgets, benchmarks, and results: `docs/search/phase5c_evaluation.md`
- Strict schemas: `schemas/search/`; examples: `examples/search/`
