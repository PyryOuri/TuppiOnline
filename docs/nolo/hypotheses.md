# Preregistration — N07 coverage screen

**Written before the screen bank was generated.** This file is a preregistration
and must not be overwritten; a later change belongs in a versioned addendum
beside it. Date: 2026-09-05.

This is a **position screen under a fixed reference trajectory**. It is not an
A/B trial, and no result from it is evidence of a playing-strength improvement.
It asks one bounded question: on deals the implementation has never seen, does
the N04 security objective ever propose a *verified, score-relevant* departure
from what the baseline actually plays, often enough to be worth building an
executable agent for.

## Frozen choices

Reproduced verbatim from `docs/nolo/tasks/N07-coverage.md`.

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

## Decision rule, fixed in advance

- **Soundness gate.** Zero false certificates, illegal choices, information
  leaks or continuation violations. Any single one is FAILED_CHECK and blocks
  N08, whatever the coverage numbers say.
- **Feasibility GO.** At least **5 distinct deals** of the 256 carry a verified,
  score-relevant deviation, and the bank completes inside the cap.
- **NO USEFUL SIGNAL.** Complete bank, sound code, fewer than 5 such deals. The
  task completes negatively and the threshold is not to be relaxed afterwards.
- **INCONCLUSIVE.** Cap reached, bank incomplete, or implementation drift.
  Counts are reported as observed, with no extrapolation from a subset.

Five deals is a prospective practical threshold, not an estimate of a useful
population rate and not a power calculation.

## Definitions used by the screen

- **Eligible choice:** a trick-play decision with at least two legal actions and
  one to three tricks remaining, taken along the v2 reference trajectory.
- **Deviation:** the security objective's selected action differs from the action
  the baseline actually played at that position.
- **Verified deviation:** a deviation whose certificate is re-checked from
  scratch by N03 and returns `EXACT_COMPLETE`.
- **Score-relevant:** N05 classifies the candidate against the baseline as
  `UNIVERSAL` or `SECURITY_ONLY` at `(0,0)`. A `TIE` is explicitly not
  score-relevant: identical score states mean a trick difference bought nothing.
- **Distinct deals:** the unit of count. The four seats of one deal are not
  independent samples and are never counted as such.

## What the decision function may see

`solve_security` receives a `PlayerObservation` and nothing else. The real layout
is recorded alongside each record for optional oracle diagnostics and is never an
input to the decision. Any record where a hidden hand could have reached the
decision path is an information leak and fails the soundness gate.

## Reported denominators, in this order

256 deals attempted and completed; all card plays; eligible choices; complete
supports; completed searches; verified deviations; strict score-relevant
deviations; distinct deals containing at least one. Broken down by lead / follow
/ discard, remaining tricks, support size and claim class.

No significance test is applied. This is a bounded discovery and feasibility
screen, and a proportion from it carries no inferential claim.

## Execution

Command, recorded as actually run:

```
python -B -m tuppi_nolo.runner coverage \
    --seed nolo-info-coverage-v1 --deals 256 --workers 10 \
    --out work/nolo/n07/screen
```

Deals are independent and each decision is deterministic given its observation,
so the bank is distributed across worker processes purely to fit the wall-clock
cap. Parallelism changes no value, and the per-decision budgets are unchanged
and unshared.

The development bank `nolo-info-dev-v1` indices 0–63 may be used to fix bugs
before the screen is locked. The screen bank must not be used to choose
features, caps or a preferred seed. If a bug invalidates a screen run it will be
labelled invalid, its records preserved, and the repair preregistered in an
addendum before any rerun; a run's favourable decisions will never be retained
on their own.

## Code under test

Tree `237ff23` plus the uncommitted N04–N06 work. SHA-256 prefixes:

| File | Digest |
| --- | --- |
| `src/tuppi_nolo/support.py` | `535c34e8b6fc631e` |
| `src/tuppi_nolo/certificates.py` | `45865022c1bf5e90` |
| `src/tuppi_nolo/security.py` | `6713c06482a7f1bf` |
| `src/tuppi_nolo/outcomes.py` | `90f5eebf253b63cb` |
| `src/tuppi_nolo/cache.py` | `de4e5ea19f1f06d7` |
| `src/tuppi_nolo/fixtures.py` | `f905ce96490c3889` |

N06 returned NO USEFUL SPEED GAIN, so the screen uses the **uncached** search,
as its task requires. `cache.py` is hashed because it is importable, not because
it is exercised here.

## Addendum, written before any screen data existed

The harness itself was written after the sections above and is hashed here. No
deal of `nolo-info-coverage-v1` had been generated or screened when this was
added; the debugging described below used only the development bank.

| File | Digest |
| --- | --- |
| `src/tuppi_nolo/runner.py` | `99505b23bcbd98ec` |
| `tests/nolo/test_coverage.py` | `e2f3f1414c0c3fa8` |

The development bank was run first, exactly as its permission allows, to shake
out harness bugs: `nolo-info-dev-v1`, indices 0–63, 10 workers, 20.6 minutes,
452 eligible positions, zero soundness failures. Two defects it surfaced were
fixed before locking — score-state pairs were serialised as tuples rather than
JSON arrays, and the independent re-verification was being run on every position
rather than on the deviations the task actually asks be re-verified.

The development bank's counts are a debugging artefact and are **not** an
estimate of the screen's rate. They are reported in N07.md for transparency and
carry no inferential weight; the gate is decided on the screen bank alone.
