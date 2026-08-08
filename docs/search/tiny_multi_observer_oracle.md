# Tiny multi-observer oracle

The production search is validated against an independent finite reference in
`tuppi_search.tiny_multi_observer_reference`. The oracle intentionally does not
import the production tree, fast transition runner, sampler, or registered
agent. It is a small policy-enumeration model designed to expose the information
structure that Phase 5E is meant to represent.

## Constructed game

There are two equally likely hidden worlds. The root chooses A or B. B pays
0.60 immediately. After A, the partner has the same observable information in
both worlds and must therefore use one shared action, X or Y. The opponent has
a private signal: `opp0` in world 0 and `opp1` in world 1. Its policy may be
conditioned on that signal, so the exact oracle enumerates one partner action
and one opponent action for each opponent information state.

The terminal payoff tables are:

| world | opponent signal | X,L | X,R | Y,L | Y,R |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 | opp0 | 1.0 | 0.0 | 0.0 | 0.0 |
| 1 | opp1 | 0.0 | 0.0 | 0.0 | 1.0 |

Clairvoyant PIMC can choose X/L in world 0 and Y/R in world 1, giving A value
1.0 and selecting A over B. The exact information-set policy cannot choose a
different partner action in the two worlds because the partner observation is
identical. Its best A value is 0.50, so the exact information-set action is B.
The fixed root-only rollout also has A value 0.50, but a one-simulation root
prefix selects A before B is visited. An independent shared-node UCT prefix
selects B at four simulations and thereafter in the tested prefixes.

This is a structural counterexample to the claim that a single-world action
choice can be averaged into an information-set policy. It also tests the
observer distinction: the partner node merges the two worlds, while the two
opponent signal nodes remain separate. The production implementation is not
called by this oracle; a separate Phase 5E integration test checks its actual
tree, re-determinization, and parent-action mapping on engine positions.

## Exact enumeration

The oracle enumerates the finite choices directly. It first evaluates the
clairvoyant maximum independently in each world. It then enumerates the one
shared partner action and the two opponent signal-contingent actions, averaging
the resulting current-deal utility over the uniform two-world prior. No hidden
allocation is sampled, no rollout policy is imported, and no production UCT
statistics are reused.

The independent UCT prefix uses canonical action order, `sqrt(2)` exploration,
integer simulation indices, and root-team utility. Its output is a diagnostic
of the expected search direction, not statistical evidence about real matches.
The acceptance test records the complete separation: PIMC A, root-only prefix A
at budget 1, exact information-set B, and multi-observer prefix B at budget 4.

## Limitation

The toy oracle is not a Tuppi rules position and cannot establish playing
strength. It establishes only that the intended node namespaces and policy
sharing are meaningfully different. Engine-level correctness comes from the
Phase 5D-C `FastTrickState` differential tests plus Phase 5E observer privacy,
deterministic re-determinization, action-mapping, and complete-simulation tests.
