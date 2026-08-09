# Policy-family mixtures

The robust diagnostic mixture is an equal-weight mixture of epsilon-smoothed
versions of the frozen Phase 4 policies:

- `reactive_contract_v1`;
- `public_counting_v1`;
- `partner_aware_v1`.

For one actor observation:

```text
P(a | o) = 1/3 P_reactive(a | o)
         + 1/3 P_counting(a | o)
         + 1/3 P_partner(a | o)
```

The weights are immutable and are not selected from held-out hidden-hand labels.
The synthetic evaluator keeps matched-policy, misspecified-policy, and mixture
results separate. An oracle-known generator policy is an offline diagnostic; the
ordinary deployable mixture receives no generating-policy identity.

The mixture is not an equilibrium model and does not simulate a policy search.
It is a transparent action likelihood intended to test whether public behavior
contains recoverable hidden-card information under a stated model family.
