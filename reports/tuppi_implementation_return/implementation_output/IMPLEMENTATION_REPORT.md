# Tuppi C0–C5 research implementation — report

Date 2026-09-26. Inputs: `audit_deliverables/tuppi_implementation_plan/` (the master prompt, spec, DAG and tests) and `audit_deliverables/tuppi_design_20260925_184608/` (the audit). Both were verified with `verify_package.py` (exit 0) and left untouched. Progress is recorded only in this directory. Per-task status and evidence are in `IMPLEMENTATION_STATE.json`.

## 1. Outcome

- **First milestone (C0 + C1): complete.**
  - C0.01–C0.07, C1.01 and C1.02 are **CONTRACT_PASS**.
  - C1.03 is **PILOT_READY**: `research/c1_pilot_manifest.json` is disabled and validates as NOT_LAUNCHABLE until the owner sets approval and numeric caps.
- **Later correctness tasks: complete at contract level.** C3b.01, C2.01, C2.02, C3a.01, C4.01, C4.02, C5.01 and C5.02 are **CONTRACT_PASS**.
- **Gated tasks: not run.** P.C1, P.C3b, P.C2, P.C4, P.C5, P.C3a, CONFIRM, COMPOSE and DEPLOY are **NOT_AUTHORISED**.
- **Tests:** 109 contract tests pass, 0 fail, 0 skipped (`logs/pytest_research_final.log`).
- **No speed, strength or deployment claim is made.** Nothing live was changed:
  - the installed `native/libtuppi.dylib` is unchanged (`02d9b4fa…`);
  - no tracked file was edited;
  - other authors' dirty files are untouched;
  - private rooms were never listed or read;
  - `TuppiAI/runs/` contents were never opened (A12, `logs/protect_check.json`).

## 2. What was implemented (all new files; no existing file edited)

| Where (TuppiAI/) | What |
|---|---|
| `native/research/` | **Separate native build:** `build_research.sh`, `overlay.patch` (a 225-line patch to a *copy* of `tuppi_env.c`), `research_api.c/.h` (API v3), and `pinned_sources.sha256`. Outputs go to `native/research/build/` (gitignored). |
| `tuppi_ai/research/identity.py`, `ledger.py`, `cli.py` | Identity and baseline capture, protected-path checks, the contract-stage resource ledger, the manifest validator and state updates. |
| `records.py`, `observation.py`, `streams.py` | Typed records with truth kept apart, split lineage, the strict inverse of the engine's observation wire form, information keys, native record codecs, and domain-separated streams. |
| `lifecycle.py`, `clone_policy.py` | Named factories, call recording, ReplayFork, NativeFork, snapshots, the mode tracker, and the deterministic clone. |
| `native_api.py`, `probe.py`, `parity.py` | Library-specific ownership, `bind_native`, the explicit-world evaluator and trace, and cross-library parity in separate processes. |
| `fixtures.py` | The bounded builder for F01–F06, with policy-facing cases and separate evaluator truth. |
| `runner_v3.py`, `statistics.py` | The authoritative v3 duplicate-deal and complete-match runner, plus paired/clustered endpoints, censoring bounds, reference-noise-corrected MSE and saving bounds. |
| `c1_control_variate.py`, `c1_dispatch.py` | C1: proxy, estimator, β fit and allocation; dispatcher with shadow and natural variants. |
| `c3_utility_stop.py`, `c3_kernel.py` | C3b certificate oracle; C3a kernel solver and mode model. |
| `c2_blind_bids.py` | C2: clone-predecessor F/R/RC model and fork-isolated searching predecessors. |
| `c4_exchange.py`, `c4_training.py` | C4: legal 52-card stage scorers, payoff tables, four-arm replay and population guards; the giver-weighted joint objective. |
| `c5_option.py` | C5: support gate, information-group optimiser and contingent option agent. |
| `manifests.py`, `testing.py` | Disabled pilot manifests; test helpers. |
| `tests/research/` (+ `tests/conftest.py`) | 109 contract tests plus an isolated RESEARCH-environment oracle. `tests/conftest.py` keeps them out of the default `pytest` run, which still collects exactly the 35 existing tests. |

`patches/` holds `overlay.patch` and the new-file list. `tuppi_research_implementation.tar.gz` is a portable archive of all new files, reports, manifests, fixtures and logs. It contains no dylibs, no model weights and no private data.

## 3. Parent identities and lifecycle tested

- **Checkouts at the audited HEADs:**
  - AI `4220f249…` (main);
  - ENGINE `1347153f…` (`rules/project-target-v3-locked-bids`);
  - RESEARCH `622d5599…` (144 dirty entries, all hashed and unchanged);
  - CLIENT `7ba8ca28…`.
- **Source drift:** 0 of 62 audit evidence files changed (`research/source_drift.json`).
- **Environment:** `~/.venvs/tuppi-v2` (Python 3.14.2, numpy 2.5.3, torch 2.14.0) resolves `tuppi_engine` and `tuppi_rules` to ENGINE, and no RESEARCH module is ever loaded there (A01). The RESEARCH oracle runs separately under `~/.venvs/tuppi-ai`.
- **Model and equity:**
  - `rollout_clone_small.pt` `38737c90…`: encoder 2, **1951 inputs**, width 256, 2 blocks, 156 outputs;
  - `equity_incumbent.json` `1496f771…` (table recomputed from the DealModel).
- **Comparators:**
  - `best_agents(worlds=128)`, dd_left 6, bid search on, per-seat seed `seed + 2·seat` (scalar RNG `(seed+2s)·2654435761+1`);
  - v3 sooli-setting issue retained as the as-is comparator;
  - `research/baseline_manifest.json` (immutable).
- **Libraries:**
  - **B0-source is byte-identical to B0-installed** (`02d9b4fa…`, `builds/build_manifest.txt`), so installed/source correspondence is proven for this toolchain;
  - R0-parity is the current research build `221fe041…` (API v3). Earlier builds and their parity evidence are archived in `builds/r0_api_v1/`.
- **Lifecycles exercised:** `independent_cold_bundle`, `retained_match_leg`, `cold_reset_per_deal` and `historical_worker_reuse` (continuity only); plus decision-case forks from cold agents.

## 4. Disabled-mode parity (A03) and its limits

- **Build history:**
  - R0 API v1 matched B0-installed and B0-source bitwise (per-world float64 values, return status, scalar RNG afterwards) on 13 probe cases plus a 6-call best-agent sequence (actions, values, both RNGs).
  - The probes cover NOLO discards (solver-only and network), a NOLO lead, a three-card lead, v3 locked bids under all three sooli-setting modes, the sooli offer, give and play, ordinary RAMI after two declines, W16, and rollout chunk 128.
  - Each rebuild (API v2, API v3) was re-verified against B0-source on the same set, bitwise (`builds/parity_report.json`).
- **Other results on the same probes:** the trace export equals the original, sample-only draws equal the traced worlds, and explicit-world re-evaluation reproduces the original, including the continuation RNG in sooli rollouts.
- **Chunk invariance:** rollout chunk 32 vs 128 is bitwise equal on the two network-using cases (4,096 and 44,928 MLP rows).
- **Limits:** this is tested equivalence on these cases, not a universal proof. The spec's historical process state is not reproduced and cannot be; nothing claims it.

## 5. Contract tests

**Command:** `~/.venvs/tuppi-v2/bin/python -m pytest tests/research -q` (TuppiAI directory, research build present). **Result:** 109 passed.

**Mapping of acceptance IDs to tests.** Every one of the 74 IDs has at least one test or artifact.

| IDs | Where |
|---|---|
| A01–A02, A04, A12 | `test_c0_identity_native.py`; A12 also `cli protect-check` → `logs/protect_check.json` |
| A03 | `python -m tuppi_ai.research.parity` → `builds/parity_report.json` (three processes) |
| A05, A10 | `test_c0_observation.py`; A10 also in `test_c0_lifecycle.py` |
| A06–A11 | `test_c0_lifecycle.py`; A08 also `test_c1.py::test_A08_*` |
| F01–F06 | `research/fixtures/*.json` (all VALIDATED, truth in `fixtures/truth/`); each fixture is re-checked by replaying its truth through the engine |
| R01–R06 | `test_c0_runner_statistics.py` |
| V01–V10 | `test_c1.py` (V01 includes the isolated RESEARCH oracle); V11 is in `test_c0_runner_statistics.py` |
| B01–B08 | `test_c2.py`, `test_c2_search.py` |
| K01–K04 | `test_c3b.py` |
| K05–K09 | `test_c3a.py` |
| X01–X03, X07, X09, X10 | `test_c4.py` |
| X04–X06, X08, X11, X12 | `test_c4_training.py` |
| O01–O10 | `test_c5.py` |

**Tests are built to be able to fail.** Negative controls include:

- a biased and a batch-reusing estimator mutant;
- hidden-card and integer-mask leak probes;
- malformed raw observations;
- invalid worlds;
- lossy information keys;
- a diverging replay;
- a declined-offer deck on which A06 failed instead of passing without an exchange;
- the unweighted-receiver error;
- the soft-to-greedy failure;
- a harmful signal;
- the stolen/unresolved bookkeeping.

Several defects were found by these tests and fixed; see the review below.

**Independent review.** A read-only reviewer found no bug in the overlay or the estimator mathematics. It found seven likely bugs and several weak tests elsewhere. All are fixed or dispositioned in `research/independent_review_c0_c1.md`. The most important was the C1 stream labelling, which would have correlated errors across fresh-fork cases; streams now hash the agent's pre-call RNG state.

## 6. Resources (contract stage; `logs/resource_ledger.jsonl`, `logs/resource_summary.json`)

| Quantity | Used | Cap |
|---|---|---|
| Wall time (all executions, incl. builds and reruns) | 245 s | 900 s |
| Total CPU (children and threads) | 454 s | 1,800 s |
| Development fixture decks | 11 | 32 |
| All cheap-policy decks (fixtures + runner tests, conservative) | 27 | 32 |
| Independent search-observation probes (W ≤ 128) | 30 | 32 |
| Complete search-played smoke deals | 2 | 2 |
| Native search calls (all) | 334 | — |

- Python workers: 1. Native searches: one at a time.
- One ledger entry (the baseline write) is a recorded conservative estimate rather than a measurement.
- The first A06 attempt played a complete search deal whose searched offers declined. It is counted as one of the two smoke deals, and no third was run: R02 drives searching agents on both teams for two legal actions only.
- **Resource failures: none.**

## 7. Mechanism status and what each still needs

| Mechanism | Contract result | Key contract findings (measured) | Next empirical requirement (gated) |
|---|---|---|---|
| **C1** control variates | PILOT_READY | Proxy exact against the RESEARCH oracle. Estimator unbiased by exact enumeration of the implementation. Shadow advancement leaves W128's state bitwise. One C1 call costs 0.013–0.091 s CPU against 0.025–0.30 s for W128 on two fixtures. **A bid search costs 2–6 s, so the NOLO-discard branch fraction *f* is likely small, and the program saving is bounded by *f*·*r*.** | P.C1: measure *f* first; fit β on FIT and (M, n) on PLAN; reference-noise-corrected MSE at equal CPU on SCREEN |
| **C3b** utility stopping | CONTRACT_PASS | Certificate equals the authoritative-rules oracle on all 45,500 grid states (29% certify, mostly at high scores); sound against exhaustive continuations; no batching effect on a case where 146 of 256 rows stopped. **With the as-is 6-trick tail, 0 rows certified on the tested case.** | P.C3b: natural eligible-row rate and saved CPU |
| **C2** consequential bids | CONTRACT_PASS (C2.01, C2.02) | F/R/RC separated with exact controls. Predecessor observations match the engine byte for byte. On F01 the clone predecessors passed in 23 of 23 sampled layouts. Searching predecessors are fork-isolated, with state-exact caching; no literal cancellation is claimed. | P.C2: reach frequencies by seat and score; calibration against search forks; then natural v3 games |
| **C3a** kernel | CONTRACT_PASS | The solver reproduces the equity table on the 100-state chain. Setter inventory complete. C ≡ P tested bitwise on a bid search (O differs), giving 1,600 nominal states. The model is an idealisation, not B0. | P.C3a: row sampling and direct-match validation at a declared tolerance |
| **C4** exchange | CONTRACT_PASS (C4.01, C4.02) | Legal 52-card scorers with a hidden-hand-invariant, switch-off-exact wrapper. 169-branch tables at 13/13 hand sizes. Exact toys show uniform message weighting fails and greedy recalibration is needed. Convention-aware defence **UNRESOLVED**. | P.C4: approved training on a fresh frozen-offer accepted bank; four-arm screen |
| **C5** three-card option | CONTRACT_PASS (C5.01, C5.02) | F05: an 18-world complete support (strict and native laws agree); the option is at least the W128 comparator's value and at most the clairvoyant bound; 1,017 nodes in 21 ms; fallbacks recorded. | P.C5: coverage, latency and equity per option on 64 eligible positions; then against searching players |

## 8. Reproduction

```sh
cd ~/Developer
python3 audit_deliverables/tuppi_implementation_plan/verify_package.py --audit-dir audit_deliverables/tuppi_design_20260925_184608
python3 audit_deliverables/tuppi_implementation_plan/reference_math.py --json /tmp/refmath.json   # 17 pure tests
cd TuppiAI
sh native/research/build_research.sh                          # B0-source (== installed) + R0 research build
P=~/.venvs/tuppi-v2/bin/python
$P -m tuppi_ai.research.fixtures                              # F01-F06 (deterministic, 10 decks)
$P -m tuppi_ai.research.parity                                # A03, three separate processes
$P -m tuppi_ai.research.parity --chunk-check                  # chunk invariance on network-using cases
$P -m pytest tests/research -q                                # 109 contract tests
~/.venvs/tuppi-ai/bin/python tests/research/oracle_research_suits.py   # RESEARCH oracle (also run by a test)
$P -m tuppi_ai.research.cli protect-check                     # A12
$P -m tuppi_ai.research.cli validate-manifest ../audit_deliverables/tuppi_implementation_output/research/c1_pilot_manifest.json
# wrap any of these in: $P -m tuppi_ai.research.ledger --purpose "..." -- <command>
```

The baseline manifest and protected snapshot are written once and are immutable, so rerunning the identity capture refuses to overwrite them.

## 9. Next executable gated task

**P.C1, the C1 planning and screening pilot.** It needs the owner to complete and approve `research/c1_pilot_manifest.json`: numeric CPU, wall and memory caps, sample sizes and the futility rule.

Its first step should be to measure the NOLO-discard branch's CPU fraction *f* in natural v3 W128 play. If *f* < 0.2, the package's full-game "20% total CPU" promotion route is arithmetically unreachable for C1 whatever its local gain. The owner may then prefer the C3b rate measurement, P.C3b, as the cheaper first pilot. Either way, no pilot starts without that approval.

## 10. Addendum (2026-09-26): C1 branch fraction measured

With the owner's approval, one bounded pre-pilot measurement ran: 12 deals, 116.8 CPU-s
(`research/c1_f_measurement_results.md`).

- The NOLO-discard branch is **f ≈ 1.3%** of CPU (95% interval 0–3.8%).
- C1's total CPU saving is therefore at most about 2% under generous assumptions, and most likely under 1%.
- Bid searches take 53% of CPU and early RAMI trick play about 32%.
- C1 is not recommended for a pilot. It stays PILOT_READY; P.C1 stays NOT_AUTHORISED.

## 11. Addendum (2026-09-26): C5 stage-1 screen (owner-approved)

- 64 eligible positions from 68 natural v3 deals; 886 CPU-s (`research/c5_screen_stage1_results.md`).
- Only 25% had a support within the 100-world cap.
- Against the real W128 opponents, 11 of 14 started options fell off-support at the next decision (fixed-clone model mismatch).
- Realized transfer was −0.0014 per position (95% −0.0040 to +0.0013). The only changed outcome lost 3 tricks.
- **C5 v1 is not recommended for promotion.** P.C5 is PILOT_COMPLETE (stage 1).

## 12. Addendum (2026-09-26): C2 stage-1 screen (owner-approved)

- 30 natural deals, 50 evaluated blind bids, 512 CPU-s including the pre-flight (`research/c2_screen_stage1_results.md`).
- The current bid search treats 22–38% of its worlds as consistent with earlier bidders who, under the clone model, would not have passed. The clone model agrees with the real W128 bidders on 96% of calibration worlds.
- Reweighting at a fixed 64-world budget made validated choices worse (a winner's curse from the smaller effective sample).
- Proposed stage 2 (not run): equal effective sample via rejection sampling, validated against the live W128 pick.

## 13. Addendum (2026-09-26): C2 stage 2 (owner-approved)

- 30 fresh deals, 44 blind bids, 548 CPU-s (`research/c2_screen_stage2_results.md`).
- Reach conditioning at an equal effective sample (128 pass-consistent worlds) did not improve validated bid choices. The conditioned pick minus an unconditioned W128 resample was −0.0005 ± 0.0003 per reached call.
- A fresh W128 resample alone changes the bid in 57% of positions: bids are near-ties dominated by sampling noise.
- **C2 is not recommended for a whole-game test.**
