# Tuppi coding and infrastructure handoff — 2026-10-02

The user authorised coding and infrastructure work while heuristic research
occupies the computer's CPU. That constraint remains in force. This delivery
contains an isolated implementation and small logic checks; no training,
benchmark, native build, decision-bank collection or deployment was run.

## Exact source and entry point

- Checkout: `/Users/pyryouri/Developer/TuppiAI-prior`.
- Branch: `research/policy-prior-infra-20261002`.
- Implementation commit: `319e12134ef10945d842f8306b811061128d9ad7`.
- Parent: `43cbaa7873d5d93bd8166d4dcd503f571545e204`.
- Detailed semantics and deferred commands: [POLICY_PRIOR_INFRASTRUCTURE.md](../../TuppiAI-prior/docs/POLICY_PRIOR_INFRASTRUCTURE.md).
- Source integrity record: [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json).
- Authoritative v3 engine: `/Users/pyryouri/Developer/TuppiProject-current/src`.

The branch was frozen with a one-command `Codex <codex@localhost>` Git
identity because no author identity was configured. Global Git configuration
was not changed. The checkout was clean after committing. Main-checkout
source, active jobs, live native library, models and best-agent factory were
not changed. The original C0–C5 and self-play handoffs were preserved.

## Delivered changes

1. **Policy-prior search:** optional `prior=<tau>` ranks legal actions using
   `Q + tau log pi`. Centered legal actor logits produce equivalent offsets;
   no privileged information enters the actor. Offsets participate in adaptive
   leadership, pruning and stopping, with paired raw-Q standard errors intact.
   Raw Q estimates remain available separately.
2. **Allocation control:** `keep_adaptive=1` puts the existing keep-margin
   anchor inside allocation. This is a separate arm from the soft prior.
   Default legacy keep and sooli mechanisms are retained. New arms reject
   incompatible candidate reduction, RAMI bonuses and two-stage showing.
3. **Reusable diagnostics:** an opt-in root recorder, authoritative v3
   collector, completion-marked bank with source/model/native provenance, and
   standard-library replay. Replay excludes partial adaptive prices and
   explicitly labels its outputs as diagnostics, not strength evidence.
4. **Stronger comparisons:** evaluation supports searched opponents and fails
   on incompatible process-wide sampler/NOLO-tail settings. Complete matches
   reaching the cap are unknown outcomes; bounds replace the previous draw
   assignment. Consumers must accept null `p_win`/`ci95` under censoring.
5. **VRPO overhead preparation:** actor batches no longer decode privileged
   critic inputs; critic batches no longer decode actor masks. Detached scalar
   metrics are read in groups. The advantage/target algorithm is unchanged.
6. **Monitoring and final outputs:** cadence zero disables periodic checks;
   optional evaluation-RNG isolation and explicit Torch seed support future
   cadence comparisons. Successful CLI completion checks and saves the actual
   final actor/critic, even between periodic checks. A periodic result is reused
   only for the same iteration and evaluation size. Nonempty output directories
   are refused. Final checking costs are separate from the soft hours limit.
7. **Timing report:** a standard-library reader estimates periodic monitoring
   overhead from existing logs and projects another cadence. New learner logs
   record training/evaluation time separately. Projection is not benchmarking.

The current baseline snapshot uses clone opponent rollouts, VRPO1 own-team
rollouts, the VRPO3 anchor, keep 0.003 and the showing sampler fix. The live
server uses 1024 worlds; the factory default is 128, with adaptive bids above
128. Refresh the actual live configuration before any future experiment;
the active main checkout continues to evolve. Keep existing v3 rollout-setting
persistence in the comparator and separately baseline any subsequent fix.

## Validation performed

`python3 -m unittest discover -s tests -p 'test_*_stdlib.py' -v` passed
**24 tests in 0.002 seconds** of test execution. These cover scoring and ties,
invalid inputs, bank completeness and partial-price exclusion, timing
projections, censored outcomes, searched-opponent routing and global-setting
conflicts. Worker routing uses dependency stubs; it does not exercise native
or Torch code. AST parsing passed for 17 changed/new Python files.
`git diff --check` passed. A source diff confirmed `best.py` and native source
were unchanged from the parent.

**Not validated:** native ABI/build, real model forwards, MPS behaviour,
trajectory equivalence, actual finalisation, end-to-end bank collection,
device throughput, saved compute or bot strength. Deferred tests are supplied
in `test_policy_prior_search.py`, `test_policy_prior_factory.py`, and
`test_vrpo_infrastructure.py`. No measured gain is claimed.

## Continuation order

Do not execute the deferred commands while the user's CPU restriction
remains in force. Continue code review or preparation independently if needed.
When compute becomes available:

1. Build only this checkout's native library; otherwise a bridge import may
   auto-build. Use the canonical v3 engine import path. Run the supplied
   targeted runtime tests, then relevant existing v3 correctness checks.
2. Compare disabled-prior/default-keep traces against a separately frozen
   parent checkout. Pin source/model/native hashes, search seeds, controller
   state, scores and workers. The changing main checkout is not a frozen
   comparison arm. Verify zero-prior plain search before testing variants.
3. Smoke-test final snapshots, both matching and off-cadence checks, and
   evaluation-RNG isolation. Profile the device changes before attributing a
   speedup. For cadence comparisons, seed Torch and enable isolation in both
   cadence-3 and cadence-12 arms; keep final evaluation sizes equal and account
   for finalisation time.
4. Collect a small bank and inspect full-world coverage. Replay can screen a
   small development tau grid, but cannot test changed trajectories or adaptive
   costs. Suggested grid: 0, 0.0005, 0.001, 0.002 equity units.
5. Compare legacy keep, integrated hard keep and soft prior with matched
   settings and compute. Start small, then confirm at W=1024 against the pinned
   full bot, strong heuristic and complete-match endpoints on fresh seeds.
   Choose the confirmation budget before tuning; report censored bounds and
   uncertainty. Do not infer strength from model-Q changes or a small screen.

The detailed document includes exact commands and model paths. No automatic
launcher or deployment switch is enabled. Other research methods and native
C allocation changes are still separate work requiring their own evidence.
