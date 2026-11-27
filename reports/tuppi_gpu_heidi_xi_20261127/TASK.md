# Task for the Colab session: Heidi 1.2 on the GPU, then a gated XI-CLEAN pilot (2026-11-27)

Written by the Mac session for the session that owns `claude/colab-pro-compute-eval-nu8in4`
(head 3a43b72 when written). The owner chose to hand this work to you rather than have a second
session commit to your branch. The owner runs the notebooks and spends the Colab compute, stage by
stage. Nothing here is authorised beyond the stage the owner starts.

## Why

- Heidi 1.2 costs about 165 CPU-s per base deal against Nelli on the owner's Mac (M3 Max, 14
  cores). So measuring Heidi and learning from it are both CPU-bound.
- XI-CLEAN means training the network on the search's choices. XI-CLEAN-2 (Mac and desktop,
  2026-10-27) projected only about 16,500 labels per Mac-day, and the owner stopped it.
- The owner wants to know whether a GPU Heidi makes XI-CLEAN worth trying, and wants to try it
  only if it might actually give a better bot.
- So the task has gates. Each stage can stop the line cheaply before the expensive one.

## What the Mac session found that you should know

**The suit-symmetry student (your `sym_preflight_v1` bake, `best_student.pt`)** is converted
and measured on the release code (`audit_deliverables/tuppi_sym_student_20261126/README.md`,
on the Mac). Student minus VRPO4, per base deal:

| Measure | Result |
|---|---|
| Plain network, 0-0, 4,096 base deals | +0.00319 [+0.00278, +0.00359] (matches your +0.00301) |
| Plain network, uniform scores, 4,096 | +0.00740 [+0.00626, +0.00855] |
| Nelli (lite C1H) on the student vs Nelli 1.1, uniform, 8,192 | +0.00637 [+0.00559, +0.00716] |
| The same, complete matches from 0-0, 3,500 pairs | 62.4% [61.4, 63.4] of matches won |

For scale: Nelli 1.1 over Nelli 1.0 (the VRPO4 step) was +0.0030 and 54.1%.

**Heidi over Nelli has never been measured directly.** The records chain it to about +0.007
(Heidi 1.2 over Nelli 1.1). The Mac has a direct run prepared (Stage 0 below).

**Your branch, read this morning:**
- `lookahead.py` already runs Heidi's `search_core` with GPU play-outs, exact against the engine.
- `focus.py`: 5.9 M single-play-out labels on VRPO1 gave nothing.
- Nothing has been timed on CUDA yet.

## How `lookahead.py` differs from Heidi 1.2 as released

Heidi 1.2 is the compact controller, mode 4: `ai/native/tuppi_browser.c` on
`ai/native/tuppi_env.c`, configured by `ai/tuppi_ai/compact.py` with `ai/models/compact/models.json`
(controller: reference_worlds 1024, dd_left 6, keep 0.003, keep_show 0.03, adaptive 128 / z 2.5 /
delta 0.005). Networks: VRPO4 anchor (role 2), VRPO3 likelihood (role 1), VRPO1 rollouts (role 0).

| | `lookahead.py` | Heidi 1.2 |
|---|---|---|
| Searched | Card play and bids (`show`). No sooli decision is searched | Card play and bids. Sooli offer (accept only if accept beats decline by > 0.02, `tuppi_browser.c:395-398`), give and sooli play (argmax, heuristic's move listed first, :399-408). Sooli return by heuristic |
| Candidates | Anchor plus the most probable moves, at most `top` 4, each with p ≥ `min_prob` 0.01 (`candidates`, lookahead.py:272-287). Even with top 0 / min-prob 0, actions whose float32 softmax is 0 are dropped | Every legal action (up to 26 at bids), in hand order (`tuppi_browser.c:223-238`) |
| Worlds | Fixed W | Card play and sooli: 1024. Bids: `adaptive()` (:328-369): batches of 128 to 1024, drop an action trailing the leader by > 2.5 SE, stop when nothing left can beat the leader by ≥ 0.005 |
| Rule | Replace the anchor if gain > keep and > z·SE (z 2, Kish effective worlds) (`decide`, :290-313) | `best = argmax`; keep the anchor if `values[anchor] >= values[best] - margin`, margin 0.03 at bids, 0.003 in card play (:409-421). No z, no effective-worlds term |
| Play inference | `--belief m`, card play with no sooli; the likelihood network is the rollout network (`build`, :388) under the AMP setting | Mult 8, VRPO3 in float32, T 2 / eps 0.5, all other seats, in PLAY **and SOOLI_OFFER** when there is no soolaaja. Human seats read at T 4 / eps 0.8 (irrelevant bot-vs-bot) |
| Play-outs | Rollout network greedy; solver tail only with `--dd`; offers by the exact heuristic or an offer model | VRPO1 float32; solver tail 6; exact offer heuristic; sooli trick play follows the seat's persistent sooli mode (solver, or heuristics after an offer search) |
| RNG | Fresh seeds per decision | One continuing stream per seat; consumed by world draws, resampling, play-out sooli and adaptive batches |

Bit-for-bit parity with native Heidi is not achievable (RNG consumption, GPU arithmetic), and
it is not needed. What is needed is a **measured behavioural equivalent**.

## Stage 0: the ceiling (Mac; prepared; runs on the owner's go)

- **Run:** Nelli (lite C1H) on the student against Heidi 1.2 as released (W1024).
  - Uniform scores, chunks of 128 base deals, up to 2,048, 9-hour cap.
  - Code: Mac worktree `TuppiAI-sym-student-20261126`, step `nelli_heidi`.
- **What it gives:** the real Heidi-over-Nelli gap, and the reference that Stage 1's GPU Heidi
  must reproduce.
- **G0 (advisory):** if Heidi 1.2 is not clearly above Nelli on the student (its lead's CI reaches
  +0.001 or below), Heidi 1.2 as such has little to teach.
  - Stage 2 can still look for a stronger search around the student, so G0 does not stop the line
    by itself.

## Stage 1: GPU Heidi, a behavioural stand-in

**Build** on `lookahead.py`, default-off, existing behaviour unchanged. Add a `--heidi` profile
(or equivalent settings) that plays Heidi 1.2's rules:

- all legal candidates, from the legal mask (not from p > 0);
- the rule: argmax, then the anchor kept within keep 0.003 in card play and 0.03 at bids (no z test);
- W1024 in card play; bids by Heidi's adaptive batches;
- `--dd 6`;
- a separate likelihood network:
  - `LookAhead(likelihood=...)` exists; add a CLI flag and a loader;
  - VRPO3 in float32 without autocast, mult 8, T 2 / eps 0.5;
- rollouts VRPO1 in float32 with TF32 off;
- the exact offer heuristic, no offer model.

Sooli searching (offer, give, play, play-inference at offers) may be left out of version 1 as a
documented omission. Your README puts the whole sooli ceiling at a few 0.0001 per deal (1.5% of
deals). Add it only if Stage 1's checks show a difference.

**Tests (CPU, in the style of `test_lookahead.py`):**
- on sooli-free PLAY states with injected seeds, the profile's worlds and per-world values equal
  `tc_search_worlds` / `tc_search_world_values`, with and without play inference;
- the adaptive bid rule equals its definition in `tuppi_browser.c:328-369`;
- the anchor-margin rule equals mode 4's on fixed value vectors, ties included. Heidi prefers the
  first action in hand order; say how you map that.

**Validation (all three must pass; report them in the README):**
1. **Agreement bank.**
   - Generate about 500 card and bid decisions with native Heidi 1.2 on the Colab CPU. The
     training build compiles the hosted sources, including `tuppi_browser.c`.
   - Compare:
     - GPU Heidi's choice with native Heidi's;
     - native Heidi's agreement with itself under a different seed. This is the noise floor:
       different worlds change near-tied decisions.
   - Pass: within 1 percentage point of the floor.
2. **Match.**
   - Preferred: GPU Heidi vs Nelli on the student, uniform scores, compared with Stage 0. The
     difference must lie inside the combined 95% interval.
   - C1H (`ai/tuppi_ai/lite.py`, options C1H) is CPU code. If wrapping it as a lockstep chooser is
     impractical, play GPU Heidi vs the plain student instead. Say so, and the Mac session will run
     the matching native reference (Heidi 1.2 vs plain student) on the owner's go.
3. **Throughput on an L4.** Report:
   - searched decisions per hour at the profile's settings;
   - base deals per hour of GPU Heidi vs plain;
   - where the time goes (likelihood scoring, play-outs, solver tail, Python).

**G1 (go to Stage 2):** checks 1 and 2 pass, and throughput is at least 10 times the Mac's. The
Mac does about 0.9 s per W1024 Heidi position on one core, with 12 workers, i.e. about 13
positions per second (`tuppi_xi_clean2_20261027/SPEED_REVIEW.md`). If G1 fails on speed, stop
after reporting the profile.

## Stage 2: the teacher, the strongest affordable search around the student

- **Arms:** anchor = the student. Vary:
  - rollouts VRPO1 or the student;
  - W 256 or 1024;
  - play inference on or off;
  - Heidi's rule or your z rule.
- **Play:** each arm against the plain student, paired duplicate, at uniform scores and at 0-0,
  with enough base deals for about ±0.001.
- **The teacher:** the arm with the best gain per GPU-hour.
- **G2:** the teacher beats the plain student by at least +0.004 at uniform scores, with its
  interval above zero.
  - Distillation recovers only a fraction of a teacher's lead: the student kept about +0.003 of
    the averaged network's lead and lost nothing to it (−0.00024).
  - Below +0.004 there is too little to learn. Stop.

## Stage 3: XI-CLEAN pilot (register the rules below before any data)

**Labels.** Write a recorder that mirrors `focus.Focused`:
- During student self-play (bake's score mix), at decisions with at least 2 candidates, record:
  - feat;
  - candidate ids (the student's move first);
  - per-candidate mean Q over the worlds;
  - effective worlds;
  - the teacher's choice.
- Use `improve.py`'s `ids` / `q` / `w` format, so `fit_policy` reads it directly.

**Fits, all judged by play, never by held-out gain:**
- (a) `improve.fit_policy` on the Q labels, at your usual step counts.
- (b) A bake variant:
  - KL to the student on every unforced decision (as `bake.py:150-195`, teacher = the student
    itself);
  - plus cross-entropy to the teacher's choice on searched rows, weight λ from a grid fixed in
    advance (e.g. 0.1, 0.3, 1);
  - needs a per-row mask and a candidate loss in the bake loop.

**Control, at equal GPU-hours:** focus labels at scale on the student. This answers whether
averaging over worlds beats more single play-outs.

**Judging:**
- each candidate vs the student, 16,384 base deals, at uniform scores and at 0-0
  (`lockstep.duplicate_eval`; your evaluate is 0-0 only);
- **GO:** at least +0.0010 at uniform scores with the interval above 0, and not below the student
  at 0-0. Then confirm on 32,768 fresh base deals;
- **Kill:** the best candidate is below +0.0003 after the label budget the owner sets (suggest 20
  GPU-hours of labelling).

**Report:**
- labels per GPU-hour;
- teacher–student agreement;
- gains split by phase (bids, card play by tricks left) and by contract.

## Stage 4: product check (Mac session, owner's go)

The winning network as lite C1H against Nelli on the student: 8,192 duplicate base deals and
3,500 match pairs, with the same harness as the student's measurement. Hand over the `.pt`, its
sha256 and the bake record.

## Odds (the Mac session's judgement, not measured)

About 15% that Stage 3 gives at least +0.001 for Nelli.

Against:
- XI-PIB failed (−0.0041, a W128 teacher);
- your `focus.py` trial found nothing;
- the Fable 5.2 audit (2026-11-10) recommended "not now";
- play inference shrank your look-ahead's gain (+0.0006 against +0.0014).

For:
- dense distillation from a stronger teacher just worked (the student);
- the GPU removes the label-count limit that stopped XI-CLEAN-2.

G0 to G2 cost a night of the Mac and a few Colab hours, and can end the line before Stage 3.

## Rules

- Every new behaviour is behind an option and off by default. Existing results stay reproducible.
- Results go to Drive and to the README's records, with sizes, seeds and intervals.
- The owner starts each stage and spends the Colab compute.
- No product or release changes, no deploys.
- The Mac runs (Stage 0, Stage 4, and any native reference) belong to the Mac session.
