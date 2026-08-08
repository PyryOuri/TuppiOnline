# Tiny exact information-set reference

The production UCT implementation is tested against an independent finite-state
diagnostic, not against a second copy of its own tree code. The diagnostic has
two equally likely hidden worlds and one future root observation shared by both.

After initial action A, world 0 rewards future action X and world 1 rewards future
action Y. Initial action B pays `0.65` in both worlds. Clairvoyant PIMC chooses a
different future action in each world and reports A = `1.0`. The exact
information-set evaluator must choose one future action for the shared observation,
so A = `0.5` and B = `0.65`; it chooses B. The independent UCT diagnostic selects
B by budget 16 and remains on B at budget 64.

This counterexample demonstrates the structural distinction, not a strength claim
about the real game. It establishes that node sharing changes the policy class:
hidden worlds can still be sampled, but indistinguishable future root decisions
cannot be chosen independently per world.

## Oracle boundary and checks

The diagnostic is intentionally a small independent state machine. It represents
the finite hidden-world prior, public observation classes, legal actions, fixed
non-root transitions, and root-team utility directly. It does not import the
production UCT tree, action selector, sampler, continuation builder, or match
runner. At each root information state its recursion chooses one action and
reuses that choice for every still-reachable hidden world in the class. After a
public action, worlds inconsistent with that observation are removed before the
next recursive step. This is the property that ordinary per-world PIMC lacks.

The test suite checks the exact values, the clairvoyant per-world upper bound,
and independent UCT replay at budgets 16 and 64. It also checks that the UCT
diagnostic never receives the hidden-world label as part of its node key. The
example is deliberately abstract and small: it is a correctness oracle for the
information-set mechanism, not an attempt to approximate a full 13-trick deal
or to certify equilibrium play. A future oracle may add more hidden worlds and
multiple public observations, but it must retain the same one-action-per-class
restriction and remain independent of the production implementation.
