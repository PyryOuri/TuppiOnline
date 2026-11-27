# Suit-symmetry student vs the released bots

Candidate minus released network; match equity per base deal, 95% intervals.

| Measure | Base deals / pairs | Result | No-change deals | CPU h |
|---|---:|---|---:|---:|
| Network alone (greedy): student vs VRPO4, 0-0 | | not run | | |
| Network alone (greedy): student vs VRPO4, uniform scores | | not run | | |
| Nelli (lite C1H): student vs VRPO4 (Nelli 1.1), uniform scores | 8192 | +0.00637 [+0.00559, +0.00716] | 1641 |  |
| Nelli (lite C1H): complete matches from 0-0, student vs Nelli 1.1 | | not run | | |
| Heidi screen W128 PIB8: student anchor vs VRPO4 anchor (Heidi 1.2), uniform | | not run | | |
| Heidi W1024 PIB8 (as released): student anchor vs Heidi 1.2, uniform | | not run | | |

## Nelli on the student vs Heidi 1.2 (W1024 as released), uniform scores

Pooled over 2 chunks (4 base deals, 0.18 CPU h): **-0.00030 [-0.01387, +0.01327]** per deal (negative: Heidi is stronger); per-base-deal SD 0.0138.
Implied Nelli 1.1 vs Heidi 1.2 (this minus the Nelli duplicate's student gain, independent samples): -0.00668 [-0.02027, +0.00692].
