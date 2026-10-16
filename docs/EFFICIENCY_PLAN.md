# Efficiency plan: faster search at the same strength

Current status on 2026-10-13: the product includes E0–E5 and adaptive bidding
E7. The original task descriptions and measurements below remain historical.
Use [the product map](../../PRODUCT.md) for current configuration and the
[maintenance programme](../../audit_deliverables/tuppi_maturity_plan_20261013/PLAN.md)
for fresh profiling and portable-runtime work.

Written 2026-09-29 from a read of the native core and search
(`native/*.c`, `tuppi_ai/search.py`, `best.py`, `evaluate.py`) and a
profile of the best agent playing v3 (the real game). Task list:
`docs/TASKS.md`, T7.

**Status 2026-09-29: E0-E5 done** on branch `perf/e0-e5` (worktree
`~/Developer/TuppiAI-perf`, subsequently installed). All five changes are exact: the
same moves and the same searched values. Measured gains:

- search 2.16x (W=128) and 2.17x (W=1024) in wall time;
- the 12-worker evaluator 2.32x.

Details are in `docs/STATUS.md`. E6-E9: E7 was adopted for bids (live); E6 was not adopted; E9 was closed with no change; E8 was not started.

## Where the time goes (measured 2026-09-29)

Setup: the best agent on all four seats, `project_target_v3`, driven through
the authoritative engine (as `tools/gen_game_db.py` does), sooli settings
reset each deal, default rollout chunk 32. The profile was taken with macOS
`sample` (40 s, one process). Scratch probes only; no repo code changed.

**By decision kind** (6 deals at W=1024, the live setting, which
`TuppiProject-current/src/tuppi_server/match_runner.py` sets to 1024):

| Decision | n | Share of decision time | Mean |
| --- | ---: | ---: | ---: |
| bids (showing) | 15 | 47.9% | 1,684 ms |
| RAMI card play, tricks 1-7 | 140 | 39.8% | 150 ms |
| sooli offer / give / play | 53 | 10.4% | 66-501 ms |
| late card play (solver only) | 120 | 1.9% | 8 ms |

At W=128 (8 deals) the split is the same: bids 51%, early RAMI play 30%.
The Python engine and bridge take 0.04 s of 10.2 s (0.4%), so they are not a
target.

**By native function** (busy samples at W=1024, idle worker threads
excluded):

| Component | Share of busy CPU | Called from |
| --- | ---: | --- |
| sooli solver (`lead_node`, `second`, `third`) | 39% | ~98% from the **offer heuristic inside bid rollouts** (`offer` -> `survives_in` -> `tc_sooli_solve`); `tc_sooli_finish` about 1% |
| endgame solver (`search` in `tuppi_dd.c`) | 27% | the 6-trick solver tail |
| rollout network (`tc_mlp_forward` + BLAS) | 26% | of which BLAS is only ~5 points; the rest is the sparse first layer, layer norms and bias loops |
| world sampler (`count_or_draw`, `exp`, `log`) | 5% | `search_core` and the offer heuristic |
| encoder, legal moves, other | ~3% | |

**Two more measurements:**

- **Network.** 84 of 1,951 features are active on an average row, yet the
  forward costs 5.5-6.4 µs per row with real features against 2.8-3.5 µs with
  all-zero input. The first layer is therefore about half the network's cost.
- **Sampler.** Drawing the worlds is serial: 20.7 ms per card-play decision at
  W=1024 (2.2 ms at W=128). That is about 14% of the 150 ms latency of an
  early card-play decision.

**Rank-equivalent cards** (24 deals, 916 searched card-play decisions,
equivalence = adjacent among cards not yet played, counting the cards in the
current trick as live):

- 22% of the legal actions searched are equivalent to another legal action.
- In 9% of searched decisions (81 of 916), every legal card is equivalent.

Caveat: one short profile on a shared laptop. The shares are good enough to
rank the tasks, not to promise gains. E0 re-measures properly.

## Two classes of task

- **Exact:** same moves, bit for bit. Checked the way the 2026-09-24
  speed-ups were: a fixed-deal move fingerprint before and after, plus a
  component oracle. These need no strength test.
- **Approximate:** they change which worlds or actions are searched, so some
  moves change. Each needs a paired strength test against the current agent
  with a non-inferiority margin fixed in advance, and its CPU saving reported.
  Run them only after the exact tasks, against the faster exact baseline, and
  with the owner's approval of the compute.

## Tasks

### E0 - Baseline, fingerprint and profiling harness (do first)

**Done:** `tools/profile_search.py`, `tools/native_oracle.py`.

A tool (e.g. `tools/profile_search.py`) that plays a fixed set of v3 deals with
the best agent on four seats. Use the 12 deals of the 2026-09-24 check plus a
W=1024 set. It records:

- every decision's action, and a hash of `last_values`;
- CPU and wall time per decision kind;
- optionally, a `sample` profile.

It resets the search environment's sooli options per deal, as
`gen_game_db.reseed` does: the ruleset-3 settings leak is left unfixed by the
owner's decision, so without the reset the fingerprint would depend on deal
order.

Freeze the fingerprint and the source hashes before any edit. Measure timings
paired, alternating order, at least 5 repetitions (the TuppiProject INF
method).

### E1 - Faster sooli solver (exact; the largest single target)

**Done:** offer heuristic 3.9x faster (two-pass budgeted solves; context struct; cheaper representatives and key).

**Why.** The offer heuristic (`tuppi_sooli_policy.c: offer`) answers every
defender's offer in every RAMI rollout of a bid search. It runs up to
`OFFER_WORLDS` = 8 full 13-trick solves per offer, and this is 39% of all busy
CPU at W=1024.

**What.** Start by counting nodes per solve on the offer bank
(`tools/sooli_bank.py`). Then:

- Remove thread-local accesses from the recursion by passing a context
  (`stt`, `nodes`); `_tlv_get_addr` shows up in the profile.
- Update the TT key incrementally instead of re-walking every live card in
  `key_of` at each lead node.
- Order the RAMI leads so that likely kills come first.
- Add stronger static win and loss tests at trick boundaries.
- Consider a table probe before the certain-survival scan.

**Gate.**

- `tc_sooli_solve` gives the same result on the bank and on a large random
  bank of sooli positions.
- The E0 fingerprint is identical.

### E2 - Build the sampler's DP once per observation (exact)

**Done:** per-thread table cache. It was built on the current sampler; the B0-S1 fix is still unmerged.

**Why.**

- `count_or_draw` rebuilds the 4 x 14 x 14 suit-split DP, with its `exp` and
  `log` calls, for every world.
- The DP depends only on the observation. Drawing W worlds for one decision,
  or 8 worlds inside one offer, rebuilds the same table W or 8 times.

**What.**

- Split `count_or_draw` into "build table" and "draw from table", and make the
  draws consume the rng exactly as now, so the worlds are the same bit for bit.
- Cover the uniform path, the locked-bid NOLO card draws, and the tilted and
  rejection sooli modes.

**Expected gain.** About 5% of CPU and most of the serial ~20 ms per decision
at W=1024.

**Coordinate first.** `../tuppi_execution_sampler_v1` found a correctness
defect in this sampler: shown cards imply fallback restrictions that it does
not enforce. It fixed the defect in a private copy
(`native_capture/tuppi_search.c`, "B0-S1"), which is not in this repository.
Decide with the owner whether B0-S1 is merged first. Build E2 on whichever
sampler is current, or it will have to be redone.

**Optional, not exact.** Drawing the worlds in parallel would cut latency
further, but it changes the rng streams, so it needs its own strength check.

**Gate.** Worlds are identical to the current sampler for the same rng state,
over many observations of every phase; the E0 fingerprint is identical.

### E3 - Faster endgame solver (exact)

**Done:** 1.68x per 6-trick solve. MTD(f) not done: one full-window search was slower.

**Why.** It is 27% of busy CPU (`tuppi_dd.c`).

**What.**

- Evaluate the last trick directly, and possibly the last two.
- Pass `tt`, `gen` and `nolo` in a context instead of `__thread` globals.
- Make `canon()` cheaper by walking the live bits of each suit once, instead
  of 13 x 4 probes.
- Replace the blind binary search of null-window probes with MTD(f) or an
  aspiration window from a first guess, such as a quick-trick count.

**Gate.**

- `tc_dd_team0_tricks` is identical on a large random bank of 1-7-trick
  positions, both polarities.
- It is independent of solve order.
- The E0 fingerprint is identical.

### E4 - Rollout network first layer (exact)

**Done:** 1.35-1.45x per row, logits bitwise identical.

**Why.** The sparse first layer is about half of the forward pass (26% of
CPU). `tc_mlp_forward` scans all 1,951 bytes of each row to find about 84
active features.

**What.**

- Have the encoder emit the active feature indices in increasing order, which
  is the order the sum uses now, so the logits stay bitwise identical.
- Skip the dense encode and scan in the rollout path.
- Fuse the bias and ReLU passes.

**Separate, not exact.** Incremental per-seat accumulators or fp16 weights
change the float rounding. They would need the argmax-agreement check (20,480
decisions, as in 2026-09-24) and then a strength check.

**Gate.** Logits are bitwise identical to the current native forward; the E0
fingerprint is identical.

### E5 - Batch-job settings (exact, small)

**Done:** chunk 128 in the evaluators and batch tools. Evaluator -4% wall and -5% CPU on its own.

**Problem.**

- `tools/gen_game_db.py` calls `native.set_rollout_chunk(128)`, which does
  about 7% less total work with the same moves.
- `evaluate.py` and `match_eval.py` do not, although they run 12 worker
  processes that each spread every search over all cores.

**What.** Set chunk 128 in their worker initialiser. Also measure whether
fewer processes with more cores each is faster than 12 oversubscribed ones.

**Gate.** Same per-deal results on a fixed evaluation.

### E6 - Search one card per rank-equivalent group (approximate)

**Tested, not adopted (2026-09-29):** -0.00057 [-0.00135, +0.00021] at W=128 for 9% less CPU.

**Why.** Two legal cards of one suit with no unplayed card between them take
the same tricks under every continuation. They differ only in what they show
the other players, and the clone rollouts read the exact card, so today the
search picks between them by its sampling noise.

**What.**

- Search one representative per group. Choose the card inside a group by a
  fixed rule, for example the blueprint's preference.
- Skip the search entirely when all legal cards are equivalent.

**Expected gain.** 22% of card-play rollouts removed (about 9% of total CPU)
and 9% of card-play searches skipped.

**Also check.** The after-deal review (`tuppi_ai/review.py`) must not report
a choice between equivalent cards as a mistake.

**Gate.** Paired non-inferiority against the current agent, on 512 or more
fresh v3 base deals.

### E7 - Adaptive world allocation for bids and early play (approximate; the largest lever)

**Adopted for bids above 128 worlds, live (2026-09-29):** -0.00032 [-0.00098, +0.00034] at W=1024, 1.48x less CPU per deal. Card play stays fixed.

**Why.**

- A bid at W=1024 costs about 1.7 s, and bids take about half of all CPU.
- C2 stage 2 found that a fresh W=128 resample changes the bid in 57% of
  positions. Most candidates are near-ties, and spending equal worlds on
  every one of them is waste.
- `tc_search_world_values` already returns per-world values for paired
  standard errors.

**What.**

- Draw worlds in batches (e.g. 128) up to a cap (1024).
- After each batch, drop actions whose paired upper bound falls below the
  leader by a preset margin.
- Stop when one action is left or the cap is reached.
- Keep it deterministic per seed.

**Variant for bids.** Screen every bid card on a small batch, then give the
full budget to the best few per contract. The earlier two-stage showing test
(`show=2`, one blueprint card per contract, W=16, v1) was inconclusive at
-0.0010 +- 0.0030; this is a different design at a different scale.

**Keep the review out of it.** The after-deal review keeps its fixed-W search:
its thresholds are calibrated on it.

**Gate.**

- Paired non-inferiority against fixed W=1024 on 512 or more fresh v3 base
  deals, with the margin set in advance.
- Report the CPU and latency saved.

### E8 - Cheaper offer model inside rollouts (approximate; after E1)

**Not started.** After E1 and E7 the offers cost much less; see the value-net plan's end-of-bidding leaf, which removes them from bid rollouts.

**Why.** The bot's real offers are decided by search with a 0.02 margin. The
8-world solver heuristic in the rollouts is only a model of that decision, so
a cheaper model could also be a more accurate one.

**What.**

- Measure the heuristic's agreement with the bot's real offer decisions on a
  bank of offers.
- Try cheaper predictors: a tighter prefilter or exposure threshold, fewer
  worlds, or a small table or classifier.
- Drop the task if E1 already makes the offers cheap.

**Gate.** Agreement on the bank, then a paired strength test.

### E9 - Solver-tail depth by cost (approximate, low priority)

**Closed, no change (2026-09-29):** depth 5 saves 4% CPU and depth 4 costs 1% more.

**Why.** Depth 4 was about as strong as 6 (v1, W=64), and depth 8 was worse.

**What.**

- Measure CPU per rollout at depths 4, 5 and 6 in v3. The solver's cost grows
  about 4-5x per extra trick, while every trick left to the network costs 4
  forward passes.
- Switch only if a depth is clearly cheaper and passes a paired strength
  test.

## Checked and not worth a task

| What | Why not |
| --- | --- |
| Python engine and bridge | 0.4% of decision time. |
| GPU for play | Already rejected: one play-out step costs about one GPU round trip (STATUS, 2026-09-24). |
| C1 control variates, C5, C2 conditioning, C3b utility stopping | Measured and set aside in the C0-C5 package (`audit_deliverables/tuppi_implementation_output/IMPLEMENTATION_REPORT.md`). |
| A larger sooli transposition table | Tried: no gain (STATUS, 2026-09-24). |

## Constraints for whoever implements this

- **Build to a separate path until the gates pass.**
  - The live server loads `native/libtuppi.dylib` on its next restart.
  - The C0-C5 research layer pins that file's SHA-256 and this checkout's
    HEAD (`tuppi_ai/research/identity.py`).
  - Replacing the installed library or re-pinning those hashes is the owner's
    call.
- **Every exact task passes the E0 fingerprint** as well as its own oracle.
  An empty comparison must fail: assert the count before an `all()`.
- **Approximate tasks need the owner's approval** of the compute. A 512-deal
  paired test at W=1024 is several hours on this machine.
