# Behavioral action likelihoods

Phase 5G-B adds a belief layer without changing search. The prior is the exact
uniform distribution over hands allowed by the Phase 5B hard constraint model.
The new layer only changes relative weights inside that set:

```text
weight(world) proportional to product_t P(observed_action_t | actor_observation_t, model)
```

The implementation uses sums of log probabilities and log-space normalization.
The acting policy receives only its reconstructed formal `PlayerObservation`.
No candidate's other hidden hands, true deal, stream, fixture, future action, or
terminal result crosses the deployable boundary.

`uniform_legal_action_model_v1` is a control. `deterministic_policy_likelihood_v1`
is an intentionally brittle matched-policy diagnostic. The primary explicit
family is `epsilon_smoothed_policy_likelihood_v1`, with fixed epsilon 0.10:

```text
P(a*) = (1 - epsilon) + epsilon/n
P(a)  = epsilon/n          for a != a*
```

where `a*` is the frozen observation-only policy action and `n` is the legal
action count. A model mismatch therefore cannot create exact zero support.

Showing is scored as the complete `(contract, shown-card)` action. Trick-play
actions are scored as the observed card. The observer's own prior actions are
excluded by default: an observation-safe model cannot use its own action to
learn the opponents' hidden cards. Hard void/show deductions remain hard and are
never softened into likelihood penalties.

The output is a finite self-normalized importance belief, not an exact posterior
over all feasible hands. It reports ESS, entropy, finite/zero-weight counts, and
owner marginals. Optional deterministic systematic resampling is infrastructure
for Phase 5G-C, not a claim that resampling improves accuracy.
