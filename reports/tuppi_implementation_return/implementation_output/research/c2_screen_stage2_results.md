# P.C2 stage 2 — results (2026-09-26)

Owner-approved run under `research/c2_stage2_manifest.json`:
- 1-deal pre-flight (29 CPU-s), then 30 fresh natural v3 deals (a deck namespace unused in stage 1), played through showing by the as-is W128 agents.
- 44 evaluated blind bids with k ≥ 1; 519 CPU-s and 70 s wall. Total 548 CPU-s of the 720 allowed.
- Raw data: `logs/c2_screen_stage2.json`.

**Arms** (all use 128 worlds):
- **live:** the bot's actual bid.
- **F128c:** a fresh unconditioned sample — a pure noise control.
- **R128:** the first 128 sampled worlds whose clone predecessors all pass.
- **RC128:** the same worlds with the predecessors' chosen cards.

**Validation:** wherever an arm's pick differed from the live bid, both were re-evaluated on 256 fresh pass-consistent worlds with the chosen cards (the RC model), as a paired difference.

| Quantity | Result |
|---|---|
| Exclusion rate (worlds rejected by the pass check) | 30% mean; no shortfalls (128 accepted every time) |
| Pick differs from the live bid | **F128c: 25 of 44**, R128: 28, RC128: 31 |
| Validated gain per reached call, F128c (noise control) − live | +0.00036 ± 0.00024 |
| Validated gain per reached call, R128 − live | −0.00027 ± 0.00045 |
| Validated gain per reached call, RC128 − live | −0.00013 ± 0.00030 |
| **Conditioning effect: R128 − F128c** | **−0.00063 ± 0.00040** |
| **Conditioning effect: RC128 − F128c** | **−0.00048 ± 0.00028** |
| Per deal, RC128 − live | −0.00019 ± 0.00042 |

(± is one standard error across positions.)

**Interpretation.**
- **Conditioning does not improve decisions.** Even at an equal effective sample, and measured under the conditioned model's own validation law, the conditioned picks are no better than an unconditioned W128 resample. The point estimates are slightly worse (about 1.7 SE); a gain above about +0.0005 per reached call is unlikely on this sample. The stage-1 premise (30% of the search's worlds are inconsistent with the earlier passes) is real, but it does not translate into better bids.
- **Bid choice is dominated by sampling noise.** Re-running the same W128 bid search on a fresh sample changes the chosen bid in 57% of reached positions, while the validated value differences between those choices are of order 0.001. Bids are mostly near-ties at W128.

**Recommendation:** do not take C2 to a whole-game test. An effect below 0.0005 per call would need thousands of paired deals to detect, and this screen points the other way. The clone-model validation law is a limitation (96% per-world agreement with the real W128 bidders in stage 1).
