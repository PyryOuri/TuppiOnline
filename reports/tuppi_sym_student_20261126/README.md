# Suit-symmetry student: ready to compare with Nelli 1.1 and Heidi 1.2 (2026-11-26)

Owner's request: turn the Colab student network into something that can be compared against the
latest Heidi and Nelli.

## The network

| | |
|---|---|
| Source | `sym_preflight_v1-20261126T190511Z-1-001.zip` (owner download), `sym_preflight_v1/best_student.pt`; extracted here in `incoming/` (the two 76 MB training checkpoints were left in the zip) |
| Made by | TuppiOnline `claude/colab-pro-compute-eval-nu8in4` c9d4f88, `training/tuppi_train/bake.py`: VRPO4 taught to play like `sym24:vrpo4_final.pt` (logits averaged over suit relabellings), 200 iterations x 16,384 deals on an L4 |
| Shape | 768x4, encoder 2, 6,351,516 float32 parameters: VRPO4's shape, a drop-in replacement |
| Files | `TuppiAI-sym-student-20261126/models/vrpo4sym_v1.pt` (sha256 `5322bd22…`), `vrpo4sym_v1.lite.npz` (`88c2ea62…`) |
| Colab's own result | +0.00301 ± 0.00014 per deal over VRPO4, network alone, 32,768 base deals from 0-0 (`incoming/.../final_eval_live.jsonl`) |

The file's metadata names the teacher `sym24:vrpo4_final.pt`; the run's `config.json` says `sym:`.
The network file and the branch's README agree on sym24.

## Code

Worktree `TuppiAI-sym-student-20261126`, branch `research/sym-student-20261126`, local commit
`5755223` on the release AI source `ac94273` (hosted release GitHub main 8841583). Engine: the
release engine `TuppiProject-dan11-20261026` 54e7cf0. The native library built there is
byte-identical to the release worktree's (`848ebd8c…`). Not pushed.

- `tools/sym_student_compare.sh`: the comparisons (below), resumable, every step under the CPU ledger.
- `tools/stage3_eval.py`, `tools/ledger.py`: Stage 3's evaluator and ledger, copied unchanged
  from research/base-network-20261022 a9efdab (the harness that measured Heidi 1.2 and Nelli 1.1).
- `tools/sym_student_check.py`: the conversion check. `tools/sym_student_report.py`: the table.

## The arms (checks/arms.json, networks named by output fingerprint)

| Arm | Spec |
|---|---|
| Nelli 1.1 | `lite:vrpo4_final.lite.npz:c1h` |
| Nelli + student | `lite:vrpo4sym_v1.lite.npz:c1h` (same C1H options) |
| Heidi 1.2 | `best:w=1024:pib=8:rs=1:bp=vrpo4_final.pt:pibp=vrpo3_final.pt`: W1024, solver tail 6, keep 0.003 / bids 0.03, adaptive 128 / 2.5 / 0.005, VRPO1 rollouts, VRPO3 likelihood, VRPO4 anchor |
| Heidi + student | the same with `bp=vrpo4sym_v1.pt`: the student as anchor only, as Heidi 1.2 took VRPO4 |
| Plain | the network alone, greedy (`vrpo4sym_v1.pt` vs `vrpo4_final.pt`) |

`rs=1` reseeds every search from the information state, so both arms meet the same opponent
searches (an evaluation device, as in Stage 3). No people at these tables, so the human-seat
settings (T4, epsilon 0.8) never apply.

## Checks done

- **Exporter**: `tools/export_lite_model.py --check` reproduces the shipped `vrpo4_final.lite.npz` bit for bit.
- **Conversion** (`checks/conversion.json`, 64 deals of Nelli 1.1, 2,782 network decisions): the lite
  student equals a native network built from the PyTorch weights bitwise; against PyTorch the
  largest Q difference is 9.5e-6 and the greedy choice agrees on all 2,782. The student chooses
  differently from VRPO4 in 1,006 of them (36%).
- **Harness on the release code** (`checks/replay_*.json`): the first 32 base deals of Stage 3's
  Nelli 1.1 vs 1.0 measurement (256 games) and the first 4 of its Heidi 1.2 vs 1.1 W128 screen
  (32 games) are reproduced exactly. Heidi is 2.3x cheaper per deal than at Stage 3
  (55.5 vs 128.5 CPU-s per base deal at W128), from the exact speed-ups since.
- **Dry run** (`dryrun/`, 19:18-19:32 UTC, 0.23 CPU-h): every step at tiny size ends normally
  (exit 0, no failures; values from 2-16 deals are meaningless). Peak memory per worker 300-450 MiB.

## What a full comparison costs (release code on this Mac, measured)

| Step (`sh tools/sym_student_compare.sh <step>`) | Size | CPU per base deal | Estimate |
|---|---|---|---|
| `plain` (0-0 and uniform) | 4,096 base deals each | ~0.2 s | ~1.5 CPU-h together |
| `nelli_dup` | 8,192 base deals, uniform | ~0.5 s | ~1.2 CPU-h |
| `nelli_pairs` | 3,500 match pairs | | ~4-6 CPU-h (Stage 3: 6.6 on older, slower code) |
| `heidi128` (screen) | 1,024 base deals | ~51 s | ~15 CPU-h, ~1.3 h wall on 12 workers |
| `heidi1024` (as released) | 256 base deals | ~340 s | ~24 CPU-h, ~2.5 h wall on 10 workers |

`cheap` (plain + nelli) is about 8 CPU-h, under an hour of wall time. Precision for scale:
Stage 3's Nelli 4,096-deal duplicate resolved ±0.0012; its Heidi W128 screen of 512 deals only
±0.0032, so a Heidi anchor effect of the size seen for the plain network would need thousands of
W128 deals and is out of reach at W1024. The branch's own README notes that a better anchor was
neutral for Heidi at W1024 before.

Run from the worktree, e.g.
`OUT=/Users/pyryouri/Developer/audit_deliverables/tuppi_sym_student_20261126/run sh tools/sym_student_compare.sh cheap`
(add `heidi`, or `confirm` for W1024); results land in `run/RESULTS.md`.

## Results: plain network and Nelli (`run/`, 2026-11-26 19:34-21:15 UTC, 13.9 CPU-h)

Owner's choice "Nelli + plain". Student minus released network, match equity per base deal, 95%
intervals over base deals (`run/RESULTS.md`, `RESULTS.json`, `LEDGER.jsonl`; no failures).

| Measure | Size | Result | CPU h |
|---|---:|---|---:|
| Network alone, 0-0 | 4,096 base deals | +0.00319 [+0.00278, +0.00359] | 1.09 |
| Network alone, uniform scores | 4,096 | +0.00740 [+0.00626, +0.00855] | 1.13 |
| Nelli (lite C1H) on the student vs Nelli 1.1, uniform | 8,192 | +0.00637 [+0.00559, +0.00716] | 2.78 |
| The same, complete matches from 0-0 | 3,500 pairs (7,000 matches, 182,897 deals) | wins 62.4% [61.4, 63.4] | 8.88 |

- The 0-0 result reproduces Colab's own +0.00301 ± 0.00014 within the interval.
- Pairs: the student won both matches of a pair 1,159 times and lost both 290 times; 2,051 split.
- For scale: Nelli 1.1 over Nelli 1.0 (the VRPO4 network step) was +0.00301 at uniform scores and
  54.1% of 3,500 pairs (Stage 3). This step is about twice that per deal and wins 62% of matches.
- Declaration rates barely move (the evaluator's `cand_declared` / `opp_declared`: 42.8% vs 42.9% in the Nelli duplicate).
- The cost was 13.9 CPU-h, not the estimated ~8: the pairs took 8.9 CPU-h against 4-6 estimated.

Not run (owner's go needed): Heidi with the student as anchor, `heidi` (W128 screen, ~15 CPU-h)
and `confirm` (W1024, ~24 CPU-h for 256 base deals, low precision). Note that this measures the
student only as Heidi's anchor (as Heidi 1.2 used VRPO4); it is not a student-everywhere Heidi.

## Prepared, waiting for the owner's go: Nelli on the student vs Heidi 1.2 (2026-11-27)

The owner wants this run while away from home and will give the go. It measures directly what has
only been chained so far (Heidi 1.2 about +0.007 over Nelli 1.1, never measured): Nelli (C1H) on
the student against Heidi 1.2 as released (W1024 PIB8, VRPO4 anchor, VRPO3 likelihood, VRPO1
rollouts, `rs=1`), uniform scores. The report also gives the implied Nelli 1.1 vs Heidi 1.2 gap
(this result minus the +0.00637 above, independent samples).

- Step `nelli_heidi` in `tools/sym_student_compare.sh`: chunks of 128 base deals, each with its
  own seed (`sym-nelli-heidi-v1-cNN`), up to 16 chunks (2,048 base deals). No new chunk starts once
  the 9 h wall cap would be passed (judged by the last chunk's duration) or when `run/STOP`
  exists; stopping loses at most the chunk in progress. Rerunning the command resumes.
- Dry run (`dryrun_nelli_heidi/`, 04:35-04:46 UTC, 2 chunks x 2 base deals, 4 workers): ends
  normally, chunks pooled, 165 CPU-s per base deal, peak 510 MiB per worker. Values meaningless.
- Full size: about 94 CPU-h, about 8.5 h wall on 12 workers (about 32 min per chunk). Precision
  depends on the spread, unknown until it runs: ±0.0013 per deal if the per-base-deal SD is 0.03.

Start it with:
`cd /Users/pyryouri/Developer/TuppiAI-sym-student-20261126 && OUT=/Users/pyryouri/Developer/audit_deliverables/tuppi_sym_student_20261126/run sh tools/sym_student_compare.sh nelli_heidi`
