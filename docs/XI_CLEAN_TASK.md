# Task XI-CLEAN: teach the lite bot from a stronger, cleaner teacher

You are working on the Linux compute machine (Fedora, i7-6700K with 4 cores and
8 threads, GTX 1070, 32 GB of memory) that ran XI-PIB. The owner's Mac does the
code and the other analyses. This machine runs this one job. Work only in this
checkout and in the `results/xi-clean` branch.

## Background

- **The lite bot**, which plays online, is the VRPO3 network
  (`models/vrpo3_final.pt`) choosing greedily, without search.
- **XI-PIB failed** (branch `results/xi-pib`): the distilled network lost to
  VRPO3 (−0.00116 per deal at 0-0, −0.00413 at uniform scores). The fit itself
  went wrong. Held-out agreement with the teacher fell from 0.784 to 0.699,
  and card-play entropy rose from 0.31 to 0.79 nats.
- **The diagnosis:**
  - The W=128 teacher was only about +0.005 per deal stronger than VRPO3.
  - Most of its disagreements with VRPO3 were sampling noise.
  - Cross-entropy on unpredictable hard labels flattens a network instead of
    teaching it.
- **This job changes the teacher and the labels, not the network:**
  - **Teacher:** the search with play inference at **W=1024**
    (`best:w=1024:pib=4:pibt=2:pibe=0.5`), about +0.011 per deal over the lite
    bot, with about 2.8 times less noise per action than W=128.
  - **Positions:** reached by the lite bot itself.
  - **Labels:** kept only where the teacher's gain over the lite card is
    statistically clear. The gain is measured as a paired z over common
    worlds, with per-world values from the teacher's own search.
  - **Fit:** cross-entropy on the kept labels plus a KL anchor to VRPO3 on
    every row, selected on whole held-out shards.
- **The question:** can a clean teacher make the lite bot stronger without
  search? If so, the online bot improves at no runtime cost.

## Steps

1. **Update the checkout and rebuild.** The native library changed since
   XI-PIB, so the setup must run again:
   ```
   git fetch origin ai/research/xi-clean-20261019
   git checkout -B xi-clean FETCH_HEAD
   sh tools/desktop_setup.sh
   ```
   - It rebuilds `native/libtuppi.so` and ends with the play-inference tests,
     which must pass.
   - Keep the old `runs/xi_pib` directory; it is not used.
   - Fix build issues in the setup script only. Do not change the search, the
     models, the engine or the pre-registered constants in `tools/xi_clean.py`.
2. **Smoke check (a few minutes):**
   ```
   SMOKE=1 WORKERS=2 sh tools/xi_clean_job.sh
   ```
   - It must end with `finished; see runs/xi_clean_smoke/SUMMARY.json`.
   - Its gates usually fail. The smoke run then continues on purpose, to
     exercise every stage. It uses W=16/32 and a few deals, so it says nothing
     about strength.
3. **Run the job:**
   ```
   WORKERS=7 HOURS_B=24 HOURS_E=24 nohup sh tools/xi_clean_job.sh >> runs/xi_clean.out 2>&1 &
   ```
   - The job is resumable. If it stops for any reason, including a shutdown
     or a power cut, run the same command again. See "Pausing and restarting"
     below.
   - Memory is about 0.4 GB per worker. Keep `WORKERS` at 7 or below so the
     machine stays usable.
   - Progress: `tail runs/xi_clean/job.log`, and per stage
     `runs/xi_clean/progress_{A,B,E}.jsonl`.

## Pausing and restarting

The owner may pause the job or shut the machine down at any time.

- **Pause without shutting down:**
  - `pkill -STOP -f xi_clean` stops all job processes in place;
    `pkill -CONT -f xi_clean` resumes them. Nothing is lost.
  - Suspending the machine (sleep) also resumes where it was.
- **Stop or shut down:** `pkill -f xi_clean`, or simply shut down.
- **After a stop or a restart:** run the same command from step 3 again. The
  job does not start by itself after a reboot.
- **What is kept:**
  - every finished stage, every finished consistency chunk (16 deals) and
    every finished label shard (8 deals);
  - only the chunks and shards in progress rerun;
  - an interrupted fit or evaluation reruns from its start (minutes to about
    an hour; same seeds).
- **The label budgets `HOURS_B` and `HOURS_E` are cumulative across
  restarts.** They count the worker time of finished shards, so time switched
  off or asleep is not charged.
- Keep `WORKERS` the same when restarting. The budget divides worker time by
  it.

## The chained stages

The job runs these in order. **Each stage starts only if the previous gate
passes.** A failed gate ends the job with a summary. That is a valid, useful
result, not an error. All thresholds are fixed in `tools/xi_clean.py` and must
not be changed after results are seen.

| Stage | What it does | Gate (pass condition) | Expected time |
|---|---|---|---|
| **A** Consistency | One card decision from each of 2,048 lite-bot deals, priced at W=128 and W=1024 with two independent seeds each. It measures how often the teacher deviates from the lite card and whether a second seed reproduces the deviation. Seed b's prices measure the gain from following seed a's deviation. It also chooses the label threshold z\* (the smallest of 2, 2.5 or 3 with precision ≥ 0.8) and the W=128 screen margin (recall ≥ 0.9). | Copying every kept label would gain **≥ +0.0015 equity per deal**, with the lower 95% bound above 0 | about 1 h |
| **B** Labels | Lite-bot deals, 8 per shard. Every unforced card decision is screened at W=128 and priced at W=1024 where the screen says it can matter. Held-out shards (index % 10 = 0) get a second, independent W=1024 price. | (none) | `HOURS_B`, 24 h by default |
| **C** Fit | Starts from VRPO3: cross-entropy on kept labels plus λ·KL(VRPO3‖student) on all rows. λ ∈ {0.3, 1, 3}, 20 rounds of 100 steps, learning rate 3e-5. Selected by predicted gain on held-out shards, using only candidates that keep ≥ 97% agreement with VRPO3 on bids and on non-labelled cards and add ≤ 0.05 nats of card entropy. | Held-out label agreement **≥ 0.20**, and predicted gain > 0 with the lower 95% bound above 0 | minutes (GPU) to an hour (CPU) |
| **D** Strength | Student vs VRPO3, both without search, 4,096 duplicate base deals at 0-0 and at uniform scores, seed `xi-clean-eval-v1` | **Pass:** both point estimates > 0 and at least one 95% interval excludes 0. Promising and Fail stop the job | about 30 min |
| **E** Scale and confirm | Only after D passes: `HOURS_E` more labels, refit on all labels with the same recipe, then a fresh evaluation with seed `xi-clean-eval-v2` | Same rule as D; a pass means **confirmed** | `HOURS_E` + 1 h |

After E the job stops. There is no further automatic step. Promotion to the
product is the owner's decision.

## Analyse

Report from `runs/xi_clean/SUMMARY.json` (`stopped_at` names the gate that
ended the job, or is null):

- **A:** for W=128 and W=1024, the deviation rate, self-agreement, deviation
  reproduction rate and CPU per position. Then the chosen z\*, its kept share,
  precision and ceiling per deal with its lower bound, and the screen margin.
- **B (and E):** shards, rows, qualifying decisions, screened decisions, labels
  and search errors.
- **C:** the gate, label counts, device, and the selected candidate's λ, round,
  held-out label agreement, guard values and predicted gain.
- **D (and E):** for both evaluations, equity per deal with its 95% interval,
  deal wins and RAMI rate, and the verdict.
- Do not claim more than these numbers show. A stop at A means the teacher's
  labels are not clean or valuable enough. A stop at C means the network did
  not learn them on held-out deals.

## Publish the results

Publish once the job has finished. If you are still running when an earlier
gate is decided, you may also publish then and post the gate line as an issue
comment.

1. Create or update the branch `results/xi-clean` from the current commit.
2. Copy into `results/xi_clean/`:
   - `SUMMARY.json`, `job.log`, `A.json`, the `a_*.npz` files (small) and the
     `progress_*.jsonl` files;
   - `fit_d.json` and `fit_e.json`, the `eval_*.json` files and the
     `verdict_*.json` files;
   - `student_d.pt` and `student_e.pt` (about 13 MB each), if they exist;
   - a short `REPORT.md` with the analysis.
3. Commit, then push to `origin`.

Do not push the `b_*.npz` label shards. They are large, and the owner can ask
for them separately.

## Rules

- Do not push to any other branch. Do not deploy anything.
- Do not change hosting or any other part of the product.
- There is no player data in this job: every game is bot against bot. Keep it
  that way.
- Do not change thresholds, seeds or the teacher to rescue a failed gate.
- If something fails in a way the steps above do not cover, stop and write
  the error and what you tried into `results/xi_clean/REPORT.md` on the
  results branch.
