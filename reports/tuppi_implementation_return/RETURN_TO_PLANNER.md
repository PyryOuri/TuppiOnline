# Return deliverable: Tuppi C0–C5 implementation and pilots

**To:** the LLM that produced `Tuppi_Implementation_Package` (IMPLEMENTATION_SPEC v1.0, EXECUTION_PLAN.json, ACCEPTANCE_TESTS.md).
**From:** the implementing LLM, working in the owner's workspace.
**Date:** 2026-09-26.
**Reading assumption:** you have your package but no workspace access. Everything referenced is inside this return package (`implementation_output/`, `code/`, `patches/`). Run `verify_return.py` to check the package's integrity.

---

## 1. Bottom line

1. **Every executable task in your DAG is implemented and contract-tested.**
   - C0.01–C0.07, C1.01–C1.02, C3b.01, C2.01, C2.02, C3a.01, C4.01, C4.02, C5.01 and C5.02 are **CONTRACT_PASS**.
   - C1.03 is **PILOT_READY**, then set aside by the owner.
   - 109 contract tests cover all 74 acceptance IDs: 109 pass, 0 fail, 0 skipped.
2. **With the owner's explicit, bounded approvals, three mechanisms were measured on the real bot. None shows a meaningful gain.**
   - **C1:** the NOLO-discard branch is only **f ≈ 1.3%** of CPU, so C1 can save at most about 2%. Your 20% total-CPU target is unreachable.
   - **C5:** coverage is 25%. The fixed-clone opponent model mismatches the real W128 opponents: 11 of 14 started options became unusable at the next decision. The transfer result is −0.0014 per position, and the only changed outcome lost 3 tricks.
   - **C2:** the premise holds (about 30% of the bid search's worlds are inconsistent with the earlier passes). But conditioning does not improve validated bids, even at an equal effective sample: −0.0005 ± 0.0003 per reached call against an unconditioned control.
3. **C3b's certificate is exact but barely applies** with the bot's 6-trick solver tail. **C4 and C3a were not piloted**, by the owner's decision.
4. **The owner agreed to stop the package's pilots here.** Nothing live was changed and nothing was committed.

## 2. Inputs verified and workspace identity

- **Your package:** `verify_package.py --audit-dir …` exited 0 (14 package payloads, 11 audit payloads, 27 tasks, 74 test IDs). `reference_math.py` ran 17 of 17 pure tests.
- **Source drift against the audit:** 0 of 62 evidence files changed. All four HEADs match the audit: AI `4220f249`, ENGINE `1347153f`, RESEARCH `622d5599` (144 dirty entries, hashed and untouched), CLIENT `7ba8ca28`.
- **Environment:** `~/.venvs/tuppi-v2` resolves `tuppi_engine` and `tuppi_rules` to ENGINE and loads no RESEARCH module (A01). It runs Python 3.14.2, numpy 2.5.3 and torch 2.14.0. Hardware: M3 Max, 14 cores, 36 GB.
- **Model and equity match the audit:**
  - `rollout_clone_small.pt` `38737c90…`: encoder 2, 1951 inputs, width 256, 2 blocks, 156 outputs;
  - `equity_incumbent.json` `1496f771…`;
  - installed `libtuppi.dylib` `02d9b4fa…`.

## 3. What was built

All new files, in the TuppiAI checkout. No existing file was edited, and the installed library is unchanged (A12 check passes).

| Area | Files (in `code/…tar.gz`) | Realises your spec |
|---|---|---|
| Native research build | `native/research/{build_research.sh, overlay.patch, research_api.c, research_api.h, pinned_sources.sha256}` | §1.2, §2.1–2.3. The patch (225 lines, applied to a *copy* of `tuppi_env.c`) splits `search_core` into `sample_root_worlds` and `continue_rollouts`, adds an optional research context (row status, work counters, switches) and the C3b certificate. `research_api.c` includes the patched file to reach private state. **API v3** covers explicit-world evaluation, trace, sample-only, ABI layout, world/observation validation, config export/import, and the C3b exports. |
| Identity, ledger, CLI | `tuppi_ai/research/{identity,ledger,cli,manifests}.py` | C0.01, C0.07, the resource caps, disabled manifests |
| Records and transport | `records.py`, `observation.py`, `streams.py` | C0.02: strict inverse of `observation_to_data`, information keys, truth store, split lineage, domain-separated streams |
| Lifecycle | `lifecycle.py`, `clone_policy.py` | C0.03: named factories, ReplayFork, NativeFork, snapshots, sooli-mode tracker |
| Native ownership and parity | `native_api.py`, `probe.py`, `parity.py` | A02–A04; three-library parity in separate processes |
| Fixtures, runner, statistics | `fixtures.py`, `runner_v3.py`, `statistics.py` | C0.05–C0.07 |
| Mechanisms | `c1_control_variate.py`, `c1_dispatch.py`, `c3_utility_stop.py`, `c3_kernel.py`, `c2_blind_bids.py`, `c4_exchange.py`, `c4_training.py`, `c5_option.py` | C1–C5 |
| Pilot scripts (owner-approved runs) | `measure_branch_fraction.py`, `c5_screen.py`, `c2_screen.py`, `c2_stage2.py` | §10 below |
| Tests | `tests/research/*.py` (109 tests plus an isolated RESEARCH-environment oracle), `tests/conftest.py` | ACCEPTANCE_TESTS.md. `tests/conftest.py` keeps them out of the owner's default run, which still collects exactly the 35 pre-existing tests. |

## 4. Task status (`implementation_output/IMPLEMENTATION_STATE.json` has the evidence per task)

| Task | Status | Task | Status |
|---|---|---|---|
| C0.01–C0.07 | CONTRACT_PASS | C4.01, C4.02 | CONTRACT_PASS |
| C1.01, C1.02 | CONTRACT_PASS | C5.01, C5.02 | CONTRACT_PASS |
| C1.03 | PILOT_READY; set aside after the f measurement | P.C1 | NOT_AUTHORISED (only a bounded f measurement was approved and run) |
| C3b.01 | CONTRACT_PASS | P.C5 | PILOT_COMPLETE (stage 1) |
| C2.01, C2.02 | CONTRACT_PASS | P.C2 | PILOT_COMPLETE (stages 1 and 2) |
| C3a.01 | CONTRACT_PASS | P.C3b, P.C4, P.C3a, CONFIRM, COMPOSE, DEPLOY | NOT_AUTHORISED |

## 5. Acceptance-test mapping (all 74 IDs; details in `implementation_output/IMPLEMENTATION_REPORT.md` §5)

| IDs | Where |
|---|---|
| A01, A02, A04, A12 | `tests/research/test_c0_identity_native.py`; A12 also `logs/protect_check.json` |
| A03 | `builds/parity_report.json`, plus `builds/r0_api_v1/` for the three-library run |
| A05, A10 | `test_c0_observation.py`; A10 also in `test_c0_lifecycle.py` |
| A06–A11 | `test_c0_lifecycle.py` |
| F01–F06 | `research/fixtures/` (all VALIDATED; truth kept separately) |
| R01–R06 | `test_c0_runner_statistics.py` |
| V01–V10 | `test_c1.py` (23 tests); V11 is in `test_c0_runner_statistics.py` |
| B01–B08 | `test_c2.py`, `test_c2_search.py` |
| K01–K04 | `test_c3b.py` |
| K05–K09 | `test_c3a.py` |
| X01–X12 | `test_c4.py`, `test_c4_training.py` |
| O01–O10 | `test_c5.py` |

**Negative controls built in:**
- a biased and a batch-reusing estimator mutant;
- hidden-card and integer-mask leak probes;
- 10 malformed raw observations;
- invalid worlds (trick totals, actor, hidden bids);
- a lossy information key;
- a diverging replay;
- the unweighted-receiver error;
- the soft-to-greedy failure;
- a harmful signal;
- censoring bounds.

**The final test log is `logs/pytest_research_final.log`.**

## 6. Parity and binary provenance (your §1.2)

- **The unmodified-source build is byte-identical to the installed library** (`02d9b4fa…`). The audit's "installed/source correspondence unproven" is resolved for this toolchain.
- **Every research build was checked against B0 with all switches off:**
  - API v1 `10352806…` against B0-installed and B0-source;
  - API v2 `d6c62316…` and v3 `221fe041…` against B0-source.
  - Each was bitwise equal on 13 probes (NOLO discards, a lead and a three-card suffix; v3 bids in all three sooli-setting modes; sooli offer, give and play; ordinary RAMI after two declines; W16; chunk 128) and on a 6-call best-agent sequence (actions, values, both RNGs).
- **Rollout chunk invariance:** chunk 32 vs 128 is bitwise equal on two network-using cases (4,096 and 44,928 MLP rows).
- **Limit:** this is tested equivalence on these cases, not a proof.

## 7. Resources

| Stage | Wall | CPU (children and threads) | Notes |
|---|---|---|---|
| Contract stage (all builds, fixtures, parity, tests and reruns) | 273 s | 485 s | Caps were 900 / 1,800 s. Fixture decks 11; all cheap-policy decks 27 (cap 32); probes 30 (cap 32); complete search smoke games 2 (cap 2) |
| Owner-approved measurements and pilots | 389 s | 2,115 s | Each had its own manifest and caps (§10) |

The full ledger is `logs/resource_ledger.jsonl`. One entry is a marked estimate. There were no resource failures.

## 8. Independent review

A read-only reviewer found **no bug in the overlay refactor or the estimator mathematics**. It found **7 likely bugs plus weak tests**; all are fixed (`research/independent_review_c0_c1.md`):
- missing native `TcObs` validation (possible out-of-bounds writes);
- weak world-consistency checks;
- an M = 1 variance field;
- **C1 stream labels that would repeat across fresh-fork cases (correlated errors)**;
- `C1Candidate` not supported by snapshots and forks;
- flat instead of within-case, then within-deal MSE averaging;
- complete-case deletion in bundle summaries.

## 9. Where I interpreted, extended or departed from your spec (please review)

1. **Budget accounting.** Contract caps were treated as aggregate over the stage. Deck and probe counts are deduplicated by identity (a deterministic rerun is not a new deal), while CPU for every rerun is charged. Runner-test decks are counted separately and conservatively. The first A06 attempt played a complete search deal whose searched offers declined; it consumed one of the two smoke games, so R02's searching teams were exercised for two legal actions only.
2. **Library selection.** `native_api.bind_native(path)` redirects `tuppi_ai/native.py`'s single `CDLL` call during import. The unmodified agent code then runs on B0-source or R0 in a process; cross-library comparisons run in separate processes.
3. **C1 streams (spec §2.2).** Candidate streams are SHA-256 over the namespace, a required run id, the seat and a **copy of the agent's pre-call scalar RNG state**. This is actor-local, reproduced by forks, and distinct per agent and call. Shadow advancement then draws and discards W128's root worlds.
4. **C1 β.** Implemented as your covariance slope (FIT only, via `fit_beta_on_split`). I also added `optimal_beta = slope·M/(M+n)`, the variance-optimal fixed β for your two-batch estimator; it is recorded but unused.
5. **C1 scope.** Only v3 decisions are eligible; other rulesets delegate. A failure falls back to W128 on an intention-to-run basis.
6. **C3a.** I deduced, and tested bitwise on a real bid search, that sooli modes **C (cold) and P are behaviourally equivalent** for the pinned factory. Belief and λ are re-set before every root sooli search; only `play_heur` and `return_pi` reach rollouts. The per-seat mode is therefore binary: **1,600 nominal states, not 8,100**. The complete setter inventory is test-enforced.
7. **C3b.** The certificate is native, behind a switch. It equals an oracle built on the authoritative `tuppi_rules` on all 45,500 grid states.
8. **F06 "zero-score award".** `DealScore` points are always positive, so I read it as an award from 0-0.
9. **Fixtures are synthetic development states.** F02, F05 and F06 use scripted NOLO contracts with clone play. F03's acceptance is the heuristic offer policy's natural choice, not the searched offer.
10. **C4 payoff tables** use frozen *heuristic* sooli play controllers, with perfect-information survival kept as a labelled proxy. No scorer was trained. Convention-aware defence is UNRESOLVED by design.
11. **C5 key and horizon.** The information key is (seat, own cards, full public play order); the deal's constant public context is checked separately as scope. Forced calls bypass the plan.
12. **Statistics.** `mse_endpoints` averages within case, then within deal, and bootstraps by deal. `bundle_summary` reports worst-case bounds instead of dropping unresolved bundles.
13. **C2 pilot design (additions, not in your spec).** After the pre-flight I added *independent validation of changed picks on fresh worlds* as a winner's-curse guard. Stage 2's equal-effective-sample candidate (rejection sampling to 128 pass-consistent worlds) is my design.

## 10. Owner-approved measurements and pilots (manifests and raw data in `implementation_output/`)

### 10.1 C1 branch fraction (`research/c1_f_measurement_*`, `logs/c1_branch_fraction.json`)

- **Run:** 8 natural v3 deals plus 4 forced-NOLO deals; as-is W128 at every seat; 117 CPU-s.
- **f = 1.3%** (deal-bootstrap 95%: 0–3.8%). There was only 1 NOLO deal among the 8.
- C1-eligible CPU per NOLO deal is 0.55 s (7.25 eligible decisions). 97% of it comes from early discards at about 0.36 s each; late solver-only discards cost 3 ms.
- **CPU by decision:** bids 53% (2.4 s each), RAMI early leads 20%, RAMI early follows 12%, all NOLO play about 7%.
- **Saving bound:** f·r ≤ 0.4–1.9% for r = 0.1–0.5.
- **Disposition:** C1 set aside by the owner.

### 10.2 C5 stage-1 screen (`research/c5_screen_*`, `logs/c5_screen_stage1.json`)

- **Run:** 68 natural deals giving 64 eligible three-card lead positions (the other 4 were sooli deals); 887 CPU-s.
- **Coverage:** complete support ≤ 100 worlds in **16 of 64 (25%)**; the other 48 had 120–1,680 worlds.
- **Started:** 14 options; 2 more hit the 100 ms deadline.
- **Fixed-clone model:** the option lead differs from W128's in 2 of 16 positions; model gain +0.00027 per exact position.
- **Transfer (real deal finished twice with forked W128 opponents):**
  - **11 of 14 options fell off-support at the next decision.** The key path was verified: the true world is in the support and its clone key is in the plan, but the W128 opponent played differently from the clone.
  - Realized difference **−0.0014 per position** (95%: −0.0040 to +0.0013).
  - The only changed outcome: **10 → 7 tricks, −0.087**.
  - Latency p50 3.9 ms, p95 93 ms, max 106 ms.
- **Disposition:** not promoted. In the endgame the real opponents are W128 searchers whose rollouts are all solved exactly, so the clone is a poor model of them.

### 10.3 C2 stage 1 (`research/c2_screen_*`, `logs/c2_screen_stage1.json`)

- **Run:** 30 natural deals (all ended RAMI), 50 reached blind bids with k ≥ 1, 64 worlds each; 512 CPU-s including the pre-flight.
- **Exclusion rate** (sampled worlds in which a clone predecessor would not have passed): **k = 1: 22%, k = 2: 38%, k = 3: 38%** (max 64%).
- **Calibration** against fresh W128 predecessor forks: per-world event agreement 96% over 24 worlds.
- Naive R/RC reweighting at a *fixed* 64-world budget changed picks in 11 and 24 of the 50 positions. **Validated on 256 fresh worlds, R's changed picks were worse: −0.0051 on average, 0 better and 3 significantly worse.** This is a winner's curse: the smaller effective sample flips choices toward high-variance RAMI bids. The same-world "regret" was positive and selection-biased.

### 10.4 C2 stage 2 (`research/c2_stage2_manifest.json`, `…_results.md`, `logs/c2_screen_stage2.json`)

- **Run:** 30 *fresh* deals, 44 bids; 548 CPU-s. Rejection sampling reached 128 pass-consistent worlds every time (30% rejected).
- **Validation law:** the RC model on 256 fresh pass-consistent worlds.

| Arm | Differs from the live bid | Validated gain per reached call vs live |
|---|---|---|
| F128c noise control (fresh unconditioned resample) | **25 of 44 (57%)** | +0.00036 ± 0.00024 |
| R128 | 28 | −0.00027 ± 0.00045 |
| RC128 | 31 | −0.00013 ± 0.00030 |
| **RC128 − F128c (conditioning effect)** | | **−0.00048 ± 0.00028** |

- **Disposition:** not recommended for a whole-game test. The conditioning changes values but not decision quality, and W128 bid choices are near-ties dominated by sampling noise.

## 11. Observations for any next plan (measured facts, not claims)

- **The compute is in bids** (53%, about 2.4 s each) **and early RAMI trick play** (about 32%). NOLO play and sooli are small.
- **W128 bid decisions are unstable:** a fresh 128-world resample changes the bid in 57% of reached positions, with value differences between the competing bids around 0.001. This fits the owner's earlier data: W256 over W128 gained only about +0.0013 per deal across all decisions.
- **The deterministic clone models endgame opponents poorly** (C5). **The native bid sampler ignores pass evidence in about 30% of worlds, yet correcting it does not help** (C2).
- **Per-decision estimator refinements** (control variates, conditioning, exact suffix options) **showed no measurable headroom** at this bot's level in these screens. This agrees with the owner's earlier assessment that the bot's strength is on a plateau. The screens are small (64 and 44–50 positions), so effects below about 0.0005 per decision remain unresolved.

## 12. Not done

- P.C3b (the natural certificate rate) and P.C4 (training plus a four-arm screen). A cheap C4 frequency and payoff check was offered and declined.
- P.C3a (row sampling and direct-match validation), CONFIRM, COMPOSE, DEPLOY.
- No commits. The new files are untracked in the owner's TuppiAI checkout. The owner's live server, app, rooms and other authors' work are untouched.

## 13. Package contents and verification

- `RETURN_TO_PLANNER.md` (this file).
- `RETURN_MANIFEST.json`: machine-readable task states, headline metrics and file hashes.
- `verify_return.py`: checks every file against `SHA256SUMS.txt`.
- `implementation_output/`: IMPLEMENTATION_REPORT.md, IMPLEMENTATION_STATE.json, `research/` (reports, all manifests, validated fixtures with separate truth, the baseline manifest, source drift, the review), `builds/` (build, ABI and parity reports), `logs/` (test logs, pilot data, the resource ledger, the protect check).
- `code/tuppi_research_implementation.tar.gz`: all 50 new source and test files. No dylibs, no model weights, no private data.
- `patches/`: `overlay.patch` and the new-file list with hashes.

**Reproduction** (in the owner's workspace; commands are in IMPLEMENTATION_REPORT.md §8):

```
native/research/build_research.sh
~/.venvs/tuppi-v2/bin/python -m pytest tests/research -q
python -m tuppi_ai.research.{fixtures,parity,measure_branch_fraction,c5_screen,c2_screen,c2_stage2}
```
