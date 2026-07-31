# `project_target_v1`: authoritative project Tuppi rules

## Status and provenance

This document is the principal engineering specification for
`project_target_v1`.

| Field | Value |
| --- | --- |
| Source type | Project-owner specification |
| Specification date | 2026-07-31 |
| Original language | Finnish |
| Status | Authoritative for this project |
| Relationship to tournament rules | Derived from traditional/tournament-style Tuppi but intentionally modified |

The owner specification expressly uses no separate physical show cards, always
plays all 13 tricks, and uses continuous rising-score play until a team reaches
52 or more. Web sources and `legacy_v9_unverified` may provide historical
context, but neither overrides this ruleset. This document makes no claim of
official status outside this project.

The machine-readable companion is
`configs/rules/project_target_v1.json`; `src/tuppi_rules/` is its small pure
executable reference. The three representations and their normative tests must
remain consistent.

## Definitions

- **Seat**: one of the fixed clockwise positions 0, 1, 2, 3.
- **Team 0**: seats 0 and 2. **Team 1**: seats 1 and 3.
- **Dealer**: the runner-supplied seat dealing the current deal.
- **Forehand** (*etukäsi*): the seat immediately clockwise from the dealer.
- **Show** (*näyttö*): one publicly revealed card from a player's hand plus an
  explicit internal contract declaration.
- **Rami declarer** (*ramaaja*): the first player to declare RAMI.
- **Up team** (*nousussa* or *ylhäällä*): the sole team with a positive match
  score.
- **At the table** (*pöydässä*): the 0–0 match state.
- **Stolen rami** (*ramin ryöstö*): a RAMI deal in which the declaring team
  takes at most six tricks and its opponents win doubled points.
- **Tuppeen paneminen**: traditional terminology that has no extra scoring or
  termination effect in this ruleset. Extreme results use the formulas below.

## Players, cards, and partnerships

Four players remain in seats 0, 1, 2, 3 in clockwise order. Partnerships never
change: Team 0 is seats 0 and 2; Team 1 is seats 1 and 3.

A standard 52-card deck is dealt completely, giving each player exactly 13
cards. Hearts and diamonds are red; clubs and spades are black. Rank order from
low to high is 2, 3, 4, 5, 6, 7, 8, 9, 10, jack, queen, king, ace. There is no
trump suit.

The executable representation serializes suits as hearts, diamonds, clubs,
spades. This is an encoding convention only; suits have no precedence over one
another. The stable encoding identifier is
`project_target_v1_suit_major_hdcs_rank_2_to_ace`: suits are the major index and
ranks run from 2 through ace inside each suit.

## Dealer and forehand

The game runner supplies the initial dealer explicitly. If a runner wants a
random dealer, the runner performs and records that selection; the rules core
contains no random dealer selection.

For dealer `d`:

```text
forehand = (d + 1) mod 4
next dealer after a completed deal = (d + 1) mod 4
```

The dealer rotates only after a completed, nonterminal deal. No next deal is
started after the match has ended.

## Showing and contract selection

The two contracts are:

- `RAMI`: teams try to win tricks.
- `NOLO`: teams try to avoid tricks.

There are no separate physical red or black show cards. A show action always
records the player's seat, one card actually held by that player, the explicit
declared contract, and the rules-derived `verbal_required` flag. The card is
publicly revealed but remains in the hand, is not reserved, and may later be
played normally.

Showing starts with the forehand and proceeds clockwise. Only ranks 3 through
9 inclusive are normally eligible. Ranks 2, 10, jack, queen, king, and ace are
normally ineligible. RAMI's normal color is red; NOLO's normal color is black.

The following hierarchy is mandatory and ordered:

| Priority | Hand condition for the declared contract | Valid shown cards | `verbal_required` |
| --- | --- | --- | --- |
| 1 | At least one eligible card of the normal color exists | Only eligible cards of that matching color | `false` |
| 2 | No eligible matching-color card exists, but at least one eligible card exists | Any eligible card, regardless of color | `true` |
| 3 | No eligible card of either color exists | Any card in the hand | `true` |

The explicit declared contract is authoritative in fallback priorities 2 and
3. A matching-color but ineligible card is not valid while any eligible card
exists. Under priority 3, speech is required even when the arbitrary
ineligible card happens to have the contract's normal color.

`verbal_required` is derived from the hand, shown card, and declaration. It is
not a caller-selected rule input. A claimed value that disagrees with the
derived value is invalid. The executable `ShowAction` validator requires the
complete 13-card hand because showing occurs before play; it validates the hand
but does not retain it in the public action value.

Showing ends as soon as the first RAMI declaration is made. That player is the
ramaaja, and later seats produce no show actions. If four ordered actions all
declare NOLO, the result is NOLO with no declarer. An all-NOLO prefix of zero to
three actions is incomplete, not a resolved contract. Duplicate seats,
out-of-order seats, skipped seats, and actions after RAMI are invalid.

## First leader

- In NOLO, the forehand leads the first trick.
- In RAMI, the seat immediately before the ramaaja in clockwise showing order
  leads: `(declarer - 1) mod 4`.

Thus the dealer leads when the forehand declares RAMI. NOLO must have no
declarer; RAMI must have exactly one valid declarer.

## Trick play and deal completion

The leader may play any held card. Every following player must play the led
suit if able; a player void in that suit may play any held card. An invalid
action is rejected and is never replaced with a different action.

Each trick has exactly four cards, one per seat in clockwise order beginning
with the leader. The highest-ranked card of the led suit wins. Off-suit cards,
including aces, cannot win. The winner leads the next trick.

A completed deal contains exactly 13 completed tricks and plays all 52 cards
exactly once. All 13 tricks are played even when the deal outcome, a future
score reset, or the eventual match result is already mathematically certain.
Scoring is applied only after the thirteenth trick.

## NOLO deal scoring

The team with fewer tricks wins. Since the totals sum to 13, a tie is
impossible. With `winner_tricks` equal to the winning team's total:

```text
points = 4 × (7 - winner_tricks)
```

| Winner's tricks | Points |
| ---: | ---: |
| 6 | 4 |
| 5 | 8 |
| 4 | 12 |
| 3 | 16 |
| 2 | 20 |
| 1 | 24 |
| 0 | 28 |

Every possible team split from 0–13 through 13–0 is scored by this rule.

## RAMI deal scoring

The declaring team is the ramaaja's partnership.

If it takes at least seven tricks, it wins and receives:

```text
points = 4 × (declaring_tricks - 6)
```

| Declaring tricks | Points |
| ---: | ---: |
| 7 | 4 |
| 8 | 8 |
| 9 | 12 |
| 10 | 16 |
| 11 | 20 |
| 12 | 24 |
| 13 | 28 |

If it takes at most six tricks, the opponents win by ramin ryöstö. With
`opponent_tricks = 13 - declaring_tricks`:

```text
points = 8 × (opponent_tricks - 6)
```

| Declaring tricks | Opponent tricks | Stolen-RAMI points |
| ---: | ---: | ---: |
| 6 | 7 | 8 |
| 5 | 8 | 16 |
| 4 | 9 | 24 |
| 3 | 10 | 32 |
| 2 | 11 | 40 |
| 1 | 12 | 48 |
| 0 | 13 | 56 |

## Rising-score match

A valid match score is 0–0, positive–0, or 0–positive. Scores are
nonnegative, and both teams may never be positive simultaneously. The sole
positive team is up; its opponent is down.

After a completed and scored deal:

| Current state | Deal winner | Result |
| --- | --- | --- |
| 0–0 | Either team | Winner receives the deal points and becomes up |
| One team up | Up team | Deal points are added to its existing score |
| One team up | Down team | Up score is erased; result is 0–0; down team receives no points |

The reset rule applies regardless of the deal's point value. A 56-point stolen
rami by the down team resets the score to 0–0; it does not award 56 points.

The match ends when the up team's score is **greater than or equal to 52**.
Overshooting is allowed. A terminal state may be represented, but no further
deal transition is valid because the match has ended.

Worked examples:

- 0–0 plus an 8-point Team 1 win becomes 0–8.
- 20–0 plus an 8-point Team 1 win becomes 0–0.
- 48–0 plus a 4-point Team 0 win becomes 52–0 and ends the match.
- 48–0 plus an 8-point Team 0 win becomes 56–0 and ends the match.
- 0–48 plus an 8-point Team 1 win becomes 0–56 and ends the match.
- 20–0 plus a 56-point Team 1 stolen-rami win becomes 0–0.

There is no fixed deal count, no early end after seven tricks, and no score
transfer to the down team when it resets the up team.

## Invalid states and edge cases

- Seats outside integer values 0–3, including booleans, are invalid.
- Cards not held by the acting player are invalid actions.
- Showing never removes or reserves the card.
- A player cannot choose fallback priority 2 or 3 while an earlier priority is
  available.
- An incomplete all-NOLO sequence has no contract result yet.
- Trick totals must be nonnegative integers summing to 13 before deal scoring.
- A deal with fewer than 13 tricks is incomplete even if its winner is certain.
- Negative match scores and two-positive-team scores are invalid.
- Rules functions reject invalid input explicitly; they do not normalize,
  default, or substitute actions.

## Differences from `legacy_v9_unverified`

The frozen artifact is not a normative source. Known comparisons include:

- Legacy defaults ban 2, jack, queen, and king, thereby normally allowing 10
  and ace; target eligibility is exactly ranks 3–9.
- Legacy asks all four players for bids before revealing in order, and only the
  reveal loop stops at RAMI. Target action collection itself ends at RAMI.
- Legacy verbal bids may carry no card. Target always records and reveals a
  card from the hand, including verbal fallbacks.
- Target always stores an explicit contract declaration and validates its
  card against the three-level hierarchy. Legacy handling varies by player
  type and can infer a human declaration from color.
- Both retain a normally shown hand card, play 13 tricks, use the same basic
  leader and deal-scoring formulas, rotate clockwise, and use a continuous
  rise to `>= 52`; these target rules are established independently by the
  owner specification.
- Legacy supports flat scoring, mutable observations, shared RNG, silent
  configuration defaults, and illegal-action fallback. None belongs to the
  authoritative reference rules.
- Legacy initializes its own dealer to seat 0. The target core requires the
  runner to supply the initial dealer.

See `project_target_v1_decisions.md` for the domain-by-domain traceability
table. Legacy characterization tests remain non-normative and separate.

## Ruleset versioning policy

`project_target_v1` is immutable once used for recorded engine experiments.
Editorial corrections that do not alter executable behavior may update these
documents with a changelog note. Any change to legal actions, contract
resolution, leaders, deal completion, scoring, match transitions, or other
observable behavior requires a new ruleset identifier and versioned config,
executable implementation, fixtures, and normative tests. Historical result
records must retain the exact ruleset identifier under which they were made.
