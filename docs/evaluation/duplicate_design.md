# Canonical duplicate design

## Eight-row block

The canonical design is `balanced_duplicate_8_v1`. For each independently
generated base deal it crosses four clockwise card/dealer rotations with both
external-team partnership assignments. Partner component order is woven into
those eight rows, so no additional rows are needed.

Let `r` be clockwise rotation, `e` exchange external Team A and Team B between
the engine's even and odd partnerships, and `p` exchange the two component
agents within both partnerships. The exact ordered rows are:

| position | r | e | p = e XOR parity(r) | A partnership |
| ---: | ---: | ---: | ---: | --- |
| 0 | 0 | 0 | 0 | seats 0/2 |
| 1 | 0 | 1 | 1 | seats 1/3 |
| 2 | 1 | 0 | 1 | seats 0/2 |
| 3 | 1 | 1 | 0 | seats 1/3 |
| 4 | 2 | 0 | 0 | seats 0/2 |
| 5 | 2 | 1 | 1 | seats 1/3 |
| 6 | 3 | 0 | 1 | seats 0/2 |
| 7 | 3 | 1 | 0 | seats 1/3 |

Card hands, shown cards, and scripted actions map from old seat `s` to
`(s + r) mod 4`. Dealer maps by the same formula, so forehand remains the next
clockwise seat. A one-sided starting score swaps engine team coordinates under
odd rotations because those rotations exchange the even/odd partnerships.
External-team assignment exchange changes which compared team occupies each
engine partnership; it does not alter the materialized cards.

## Balance proof

Each rotation occurs twice. Therefore the transformed dealer visits every seat
twice, and transformed forehand also visits every seat twice. Each external
team occupies the even partnership in four rows and the odd partnership in
four rows, and consequently holds dealer and forehand in four rows each.

For a heterogeneous partnership, the XOR partner-order rule places each
component agent at each physical seat twice across the block. Homogeneous teams
obtain the same role balance even though their component IDs coincide.

Four rotations are necessary to balance all physical dealer seats for an
arbitrary base dealer. Both partnership assignments are necessary to compare
two external teams on both engine partnerships. Their product gives a lower
bound of eight rows; the partner-order factor is folded into those rows. Thus
eight is the smallest complete crossing of the required nuisance factors.

## Correlation and inference unit

The eight games reuse the same 52 cards and are intentionally correlated.
Counting them as eight independent observations would understate uncertainty.
All raw rows are retained for diagnostics, but the primary inference value is
one average signed utility per complete base-deal block. A block with any
failed row is incomplete and excluded from ordinary outcome inference.

Rotations are reported as a diagnostic stratum because seat-specific agents
need not be rotation-equivalent. Suit permutations are supported only for
evaluator validation, carry `strength_estimation=false`, and are never inserted
automatically into this strength-comparison schedule.

## Match sequences

In match mode the same table is applied to an ordered sequence rather than one
deal. The sequence—not its constituent transformed matches—is the independent
unit. Dealer order and rising score evolve inside each transformed match.
