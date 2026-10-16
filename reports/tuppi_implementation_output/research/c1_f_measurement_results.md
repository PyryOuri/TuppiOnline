# C1 branch-fraction measurement — results (2026-09-26)

Owner-approved, bounded run under `research/c1_f_measurement_manifest.json`:
- 12 deals: 8 natural v3 deals and 4 forced-NOLO deals.
- The installed best agent (W128) at all seats, with fresh agents per deal.
- Cost: 116.8 CPU-s and 23.3 s wall, inside the caps (300 CPU-s, 240 s). No early stop, no failures.
- Raw rows: `logs/c1_branch_fraction.json`.

| Quantity | Value |
|---|---|
| CPU per natural deal | 10.8 s |
| NOLO deals among the 8 natural deals | 1 (12.5%) |
| **f (C1-eligible NOLO-discard CPU / total), natural deals** | **1.3%** (deal bootstrap 95%: 0–3.8%; one NOLO deal, so this is very imprecise) |
| C1-eligible CPU per NOLO deal | 0.55 s (forced NOLO; 7.25 eligible decisions per deal); 1.13 s in the one natural NOLO deal |
| of which early discards (> 6 tricks left, network rollouts) | 97%; about 0.36 s each, about 1.5 per deal. Late (solver-only) discards cost 0.003 s each |
| f modelled for a NOLO share of 5–30% | 0.26–1.5% |
| **Bound on C1's total CPU saving, f·r** (f = 3.8%, the upper bootstrap end) | **0.4% (r = 0.1), 1.3% (r = 0.35), 1.9% (r = 0.5)** |

Where the CPU goes in natural deals:

| Decisions | Share of CPU |
|---|---|
| Bid searches | 53% (2.4 s each) |
| RAMI early leads | 20% |
| RAMI early follows | 12% |
| NOLO play (all) | about 7% |
| Sooli offers | 2.5% |

Even inside a NOLO deal, the discards are only 8% of play CPU; leads (51%) and follows (37%) dominate.

**Conclusion.** C1 as specified cannot approach the package's 20% total-CPU target. Its saving is bounded at about 2% even with generous assumptions, and is most likely well under 1%. The implementation stays PILOT_READY but is not recommended for a pilot. The within-branch saving r was not measured here, and no strength claim is made.
