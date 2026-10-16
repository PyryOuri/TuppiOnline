# P.C5 stage 1 screen — results (2026-09-26)

Owner-approved stage 1 run under `research/c5_screen_manifest.json`:
- 68 natural v3 deals, played by the as-is W128 agents at all seats.
- Cost: 886 CPU-s and 195 s wall, inside the caps (1,200 CPU-s, 400 s). No early stop.
- Raw rows: `logs/c5_screen_stage1.json`. A 2-deal pre-flight and a key diagnostic also ran (`logs/c5_screen_smoke.json`).

| Quantity | Result |
|---|---|
| Source deals / eligible three-card lead positions | 68 / 64 (the 4 gate failures were sooli deals) |
| Complete support ≤ 100 worlds (strict = native) | **16 of 64 (25%)**. The other 48 had 120–1,680 worlds; 12 had the unconstrained maximum of 1,680 |
| Options actually started | 14 (2 exact positions hit the 100 ms deadline and fell back) |
| Option lead differs from W128's lead (fixed-clone model) | 2 of 16 |
| Model gain, option minus full W128 policy, fixed-clone opponents | +0.00027 per exact position (95%: −0.00011 to +0.00064); non-zero in 2 of 16 |
| **At the next root decision against the real W128 opponents** | **1 of 14 options followed its plan; 11 fell back off-support.** The real searching opponents did not play as the clone predicts. Diagnostic on source 0: the true world is in the support and its clone-predicted key is in the plan, but the W128 opponent played the 8 where the clone plays the 2 |
| **Transfer: realized equity, C5 minus W128, same forked opponents** | **−0.0014 per eligible position** (95%: −0.0040 to +0.0013); non-zero in 1 of 64 |
| The one changed outcome (source 22, RAMI, 80 worlds) | The model preferred lead 28 over W128's 10 (Q 0.0453 vs 0.0438). In the real deal the root's team took **7 tricks instead of 10: −0.087** |
| First-decision latency (support + solve) | p50 3.9 ms, p95 93 ms, max 106 ms |

**Interpretation.** C5 v1 optimises against fixed clone opponents. In the last three tricks, the real opponents are W128 searchers whose rollouts are all solved exactly, which is much stronger play than the clone's. So the plan is rarely usable, and when it changed the lead it chose a line that the real opponents punished.

Three failure modes, all measured:
- coverage is limited by the 100-world cap;
- the fixed-clone opponent model mismatches the real searching opponents;
- the only observed real deviation was a loss.

64 positions cannot confirm or exclude a +0.001 effect. But no evidence of a gain was seen, the model and reality disagreed in the one case that mattered, and a model matched to the real opponents (W128 searches inside the option solve) would cost far more than the latency budget.

**Recommendation: do not promote C5 v1; treat the fixed-clone design as rejected for this bot.**
