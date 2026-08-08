# Phase 5D-B: root-player information-set UCT

`root_info_uct_v1` is the first Phase 5D-B search agent. It receives one formal
`PlayerObservation`, samples hard-feasible hidden worlds with the exact Phase 5B
sampler, and runs a fixed number of deterministic simulations. The tree is fresh
for each real trick-play decision and is discarded when that action is returned.

Only the original root seat uses UCT. At every root turn inside a simulation the
hypothetical state is projected back to that seat's observation and keyed by the
canonical root information-state identity. The sampled hidden allocation is never
part of that key. Partner and opponent turns receive only their own observation
and use frozen `partner_aware_v1` policies in the primary configuration.

This removes root-player strategy fusion inside the searched part of a simulated
deal: equivalent future root observations share action statistics across worlds.
It does not model a partner or opponent, compute an equilibrium, or make a
perfect-information claim. Those seats remain fixed observation-only policies.

The tree policy is UCT with bounded root-team current-deal utility in `[-1, 1]`,
using `match_transition_v1` and the identity normalization
`identity_bounded_minus_one_to_one_v1`. First visits enumerate every legal action
in engine order. The final action is selected by highest visit count, then mean
utility, then canonical legal-action order. Exact-tail solving is disabled in the
primary agent.

Showing is a separate invariant: `partner_aware_v1` is called directly with the
formal showing observation. No sampler or tree is constructed for showing.

## Determinism and privacy

The world stream is derived from the protocol version, root information-state ID,
decision seed, and simulation index. It does not depend on the candidate action,
worker count, process ID, output path, or clock. The first `N` world samples of a
larger budget are therefore exactly the prefix used by an `N`-simulation run.

Diagnostics contain counts, action IDs, values, node counts, merge counts, and
configuration IDs. They never contain a true deal ID, hidden hand, sampled hand,
or sampled-world identity.

Registered development configurations are `root_info_uct_smoke_v1`,
`root_info_uct_small_v1`, and `root_info_uct_standard_v1`. Their budgets and
identities are independent of the frozen Phase 5C registry.
