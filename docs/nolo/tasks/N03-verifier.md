# N03 — Verify a supplied continuation without optimizing it

Status: WAITING_DEPENDENCY. Requires N02 PASS. The verifier must be independent
of N04's search choices; it checks a supplied claim, including a deliberately
wrong one. Read BACKGROUND and framing 1's A/B proofs.

## Outputs and steps

Create `src/tuppi_nolo/certificates.py` and `tests/nolo/test_certificates.py`.
Define an immutable certificate: source information key, root seat/action,
objective/control model, complete support digest, finite own-plan table,
claimed terminal bound, and completeness/budget provenance. The plan table maps
**observable information keys to actions**, never hidden-world keys to actions.

Provide `verify_certificate(observation, certificate, budget)`. Rebuild/validate
the complete support independently of the certificate's asserted count. At the
controlled seat apply its specified plan; at every other seat traverse all legal
actions. An omitted non-forced own decision invalidates the plan. A forced sole
legal action may be implicit. Reject an illegal action or two different actions
for the same information key. Retain an actual counterexample path on failure.

Also provide `all_action_bounds(observation, root_action, budget)`, which explores
arbitrary subsequent actions at **all** seats, including the root. This is the
independent comparator for universal claims. Preserve terminal totals and score
states as sets; counts are diagnostics only. It is acceptable to use an
uncached exhaustive traversal initially. Budget exhaustion means unresolved,
never a certificate based on the leaves visited so far.

## Acceptance endpoints

- A with root `8S`: verify upper bound 7, even without restricting future own
  decisions. Compare with the absolute lower bound already-taken 7 and a
  baseline `QD` path reaching 9. Classify this UNIVERSAL, not merely sampled.
- B with `9C`, next own `3C`: verify upper bound 4 across both worlds, any
  opponent actions and any partner actions. B duck permits totals 3 and 5:
  do **not** classify the take as universal dominance over the duck.
- B with `9C`, next own `3H`, claimed bound 4: reject and return a legal path
  ending at 6. Removing one of the two worlds or omitting a future own branch
  must also fail exact verification.
- C: reject a universal improvement claim for `10D` over `KC`; return a layout
  and continuation demonstrating the claim's failure.
- Invalid input, incomplete support, illegal plan, budget exhaustion, and a
  disproved bound have distinct machine-readable outcomes.

Run `tests/nolo/test_certificates.py`; compare all terminal sets with N01's
independent helper. Write `docs/nolo/results/N03.md`. Zero false certificates is
the absolute endpoint. Do not proceed to search if even one invalid plan passes.
