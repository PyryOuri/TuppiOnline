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
   it trains on it (`critic_mc_mse`); when that stops improving (or after `warmup_max`
   iterations) the actor starts, at a third of its learning rate, rising over `actor_ramp`
   iterations.
2. **Training.** The update of `vrpo.py`, unchanged.
3. **Monitoring.** Every `eval_every` iterations: paired duplicate, greedy, on the same 2,048
   base deals each time, against `vrpo4_final` (the parent), `vrpo3_final` and `vrpo1`. The
   actor with the best result against the parent is kept as `best_actor.pt`.
4. **Stop rule.** Three consecutive evaluations significantly below the parent end the run.

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
