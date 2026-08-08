# Phase 5D-B results

Phase 5D-B implements `root_info_uct_v1`, an observation-safe root-player
information-set UCT agent. Showing remains exactly the frozen `partner_aware_v1`
policy; trick play uses a fresh per-decision tree, the Phase 5B hard-feasible
sampler, and frozen observation-only non-root rollouts.

## Structural acceptance

- Phase 5C identities and registry digest are unchanged.
- The sealed promotion bank remains unopened.
- The independent tiny reference has the preregistered result PIMC A = 1.0,
  exact information-set A = 0.5, B = 0.65, with UCT selecting B from budget 16.
- Focused root-information tests cover showing delegation, legal actions,
  deterministic replay, node merging, public-information separation, privacy,
  non-root observation boundaries, sampler prefix stability, and strict failure
  classification.

## Development evaluation status

All reports below are in the permitted development directory
`/Users/pyryouri/Developer/TuppiRuns/phase5d-b`; none is promotion evidence.

The registered configurations are:

- `root_info_uct_smoke_v1`: 2 simulations, exploration constant `sqrt(2)`;
- `root_info_uct_small_v1`: 4 simulations, exploration constant `sqrt(2)`;
- `root_info_uct_standard_v1`: 8 simulations, exploration constant `sqrt(2)`.

All use `match_transition_v1`,
`identity_bounded_minus_one_to_one_v1`, canonical legal-action expansion,
highest-visit final selection, the Phase 5B uniform-feasible sampler, and no
exact tail. The registry report is
`reports/phase5d_b/root_info_uct_registry.json`.

The six-position stability corpus measured adjacent action agreement of 0.500
from budgets 2 to 4 and 0.833 from 4 to 8; agreement with the budget-8 result
was 0.667, 0.833, and 1.000 for budgets 2, 4, and 8. This is a small
development diagnostic, not a convergence claim. The same corpus contained
three showing and three trick-play positions; showing remained delegated and
unchanged.

On the six-position behavioural corpus, UCT agreed with the frozen PIMC action
in the reference-disagreement category once, agreed with the reference against
PIMC four times, and all three differed once. The archived Phase 5C complete-
match negative result remains the comparison baseline; it was not recomputed.

The bounded four-pair homogeneous comparison at the small budget produced
`0/4` candidate wins, `0/4` ties, and `4/4` losses (`p_win = 0.000`; the
four-pair interval is `[0.000, 0.000]`, with exact sign-flip `p = 0.125`). This
is deliberately reported as low-power development evidence. Each run took
about 5.6 minutes at four workers with safety cap 96, demonstrating that the
current implementation is compute-limited before a larger strength bank is
justified.

The seat-balanced heterogeneous diagnostic, two pairs per arrangement, also
gave `0/2` candidate wins in both the lower-seat and higher-seat arrangements.
It shows no recovery at this tiny budget, but its uncertainty is too large for
a partnership claim. A complete-match PIMC control was not rerun: the Phase 5C
negative result is frozen, and a bounded attempt was stopped after it proved
operationally impractical on this machine rather than changing that baseline.

## Decision gate

The phase is classified **Path E2 — structurally correct but computationally
limited**. The independent exact information-set counterexample and node-merging
tests validate the mechanism, while the small complete-match runs are negative
and the current per-decision cost prevents a decision-relevant strength bank.
The next step is representation/rollout optimization and a preregistered larger
budget-stability and complete-match evaluation. This phase does not support a
claim that root-information UCT is stronger than either frozen PIMC or the
development reference.

The primary limitations remain deliberate: no partner/opponent tree, no
re-determinization, no learned belief weighting, no exact-tail leaf in the primary
agent, no persistent tree, no recursive search, and no equilibrium computation.
