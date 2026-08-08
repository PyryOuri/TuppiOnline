# Phase 5E observer privacy contract

Phase 5E has two state boundaries. The authoritative parent simulation is an
internal search object containing one root-consistent sampled deal. The policy
boundary exposes only formal `PlayerObservation` objects. A temporary
observer-local state exists only inside the tree-selection operation and is not
serialised, returned, or used to advance the parent simulation.

## Allowed inputs

The real root agent receives one formal observation for its own seat. Root
world generation uses that observation and the exact Phase 5B sampler. During a
simulation, a tree-controlled root turn uses the parent projection of the root
observation. A tree-controlled non-root turn uses a re-determinized observer
projection that contains:

- the acting observer's current hand;
- the public showing and played-card history;
- the current trick and its leader;
- contract, declarer, dealer, forehand, and first leader;
- team trick totals and public match score;
- public void facts implied by played cards;
- the observer's legal action set.

The selected card must be legal in the parent state before the parent is
advanced. The frozen fallback receives the parent projection for its own seat.
No policy receives a `DealState`, `FastTrickState`, `HiddenHandAssignment`,
constraint model, tree object, sampler, or root diagnostics.

## Forbidden information

The following are never included in a Phase 5E information-state key, seed, or
public diagnostic: another seat's private hand, the parent sampled-world ID,
the observer-local sampled-world ID, true deal ID, fixture ID, worker index,
output path, timestamps, or raw hidden-card arrays. Diagnostics contain counts,
IDs, action statistics, and timing only. Search-world serializers are not public
result serializers.

The root's actual hand is intentionally retained in the authoritative parent
simulation. It is not copied into an opponent's observer-local state unless the
opponent's own formal observation proves the card. Re-determinization may place
that card elsewhere in the temporary opponent world, and the parent is still
unchanged. This is the required separation between root consistency and
observer privacy.

## Tests and failure policy

The Phase 5E test suite records fallback policy calls and checks that every call
contains the correct seat's `PlayerObservation`. Sentinel hidden cards are
searched for in diagnostics. Same-observation re-determinations are compared
across alternate parent references, and observer-local actions are checked
against the parent legal action set. The independent tiny oracle checks that a
partner node shared across hidden worlds and opponent nodes split by private
signal have the expected policy values.

Any privacy or mapping discrepancy is fatal. Phase 5E does not repair an
illegal action, drop an unfavourable simulation, substitute a legal card, or
continue after an impossible re-determination. That strict behaviour is part of
the registered algorithm identity and keeps a privacy defect from becoming a
silent strength result.

## Scope

Showing remains exactly the frozen `partner_aware_v1` action and does not enter
the sampler or tree. Exact-tail solving is disabled. There is no persistent
tree, nested independent search, learned belief, neural component, self-play,
or training process. The shared tree backs up one real root-team utility, so
the implementation is a root-evaluated diagnostic search, not an equilibrium
method for four privately informed agents.
