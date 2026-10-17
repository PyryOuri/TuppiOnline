# Task XI-PIB: teach the lite bot what the search with play inference knows

You are working on a Linux compute machine (Fedora, i7-6700K with 4 cores and
8 threads, GTX 1070, 32 GB of memory). The owner's Mac does the code and the
other analyses. This machine runs this one job. Work only in this checkout
and in the `results/xi-pib` branch.

## Background

- **The lite bot**, which plays online, is the VRPO3 network
  (`models/vrpo3_final.pt`) choosing greedily, without search.
- **The search bot with play inference** is about 0.01 equity per deal
  stronger: `best:pib=4:pibt=2:pibe=0.5`. Play inference weights sampled
  worlds by how likely VRPO3 finds the other seats' past moves
  (`docs/PLAY_INFERENCE.md`).
- **The question:** if the search's choices are distilled into the VRPO3
  network (one round of expert iteration), does the network get stronger
  without search? If so, the online bot improves at no runtime cost.
- **Earlier evidence:** in September a round of expert iteration over a
  weaker policy and teacher gained in round 1 but did not compound in round 2
  (`docs/STATUS.md`, 2026-09-23). A null result is possible and still useful.

## Steps

1. **Setup, once.** From the repository root on branch
   `ai/research/play-inference-20261016`:
   ```
   sh tools/desktop_setup.sh
   ```
   - It installs the build tools, adds the v3 rules engine as the worktree
     `../tuppi-engine`, creates `.venv` (PyTorch with CUDA 12.6) and builds
     `native/libtuppi.so` with OpenBLAS.
   - It ends by running the play-inference tests, which must pass.
   - If the GPU is unusable (no kernels for sm_61 in that PyTorch), continue on
     the CPU. Only training is slower; nothing else changes.
   - Fix build issues in the setup script only. Do not change the search, the
     models or the engine.
2. **Run the job:**
   ```
   HOURS=20 WORKERS=7 nohup sh tools/xi_pib_job.sh > runs/xi_pib.out 2>&1 &
   ```
   The stages are:
   - **Generation:** the teacher plays itself and every unforced showing and
     card decision is saved (`tools/gen_xi_pib.py`). It stops starting new
     work after `HOURS`. Check progress with `tail runs/xi_pib/data/progress.jsonl`.
   - **Distillation:** VRPO3 is fine-tuned toward the teacher's actions
     (`tuppi_ai/distill.py`: 3 epochs, learning rate 1e-4).
   - **Evaluation:** the distilled network against VRPO3, both without search,
     4,096 duplicate base deals at 0-0 scores and again at uniform match scores.

   The job is resumable: if it stops, run the same command again and finished
   stages are skipped. Keep `WORKERS` at 7 or below, so the machine stays usable.
   Memory use is about 1 GB per worker.
3. **Analyse.** Report from `runs/xi_pib/SUMMARY.json`:
   - **Data:** rows generated, and how often the teacher's action differs from
     the lite bot's.
   - **Fit:** the final held-out agreement with the teacher and with the
     blueprint (`distill.log`).
   - **Strength:** for both evaluations, equity per deal with its 95% interval,
     deal wins and RAMI rate.
   - **Verdict:**
     - **Pass:** both point estimates are above 0 and at least one interval
       excludes 0.
     - **Promising:** the point estimates are above 0 but both intervals
       include 0.
     - **Fail:** otherwise.
   - Do not claim more than these numbers show.
4. **Publish the results.** Create the branch `results/xi-pib` from the current
   commit. Copy into `results/xi_pib/`: `SUMMARY.json`, `gen.log`,
   `distill.log`, the two `eval_*.log` files, `xi_pib.pt` (about 13 MB) and a
   short `REPORT.md` with the analysis. Commit, then push to `origin`. Do not push
   the data shards. They are large, and the owner's Mac can regenerate them.

## Rules

- Do not push to any other branch. Do not deploy anything.
- Do not change hosting or any other part of the product.
- There is no player data in this job: every game is bot against bot. Keep it
  that way.
- If something fails in a way the steps above do not cover, stop and write
  the error and what you tried into `results/xi_pib/REPORT.md` on the results
  branch.
