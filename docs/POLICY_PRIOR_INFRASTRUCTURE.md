# Policy-prior search and VRPO infrastructure

Prepared 2026-10-02 for the authorised coding task while heuristic research
occupies the computer. Implementation is isolated in
`/Users/pyryouri/Developer/TuppiAI-prior`, branch
`research/policy-prior-infra-20261002`, forked from
`43cbaa7873d5d93bd8166d4dcd503f571545e204`.

**Status: code prepared; runtime validation and experiments deferred.** No
training, benchmark, bank collection, native build or deployment was run.
The live checkout, running jobs, model files and `best.py` were not changed.
This work is separate from the immutable C0–C5 and self-play planning packages.

## What is implemented

| Component | Change | Purpose |
| --- | --- | --- |
| `tuppi_ai/policy_prior.py`, `search.py` | Optional legal-action scores `Q + tau log pi`; offsets affect E7 leadership, elimination and stopping | Test whether the actor's full preference distribution improves search or saves worlds |
| `search.py` | Separate `keep_adaptive=1` arm adds the existing fixed anchor margin during allocation | Distinguish changing allocation from using a full soft prior |
| `search.py` | Optional logits, raw Q and per-action world counts | Support reusable decision diagnostics without confusing dropped estimates with fully priced actions |
| `evaluate.py` | Search specs and `best` accepted as opponents; incompatible global sampler/NOLO settings rejected | Compare a candidate against a strong searched bot |
| `match_eval.py`, `match_statistics.py` | Capped matches are unknown outcomes with identification bounds | Avoid treating unfinished games as draws |
| `vrpo.py` | Actor batches omit privileged critic features; critic batches omit actor masks; detached scalar metrics transferred in groups | Remove unnecessary decoding and repeated device reads |
| `vrpo.py` | Configurable cadence, separate optional evaluation RNG, explicit Torch seed, actual final-iteration check and actor/critic files | Reduce monitoring work while preserving an explicit endpoint |
| `tools/vrpo_timing_report.py` | Read-only timing projection from existing logs | Estimate the benefit of fewer periodic checks before spending compute |
| `tools/collect_prior_bank.py`, `prior_replay.py` | Provenance-bearing authoritative v3 bank and cheap scoring diagnostics | Screen prior strengths using already computed root values |

None of these changes proves a stronger bot. The VRPO advantage/target recipe
is unchanged. Native C scratch-buffer changes and the other research methods
remain outside this implementation; they need measurements and separate work.

## Search semantics and defaults

`prior=<tau>` uses legal logits from the anchor model, encoded from the
searching player's observation. Centering logits gives offsets
`tau * (logit - max_legal_logit)`, which rank actions identically to
`tau log pi` at temperature one. Tau and keep are in **equity units**, not
`RETURN_SCALE` units. No hidden hands are supplied to this actor.

Raw searched Q values remain raw in `last_values`. The prior is deterministic
for the root observation: it shifts paired means without changing their
standard errors. Adaptive search returns its surviving leader; dropped
actions must not be reselected by comparing stale means afterward.

The existing post-search `keep` rule remains the default. `prior=0` with no
diagnostic recording follows plain search without an extra actor forward.
Soft prior and fixed keep cannot be combined. New prior arms reject card
equivalence reduction, RAMI bonuses and the two-stage showing shortcut,
because those would change the candidate set or objective. Sooli offer,
acceptance, exchange and play mechanisms are unchanged. In particular, the
existing v3 rollout-setting persistence is retained as part of the comparator;
changing it requires separate baselining.

`record_prior=1` records the legal anchor logits and per-action sample counts
when ordinary root search runs. It is diagnostic and opt-in. Forced actions
and sooli decisions do not produce ordinary root-prior records.

Search sampler fixing and NOLO tail length are process-wide native settings.
Both searched sides must request the same `sf` and `ddn`; otherwise worker
initialisation fails. `best` declares `sf=1, ddn=0`. A direct search spec
defaults to `sf=0, ddn=0`, so specify `sf=1` to compare with `best`.

## VRPO monitoring and final outputs

Historical defaults remain `eval_every=3`, `eval_base=8192`,
`isolate_eval_rng=False`, `torch_seed=-1`. `eval_every=0` disables periodic
checks, but successful CLI completion still calls `finalize()`.
`final_eval_base=0` inherits `eval_base`. A periodic check can substitute for
the final check only if both iteration and sample size match.

Finalisation produces `actor_final.pt`, `critic_final.pt` and `final.json`
from the actual last iteration, including between scheduled checks. These
are model snapshots, not full optimizer/resume checkpoints. Final checking
is additional to the soft `--hours` training limit, and its cost is recorded
in `finalize_s`. Each iteration also records `training_s`, `evaluation_s`
(including checkpoint writes), and `total_s`.

For a future cadence comparison, use an explicit Torch seed and enable
evaluation-RNG isolation in **both** arms. The option separates the native
check RNG and preserves the CPU Torch RNG around snapshot construction.
Its full runtime independence still needs validation; it does not promise
deterministic MPS training. Changing cadence with historical shared RNG can
change the training trajectory.

Candidate future configuration, after validation: retain the existing model
and learner settings, use `--eval-every 12 --eval-base 8192
--final-eval-base 8192 --isolate-eval-rng true --torch-seed 19`.
Compare against cadence 3 with the same RNG isolation, seed and final size.
Account for finalisation and confirmation in both compute budgets.

## Checks already run

Only standard-library work was executed:

```bash
cd /Users/pyryouri/Developer/TuppiAI-prior
python3 -m unittest discover -s tests -p 'test_*_stdlib.py' -v
git diff --check
```

Result: **24 logic tests passed in 0.002 seconds** of test execution.
AST parsing passed for all 17 changed/new Python files without executing
imports. Tests cover scoring/ties/invalid inputs, bank integrity and partial
pricing, timing projections, censored results, searched-opponent routing and
global-setting conflicts. Worker tests use dependency stubs: they do not
validate the actual native ABI, Torch model forward or authoritative game loop.

The following files contain deferred runtime checks:

- `tests/test_policy_prior_search.py`: adaptive prior pruning, zero prior and invalid offsets.
- `tests/test_policy_prior_factory.py`: factory wiring and rejected arm combinations.
- `tests/test_vrpo_infrastructure.py`: final snapshots, sample-size matching, CPU snapshot RNG and host reduction.

## Next execution steps when compute is available

No command below has been run. Use a project Python interpreter that already
has the dependencies; do not install or change the active job's environment.
Run from this worktree, with the v3 engine explicitly first on the engine
import path. The collector verifies that engine's actual module path.

```bash
cd /Users/pyryouri/Developer/TuppiAI-prior
export PYTHONPATH=/Users/pyryouri/Developer/TuppiAI-prior:/Users/pyryouri/Developer/TuppiProject-current/src
sh native/build.sh
python3 -m pytest -q tests/test_policy_prior_search.py tests/test_policy_prior_factory.py tests/test_vrpo_infrastructure.py
```

This build writes only the isolated worktree's library. It is required before
Torch/native imports: the bridge can otherwise automatically build a missing
library. After these checks, reproduce baseline traces and benchmark unchanged
native paths on a separately frozen parent checkout. Pin engine source,
model hashes, native library, starting scores, worker count and search seeds;
the active main checkout can continue changing and is not a frozen control.
Require `prior=0` and disabled recording to reproduce plain-search choices,
and default legacy keep to reproduce the parent. Run existing relevant v3
sampler, differential and best-agent checks as part of that validation.

For a small VRPO smoke run after that gate, use a fresh output name:

```bash
python3 -m tuppi_ai.vrpo --name infra_smoke_20261002 --iterations 1 --hours 0.1 --games-per-iter 32 --minibatch 128 --actor-epochs 1 --critic-epochs 1 --critic-width 32 --critic-blocks 1 --compile false --eval-every 0 --eval-base 8 --final-eval-base 8 --isolate-eval-rng true --torch-seed 19
```

This is a runtime smoke check, not strength evidence. The default baseline
checkpoint is in `TuppiAI/runs/bc_small.pt`; verify that explicit dependency
before running. The learner refuses nonempty output directories.

For a read-only projection once an existing log path is selected:

```bash
python3 tools/vrpo_timing_report.py /absolute/path/to/log.jsonl --old-eval-every 3 --new-eval-every 12
```

Old logs estimate check overhead from neighboring non-check iterations after
warmup; new logs use recorded evaluation time. The projection holds training
work per iteration constant, scales periodic-check frequency, and excludes
extra final checking. It is not a measured speedup or a learning-quality result.

### Reusable decision bank

After baseline validation, collect a small bank in a fresh location:

```bash
python3 tools/collect_prior_bank.py --out runs/prior_bank_20261002.jsonl --deals 16 --worlds 1024 --seed 19 --max-seconds 600
python3 tools/prior_replay.py runs/prior_bank_20261002.jsonl --tau 0 0.0005 0.001 0.002
```

The collector follows the unchanged best factory through the authoritative
v3 engine. Controllers persist across deals; each deal starts a fresh match
state with randomized dealer and score. A manifest identifies AI and engine
commits, selected source hashes, native library and models. A `.partial` file
is renamed only after a completion record; the wall cap is soft at deal
boundaries and may exceed 600 seconds. Model/source identity must be frozen
during collection. Full hands are stored for research; the actor sees only
its player observation.

Replay is standard-library-only. It excludes decisions where any action saw
fewer than the full requested worlds, including early-stopped E7 bids. That
exclusion can bias the diagnostic subset, so do not generalise it to all
decisions. Action-change rates and mean model-Q changes on baseline
trajectories are diagnostics; `strength_evidence` is explicitly false.
Replay cannot assess changed trajectories, uncertainty or allocation costs.
If too few full-world records remain, collect a separately identified fixed
allocation bank rather than interpreting partial estimates as full prices.

### Controlled search comparisons

Use the following common configuration with **explicitly frozen model files**.
The paths below refer to this worktree's snapshots. `rs=1` is common to all
controlled arms so search worlds are seeded from each information state.

```bash
ROLLOUT=/Users/pyryouri/Developer/TuppiAI-prior/models/rollout_clone_small.pt
TEAM_POLICY=/Users/pyryouri/Developer/TuppiAI-prior/models/vrpo1_actor_0504.pt
ANCHOR_POLICY=/Users/pyryouri/Developer/TuppiAI-prior/models/vrpo3_final.pt
COMMON="search:${ROLLOUT}:w=1024:dd=6:show=1:team=${TEAM_POLICY}:sf=1:bp=${ANCHOR_POLICY}:adb=128:adz=2.5:add=0.005:rs=1"
LEGACY="${COMMON}:keep=0.003"
HARD="${COMMON}:keep=0.003:keep_adaptive=1"
SOFT="${COMMON}:prior=0.001"
PLAIN="${COMMON}:prior=0"
python3 -m tuppi_ai.evaluate --checkpoint "$SOFT" --opponent "$LEGACY" --ruleset v3 --scores uniform --deals 64 --workers 1 --seed prior_dev_20261002 --out runs/prior_dev_20261002.json
```

The example is a development screen, not confirmation. Also compare hard
versus legacy, soft versus hard, and plain versus legacy. Start with a small
W=128 fixed-allocation screen if useful, then test W=1024/E7; report both
absolute strength and seconds per deal. Predeclare a small tau grid and a
separate fresh-seed confirmation budget before choosing the candidate.
Include the strong incumbent profile, the pinned full searched baseline,
and complete-match results. Tests only against a heuristic do not establish
a stronger live bot. Explicit reseeding is an experimental control; the
unchanged live factory does not enable it, so also confirm against the pinned
factory configuration under its original sampling behaviour.

```bash
python3 -m tuppi_ai.match_eval --checkpoint "$SOFT" --opponent "$LEGACY" --ruleset v3 --pairs 64 --workers 1 --cap 400 --seed prior_confirm_20261002 --out runs/prior_matches_20261002.json
```

This example size is not a power calculation. Complete-match censoring
produces `p_win_bounds`, which bound the observed missing outcomes and are
**not confidence intervals**. If any leg is censored, `p_win` and `ci95` are
null; complete-pair win/tie/loss counts are descriptive only. Increase the
cap or report unresolved bounds. Even uncensored normal-approximation paired
intervals need adequate sample size. Pin worker count and controller state;
searchers can retain state across games, so a fixed seed alone is not a
guarantee of independence or exact reproduction.

Record builds, runtime correctness, measured throughput and strength results
separately. Until those gates pass, keep this branch out of the live bot.
