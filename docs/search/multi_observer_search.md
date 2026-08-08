# Phase 5E multi-observer re-determinizing search specification

This document is the implementation contract for the first Phase 5E baseline.
The registered algorithm name is `redeterminizing_ismcts_v1`. It is a narrow,
root-evaluated multi-observer information-set search experiment. It is not
MO-ISMCTS in the broad equilibrium-search sense, and it is not an opponent
model, a posterior sampler, or an equilibrium solver.

## State roles

Each real decision begins with one formal `PlayerObservation` for the acting
root seat. That observation supplies the root information state, the root hard
constraint model, and the decision seed. For simulation index `i`, the Phase 5B
exact hard-feasible sampler produces the root assignment at index `i`. The
resulting immutable `FastTrickState` is the authoritative parent simulation.
Its hidden hands are simulation data only; they are never passed to a policy or
included in a node key.

There are four distinct concepts in a simulation:

1. The real root observation and its private hand.
2. The root-consistent parent world sampled for this simulation.
3. The current acting observer's formal observation of that parent state.
4. A temporary observer-local re-determinized world used only to select the
   acting observer's tree action.

Only the parent state is advanced. The temporary observer-local state is
discarded immediately after its action has been selected.

## Tree traversal

One fresh tree is created for each real decision. It owns nodes for all four
physical seats, with a separate namespace for each seat. A node key is the
canonical semantic digest of that seat's formal observation plus the seat and
Phase 5E namespace. It excludes match and deal references, parent-world
identity, sampled-world identity, re-determinization identity, simulation
index, worker identity, output paths, and timestamps.

At every tree-controlled decision, the node records availability for every
legal action in the acting observation. A newly encountered information node
creates one stable statistic per legal action in canonical engine order. The
first action whose selection count is zero is selected in canonical order. If
all available actions have been selected, action `a` uses:

```text
mean(a) + sqrt(2) * sqrt(log(max(1, node_visits)) / action_visits(a))
```

Only actions available in the current formal observation are candidates. An
action that is unavailable in another determination is not counted as a loss.
The selected action and every visited node/action pair are appended to the
simulation path. Expanding the first unvisited edge does not stop tree control:
later root, partner, and opponent turns continue through the same shared tree.
The tree stops only at the configured maximum tree depth; at that explicit
boundary `partner_aware_v1` completes the parent simulation as the
observation-only fallback. Thus future root turns in one simulation never call
the frozen fallback merely because an earlier edge was expanded, and no nested
independent search is started.

Every backed-up value is the bounded `match_transition_v1` utility for the
real root team. The same utility is added to every node/action pair on the
tree path. The final real action is selected at the root node by highest visit
count, then mean utility, then canonical legal-action order.

## Re-determinization

When the tree-controlled actor is not the real root seat, the parent state is
projected to that seat's formal observation. A fresh `HardConstraintModel` is
constructed from that observation and sampled with the exact Phase 5B
uniform-feasible sampler. The deterministic sampling domain contains:

```text
algorithm version
root information-state ID
decision seed
simulation index
observer seat
observer information-state ID
observer decision occurrence
sample domain
```

The sampled assignment preserves the observer's current hand and every public
fact. It may reassign cards hidden from that observer, including cards held by
the real root in the parent world. The assignment is converted to a temporary
`FastTrickState` using the observer's formal observation. The tree sees only
that temporary observation. The chosen `PlayCardAction` must also be present
in the parent actor's actual legal action set; otherwise the decision fails
strictly. The parent state is then advanced with that action and is never
replaced by the observer-local state.

The root seat is not re-determinized. Its tree observation is always the root
observation projected from the parent state, so its real private hand and the
root-consistent parent history remain authoritative. Fallback actions are
chosen from the acting seat's parent observation by the frozen
`partner_aware_v1` object and receive no hidden state.

## Showing and boundaries

Showing delegates byte-for-byte to frozen `partner_aware_v1`; the search and
sampler are not entered. Trick play is the only searched phase. Exact-tail
solving is disabled. The tree is discarded after the real decision and is not
reused across decisions, deals, or matches. The uniform hard-feasible prior is
kept deliberately unchanged: Phase 5E isolates observer-consistent search
structure from belief weighting.

The algorithm can reduce root, partner, and opponent strategy fusion inside the
searched prefix, but it still backs up one root-team utility, uses one shared
root-evaluated tree, and does not compute a multi-agent equilibrium. Those
limitations are part of the identity and must not be described as solved by
this phase.
