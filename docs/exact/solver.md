# The exact late-game solver

`solve_late_game(state)` computes the game-theoretic optimum of a perfect-information
trick-play position **exactly**. It never estimates. A position beyond the
configured budget raises `SolverBudgetError`.

That is a deliberate design constraint, not caution. A solver that silently
degraded into a heuristic would keep the interface - and the authority - of an
exact answer while losing the property that earned it, and every downstream number
would inherit a confidence it no longer deserved.

## One search covers both contracts

`project_target_v1` has no trump suit, always plays all 13 tricks, and scores a
deal purely from the team trick split. Both scoring formulas are strictly monotone
in one team's trick count:

- **RAMI.** The declaring team's signed value rises with its own tricks (`+4` per
  trick above six). The defenders' *stolen-rami* value also rises with **their**
  tricks (`+8` per trick above six). So in RAMI both partnerships want tricks.
- **NOLO.** The team with fewer tricks wins, and the winner's points rise as its
  tricks fall. So in NOLO both partnerships want to avoid tricks.

Either way the deal is zero-sum in the trick split, so one minimax on team-0's
final trick count suffices, with the polarity taken from the contract. There is no
separate NOLO engine and no separate RAMI engine to keep in agreement.

`team0_prefers_more_tricks(contract)` is that polarity. Getting it wrong is not a
subtle degradation - it inverts every NOLO answer - and it once did:
`test_nolo_minimizes_own_tricks_regression` exists because the root move loop
originally took a maximum unconditionally.

## The match score does not change optimal play

Fix the contract and the declarer. Then:

- the deal outcome is a function of the trick split alone;
- the rising-score transition is a function of the deal outcome and the starting
  score alone.

So each team's **match utility is a function of the trick split alone**, and
`monotonicity_certificate()` verifies exhaustively - every contract, every legal
declarer, every reachable score state, both teams, all fourteen splits, 250 cases -
that it is weakly monotone in the same direction as the deal points.

A weakly monotone transform of a zero-sum game leaves the minimax solution an
equilibrium. Therefore:

> **Every trick-optimal card is also match-optimal, at every score state, under
> perfect information.**

The converse fails only by adding ties: a match-optimal set can be strictly larger,
because the rising score discards margin that trick-optimal play still competes
for.

This is the structural result that drives the Phase 5B diagnosis. Two of Phase 4's
four rising-score rules change **cards**, and a card-changing rule cannot buy
anything a perfect-information player would want. See
`docs/exact/phase5b_results.md`.

### Scope, stated precisely

The claim is about perfect information and nothing else. Under **imperfect**
information a team facing a step-shaped utility - any win resets the opponents'
rise, whatever the margin - may rationally prefer the line that maximizes the
*probability* of a win over the one that maximizes expected points. That is a real
effect and it is exactly what a later phase's search agent has to represent. What
Phase 4's rules do not do is compute it.

## The utility currency

`match_utility_from_score(after, team)` is an ordered pair:

| State | Utility |
| --- | --- |
| Match won | `(1, 0)` |
| Nonterminal | `(0, own_rise - opponent_rise)` |
| Match lost | `(-1, 0)` |

**Overshoot past 52 is worth nothing.** Crediting it would rank a 56-point win
above a 52-point win and would score a rule that stops competing for a worthless
margin as *harmful*. That mistake was made and caught: an earlier version credited
the overshoot, and the coasting rule appeared to lose match value it had never had.

This is a documented **ordering**, not a match win probability - a win probability
would need a model of the deals still to come. It is strong enough for the only
question asked of it, *did this card reach a strictly worse match state than exact
optimal play*, and weak enough to stay exact.

`regret_in_deal_points` is kept alongside `match_utility_regret` and is expected to
disagree with it. Deal points are the wrong currency for judging a match rule; both
are recorded so the disagreement is visible rather than resolved silently.

## Exactness aids

**Alpha-beta with a bound-typed transposition table.** A cutoff yields a *bound*,
not a value. Every entry records whether it is exact, a lower bound, or an upper
bound, and lookups respect that. Storing a cutoff value as if exact is the classic
way to make an "exact" solver quietly wrong.

**Equivalent-card reduction.** Two cards of one suit in one hand are
interchangeable when no card that can still matter lies between them in rank -
the cards in between are the actor's own, so whichever is played the rest keep the
same relationship to every card that can still matter.

"Can still matter" has two parts, and omitting the second was a real defect:

1. cards another seat still holds, which decide future tricks;
2. **cards already in the current trick**, which decide *this* trick.

A card of the led suit sitting between two of the actor's cards means one of them
beats the trick and the other does not, so they are not interchangeable even though
no hand holds anything between them. `test_equivalence_reduction_counts_the_current_trick_regression`
pins this with a minimal position: the actor holds `5H` and `7H`, and `6H` is on the
table.

## Cross-checked, not trusted

The suite keeps an independent unpruned minimax reference. It is slow and obviously
correct, and it found both defects above.

- 480 RAMI positions and 240 NOLO positions agreed exactly, including 1 638
  per-action values.
- `test_solver_agrees_with_the_reference_at_every_late_position` and
  `test_every_action_value_agrees_with_the_reference` keep a CI-sized subset of
  that comparison running on every commit.

## Cost, and choosing the budget

Measured on this machine, from a cold transposition table per position:

| Tricks remaining | Mean time | Mean nodes |
| ---: | ---: | ---: |
| 1 | 0.03 ms | 2 |
| 2 | 0.05 ms | 14 |
| 3 | 0.18 ms | 82 |
| 4 | 0.86 ms | 377 |
| 5 | 5.6 ms | 2 401 |

Roughly a factor of six per extra trick, so 6 tricks is tens of milliseconds and 7
approaches a second. `DEFAULT_MAXIMUM_TRICKS_REMAINING = 5` is a cost decision, not
an accuracy decision: the answer is exact at any budget. `DEFAULT_NODE_BUDGET`
exists as a backstop and also raises rather than truncating.

A full 13-trick double-dummy solve is **out of scope** for this pure-Python
implementation. Nothing in Phase 5B pretends otherwise, and the showing-decision
analysis in the diagnosis is built to need only late-game solving plus exact
combinatorics, precisely because full-deal solving is unavailable.

## Research-private by construction

The solver reads all four hands. It is never handed to a policy, no observation
carries its output, and no Phase 4 agent can import it - `tuppi_exact.integrity`
verifies that containment. `solve_continuation` is the sampled-world entry point,
and its result is exact **for that sampled world**, which is the only honest
reading: it says what optimal play achieves if the opponents' cards really lie where
the sampler put them, not what the position is worth.
