# Phase 5E re-determinization

Re-determinization is the operation that separates the authoritative parent
simulation from the temporary world used to select a non-root observer's action.
It is necessary because the parent world contains every hidden hand, while a
partner or opponent may legitimately know only its own hand and the public
history. Passing the parent state to a policy would turn ordinary simulation
data into an information leak.

## Exact operation

At a tree-controlled non-root turn, Phase 5E first projects the parent
`FastTrickState` to the acting seat's formal `PlayerObservation`. This projection
contains the acting hand, public show history, completed tricks, current trick,
contract, team totals, match score, and legal actions. It contains no other
hand. The Phase 5B `HardConstraintModel` is then built from that observation.
The model includes exact public void information, show-derived exclusions, known
held cards, played cards, and residual hand capacities. It does not use action
likelihoods or a behavioural prior.

The exact uniform-feasible sampler draws one current-hand assignment from that
model. The assignment preserves the observer's hand because that hand is part of
the observation. It may assign cards differently from the parent world whenever
those cards are hidden from the observer. The assignment is converted to a
temporary immutable `FastTrickState`, and the observer's node key and legal
action selection are computed from its formal observation. The temporary state is
discarded after selection.

The parent state is never replaced. Before applying the selected action, Phase
5E checks that its physical card is in the parent actor's hand and that the full
action is in the parent actor's legal action set. A mismatch is a strict action
mapping failure; there is no fallback repair. The parent then advances through
the validated fast transition path. This preserves the root's sampled world,
root private hand, public history, trick totals, and scoring state.

## Seed domain

The observer sampler seed is a digest over the explicit Phase 5E protocol,
root information-state identity, decision seed, simulation index, observer seat,
observer information-state identity, observer decision occurrence, and the
`observer_redeterminization` sample domain. Parent hidden-hand identity, true
deal identity, worker identity, process identity, output path, and wall-clock
time are absent. The sampler receives the simulation index as its random-access
sample index, so nested simulation prefixes are stable.

The observer information-state identity is the canonical digest of the formal
observation in a Phase 5E namespace. It excludes `match_ref` and `deal_ref` and
therefore remains stable when the same observable position is represented by
different hypothetical protocol references. Two parent worlds that generate the
same acting observation produce the same constraint model, seed coordinates,
and observer-local sample.

## Frequency and limitation

The primary configuration re-determinizes at every tree-controlled decision by
a non-root seat. The root is never re-determinized. Once a new tree edge is
expanded, or the maximum tree depth is reached, the simulation leaves the tree
and the frozen `partner_aware_v1` policy completes the parent world. Fallback
policies receive only parent-state formal observations and never receive the
temporary assignment.

This is not a posterior. The observer-local draw is uniform over hard-feasible
worlds, not weighted by how the observer would have generated the observed
actions. Re-determinization prevents direct hidden-card leakage into an
observer's decision, but it does not compute a Bayesian belief, a Nash
equilibrium, or a multi-agent best response under learned policy likelihoods.
