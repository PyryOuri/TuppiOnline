# Independent review of C0+C1 (+ C3b overlay) and dispositions

An independent reviewer (read-only; no code executed) examined the milestone on
2026-09-26. It found **no bug in the overlay refactor or in the estimator
mathematics**. Every other finding and what was done about it:

| # | Finding (reviewer's severity) | Disposition |
|---|---|---|
| 1 | Research entry points did not validate the `TcObs`. The sampler copies `n_played` bytes and indexes by play seat unchecked, so a malformed observation could write out of bounds (likely-bug). | **Fixed.** `research_obs_valid` runs at every entry point and returns `RESEARCH_BAD_OBS` (−8); research API v3. Test `test_A04_malformed_observations_*` builds 10 malformed raw structures, bypassing the Python codec. |
| 2 | `research_world_consistent` ignored trick totals and `cur`, the legality of hidden locked bids, and sooli-phase hand counts (likely-bug). | **Fixed.** It now recomputes totals and the actor from the history, checks every showing bid (seat order, NOLO, legal tier from the bidder's hand, verbal flag) and per-phase hand sizes. Test `test_A04_worlds_with_wrong_*`. |
| 3 | The variance field omitted β²Var(G)/M when M = 1 and β ≠ 0 (likely-bug). | **Fixed.** The field is NaN there, and `C1Config` requires M ≥ 2 when β ≠ 0. Test `test_V05_one_cheap_draw_*`. |
| 3n | The variance-optimal fixed β is slope·M/(M+n), not the regression slope (nit). | **Adopted** as `optimal_beta`, frozen only after (M, n) are fixed on PLAN. Recorded in the manifest. |
| 4 | C1 streams labelled `(run, seat, calls)` with a default run id would repeat across fresh-fork cases, correlating errors across clusters (likely-bug). | **Fixed.** Streams now derive from a copy of the agent's pre-call scalar RNG state (actor-local, as spec 2.2 describes), and `run_id` is required. Tests `test_V09_experiment_streams_*` (distinct agents give distinct streams; the factory and a fork reproduce them). |
| 5 | Snapshots and forks did not understand `C1Candidate` (likely-bug). | **Fixed.** A `c1` factory is registered; `snapshot` unwraps to the base controller and records the candidate id, calls and fallbacks; `native_fork` copies them. |
| 6 | `mse_endpoints` averaged flat and had no clustered interval (likely-bug). | **Fixed.** Averaging is within case, then within base deal; an optional bootstrap over base deals covers the difference and the corrected ratio. Test `test_V11_mse_is_averaged_*`. |
| 7 | `bundle_summary` averaged resolved bundles only, i.e. complete-case deletion (likely-bug). | **Fixed.** Worst-case bounds for unresolved bundles (per-game equity changes in [−1, 1]); the resolved-only mean is labelled descriptive. Test `test_R04_unresolved_bundles_*`. |
| 8 | No fallback in the C1 branch (nit). | **Fixed.** On failure, the unchanged W128 call runs and the failure is recorded on an intention-to-run basis. In shadow mode a failure after the persistent RNG has moved is an error, not a silent fallback. Test `test_V09_a_failed_C1_branch_*`. |
| 9 | The candidate skipped W128's ruleset-2 `set_sooli` block (nit). | **Fixed by scope.** Only v3 decisions are eligible; everything else is delegated unchanged. |
| 10 | Wrong, reversed and constant proxies were checked only through the test's own formula (weak-test). | **Fixed.** `test_V03_the_implementation_is_unbiased_for_wrong_*` enumerates the implementation itself. |
| 11 | The β-fit test used the same offset for every action (weak-test). | **Fixed.** Action-specific offsets. |
| 12 | The A10 diagnostic ran on a separate fork (weak-test). | **Strengthened.** `test_A10_a_diagnostic_on_the_live_agents_own_environment_*` evaluates counterfactual worlds in the live agent's own environment, then checks its next decision and snapshot against an untouched twin. |
| 13 | A08 was never run on `C1Candidate` (weak-test). | **Added** `test_A08_the_C1_candidate_sees_only_its_observation`: a consistent hidden swap leaves the observation, decision and gaps identical. |
| 14 | V08 tested only the registry utility (weak-test). | **Added** `fit_beta_on_split`, which rejects non-FIT parents. Test `test_V08_beta_fitting_accepts_only_FIT_parents`. |
| 15 | V06 compares two paths that share `continue_rollouts` (weak-test). | **Accepted as designed.** The comparison with unmodified code is A03 (`builds/parity_report.json`: B0-source vs R0 in separate processes). |
| 16 | The overflow check can never trigger under the w/k caps (nit). | **Documented** in code and test as a guard for future cap changes. |
| 17 | `check_no_truth` would miss integer masks (nit). | **Fixed.** Free-form fields may not hold integers above 255. |
| 18 | Seat seeds share the bundle index with the deck stream (nit). | **Documented** in `runner_v3.py`: separately labelled SHA-256 streams; the seed holds no card information. |
| 19 | `match_summary` would divide by zero on a pair with no legs (nit). | **Fixed** (raises). |
| 20 | Stale evidence after the rebuild (nit). | **Regenerated:** parity for R0 `221fe041…`, the full suite rerun, manifest source hashes, and the contract report. |
