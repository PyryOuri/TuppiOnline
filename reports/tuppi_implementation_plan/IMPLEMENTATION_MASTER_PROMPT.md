# Task: implement the audited Tuppi research programme

You are the implementation lead in a workspace containing TuppiAI, the authoritative v3 engine checkout, and the separate older research checkout. This is an implementation task, not another general research review.

Read `IMPLEMENTATION_SPEC.md`, `ACCEPTANCE_TESTS.md`, `EXECUTION_PLAN.json` and the supplied audit bundle. The specification defines five research mechanisms, their scope, integration points, tests and empirical gates. Proposed names in that specification are interfaces to implement, not existing functions to invoke blindly.

## Objective

Build isolated, reproducible research implementations and a trustworthy v3 evaluation path. The first release milestone is C0 plus C1: correct identities, legal observation transport, controller replay/forking, explicit-world ordinary NOLO evaluation, the analytical proxy and fixed-target control-variate estimator, with discriminating tests and a pilot-ready manifest. Continue to the remaining correctness implementations in dependency order as resources permit. Do not claim a mechanism improves play before its separate empirical test.

Deliver all code, patches, tests, commands and reports needed for someone else to reproduce the work. Complete tasks now within the authorised scope; do not promise asynchronous progress. Persist checkpoints if the task must be resumed.

## Authority and boundaries

This prompt, when supplied as a coding task, requests isolated research code and bounded correctness tests. It does not authorise modifying the live bot, replacing the installed dylib, repairing the intentionally retained v3 settings issue in place, altering persistent rooms or client schemas, opening protected banks, training at scale, starting long evaluation campaigns, using paid services, installing/upgrading dependencies globally, or running background processes.

Obey stricter repository/user restrictions. Defaults for the contract-test stage are ceilings, not required workloads: one Python worker; no concurrent native searches; at most 32 development deals generated with cheap policies for fixture construction; at most 32 independent search-observation parity probes, W<=128; at most 2 complete search-played games strictly as engine smoke tests; 15 minutes aggregate wall and 30 minutes aggregate total CPU for the contract stage. Count descendant CPU. Stop earlier if metadata/resource limits cannot be respected. These tests cannot support a playing-strength claim. A pilot/training/confirmation run requires a separately enabled manifest and numeric approved caps; none is enabled by default.

No permission escalation. No deletion/reset/stashing of other people's work. Do not solve import conflicts by loading two versions of the same engine package into one process.

## First actions

1. Locate the supplied files and verify audit package hashes. Compare the named on-disk sources to their audit hashes; record changed files and review only the affected dependencies. Do not force the workspace back to the old snapshot.
2. Identify the actual designated Python environment and imported ENGINE paths from safe documented configuration. Record source, model, equity and loaded-library identities. Do not read private rooms or process secrets.
3. Create a separate research output directory and immutable baseline manifest. Preserve AI, ENGINE, RESEARCH and CLIENT identities as distinct. Dirty RESEARCH files must not be overwritten.
4. Run the provided `reference_math.py` pure tests. They check design identities only; they do not validate Tuppi code. Then build real contract tests from the game source and fixture recipes.
5. Write `IMPLEMENTATION_STATE.json` with every DAG task's status before implementation. Use statuses NOT_STARTED, IN_PROGRESS, IMPLEMENTED_NOT_TESTED, CONTRACT_PASS, PILOT_READY, BLOCKED, NOT_AUTHORISED, REJECTED or CONFIRMATION_PASS. Never equate scaffolding or test presence with a pass.

## Non-negotiable design choices

- Use current `best_agents` settings for as-is comparisons, including the effective per-seat seed mapping and inherited settings. The audited clone is encoder 2 / 1951 inputs, not encoder 1 / 1223.
- Separate installed binary, unmodified-source build and instrumented research build. Build to a new path. No pointer from one library may be passed to another. Record parity boundaries honestly if installed/source correspondence cannot be proved.
- Preserve the source's float32 terminal-equity rounding, float64 aggregation, legal-action order and tail threshold in parity mode.
- `Env.set_state` is not a controller clone. Implement ReplayFork first; add complete native-state export only where justified. Reference searches must not advance an actual candidate/comparator.
- Baseline worker reuse causes cross-deal state dependence. The principal new deal instrument creates independent matched arm environments per base bundle. Full matches preserve controller state across deals within each leg. Both lifecycle labels are explicit.
- The old complementary-match runner is not a v3 confirmation instrument. Build a v3 runner around authoritative legal engine transitions and arbitrary named opponent factories, including searching teams.
- A match cap is unresolved, not an automatic 0.5 draw. Keep failures and report appropriate bounds.
- Policies receive only their own legal observation and allowed own state. Full worlds remain private evaluator data. Do not leak truth through IDs, seeds, filenames, masks or feature shortcuts.

## Mechanisms to implement

**C1:** only ordinary NOLO discards initially. Split sampling from native continuation evaluation. Calculate the per-world contested-round liability contrast from remaining hands; do not use an observation-constant analytic mean. Fit a single beta on independent development data and combine independent cheap and expensive batches. Preserve the current sampling/continuation target. Validate mean/variance identities, signs, action order, input immutability, trace parity and RNG advancement. Shadow-advancement and natural-stream variants have separate identities and cost accounting. No adaptive racing or deviation-margin heuristic in version1.

**C2:** start with deterministic clone predecessors. Construct legal masked precommit observations, derive the all-earlier-NOLO event from jointly sampled hands, retain actual chosen shown cards, and estimate unnormalised event-weighted contrasts. Test forehand/all-pass/never-pass cases and separate event weighting from shown-card generation. Search-predecessor extension must use side-effect-isolated forks and a faithful call schedule; do not assert cancellation for arbitrary persistent-state interventions.

**C3b:** conservatively enumerate feasible final ordinary trick totals and stop a simulated row only when all map to the same existing float-rounded utility. Do not manufacture a completed game outcome. Check whole-evaluator batching effects before claiming bitwise parity.

**C3a:** build a pure kernel solver and state-sufficiency report. Investigate the proposed cold/offer/play mode automaton and its at-most-8100-state independent-randomness model. This is a proposed model, not a validated reduction of the literal PRNG machine. Do not run row sampling or replace the equity table until state assumptions and budget are explicitly approved.

**C4:** add legal stage-specific 52-card scorers and pre-give four-arm replay. Freeze offer and play functions. Train/prepare the joint objective with receiver examples weighted by the giver's message policy; uniform enumeration of messages does not establish a learned convention. Whole-deal splits, accepted-population denominators, strong legal continuation, harmful-message tests and independent greedy-policy validation are mandatory. Large training and convention-aware-defender experiments remain disabled until approved.

**C5:** actual-root ordinary three-card option, not a per-world DD replacement. Initially require complete strict/native-support agreement under a small cap, v3-preserving reconstruction and deterministic masked other-seat clones. Group histories by full root information, choose one response per group, retain the option and fall back on off-support events. Compare complete root policies with correct forks. Root-optimal value cannot be below a feasible comparator in the same exact model; negative action gaps, not negative optimal improvements, are the negative controls.

## Execution and collaboration

Use EXECUTION_PLAN.json as a dependency graph. The default first milestone ends with C0+C1 contract completion and pilot readiness; the full specification governs subsequent milestones without requiring a new broad audit. On a real blocker, finish independent tasks and report the precise missing interface/evidence/authority. Do not build empty placeholder APIs and call the milestone implemented.

If subagents are available, assign bounded modules and independent test review. One owner alone edits native overlays and shared runner/contracts. No subagent launches costly runs. Require each to return changed paths, hashes, commands, test results and unresolved issues. Do not request private chain-of-thought; request technical justifications and evidence.

Implement tests capable of failing: hidden-world collisions, a wrong proxy, zero-hit reach, harmful exchange, reset/overshoot, off-model option and unresolved matches. Do not merely snapshot your own implementation's output as its oracle. Use independent small enumerators and authoritative engine transitions.

## Required final handoff

Return `IMPLEMENTATION_REPORT.md`, `IMPLEMENTATION_STATE.json`, source/new-file patches, exact reproduction commands, test logs, baseline/build/ABI manifests, validation fixtures with separate truth, and the generated pilot manifests (disabled unless separately approved). Provide a portable archive containing the new files and manifests, not model weights or copied private data. Do not duplicate the entire audit in your prose.

The report must state:
- what was actually implemented and executed;
- the exact parent identities and lifecycle tested;
- disabled-mode parity results and limits;
- contract tests passed/failed/skipped with commands;
- measured test CPU/wall and any resource failures;
- each mechanism's status and remaining empirical requirements;
- the next executable gated task, not another generic review request.

A successful first milestone is a verified, isolated C0+C1 implementation and a v3 pilot-ready instrument. It is not a claim of 20% speedup, stronger play, historical reproduction or deployment approval.
