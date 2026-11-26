# Training on a GPU machine (Google Colab)

Training-only code. Nothing here is part of the hosted site: the Docker image copies `ai/`,
`engine/`, `qualification/`, `web/` and `start.sh`, never `training/`, and no file under those
directories is changed. `SOURCE.json` (the hosted release's file manifest) therefore still
describes the release exactly; `tests/test_hosted.py` checks that. `training/` is deliberately
not listed in it.

## What this is

`ai/tuppi_ai/vrpo.py` trains on an Apple Silicon Mac: the learner is fixed to `mps`, and
self-play runs in C loops that are parallel on macOS only. On Linux those loops are serial and
the network is evaluated on one CPU core. This directory makes the same training run on a CUDA
machine:

| Piece | File | What it does |
|---|---|---|
| Training library | `build_train.sh`, `native/tuppi_train.c` | Compiles `ai/native/tuppi_env.c` unchanged, with its parallel loops on OpenMP threads, plus `tc_ls_*` functions that let Python drive the engine |
| Lockstep collector | `tuppi_train/lockstep.py` | The engine steps all deals together; the network is evaluated in one batch per step on the GPU. Same rows and rewards as `native.ppo_rollouts` |
| Learner | `tuppi_train/vrpo_gpu.py` | The update of `vrpo.py` on any device, with critic warm-up, evaluation, a stop rule and full resume |
| Offer model | `tuppi_train/offer.py` | Rebuilds the fast sooli-offer model (the original is not in this repository) |
| Evaluation | `tuppi_train/evaluate.py` | Large paired duplicate evaluations |
| Benchmark | `tuppi_train/bench.py` | Throughput of every stage on the machine at hand |
| Notebook | `colab/tuppi_train.ipynb` | All of the above, from a browser |

## Running it

On Colab: open `training/colab/tuppi_train.ipynb` and follow its first cell.

Elsewhere (Linux, Python 3.10+, PyTorch, a C compiler):

```sh
sudo apt-get install -y libopenblas-dev        # or: pip install scipy-openblas32
sh training/build_train.sh                     # training/build/libtuppi_train.so
sh training/build_train.sh --stock             # reference build of the hosted sources, for the tests
python -m pytest training/tests -q             # about 3 minutes on 4 cores, CPU only
python -m tuppi_train.check                    # the same kind of check on the training device
export PYTHONPATH=training
python -m tuppi_train.bench
python -m tuppi_train.offer --out training/runs/offer          # once
python -m tuppi_train.vrpo_gpu --name run1 --hours 1.5 --offer-model training/runs/offer/offer_model.pt
python -m tuppi_train.vrpo_gpu --name run1 --hours 1.5         # same command again continues run1
python -m tuppi_train.evaluate --a training/runs/run1/best_actor.pt --b vrpo4_final.pt,vrpo3_final.pt
```

A run directory holds `log.jsonl` (one row per iteration), `ckpt/` (two rotating full states),
`actors/` (milestones), `best_actor.pt` and `config.json`. On resume the saved configuration is
used; options given on the command line override it.

## Speed options

The default run is plain float32 (with TF32 on CUDA), four critic and four actor epochs on
16,384 deals: the configuration whose update is proven equal to `vrpo.py`. These options trade
that for speed; `python -m tuppi_train.bench --sweep` measures each on the machine at hand.

| Option | Effect | Cost |
|---|---|---|
| `--amp bf16` / `--amp fp16` | Network forward passes in half precision in the sampler and the learner; sums, softmax and losses stay float32; fp16 uses gradient scaling | The learner recomputes the behaviour log-probabilities in its own arithmetic (free: it needs that forward pass anyway), so PPO's ratio still starts at exactly 1. The trained policy is optimised in half precision but evaluated, and deployed, in float32; the sweep reports how often the greedy action differs |
| `--compile true` | `torch.compile` on both networks | Tens of seconds of compilation at the start of every session |
| `--tf32 false` | Exact float32 products on CUDA | Slower on recent GPUs |
| `--games-per-iter N` | Larger batches spread the fixed cost of each lockstep step | More memory; fewer updates per hour |
| `--actor-epochs K --critic-epochs K` | Fewer passes over each batch, more fresh deals per hour | Changes the algorithm: see below |

The sweep recommends the fastest precision that leaves the advantages (correlation at least
0.999 against float32) and the greedy action (at least 99.8% the same) essentially unchanged,
and adds compilation only if it gains more than 10%. Run `python -m tuppi_train.check --amp <x>`
on the device before training with a half-precision option.

Epochs and batch size are a different kind of choice. With the network on a GPU, playing a deal
costs far less than training on it, which argues for fewer epochs on more deals; but that is a
claim about learning, not about speed, and the sweep only reports speed. Settle it by running
two short runs from the same start and comparing their evaluations at equal training time.

## What a run does

1. **Warm-up.** The actor starts as `vrpo4_final` and stays frozen while a new critic learns.
   The critic's error against the deals' actual outcomes is measured on each fresh batch before
   it trains on it (`critic_mc_mse`). The actor starts after at least `warmup_min` (20)
   iterations, once the mean error of the last 5 batches is less than 1% below the mean of the 5
   before, or after `warmup_max` (120). The actor's learning rate then rises from a third of
   `lr_actor` over `actor_ramp` iterations. (The first version compared single batches, whose
   noise ended run1's warm-up at iteration 20 while the critic was still improving.)
2. **Training.** The update of `vrpo.py`, unchanged.
3. **Monitoring.** Every `eval_every` iterations: paired duplicate, greedy, on the same 2,048
   base deals each time, against `vrpo4_final` (the parent), `vrpo3_final` and `vrpo1`. The
   actor with the best result against the parent is kept as `best_actor.pt`.
4. **Stop rule.** Three consecutive evaluations significantly below the parent end the run.

## Starting again from VRPO4 with a trained critic

A run that has trained its critic but whose actor drifted can hand its critic to a new run. The
new run's actor starts from `init` (VRPO4) again; the critic and its optimizer state come from the
old run's latest checkpoint, so no warm-up is needed:

```sh
python -m tuppi_train.vrpo_gpu --name run2 --hours 3 --offer-model training/runs/offer/offer_model.pt \
    --critic-init training/runs/run1 --warmup-max 0 \
    --games-per-iter 65536 --minibatch 65536 --max-kl 0.01 --lr-actor 1e-5 --actor-ramp 10 --eval-every 10
```

These are gentler settings for fine-tuning a network that is already near its optimum: four times
the deals per update, so each gradient step averages four times as many decisions (half the
noise), with the same number of steps per iteration, a third of the learning rate and half the
permitted policy change per iteration. Each iteration takes about four times as long.

`--critic-init` also accepts one of a run's `ckpt/state_*.pt` files, or a critic saved by
`ai/tuppi_ai/vrpo.py` (`critic_latest.pt`; then without optimizer state).

## Stopping a run

Stopping the notebook's training cell (or `kill -TERM`, or Ctrl-C) lets the current iteration
finish, saves, and exits: nothing is lost. A second stop kills it at once; the last 5-minute
checkpoint is then what remains.

## Suit symmetry (the result that matters so far)

By the rules the two red suits are interchangeable and so are the two black ones: a red card
shows RAMI and a black one NOLO, tricks compare ranks within the led suit, there are no trumps.
A perfect policy therefore chooses the corresponding action in all four relabellings. The trained
networks do not: VRPO4's greedy action differs in about 40% of unforced decisions when two
same-coloured suits are swapped. `symmetry.Symmetric(net)` averages the network's logits over the
four views. Paired duplicate on CPU, the averaged network against its plain self:

| Network | Averaged against plain, per deal | Base deals |
|---|---|---|
| `vrpo4_final` | +0.00263 +/- 0.00026 | 8,192 |
| `vrpo4_final`, sooli tricks played by the live bots' rules | +0.00314 +/- 0.00050 | 2,048 |
| `vrpo3_final` | +0.00196 +/- 0.00053 | 2,048 |
| `vrpo1` | +0.00143 +/- 0.00051 | 2,048 |

No training is involved, and the gain is about twice the step from VRPO3 to VRPO4.

**All 24 arrangements in card play.** Only those four are symmetries of the rules, because a show
depends on the card's colour. In card play the other twenty are nearly equivalent (only the shown
cards keep a trace of colour), and averaging card-play decisions over all 24 while showing
decisions keep the exact four (`Symmetric(net, play_views=range(24))`, prefix `sym24:`) gained a
further +0.00081 +/- 0.00064 (1,024 base deals) and +0.00044 +/- 0.00038 (3,072 fresh ones) over
the exact four: about +0.0005 pooled. This is an empirical gain, not a symmetry.

```sh
python -m tuppi_train.evaluate --a sym24:vrpo4_final.pt --b vrpo4_final.pt,sym:vrpo4_final.pt --base 32768
python -m tuppi_train.bake --name sym4 --hours 1.5 --teacher sym24:vrpo4_final.pt --student-share 0.75 \
    --offer-model <offer_model.pt>
python -m tuppi_train.evaluate --a training/runs/sym4/best_student.pt --b vrpo4_final.pt,sym24:vrpo4_final.pt
```

Two ways to use it:

- **At play time**: 4 forward passes per show and up to 24 per card instead of one. Negligible for
  the bots that play the network directly, but it needs the suit relabelling (a fixed permutation
  of feature columns and action ids, `symmetry.feature_perm` / `action_perm`) in the hosted bot
  code. This keeps the whole gain.
- **Baked in** (`bake.py`, `colab/tuppi_symmetry.ipynb`): a plain network, the student, is trained
  to give the averaged network's policy from one pass. Deals are played by the teacher and by the
  student in turn, every unforced decision is labelled with the teacher's policy, and the student
  sees each minibatch through a random exact suit view, so it is taught to be symmetric too. The
  result is an ordinary network file. A CPU trial on VRPO1 (256x2, 150 iterations of 2,048 deals,
  exact-four teacher) baked in +0.00056 +/- 0.00033 of the teacher's +0.0014, about 40%, and was
  still improving slowly; how much a 768x4 student holds after a real run is what the notebook
  measures.

`tests/test_symmetry.py` checks the permutations against the engine (relabel a full state, let the
engine encode it, compare) and the averaged networks against their definitions;
`tests/test_bake.py` checks that the loop learns and resumes exactly.

### What else was checked while looking for flaws of the same kind

Measured on CPU with scratch scripts (paired duplicate unless stated), VRPO4:

| Question | Result | Conclusion |
|---|---|---|
| Are votes split between equivalent cards of one hand (touching cards with nothing live between them), so that the greedy choice misses the preferred group? | Summing them changes 0.3% of decisions: +0.00007 +/- 0.00017; on the averaged network -0.00000 +/- 0.00018 | No |
| Does averaging with VRPO3 help (each suit-averaged, 70/30)? | -0.00005 +/- 0.00049 | No |
| Mean of probabilities instead of mean of logits over the views? | -0.00075 +/- 0.00055 | Worse; logits stay |
| Is the match-equity table (fitted to the heuristic incumbent's deals) still right for VRPO4's deals? | Dealer's side wins 51.3% (table 49.6%), mean 12.6 points a deal (11.3), deals of 24 points or more about twice as frequent; the table rebuilt from 32,768 VRPO4 deals differs by 0.0095 on average, 0.0146 at most | Mildly out of date; matters only through retraining |
| Is 4 of 8 surviving layouts the right threshold for accepting a sooli? For 16,998 first offers both answers were played out from the same deal | With sooli tricks finished by the solver (training, evaluation): accepting at 4 loses 0.051 +/- 0.031 against declining, and pays from about 7. With sooli tricks played by the heuristics (the live lite bots): accepting pays from 2 (+0.027 +/- 0.017 at 2, +0.050 +/- 0.033 at 4); about +0.0003 per deal for a side that accepts from 2, read from the play-outs | The existing option `sooli_need=2` is right for the live bots' sooli play; `lite.py` records it as tested |
| Do training and evaluation value a sooli as live play does? | No: the solver finishes sooli tricks with open cards, and a soolaaja survives far less often than against the heuristics | A mismatch between the training world and the deployed one; a design decision, not a quick fix |

Every evaluation above starts from 0-0 with dealer 0; other match scores have not been checked.

## The exploiter test: a lower bound on how exploitable a bot is

How far a bot is from optimal play cannot be computed. What can be measured is a lower bound:
freeze the bot (the target) on one team, greedy as it is deployed, and train a pair sharing one
network (the exploiter) for nothing but beating it. What the exploiter wins per deal bounds the
target's exploitability from below, for this kind of attacker and this training budget.

```sh
python -m tuppi_train.exploit --name ex1 --target <best_student.pt> --others vrpo4_final.pt --hours 3 \
    --offer-model <offer_model.pt> --critic-init <an earlier VRPO run> --warmup-min 5 --warmup-max 30
python -m tuppi_train.exploit_report --run training/runs/ex1 --base 32768
```

`exploit.Exploiter` is `vrpo_gpu.Learner` with another collection step: deals are exploiter
against target (in every second deal the exploiter is the other team), only the exploiter's
decisions are kept and their steps renumbered per deal. The update is unchanged; the return
calculation is exact for such one-team sequences (a test compares the learner's advantages on a
real exploiter rollout with a plain deal-by-deal calculation). Design choices:

- **The exploiter starts as a copy of the target**, so it scores exactly 0 at iteration 0, which
  is logged and kept as the first best: the reported bound cannot be negative.
- **Settings for a fixed opponent**: 65,536 deals per update, learning rate 1e-5, KL cap 0.01, no
  entropy bonus.
- **One game for monitoring and the final check**: every evaluation uses the exact sooli-offer
  heuristic (training uses the offer model for speed) and the run's sooli trick play, by default
  the observation-only heuristics the live bots use.
- **The report** (`exploit_report.py`) confirms the run's last network on fresh deals (the
  best-on-monitoring one is shown separately, since picking it flatters it) and says where a gain
  comes from: deals with and without a sooli, each side's RAMI declarations, points per deal and
  deals won (which do not depend on the equity table), the same match with the target sampling
  its moves (a gain that vanishes there came from the target being predictable), and the match
  over the match scores training uses.

What the number is not: the distance to optimal play; a statement about Nelli's safety net or
Heidi's search; or a guarantee that a longer or sharper attack would not find more. Run the
control first (`colab/tuppi_exploit.ipynb`, `STAGE = "control"`: the attacker against VRPO1): if
the method cannot exploit a weak bot, a null result on a strong one says nothing.

## The label-based attempt (stage 1: the verdict run)

Continuing VRPO from `vrpo4_final` did not improve on it (run1: 185 iterations, every evaluation
against the parent slightly negative). The other method in this repository,
`ai/tuppi_ai/selfplay.py`, learns from exact counterfactual labels: at a recorded decision every
legal action is played out to the end of the deal from the same full state. On the Mac it was
limited by CPU time for the play-outs; here they run in lockstep with the policy on the GPU.

| Piece | File |
|---|---|
| Engine functions: copy states, load every (state, action) into play-out slots with one seed per state, solver tail | `native/tuppi_train.c` (`tc_ls_copy_states`, `tc_ls_branch_begin`, `tc_ls_resolve`) |
| Recording during self-play and labelling | `tuppi_train/labels.py` |
| Teacher fitting, held-out gain, the composite and its chooser | `tuppi_train/improve.py` |
| Stage 1 as one resumable command | `tuppi_train/verdict.py`, `colab/tuppi_improve.ipynb` |

Two label kinds are produced from the same states and seeds: `q0`, the policy's own play to the
end, and `q6`, the same with the deal finished by the perfect-information solver once 6 tricks
remain (what Heidi's search does). They are different teachers: on VRPO4 their best action agrees
in about 80% of decisions.

```sh
python -m tuppi_train.check --labels --amp fp16      # the device reproduces the CPU's labels
python -m tuppi_train.verdict --out <dir> --hours 1.5 --offer-model <offer_model.pt>
```

Run the second command until it prints `VERDICT`. For each label kind it produces two sorts of
candidate:

- **composites**: a teacher Q network (of the policy's own shape, started from its weights, and a
  larger one from scratch) corrects the policy where it prefers another action by more than a
  margin; three cautious margin settings per teacher;
- **directly improved networks**: a copy of the policy trained by small steps to maximise the
  expected label of its own choice (`improve.fit_policy`), kept at six step counts. No teacher,
  no argmax over noisy estimates.

Every candidate plays the policy on the same 16,384 base deals; the best is confirmed on 32,768
fresh ones, in full and with changes only while more than 6 tricks remain. The identical pipeline
runs on `vrpo3_final` as a positive control. `GO` names the candidate and label kind to continue
with; `STOP` means the method lifts the control but not VRPO4; `INCONCLUSIVE` means it does not
lift the control either.

**Why candidates are chosen by play and not by held-out gain.** `selfplay.py` gates on the
held-out one-step gain, which worked when policies were weak. For a strong policy the gains
that matter are about 0.00001 per decision (+0.0005 per deal over about 41 decisions); a few
hundred thousand held-out states have a standard error several times that, so such a gate
rejects real improvements and noise alike. A CPU trial on VRPO1 with 142,000 decisions showed
exactly this: every held-out gain within noise, and teachers' composites at small margins
clearly worse in play (-0.005 per deal), because an argmax over noisy estimates changes many
decisions for the worse. Play resolves about +/-0.0002 per deal on 16,384 base deals. The
held-out figures are still printed for every candidate.

Choices that differ from `selfplay.py`, and why:

- **No label sharing.** One play-out for a run of rank-equivalent cards is documented as giving
  identical labels 95.7% of the time; with VRPO4 it is about 73%. `native.set_branch_share` stays
  off.
- **One seed per state.** All play-outs of a state share an explicitly set random stream, so
  labels are paired and do not depend on what the slots held before (tests check both).
- **Exploration** is at most one random move per deal (probability 0.01 per decision), and every
  state records whether one preceded it; gains are measured on the clean states.
- **Judged by play.** A composite is played directly in lockstep games against the policy; the
  held-out one-step gain is used only to choose margins.
- **Ties** in every greedy choice go to the lowest action id on float32 values, as in the C code.

The improvement loop (stage 2) is not written yet; it follows only if the verdict is `GO`.

## Judging a result

`best_actor.pt` was picked on the monitoring deals, so its monitoring score flatters it. Confirm
on deals it never saw, with a large sample:

```sh
python -m tuppi_train.evaluate --a .../best_actor.pt --b vrpo4_final.pt,vrpo3_final.pt,vrpo1_actor_0504.pt \
    --base 65536 --seed 12345
```

Accept only if it is significantly above `vrpo4_final` and not below the other two. The per-base
-deal standard deviation is about 0.013, so 65,536 base deals resolve about +/-0.0001 equity per
deal. For scale: `vrpo3_final` beats `vrpo1` by about +0.0035 here.

What this evaluation plays is the network greedily with the sooli heuristics, which is the plain
lite bot ("TuppiAI" in the room menu). It does not include Nelli's late-trick safety net or
Heidi's search. `ai/tuppi_ai/best.py` records that a better network as Heidi's anchor was
neutral at W=1024, so do not expect a gain here to carry over to Heidi.

A network that passes is a candidate for the release process (lite and compact exports, new
reference files, browser runtime), which is not part of this directory.

## Tests

`python -m pytest training/tests -q`, CPU only.

| File | Checks |
|---|---|
| `test_native.py` | The training library on 8 threads equals the serial loops and an unmodified build of the hosted sources, bit for bit. The lockstep engine fed a native rollout's actions reproduces its rows and rewards exactly. Lockstep duplicate evaluation equals `native.duplicate_eval`. A policy against itself scores exactly 0 in paired mode |
| `test_torch.py` | PyTorch and C forward agree. Sampling follows the softmax (chi-square), never draws an illegal action, returns the right log-probabilities. Sampled lockstep rollouts and native rollouts agree statistically |
| `test_learner.py` | Two updates here equal two updates of `ai/tuppi_ai/vrpo.py`: same losses, bit-identical actor and critic. Warm-up keeps the actor frozen. Half precision trains, stays finite and resumes; recomputed log-probabilities equal the sampler's in float32 |
| `test_checkpoint.py` | 2 iterations + resume + 1 equals 3 straight, bit for bit. Rows of lost iterations leave the log. A write cut off half-way, or a damaged newest state, falls back to the previous one |
| `test_offer.py` | Offer recording and a small model build; the recorder reports the engine's actual answers |
| `test_improve.py` | Lockstep labels equal `native.branch_values` exactly (own play and solver tail, sharing on and off, sooli always and never accepted) and do not depend on the slots. Teacher fitting, held-out gain and the composite equal `selfplay.py` on the same data. The composite chooser plays its definition, ties included |
| `test_verdict.py` | The verdict run at toy size: reaches a verdict, a rerun changes nothing, a lost step is redone, other settings are refused |
| `test_symmetry.py`, `test_bake.py` | The suit relabelling maps equal the engine's encoding of relabelled states; the averaged network is invariant and equals relabel-encode-forward-map-back; baking learns, resumes exactly and keeps its best |
| `test_exploit.py` | The exploiter's rollout keeps exactly its own decisions, in order; its advantages equal a brute-force calculation; iteration 0 is exactly 0 and kept; resume is exact; evaluations use exact offers and the run's sooli play; with a planted reward for declaring RAMI its declaration rate rises, and falls with the sign flipped |
| `test_hosted.py` | Every hosted file matches `SOURCE.json`; nothing was added to the image's directories |

Not covered by tests here: anything specific to CUDA (the container the suite was written in has
no GPU). The notebook's check cell runs one update on CUDA and on the CPU from the same rollouts
and prints the difference.

## Measured so far (4-core Xeon, no GPU, 2026-11-25)

| Stage | Result |
|---|---|
| Native rollouts, 768x4 network on the CPU | 8,200 rows/s on one thread, 30,400 on four (OpenMP) |
| Engine alone, encoding the decisions | 5.1 million rows/s on four threads |
| Engine alone, with the exact offer heuristic | 160,000 rows/s: the offers are 97% of the engine's time |
| Sooli time per deal, exact heuristic / offer model | 0.28 ms / 0.016 ms |
| Offer model (60,000 offers, VRPO1 self-play) | AUC 0.89; acceptance 2.25% against 2.38% exact (z = 0.8) |
| `vrpo4_final` against `vrpo3_final` (4,096 base deals) | +0.00123 +/- 0.00042 per deal |
| `vrpo4_final` against `vrpo1` | +0.00427 +/- 0.00046 |
| `vrpo3_final` against `vrpo1` (2,048 base deals) | +0.00348 +/- 0.00057 |

So with the network on a GPU and the offer model in place, the engine is no longer the limit;
how fast an iteration is on a given Colab GPU is what `tuppi_train.bench` reports there.
Nothing here has run on CUDA yet.

## Known limits

- `vrpo4_final.pt` was written by a newer VRPO script than the `vrpo.py` in this repository
  (it was saved as `actor_latest.pt`, a name this one never writes). Its exact hyperparameters,
  its critic and the original offer model are not here. If you have them, pass
  `--critic-init <critic_latest.pt>` (then `--warmup-max 0` is reasonable) and
  `--offer-model <offer_model_selfplay.pt>`.
- The paired evaluation is not the native one: both team assignments of a rotation share the
  seed of the sooli heuristics' draws. That is why a policy against itself scores exactly 0
  here and only approximately 0 with `native.duplicate_eval`. `--unpaired` reproduces the
  native seeds.
- The offer model accepts with its predicted probability (as the C code does), not by the
  threshold screen that `offer_screen.py`'s docstring describes.
- Self-play here is on-policy against itself only. There is no opponent pool yet; the
  milestone actors in `actors/` are kept for one.
