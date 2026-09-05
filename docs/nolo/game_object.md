# Gate 0: `project_target_v1` stated as a mathematical object

Read cold from `docs/rules/project_target_v1.md` and verified against the
executable reference in `src/tuppi_rules/`. Written before any mathematics was
chosen, and it **proposes none** — that is Gate 1's job, and a suggestion here
would anchor it.

Every claim below is rules-derived. Where a consequence follows by deduction
rather than being stated in the spec, it is marked **[deduced]**. Nothing here
is empirical; measured facts live in `docs/nolo/charter.md` §4–§6.

---

## 1. The deal

Four seats `0..3` clockwise. Partnerships are fixed and never change:
**Team 0 = {0, 2}**, **Team 1 = {1, 3}**. A standard 52-card deck is dealt
completely, 13 cards per seat, so every card is somewhere and no card is
withheld.

Ranks run 2 (low) through ace (high). Hearts and diamonds are red; clubs and
spades are black.

**There is no trump suit.** Suit order in the encoding
(`project_target_v1_suit_major_hdcs_rank_2_to_ace`) is a serialization
convention only; no suit has precedence over another. Colour has exactly one
role in the rules — show eligibility (§3) — and **no role in trick play**.

Dealer `d` is supplied by the runner; `forehand = (d + 1) mod 4`; the dealer
rotates by one after each completed nonterminal deal.

## 2. Information structure

Sequential, not simultaneous. Perfect recall.

A seat observes: **its own 13 cards**, the public show actions, and the public
play history. It never observes another seat's hand. The formal boundary is
`PlayerObservation` (`src/tuppi_engine/observations.py`), which carries
`own_hand`, `show_actions`, `publicly_shown_cards`, `completed_tricks`,
`current_trick`, `team_tricks`, `match_score`, and the seat's `legal_actions` —
and nothing else.

So the hidden state is a partition of the 39 cards not in your hand across three
other seats, subject to whatever the public record constrains. **[deduced]**

## 3. Showing and contract selection

One round, starting at the forehand, proceeding clockwise. A show action is a
seat, one card actually held, an explicit declared contract, and a rules-derived
`verbal_required` flag.

**The shown card is revealed but stays in the hand.** It is not reserved and may
later be played normally.

Eligible ranks are **3 through 9 inclusive** (`ELIGIBLE_SHOW_RANKS`). Ranks 2,
10, J, Q, K, A are ineligible. The normal colour is **red for RAMI, black for
NOLO** (`showing.py:21`).

A mandatory, ordered hierarchy governs which card may be shown:

| Priority | Hand condition | Valid cards | `verbal_required` |
| --- | --- | --- | --- |
| 1 | Holds an eligible card of the normal colour | Only eligible cards of that colour | `false` |
| 2 | No eligible normal-colour card, but some eligible card | Any eligible card | `true` |
| 3 | No eligible card of either colour | Any card at all | `true` |

A player may not choose a lower priority while a higher one is available, and
`verbal_required` is derived, not chosen.

Showing **ends at the first RAMI declaration**; that seat is the *ramaaja* and
later seats produce no action. If all four seats declare NOLO, the contract is
NOLO **with no declarer**. Fewer than four all-NOLO actions is an incomplete
sequence, not a resolved contract.

Three consequences matter for NOLO:

- **Every NOLO deal contains exactly four show actions, one per seat.**
  **[deduced]** NOLO is reached only by four declarations, so in any NOLO deal
  all four seats have publicly revealed one card each, and those cards are still
  in their hands.
- **The priority level of a show is itself public and constrains the whole
  hand.** **[deduced]** A NOLO show at priority 1 reveals a black card of rank
  3–9 and little else. A show at priority 2 proves that seat holds **no black
  card of rank 3–9 at all**. A show at priority 3 proves it holds **no card of
  rank 3–9 in any suit**. These are hand-level exclusions, not single-card
  facts, and they are available before the first lead. This is what
  `tuppi_exact.derive_show_exclusions` encodes.
- **NOLO deals are not a random sample of deals.** **[deduced]** NOLO occurs
  only when all four seats declined RAMI, so the joint distribution of the four
  hands is conditioned on that. Any probability model fitted on observed NOLO
  deals inherits this selection. `ContractCondition.FORCED_NOLO` exists to break
  it.

## 4. Trick play

In NOLO the **forehand leads the first trick**. (In RAMI it is
`(declarer − 1) mod 4`.)

The leader may play any held card. Every follower **must follow the led suit if
able**; a seat void in the led suit may play any card. Invalid actions are
rejected outright and never silently replaced.

Each trick is exactly four cards, clockwise from the leader. **The highest card
of the led suit wins.** Off-suit cards — including aces — cannot win, because
there is no trump. The winner leads the next trick.

**All 13 tricks are always played**, even when the deal result, a future score
reset, or the match outcome is already mathematically certain. Scoring happens
only after the thirteenth trick. **[deduced]** There is therefore no concession
and no early termination: every position is played to exhaustion, including
positions whose outcome is already determined.

## 5. The NOLO objective

The team with **fewer** tricks wins. Totals sum to 13, so a tie is impossible.
With `w` the winning team's trick count:

```
points = 4 × (7 − w)          w ∈ {0, …, 6}
```

giving 4 points at `w = 6` up to 28 points at `w = 0`.

Verified in `scoring.py:25-29`: the winner is the team with the strictly smaller
total, and `w` is that team's count — so **`w = min(t₀, t₁)`**.

Two structural consequences, both **[deduced]**:

- **The score depends only on the minimum of the two team totals.** The losing
  team's count is exactly `13 − w` and enters the formula nowhere.
- **The marginal value of a trick is asymmetric and side-dependent.** For the
  team that will end up smaller, each trick it avoids is worth 4 points. For the
  team that will end up larger, its own additional tricks change the score not
  at all — its only lever is to raise the other side's count, which is the same
  as changing who the minimum belongs to. "Avoid tricks" is therefore not a
  faithful statement of the objective for both sides at once.

## 6. The match layer

A valid match score is `0–0`, `positive–0`, or `0–positive`. Both teams positive
is invalid. The single positive team is **up**; its opponent is **down**; `0–0`
is **at the table**.

After a scored deal:

| State | Winner | Result |
| --- | --- | --- |
| 0–0 | either | winner takes the points and becomes up |
| one team up | the up team | points are added to its score |
| one team up | the down team | **the up score is erased to 0–0; the down team receives nothing** |

The match ends when the up team reaches **≥ 52**. Overshoot is allowed and
carries nothing.

**[deduced]** This makes the value of a deal's *magnitude* depend entirely on
where you stand:

- **Down**: the size of a win is worth **exactly zero**. A 4-point win and a
  28-point win both produce the same state, `0–0`. Only the binary win/loss
  matters.
- **Up, or at the table**: magnitude is worth the full 4 points per trick below
  seven, since it accumulates toward 52.

So in NOLO the same card decision can be worth four points per trick or nothing
at all, determined by the scoreboard rather than by the cards. The rules-level
reason the down team's margin is worthless is this reset rule.

## 7. What this object is *not*

Stated because the parent programme lost real time to imported assumptions
(`docs/valuation/handoff.md` §2.11).

- **No trump.** Off-suit cards can never win a trick.
- **No dummy and no visible hand.** No seat's cards are ever exposed, at any
  point. Maxims that assume a declarer playing against a visible dummy do not
  have their preconditions here.
- **No bidding beyond a single round of shows**, and no contract level, no
  doubling, no suit choice.
- **No partnership signalling defined by the rules.** Any signal is emergent
  from policy, not conferred by the ruleset — so it exists only to the extent
  both partners run compatible rules, and an opponent modelling it is modelling
  a *policy*, not a rule.
- **No early end.** Thirteen tricks, always.

## 8. What the rules leave open

The ruleset fixes legality and scoring, and nothing else. It says nothing about
which legal card to choose. Every strategic question — which suit to lead, when
to duck, what to discard, what a partner's card means — is unconstrained by the
rules and is entirely policy.

---

**This document deliberately proposes no mathematics.** If you are reading it as
part of Gate 1, the next thing to read is `docs/nolo/charter.md` §4–§8.
