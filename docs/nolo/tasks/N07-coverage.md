# N07 — Test whether the framing changes useful new decisions

Status: WAITING_DEPENDENCY. Requires N05 PASS; use N06 only if its reduction
passed. This is a position screen under a fixed reference trajectory, not an
A/B trial or proof of playing-strength improvement.

## Outputs and preregistration

Create `src/tuppi_nolo/runner.py` with a coverage command, a focused harness test
`tests/nolo/test_coverage.py`, and `docs/nolo/results/N07.md`. Before generating
the new bank, write `docs/nolo/hypotheses.md` if absent, otherwise a new versioned
addendum under `docs/nolo/`; never overwrite an existing preregistration.
Include these choices verbatim, plus input/code hashes and actual CLI arguments:

| Field | Frozen value |
| --- | --- |
| Development | `nolo-info-dev-v1`, indices 0–63; no holdout claims |
| New screen | `nolo-info-coverage-v1`, indices 0–255 |
| Deal generation | `generate_base_deal`, round-robin dealers, initial dealer 0 |
| Score / contract | `(0,0)` / FORCED_NOLO with canonical shows |
| Reference play | v2 at all four seats; no candidate-generated trajectory |
| Eligibility | Every decision with at least 2 legal actions and 1–3 tricks left |
| Limits | Shared 100-world / 100,000-transition limits; no seed or cap sweep |
| Run cap | 4 wall-clock hours; unfinished decisions remain in the report |

The development bank may be used to fix bugs before the screen is locked. The
screen must not be used to choose features, caps, or a preferred seed. If a bug
invalidates the run, label it invalid, preserve its records and preregister the
repair before rerunning. Never keep only its favourable decisions.

## Measurements and decision gate

For each eligible position record exact/unresolved status, world count, bot
action, proposed action/plan, UNIVERSAL or SECURITY_ONLY claim, exact score
relevance, verified bound, compute cost, and deal id. Re-verify every proposed
deviation with N03. Preserve the real layout separately for optional oracle
diagnostics; it must not enter the decision function.

Report denominators in this order: 256 deals attempted/completed; all card plays;
eligible choices; complete supports; completed searches; verified deviations;
strict score-relevant deviations; distinct deals containing one. Break down by
lead/follow/discard, remaining tricks, support size and claim class. Do not count
four seats of a deal as independent samples. No significance test is needed for
this bounded discovery/feasibility screen.

- **Soundness gate:** zero false certificates, illegal choices, information leaks,
  or continuation violations. Any one is FAILED_CHECK and blocks N08.
- **Feasibility GO:** at least **5 distinct new deals** have a verified,
  score-relevant deviation, and the fixed bank completes within the run cap.
  This is a prospective practical screen threshold, not an estimate of a minimum
  useful population rate or a power calculation.
- **NO USEFUL SIGNAL:** complete bank, sound code, fewer than 5 such deals.
  This completes the task negatively. Do not proceed to the adapter by weakening
  the threshold. A revised scope needs a new documented research task.
- **INCONCLUSIVE:** cap reached, incomplete bank, or unresolved implementation
  drift. Report observed counts without extrapolating success from a subset.

Store compact decision evidence sufficient to reconstruct each claimed
deviation. Run `tests/nolo/test_coverage.py` with deliberate unresolved positions
to prove they stay in the denominators. N08 additionally requires G1 adoption
or an explicit waiver; this screen alone does not choose the programme's theory.
