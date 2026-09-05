# N04 — Find an information-legal security continuation

Status: WAITING_DEPENDENCY. Requires N03 PASS. Scope: one controlled seat,
deterministic own plans, all other seats arbitrary. This deliberately includes
an unhelpful partner. It gives a robust guarantee, not the cooperative game value
or an equilibrium. Do not add likelihoods, sampling, learning or a new heuristic.

## Outputs and exact recursion

Create `src/tuppi_nolo/security.py` and `tests/nolo/test_security.py`.
Entry point: `solve_security(observation, budget)`, returning all root action
values, an optimal own plan and its verified certificate, or an unresolved status.

Let S be all hypothetical states compatible with the root's observed action
history. They must have the same current actor and root observation. Define
cost as the root partnership's final tricks. The recursion is:

```
terminal: V(S) = max(final own-team tricks over states in S)
root's turn: V(S) = min over common legal a of V(T(S,a))
other turn: V(S) = max over union of possible public a of V(T(S,a))
T(S,a) = engine successors of exactly the states where a is legal
```

At a root turn choose **one** action for the whole information class. Never
minimize separately per world. At other turns filter on the publicly observed
action before continuing; keep all feasible states, not just one convenient
world. If distinct root-observation classes arise, partition by the semantic
key before own choices; a hidden field may not create those classes.

For each root card run the recursion with that first action fixed. Resolve equal
values using the inherited v2 ranking, not arbitrary iteration order. Export the
chosen action at every reachable future root information key. Have N03 verify
the returned plan separately. Do not substitute solve_late_game: its partner
cooperates and its players see the hidden hands.

## Acceptance endpoints

- A: best root `8S`, security value 7; other root cards value 9.
- B: `9C` value 4, `3C` value 5; emitted next own action after `9C` is `3C` in
  both worlds. A first-card-only recommendation does not pass.
- C: all three root cards security value 6; preserve baseline `KC`; no universal
  correction. Verify these expected values rather than trusting the table.
- Construct a tiny two-world counterexample with a shared future observation,
  opposite favourable future choices, and a safe alternative. Its strategy table
  must contain one shared choice. The existing tiny-information-reference has
  expected utility A=0.5/B=0.65; under **worst-case worlds**, A=0/B=0.65. Do not
  confuse the two objectives or assert their values are identical.
- For tiny positions, compare against brute enumeration of complete legal root
  plans followed by adversarial continuation. Zero value differences; every
  reported plan passes N03. Swapping unseen hands under the same observation
  changes no decision. Reordering the support changes no value or action.
- Deliberately too-small budget returns SEARCH_BUDGET with no exact choice.

Write `docs/nolo/results/N04.md`, including node counts and a small trace showing
why per-world minimization would be invalid. Run `tests/nolo/test_security.py`.
If the one-seat conservative model is too pessimistic elsewhere, report that
limitation; do not silently make the partner omniscient to improve results.
