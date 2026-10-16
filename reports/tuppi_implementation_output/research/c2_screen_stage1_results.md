# P.C2 stage 1 screen — results (2026-09-26)

Owner-approved stage 1 under `research/c2_screen_manifest.json` (about 12 CPU-minutes):
- 2-deal pre-flight: 81 CPU-s.
- Main run: 30 natural v3 deals by the as-is W128 agents, played through showing; 431 CPU-s and 65 s wall. No early stop.
- Raw data: `logs/c2_screen_stage1.json`.

| Quantity | Result |
|---|---|
| Contracts | 30 of 30 deals ended RAMI |
| Reached blind bids by reveal position k (0/1/2/3) | 30 / 23 / 18 / 9; the 50 with k ≥ 1 were evaluated |
| **Exclusion rate: sampled worlds in which a clone predecessor would NOT have passed** | **k = 1: 22%, k = 2: 38%, k = 3: 38% (max 64%); some exclusion in every one of the 50 positions** |
| Calibration: W128 search predecessors vs the clone model (4 positions, 24 worlds) | search 21/24 passes, clone 20/24; per-world agreement 96% |
| Bid choice changes vs F, at 64 worlds | R: 11 of 50, RC: 24 of 50 |
| "Regret of F" on the same worlds (selection-biased) | +0.0007 (R), +0.0009 (RC) per position |
| **Validated on 256 fresh independent worlds: R's pick minus F's pick, under R's own model** | **mean −0.0051 over 11 changed positions; 0 significantly better, 3 significantly worse** |
| Same for RC | mean −0.0024 over 24 changed positions; 1 better, 5 worse |
| Per reached call, over all 50 evaluated positions | −0.0011 (R), −0.0012 (RC) |

**Interpretation.**
- **C2's premise holds.** The current bid search counts 20–40% of its sampled worlds as if the earlier bidders might hold hands with which they would have declared RAMI. That is material, and the clone model agrees with the real W128 bidders on 96% of calibration worlds.
- **Naive reweighting at a fixed world budget hurts.** R keeps about 70% of the worlds, so its estimates are noisier. The picks it overturned, mostly switches to a high-variance RAMI bid, were worse on fresh worlds: a winner's-curse effect, not evidence against conditioning itself.
- **The same-world "regret" was positive.** It was selection-biased; the fresh-world validation reverses its sign.

**Next (stage 2, not run):** keep the effective sample. Rejection-sample until 128 worlds pass the predecessor check; the clone check is 1–3 network forwards per world, negligible next to rollouts. Then evaluate at the same W128 continuation cost, and validate against the current W128 (F) pick on fresh worlds; then, if promising, a paired full-game test.
