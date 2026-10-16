# Broad differential test of the compact128 speed baseline

Run on 2026-10-14. Question: could the qualified speed changes affect playing
strength? Answer: at W1024 on this Mac, they reproduced the reference's
decisions bit for bit on every decision tested. One narrow numerical mechanism
could in principle flip a rollout move. It was located and measured, and it
did not fire on any decision tested.

Nothing in the sealed packages, the product, the installed library, the
server or the app was changed. Next steps for an implementing agent are in
[HANDOFF.md](HANDOFF.md).

## 1. Static review of the patches

The patches are the diffs of `builds/reward_compact/{tuppi_dd.c,tuppi_env.c}`
against the frozen sources.

- **Reward buckets: exact by construction.**
  - `finish()` reads only the contract, declarer parity and trick split.
  - `tc_next_score` and `equity0` read only score and dealer, which every
    world of a root search shares.
  - The bucket value uses the same float cast and double addition as
    `record_if_done`.
  - The binary search finds the largest payoff cut that is no more than the
    DD result. Payoff is constant between cuts, so this is exact for any
    payoff table.
  - The DD transposition table verifies the full canonical key, so earlier
    contents cannot bias a probe.
- **Shared model: no behaviour change.** The factories match except for the
  intended `team_net=None` and `shared_mlp`. Both teams' rollout models are
  the same VRPO1 weights.
- **Compaction and chunk 128: these change only matrix batch composition.**
  Forced rows skip the argmax, which had one candidate anyway. Exactness
  therefore depends on whether a row's network output is independent of the
  rest of its batch. Section 2 tests that.

## 2. Network batch invariance

Inputs were 2,827 decision states from 120 random ruleset-3 deals, covering
all 25 score cells, showing, both contracts and accepted-sooli phases. Both
the reference and compact128 libraries were tested, with Accelerate limited
to one thread and with its default thread count.

| Batch size | Rows checked | Rows not bit-identical to the full-batch output |
|---|---:|---:|
| 2–259, 300, 383, 512, 777, 1024, 2048; random subsets and contiguous | 232,278 per run | **0** |
| 1 (single row) | 6 per run | **6**, max abs difference 6.1e-5 |

A **one-row call takes a different Accelerate kernel**. Both variants make
such calls, at different rows:

- The reference through its team split and chunk remainders.
- Compact128 when all but one row of a chunk is forced.

A rollout move can therefore differ only when that row's top two legal
Q-values lie within about 6e-5.

On 9,944 network-scored rows ([mlp_argmax_flips.json](results/mlp_argmax_flips.json)):

- The single-row and batched argmax never differed.
- The median top-two gap was 7.2 and the 0.1% quantile 0.016.
- The largest single-row difference was 3.6e-5.

These rows came from random play rather than rollouts. They indicate
magnitude; they are not an estimate of rollout frequency.

Strength impact: any such flip chooses between two moves the network rates
equal to within 1e-4 on a points scale. Its direction is arbitrary, not
systematic. This can be removed entirely by padding one-row calls (HANDOFF
item 1).

## 3. Broad end-to-end differential at W1024

- **Inputs.** 100 fresh seeds (`speed-differential-0` … `-99`), two deals
  each with controllers retained. The deals are disjoint from the
  qualification bank.
- **How it ran.** Through the qualified `worker.py`, serial, single-thread
  BLAS, 12 concurrent processes.
- **What was compared.** Each decision's action, searched values (float hex),
  RNG state, world counts, legal set, input hash and sooli settings.

| | Result |
|---|---|
| Seeds / deals | 100 / 200, all complete |
| Decisions compared | 10,904 |
| Seeds with any difference | **0** |
| Phases | 9,464 trick play, 539 showing, 331 sooli offers, 18 give, 18 return, 534 sooli play |
| Contracts (decisions) | 8,805 RAMI, 1,560 NOLO |
| Score cells | All 25, 4–12 deals each |
| Root decisions with exact value ties | 30.0% (resolved identically, since values are bit-identical) |

Total child CPU fell 32.6%: 7,530 s for the reference against 5,077 s for
compact128. This ran under 12-way contention and is not a timing
qualification. It is consistent with the sealed 34.6%.

## Conclusion and limits

On this host and at the analysis configuration, compact128 makes the same
decisions as the reference. Strength comparisons between them would measure
nothing but noise. The one non-exact mechanism is single-row BLAS rounding,
bounded at about 6e-5 in Q. It needs a near-perfect rollout tie and was not
seen in about 11,000 decisions.

Not covered:

- Native-parallel mode at this scale. The sealed qualification covered
  serial and parallel parity.
- Other BLAS implementations or devices: iPhone, Linux, WebAssembly.
  Batch invariance must be re-measured on each.
- W other than 1024.
- Hard-anchor and suit-ensemble arms, which change decisions by design.

## Files

| File | Purpose |
|---|---|
| [mlp_batch_invariance.py](mlp_batch_invariance.py), [mlp_batch_profile.py](mlp_batch_profile.py) | Network batch-invariance tests. The `mlp_invariance_*.json` files report `pass: false` because they use single-row output as the reference; that is the M=1 effect itself. Read the `mlp_profile_*.json` files for the per-batch-size result. |
| [mlp_argmax_flips.py](mlp_argmax_flips.py) | Whether single-row rounding changes the masked argmax |
| [run_games.py](run_games.py), [compare_games.py](compare_games.py) | Differential games and their comparison |
| `results/` | All outputs; [games_comparison.json](results/games_comparison.json) is the main result |
| `runs/games/` | Per-job inputs, logs and full decision records |
