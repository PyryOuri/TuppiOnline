# C1 contract report — analytical control variates for ordinary NOLO discards

Task C1.03 output. Date 2026-09-26. **Status: PILOT_READY (pilot disabled).**
This is a contract/readiness result. No pilot, screen or strength test ran, and
no speed or strength claim is made.

## What exists

| Piece | Where | Notes |
|---|---|---|
| Per-layout proxy `G_a(w) = -(L_a(w) - L_a0(w))` | `tuppi_ai/research/c1_control_variate.py` | Contested within-suit "everyone ducks" rounds over the current holdings; discard removed, not reassigned; partner counts as another seat. |
| Fixed-β two-batch estimator, β fit, allocation | same | `gap = β·mean_M(G) + mean_n(D − βG)`; β centred within case and action, equal case weights; allocation minimises the worst action's `A/M + B/n` at a fixed budget. Rejects β ≠ 0 without a cheap batch, a non-zero reference column and non-finite input. |
| Explicit-world evaluator | `native/research/research_api.c` (+ `overlay.patch`) | The original continuation on caller-supplied worlds; never samples a root world; validates each world against the observation. |
| Dispatcher | `tuppi_ai/research/c1_dispatch.py` | `C1-shadow-v1` and `C1-natural-v1`, separately named. Shadow draws its experimental streams from a hash of a copy of the agent's pre-call scalar RNG (actor-local; distinct per agent and call; reproduced by forks), then discards W128's root draws on the persistent RNG. Natural advances its own stream. Only v3 decisions are eligible; everything else delegates unchanged. A failure falls back to W128 and is recorded. |
| Disabled pilot manifest | `research/c1_pilot_manifest.json` | `cli validate-manifest` → NOT_LAUNCHABLE: approval, sample size, CPU/wall/memory/worker caps and the futility rule are the owner's to set. |

## Acceptance tests (command: `~/.venvs/tuppi-v2/bin/python -m pytest tests/research -q`; the C1 file now holds 23 tests after the review additions)

| ID | Test(s) in `tests/research/` | Result |
|---|---|---|
| V01 | `test_c1.py::test_V01_*` (4 tests, 5 cases) + isolated RESEARCH oracle `oracle_research_suits.py` | PASS. Proxy = brute-force ducking simulation on 64 real sampled F02/F02b worlds × all actions and 300 synthetic layouts. RESEARCH `play_out` gives 0 mismatches on 400 layouts. The exact Fraction expectation over RESEARCH `conditional_layouts` equals E023 `expected_ducking_tricks` on all 9 E024 grid cases (oracle ran under `~/.venvs/tuppi-ai`, no ENGINE module loaded). The target value and sign are recomputed with the DD solver on solver-only discards for a team-1 (F02) and a team-0 (F02t0) actor. Removed-card semantics: reassignment changes the value in some layouts, so the test is not vacuous. |
| V02 | `test_V02_*` | PASS. F02's proxy varies across worlds; F02t0 is a real case whose proxy is constant, and there the estimator equals plain MC for every β. |
| V03 | `test_V03_*` (2 tests) | PASS. Exact enumeration over a six-world law of real F02 worlds (with their evaluator values): unbiased for correct, wrong, reversed and constant proxies, β ∈ {0, 0.37, −1.5}, (M, n) ∈ {(1,1), (2,2)}. The *implementation* is also enumerated. A mutation that forgets the −βG correction is detected. |
| V04 | `test_V04_*`, `test_V03_V04_*` | PASS. The independent-batch variance equals `β²Var(G)/M + Var(D−βG)/n` exactly. The implementation's variance field is unbiased. Reusing the expensive worlds as the cheap batch leaves the mean unbiased but breaks the actual variance, and the check detects it. |
| V05 | `test_V05_*` (2 tests) | PASS. β = 0 gives plain MC; zero proxy variance gives β = 0; the reference gap is exactly 0; all-equal values select the reference; degenerate allocations are handled. The β fit ignores huge per-case offsets. |
| V06 | `test_V06_*` + `builds/parity_report.json` | PASS. Explicit-world values equal the traced W128 search bitwise on F02b (4,096 MLP rows); the continuation stream and world buffers are untouched; duplicated worlds give identical rows. |
| V07 | `test_V07_*` | PASS. Reversing or truncating the action list permutes/selects exactly the matching columns bitwise on a network-using case. |
| V08 | `test_V08_*` | PASS. Parent-deal overlap is rejected at assignment, record and set level; stream seeds are distinct across namespaces; a label naming evaluator data is refused. |
| V09 | `test_V09_*` (2 tests) | PASS. On a matched two-call history (F02b then F02, seat 3), the shadow candidate's full controller snapshot equals W128's after each call: scalar RNG, NumPy RNG, native sooli settings, slot digest. The natural variant's differs, and the two variants have distinct ids. Non-eligible calls are identical to the base agent. |
| V10 | `test_V10_*` | PASS. Cost records reference, sampling, expensive, proxy and shadow CPU plus totals and native work; `total_saving_bound` enforces `f·r`. |
| V11 | `test_c0_runner_statistics.py::test_V11_*` | PASS. The raw MSE ratio is biased toward 1 by reference noise; the corrected ratio and the MSE difference recover the truth; one replicate is refused. |

## Parent identities and lifecycle tested

- Comparator: `best_agents(worlds=128)`, dd_left 6, bid search on, seed map seed+2·seat, sooli defaults as recorded in `baseline_manifest.json`. The retained v3 sooli-setting issue is left in place, and the native settings trace in the parity report shows it (cold settings throughout a v3 ordinary sequence).
- Libraries:
  - B0-installed `02d9b4fa…`;
  - B0-source is **byte-identical** to B0-installed (`builds/build_manifest.txt`);
  - R0-parity agreed bitwise with both on 13 probe cases plus a 6-call best-agent sequence. This was re-established after every rebuild: API v1 `10352806…` against both B0 libraries (`builds/r0_api_v1/`), then API v2 `d6c62316…` and current API v3 `221fe041…` against B0-source (`builds/parity_report.json`). Rollout chunk 32 vs 128 is bitwise equal on two network-using cases (`builds/r0_api_v1/`).
- Tested lifecycle: decision-case forks from cold agents (ReplayFork/NativeFork); no controller state is carried between cases.

## Measured contract-stage costs (`logs/c1_cost_calibration.json`)

| Case | W128 CPU | C1 (M=256, n=32) CPU | of which proxy |
|---|---|---|---|
| F02 (5 tricks left, solver only) | 0.025 s | 0.013 s | 0.008 s |
| F02b (8 tricks left, network) | 0.298 s | 0.091 s | 0.015 s |

These are single timings on two fixtures, not throughput estimates and not a speed comparison at equal precision. The proxy runs in Python and is counted.

## Independent review

A read-only independent review found no bug in the overlay or the estimator mathematics. It found seven likely bugs and several weak tests elsewhere; all are fixed or dispositioned in `research/independent_review_c0_c1.md`. The suite was rerun afterwards: 84 passed, `logs/pytest_research_after_review.log`.

## Limitations and what the pilot must establish

1. **The branch fraction probably caps any program-level saving.** Bid searches cost 2–6 s CPU against 0.03–0.3 s for a NOLO discard, so the discard branch is likely a small CPU fraction *f*. The total direct saving cannot exceed *f*·*r*. The pilot should measure *f* first; if *f* < 0.2, the full-game "20% total CPU" promotion route is unreachable for C1.
2. **Fixtures are synthetic development states.** F02 uses scripted NOLO bids and clone play. The pilot's cases must come from the declared population in the manifest.
3. **β, M and n are placeholders in the tests.** β must be fitted on FIT and M, n allocated on PLAN.
4. **Parity holds on the tested cases only.** It is bitwise on 13 probes and 2 sequences, not a universal proof.
5. **The first executable gated task is P.C1** (planning then screening), once the owner approves the manifest's caps.
