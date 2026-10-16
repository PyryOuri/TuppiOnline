# Handoff: further exact speed work after the compact128 qualification

Written 2026-10-14 for an implementing agent. Read [REPORT.md](REPORT.md) in
this directory first. It records the differential test that motivates item 1
below. Then read the qualified baseline's
[README](../tuppi_speed_qualification_20261014/README.md) and
[REPORT](../tuppi_speed_qualification_20261014/REPORT.md).

This is a task list, not an authorisation. The owner has **not** asked for
profiling, strength runs, training, deployment or changes to the live
product. Implement and qualify exactness only. Anything marked
"approximate" needs the owner's approval and a paired strength test.

## Ground rules

- **Do not modify these sealed packages:**
  `tuppi_cheap_wins_preparation_20261014`,
  `tuppi_additional_exact_wins_20261014` and
  `tuppi_speed_qualification_20261014`. The qualification launcher rejects
  any added or changed `.py` file in its directory.
- **Work in a new versioned directory,** for example
  `audit_deliverables/tuppi_speed_exact_v2_<date>/`. Build private libraries
  there, following `tuppi_speed_qualification_20261014/build.py`: copy the
  sources, apply a patch, record clang commands and hashes in a `BUILD.json`.
- **Leave the installed product alone.** That covers
  `TuppiAI/native/libtuppi.dylib`, its pinned hash in
  `tuppi_ai/research/identity.py`, the running server and the app.
- **Start from the current comparator sources.** These are in
  `tuppi_speed_qualification_20261014/builds/reward_compact/`. Line numbers
  below refer to those files.
- **Python environment:** `/Users/pyryouri/.venvs/tuppi-v2/bin/python`, with
  `-B`. Run jobs single-threaded: `OMP_NUM_THREADS=1`,
  `VECLIB_MAXIMUM_THREADS=1`. The machine has 14 cores; one process per core
  is fine for parity jobs.
- **Exactness standard.** Every action, every searched value (float hex), RNG
  state and sooli-option trace must match the comparator. Reuse
  `tuppi_speed_qualification_20261014/worker.py` through a job file, as
  [run_games.py](run_games.py) does, and compare with
  [compare_games.py](compare_games.py).
- **One version per change set.** Do not change models, W1024, margins,
  equity, the solver tail (6) or controller lifecycle. Do not spend saved CPU
  on extra worlds.

## Background you need

- **Batch sizes.** On this Mac, `tc_mlp_forward` (`tuppi_mlp.c:146`) gives
  every row a bitwise-identical output for any batch size from 2 to 2048, at
  any position and with any neighbours. A **one-row call** takes a different
  Accelerate kernel and differs by up to 6.1e-5. The evidence is
  `results/mlp_profile_*.json`, produced by
  [mlp_batch_profile.py](mlp_batch_profile.py).
- **Rollout flips.** A rollout move can flip only when the top two legal
  Q-values lie within that difference. On 9,944 sampled decisions the
  smallest 0.1% of gaps was 0.016 and no flip occurred
  (`results/mlp_argmax_flips.json`).
- **Where one-row calls come from.** Both the reference and compact128
  produce them. The reference makes them through the team split at
  `tuppi_env.c:658` and chunk remainders. Compact128 makes them when 127 of
  128 rows in a chunk are forced (compaction at `tuppi_env.c:644`).
- **Reward buckets** (`tuppi_dd.c:193`, `reward_maps` at `tuppi_env.c:333`)
  are exact by construction. `finish()` reads only the contract, declarer
  parity and trick split. Score and dealer are shared by every world of a
  root search. The DD transposition table verifies full canonical keys.
- **Already done; do not redo:**
  - two-pass sooli offer;
  - sampler DP;
  - DD canonical TT and move pruning;
  - tiled first layer;
  - skipping the root search when only one move is legal (`search.py:379`).
- **Investigated; do not pursue:**
  - **Scratch-buffer reuse:** measured slower.
  - **Prefix-cached first layer:** the hand features (0–51) change every move,
    so shared prefixes are short.
  - **Explicit sharing of equivalent root cards in the DD region:** the TT
    already canonicalises them.
  - **Equivalent-card choice (E6):** it lost strength.
- **Profile caveat.** The last profile (2026-09-29) was taken before buckets
  and compaction: sooli 39%, DD 27%, network 26% of busy CPU. The owner
  declined a new profile for now. Treat the order below as a hypothesis, and
  record measured savings per item.

## Tasks, in order

### 1. One-row network calls (do first)

In `tc_mlp_forward` and `tc_mlp_forward_h0` (`tuppi_mlp.c:146`, `:188`),
handle `rows == 1` by running a two-row batch: the row duplicated, keep row 0.
Then every row's output becomes a pure per-row function on this host.

- **Why first:** it turns every later batching change into an exact
  refactor. That covers chunk size, compaction, deduplication and thread
  splits, including item 5.
- **Consequence:** this changes the rare one-row outputs that the current
  reference also produces. It therefore defines a **new reference**. Qualify
  it as "reference + padding" against compact128 + padding. Separately,
  report how many decisions differ from the unpadded comparator; expect none
  or almost none.
- **Exactness check:** run [mlp_batch_profile.py](mlp_batch_profile.py) on the
  new library. It must show zero mismatches for every batch size, including
  M=1.
- **Also check** the offer-model call at `tuppi_sooli_policy.c:208`, which
  passes `rows=1` but is used only when an offer model is set. It is off in
  search. Leave its behaviour unchanged unless you version it.

### 2. Sooli offer: graduated solve budgets

`offer()` is at `tuppi_sooli_policy.c:202`. It accepts when at least 4 of
`OFFER_WORLDS = 8` sampled worlds survive under perfect information. It
already draws all worlds first, then runs a 2,000-node pass
(`OFFER_QUICK_BUDGET`, `:185`) and then full solves. It stops once the count
is settled.

- **Change:** replace the two passes with a budget ladder, for example
  2,000 → 20,000 → 200,000 → unlimited. Re-test the early-stop condition after
  every world. Optionally choose which undecided world to solve next by the
  cheapest remaining expected cost.
- **Why exact:** each world's survival is a fixed fact. The decision depends
  only on the count. The solver and `offer_world` draw no RNG; verify this
  with a unit test that compares the RNG state after `offer()` in old and new
  builds.
- **Cost model:** refutations are cheap and survival proofs cost about 10⁵
  nodes. Accepting needs 4 proofs, so the gain is bounded. Measure first with
  a micro-benchmark: log node counts per world from bid searches.
- **Same idea elsewhere:** `tc_sooli_finish` (`tuppi_sooli.c:248`) and
  `pi_return` (`tuppi_env.c:361`) need a full survival value, so a ladder
  cannot help them.
- **Why it matters:** this is the likely bottleneck for bid latency. Bid p95
  improved only about 4% in the qualification.

### 3. DD reward buckets: bounds and probe order

`tc_dd_reward_bucket` (`tuppi_dd.c:193`) binary-searches the payoff cut
points with null-window probes.

- **Bounds:** compute cheap valid bounds `[lo, hi]` on team-0 additional
  tricks first, for example top-card sure winners for each side in RAMI and
  forced takers in NOLO. Drop cuts outside the range; if no cut remains
  inside, return the payoff directly. Any bound must be provably valid; a
  wrong bound breaks exactness silently. Add a randomized oracle test against
  `tc_dd_team0_tricks` on many positions of 1–7 remaining tricks, both
  contracts and mid-trick.
- **Probe order:** the result is the largest cut that a null-window probe
  confirms, so any probe order finds the same answer. Probing near a
  predicted value first may save work. A candidate prediction is the previous
  row's result for the same world. Measure; do not assume.
- **Where it pays:** expected gain is largest at early scores, where most
  trick counts change the payoff. The 0–0 control saved only 16.7%, against
  34.6% on the 24–0/40–0 bank.

### 4. Shared rows in locked-bid rollouts (optional, needs item 1)

Under ruleset 3 (`TC_LOCKED`), other seats cannot see bid cards; `tc_encode`
skips shows. In a bid search, rows `(world wi, root action a)` for the same
`wi` can then have identical features for other seats during the rest of the
showing phase.

- **Change:** deduplicate identical feature rows within a network batch and
  forward each unique row once.
- **Why it needs item 1:** without padding, deduplication could create a
  one-row batch where none existed, changing outputs.
- **Expected gain:** small, because showing is a few steps out of about 55
  per rollout. Measure the duplicate share before implementing.

### Approximate work (not authorised; listed so it is not mistaken for exact)

- **Rollout offer model (E8).** `tc_set_offer_model` already exists for
  self-play. It targets the largest cost but changes decisions.
- **Adaptive worlds for card play.** E7 already does this for bids.
- **Anything that skips or merges equivalent cards.** E6 lost strength
  because the choice between equivalent cards carries signalling value.

## Qualification sequence for each item

1. **Unit oracles.** For example:
   - MLP batch invariance (item 1);
   - offer decision and RNG identity on many sampled offer observations
     (item 2);
   - bucket result equal to the payoff of `tc_dd_team0_tricks` (item 3).
2. **Native roots and history bank.** Use the qualification modes
   `native_roots`, `history_bank` and `forced_sooli`. Run serial and
   native-parallel.
3. **Broad games.** Use [run_games.py](run_games.py) with fresh seeds, for
   example `--first 100 --seeds 100`, so they differ from this report. The
   comparison must show no divergences.
4. **Paired timing.** Compare each item against the immediately preceding
   build, rotating order across five rounds, as in the qualification's
   `PLAN.json`. Record CPU, p95 decision time and p95 bid time.
5. **Seal.** Write a new package with BUILD.json, results, a REPORT and
   VALIDATION. Only then may prepared strength plans switch comparator, and
   all arms must switch together.

Report failures as found. If an item does not preserve exact traces, record
it and drop it; do not relax the exactness standard.
