# N05 — Distinguish valuable guarantees, score ties, and policy sensitivity

Status: WAITING_DEPENDENCY. Requires N04 PASS. Read BACKGROUND's objective
corrections and framing 1's rules audit. Do not fit an equity table or an
opponent model in this task.

## Outputs and steps

Create `src/tuppi_nolo/outcomes.py`, `tests/nolo/test_outcomes.py`, and
`docs/nolo/results/N05.md`.

1. Map every attainable final **own-team** total to a Team-0/Team-1 split in the
   correct seat orientation, then call score_nolo and transition_rising_score.
   Keep the set of resulting score states. Do not plug an expected trick count
   into the scoring formula or use the points won by the losing side.
2. Add the exact rational score-state proxy from BACKGROUND, checked against
   match_transition_value. Name it `score_state_proxy`, never `match_equity`.
   When a scalar security choice is needed, maximize its worst-case value.
   The proxy is monotone in avoiding own tricks, so it can add ties to a trick
   optimum; it does not justify more own tricks to improve a deterministic leaf.
3. Classify claims separately: UNIVERSAL, SECURITY_ONLY, TIE, UNCLASSIFIED.
   A strict trick difference with identical score states is not a score gain.
   Preserve the baseline on ties. Retain all unresolved reasons.
4. Add a small analytical sensitivity report for B: after a duck the total is
   3 with probability q and 5 otherwise; the take-and-club line yields 4.
   Calculate `5-2q` for q=0, 1/2, 1 and the crossing at 1/2. These are assumed
   scenario probabilities, not fitted observations. C's reference means remain
   labelled reference-only, with no claim of policy-free optimality.

## Exact endpoints

| Position and starting score | Expected score consequence |
| --- | --- |
| A at `(0,0)`, total 7 versus 9 | `(0,4)` versus `(0,12)` |
| A with Team 0 down at `(0,40)` | `(0,44)` versus terminal `(0,52)` |
| A with Team 0 up at `(40,0)` | Both `(0,0)`: TIE for this margin |
| B at `(0,0)`, totals 4/5/6 | `(12,0)` / `(8,0)` / `(4,0)` |
| B at `(40,0)` | `(52,0)` / `(48,0)` / `(44,0)` |
| B at `(0,40)` | All `(0,0)`: TIE for these winning lines |
| Up at 48, any winning margin | All terminal victories; no overshoot preference |

Mirror the checks to root seats 1/3 so team indexing cannot accidentally pass
only for Team 0. At q=0 the B security line is better in expected tricks, at
q=1/2 it ties, and at q=1 the duck is better. The label SECURITY_ONLY must not
be promoted to UNIVERSAL in the last case. Zero exact score discrepancies is
required. Run `tests/nolo/test_outcomes.py`; report which witness decisions are
score-relevant and which are ties before proceeding to the coverage screen.
