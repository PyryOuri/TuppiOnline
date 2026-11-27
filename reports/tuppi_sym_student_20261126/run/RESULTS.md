# Suit-symmetry student vs the released bots

Candidate minus released network; match equity per base deal, 95% intervals.

| Measure | Base deals / pairs | Result | No-change deals | CPU h |
|---|---:|---|---:|---:|
| Network alone (greedy): student vs VRPO4, 0-0 | 4096 | +0.00319 [+0.00278, +0.00359] | 194 | 1.09 |
| Network alone (greedy): student vs VRPO4, uniform scores | 4096 | +0.00740 [+0.00626, +0.00855] | 822 | 1.13 |
| Nelli (lite C1H): student vs VRPO4 (Nelli 1.1), uniform scores | 8192 | +0.00637 [+0.00559, +0.00716] | 1641 | 2.78 |
| Nelli (lite C1H): complete matches from 0-0, student vs Nelli 1.1 | 3500 | win rate 0.6241 [0.6143, 0.6340] (0 unfinished) | | 8.88 |
| Heidi screen W128 PIB8: student anchor vs VRPO4 anchor (Heidi 1.2), uniform | | not run | | |
| Heidi W1024 PIB8 (as released): student anchor vs Heidi 1.2, uniform | | not run | | |
