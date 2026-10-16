# Tuppi Lite: results of the first round

Run 2026-10-14 under the pre-registered [PLAN.md](PLAN.md). The thresholds,
seeds and deal counts below are as registered; none were changed after any
result.

## Answer

**L0** is the VRPO3 policy network playing greedily, with no search and with
native sooli heuristics. It costs **about 1/11,000 of the live bot's CPU**
and decides in well under a millisecond.

- Against the live bot at **W128** it is level: +0.0006 per deal over 1,024
  base deals.
- Against the heuristic it matches the live W128 bot.
- Against the actual live bot at **W1024** it scored **−0.0031 per deal**,
  with a 95% interval of [−0.0073, +0.0010] over 512 base deals.

By the pre-registered rule (point estimate > −0.003), the confirmation
**fails narrowly**, by 0.00014. The result is statistically indistinguishable
from the margin itself. The best summary is that L0 gives up roughly 0.003
equity per deal against the full W1024 bot: about 15% of the live bot's
measured edge over the old incumbent (≈ +0.0197).

## Cost (PLAN step 1)

Same 8 deals, all seats the arm, this Mac, one thread
([results/cost](results/cost)):

| Arm | CPU per bot-seat-deal | vs live1024 | p95 decision | p95 bid | Verdict |
|---|---:|---:|---:|---:|---|
| live1024 | 10.13 s | 1 | 0.31 s | 1.49 s | Reference |
| live128 | 1.61 s | 1/6.3 | 0.12 s | 0.41 s | **Fails** the 1/8 target |
| L2 (L0 + W128 DD endgame) | 0.030 s | 1/330 | 2.3 ms | <1 ms | Passes |
| **L0** | 0.0009 s | 1/11,000 | 0.1 ms | <1 ms | Passes |

Live times were measured with three benches running concurrently, so they
include some contention. Peak memory in these Python processes includes
PyTorch: 257 MB for L0, 579 MB for live1024. L0's decision path needs only
the native MLP and the sooli heuristics, so a hosted build can drop PyTorch.

## Strength (PLAN steps 2–5)

All evaluations use the duplicate format (4 rotations × 2 seatings per base
deal) in the authoritative v3 engine, with uniform scores. Values are
candidate minus opponent, in equity per deal, with 95% CIs.

| Step | Comparison | Base deals | Result | Gate | Verdict |
|---|---|---:|---|---|---|
| 2 Screen | L0 vs live128 | 512 | +0.0009 [−0.0029, +0.0047] | point > −0.002 | Pass, L0 selected |
| 3 Primary | L0 vs live128, pooled | 1,024 | +0.0006 [−0.0023, +0.0034] | lower > −0.004 and point > −0.002 | Pass |
| 5 Guard | (L0 − live128) vs `partner_aware_lead_v3`, paired | 2,048 | +0.0001 [−0.0022, +0.0025] | lower > −0.005 | Pass |
| 4 Confirm | L0 vs live1024 | 512 | **−0.0031 [−0.0073, +0.0010]** | point > −0.003 | **Fail (narrow)** |

The guard's absolute levels were L0 +0.0415 per deal and live128 +0.0413 per
deal against the heuristic.

The implied W1024-over-W128 premium is about 0.0037. The older measurement
was 0.0011, but both intervals are wide enough that this is not a contradiction.

**Behaviour.**

- RAMI declaration rates are close: L0 42.4%, live1024 43.2% of games.
- L0 enters sooli in about 0.5–0.6% of games, against the live bot's
  3.6–4.5%. **The owner considers L0's rate fine;** it is close to human
  play. It is recorded here as behaviour, not as a defect to fix.

**Compute used:** 24.9 CPU-hours and about 2.2 hours of wall time for
strength, plus a few minutes of cost benches. That is within the approved
2–4 hours. No training, product or server change was made.

## What this means for hosting

- **Where the remaining gap is.** All of it is the W1024 search's
  contribution; at W128 the search buys nothing over the policy. The live bot
  needs about 10 s CPU per seat-deal (about 30 s per deal for three bot seats)
  and multi-second bids. L0 needs about 1 ms.
- **What L0 would mean for the server.** One small vCPU could serve
  effectively any number of bot-filled rooms; CPU would stop being the cost
  driver.
- **What it costs.** About 0.003 per deal against the strongest bot, which
  humans are very unlikely to notice. The owner decides whether that is
  acceptable.

## Owner decision and productisation (2026-10-14, same day)

The owner accepted L0 as the hosted bot, "good enough here", and declined L2.
Productisation:

- **TuppiAI-hosted** (branch `maintenance/hosted-bot-20261014`, commit `d573b63`):
  - `tuppi_ai/lite.py`: a PyTorch-free `LiteAgent`; the sooli cursor is its
    only state.
  - `native.Mlp.from_flat` and `native.flat_weights` (a refactor; bytes
    unchanged).
  - `tools/export_lite_model.py` writes `models/vrpo3_final.lite.npz`
    (sha256 `477a32f2…f468`), added to `hosted-models.json`.
  - `tests/test_lite.py`: 3 tests pass. Existing Mlp-related tests (10) pass.
- **TuppiProject-browser-network** (branch
  `feature/browser-network-20261014`, commit `3df4588`):
  - `TUPPI_HOSTED_BOT_LEVEL=lite|full`, defaulting to `full` in code.
  - `HostedLiteAgent` runs in the server process with the checkpoint schema
    `tuppi.hosted.controller.lite.v1`.
  - The identity profile is `tuppi_ai_lite_v1`.
  - With `lite`, every active room may use bots (8 instead of 1).
  - 3 new hosted tests; `tests/server` 120 passed. Its 3 failures (deal review
    and post-match diagnostics) also fail on unmodified HEAD.
- **TuppiBrowser** (`main`, commit `d95bfe3`):
  - The Dockerfile sets `TUPPI_HOSTED_BOT_LEVEL=lite`.
  - `prepare_hosted.py` ships the lite model.
  - `qualify.py` records the level.
  - `check_hosted_image.mjs` adds an in-image lite bench and level labels.
  - The deploy README documents both levels.

**Parity:**

- **[results/parity.json](results/parity.json):** 2,000 deals and 112,433
  decisions, every phase including sooli. The hosted lite bot
  (TuppiAI-hosted, hosted engine branch, no PyTorch) is identical to the
  evaluated L0 (TuppiAI with PyTorch-loaded weights).
- **[results/linux_parity.json](results/linux_parity.json):** the Linux
  x86-64 OpenBLAS image matches macOS on the first 500 of those deals (28,036
  decisions).

**Linux image** `tuppi-online:lite`, sha256 `9354e1c4…1ab7`, built from
`deploy/TuppiNetwork-lite` in the isolated Lima VM with x86-64 translated by
Rosetta:

- The in-build W128/W1024 qualification passed, with identity
  `tuppi_ai_lite_v1`.
- [The full image check](results/linux_image_check.json) passed: static and
  origin checks; a complete 9-deal match of one human against three lite bots
  with mid-game restart, reload and uncertain-action reconnect;
  replacement-container volume restore; and the partner lobby.
- The lite bench, inside the container with `--cpus=1`: 29 ms CPU per bot
  seat and deal, p50 2.7 ms, p95 2.8 ms, maximum 51 ms per decision, 88 MB
  peak process memory, and PyTorch never imported. Translation makes this
  slower than native x86 would be.

**Still open:**

- A slimmer image without PyTorch. It is still needed for the W128/W1024
  build qualification and the `full` level.
- Native-host and provider capacity: real CPU and Internet TLS/WSS.
- Physical-device play against hosted lite bots.

The deploy context `deploy/TuppiNetwork-lite` was prepared from the
uncommitted working trees. Its `SOURCE.json` per-file hashes identify the
exact bytes, but its recorded commits are the parents. The owner approved
committing on 2026-10-15. Each tree was committed as built, with no edits,
directly on its recorded parent: browser `ef67d99` → `d95bfe3`, engine
`3cfd8be` → `3df4588`, ai `e8bb6b8` → `d573b63`. All 510 context files still
match their `SOURCE.json` hashes. `SOURCE.json` itself was left unchanged.

## Next steps that were not taken

The owner chose L0, so these were not run.

1. **Confirm L2 against live1024** (512 base deals, about 1.6 h, gate
   point > −0.003, pre-registered before running). L2 adds exact DD-endgame
   search on the last 6 tricks at 1/330 of live cost. It is the cheapest arm
   that could recover part of the gap.
2. **Uncertainty-gated search (L3).** Search only when the policy's top
   choices are close. This needs a threshold calibration first and is
   costlier to evaluate.

## Files

| File | Purpose |
|---|---|
| [PLAN.md](PLAN.md) | Pre-registration (targets, arms, gates) |
| [lite_agents.py](lite_agents.py) | L0/L2 agents and live factories, importing TuppiAI read-only |
| [lite_eval.py](lite_eval.py), [run_selected.sh](run_selected.sh) | Duplicate evaluation driver and the run sequence |
| [cost_bench.py](cost_bench.py) | Cost and latency bench |
| [parity.py](parity.py), [build_image.sh](build_image.sh) | Hosted-vs-evaluated parity and the Lima image build |
| [analyse.py](analyse.py) | Gate statistics, including the paired guard against `TuppiAI/runs/panel/P1b-A__heur__cand.json` |
| `results/` | Raw per-deal and per-game outputs, logs, and analysed summaries |
