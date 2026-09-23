# Partnership conventions for human play

Status: **research notes only, nothing implemented.** Started 2026-09-23 and
revised the same day with the owner's answers (section 8) and new
conventions (section 5), which were then reviewed critically with the owner. No code, config,
rules or test file was changed for this. Section 5.5 (sooli) depends on
`project_target_v2`, which is still being built, and is deferred on purpose.

## 0. A rules gap found while writing this

**The owner (2026-09-23):** in the real game, every player's bid card is
locked before any other card is seen, so nobody can change their card after
seeing their partner's.

- The declaration is locked too, including the spoken counter-colour bid
  (*vastaväri*, the verbal fallback), which must be honoured.
- Cards after the first RAMI are never turned over.

**`project_target_v1` does not model this.** Showing there is sequential.
During showing, a seat's observation includes every earlier show
(`TuppiProject/src/tuppi_engine/observations.py`: `show_actions`,
`publicly_shown_cards`), and the native core copies that. So the third and
fourth seats choose *after* seeing the earlier cards. The decisions table even
records that the legacy emulator "collects all four choices before an ordered
reveal". The target replaced this with "the first RAMI ends showing
immediately" (`TuppiProject/docs/rules/project_target_v1_decisions.md`,
contract-termination row).

**What depends on it:**

- the engine, the bot and every showing result;
- the app the owner plays in;
- the human benchmark.

**The change would be small.** A bid that is never revealed has no effect. So
"everyone bids at once, then the cards are revealed in order until the first
RAMI" gives the same outcomes and the same information as the current
sequential model, with one change: a seat's observation during showing leaves
out the earlier shows. Legal actions, contract resolution and scoring stay
as they are.

Under the versioning policy, changing it still needs a new ruleset identifier.
`project_target_v2` is being specified right now in the `TuppiProject-sooli`
worktree, so this is the cheapest moment to decide.

**Decided by the owner on 2026-09-23: switch to locked bid cards.** The plan is
in [`LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md`](LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md),
Part A.

For conventions, the consequence is simple: **the contract decision is made
blind.** No card can carry information to a partner before the partner bids.
The only way to coordinate bids is an agreed bidding style (section 5.4).

## 1. The question

Which partnership agreements can two people use at a real Tuppi table, and
which are worth learning?

This is **not** a search for more bot strength. The bot matters here only as a
measuring instrument (section 7). A convention is deployable for humans when:

1. **It works through card choice or agreed style only.** The carriers are
   your bid, your bid card, and which card you lead, follow with or discard.
   Speech, tempo and gestures are out.
2. **It survives being worked out.** Rules are not announced at the table.
   Regular opponents still work a pattern out, and the NOLO short-suit lead is
   already common knowledge. So two values matter: opponents unaware (the
   short run) and opponents aware (the long run at a regular table).
3. **It costs little or nothing to follow.** The best conventions are either
   good play made reliable, or a choice between cards that are otherwise equal.
4. **It fits in one sentence** and can be applied in a few seconds. Players do
   not count HCP today, but they could be taught to.
5. **It fails gently.** Strong players already break the existing convention
   when it would cost tricks. So the partner has to read a signal as likely,
   not certain.
6. **It comes up often, at a decision that matters.**

## 2. The channels the rules leave open

| Channel | When it is chosen | How much freedom | Who learns it, and when |
| --- | --- | --- | --- |
| Bid (NOLO or RAMI) | Simultaneously, locked | 2 options | Everyone, at the reveal, up to the first RAMI |
| Bid card (black 3-9 for NOLO, red 3-9 for RAMI) | Simultaneously, locked | A real choice in most hands (below) | Everyone, at the reveal, if it is reached |
| Fallback (verbal) bid | No card of the needed colour in 3-9 | Forced; reveals that the colour is missing | Everyone |
| Opening lead | Trick 1 | Suit and card | Everyone |
| Follow with equal cards | Cards that cannot change the trick | Often several | Everyone |
| Discard | Void in the led suit | Suit and card | Everyone |
| Sooli give and return | Sooli deals only (v2) | One card each | **Partner only** |

**How much choice the bid card gives** (300,000 random hands, see the appendix):

- A hand holds at least two black 3-9 cards 93% of the time.
- It holds black 3-9 cards in both black suits 78% of the time, and none at
  all 0.85% of the time (the verbal fallback).
- By rank: a black 7-9 in 84% of hands, a black 3-5 in 84%, both in 70%.
- Red cards give the same numbers.

**Whose card is known when play starts.** Cards are revealed from the
forehand `f`, then `f+1`, `f+2`, `f+3`, stopping at the first RAMI. The
partnerships are `(f, f+2)` and `(f+1, f+3)`. The RAMI opening leader is the
seat before the declarer, which is always a defender.

| RAMI declared by | Cards revealed | Declarer's partner's card known? | Opening leader's partner's card known? |
| --- | --- | --- | --- |
| `f` (forehand) | `f` | no | no |
| `f+1` | `f`, `f+1` | no | no |
| `f+2` | `f`, `f+1`, `f+2` | yes | no |
| `f+3` (dealer) | all four | yes | yes |
| nobody (NOLO) | all four | yes | yes |

Locked cards after the first RAMI are never turned over.

A bid card chosen blind has to work whatever happens next: NOLO or RAMI, and
whether you end up the declarer's partner or a defender. Its information only
reaches the *play*, not the contract decision.

## 3. What earlier project work already says

1. **Leading from the shortest suit in NOLO is the best lead rule measured.**
   Lead the shortest suit and the lowest card in it, with no partner return.
   That gives −0.69 tricks and +13.9 points of deal-win rate against "lead the
   lowest card". It still gains +12.2 points when the opponents lead the same
   way.
   - The void pays back late: it costs tricks 1-4 and collects in tricks 9-13,
     about 0.58 tricks saved per extra discard.
   - Leading the *highest* card of the short suit is worse (+0.49 tricks), also
     measured without a partner return.
   - Choosing between tied suits by "no high cards" gains nothing; length alone
     decides.

   (`TuppiProject/docs/valuation/void_seeking_lead.md`)
2. **Leading the partner's short suit back measured slightly negative.** Doing
   it first cost +0.094 tricks (z = +1.2), which is not significant. Waiting
   until the suit has gone round twice cost +0.053. Preferring a suit where the
   partner is *proven* void gained +0.006 (z = +0.2), which is no effect.
   - The reason given: the partner led their *lowest* card, so what they have
     left is higher.
   - The followers were heuristic bots.
   - Using the information to decide when to duck and when to take a trick was
     never tested.

   (`TuppiProject/docs/valuation/handoff.md` §1.4, §2.6)
3. **Without agreements, card choice says little.** If you do not know how a
   player picks cards, reading which low card they ducked with keeps only 1-5%
   of the signal it seems to have. What survives is voids, and tricks a player
   took when they could have ducked (`handoff.md` §3.1). **This is the main
   reason conventions should help humans:** an agreement turns a partner's
   unpredictable card choice into something you can read.
4. **Bridge maxims do not carry over automatically.** Second-hand-low and
   third-hand-high both lost in RAMI (`handoff.md` §2.11), because they assume
   a visible dummy. Tuppi has no dummy, so **both** partnerships play blind,
   like bridge defenders. Whist is the closer ancestor, since it has no dummy
   either, but whist has trumps and RAMI does not. Signals should use only
   cards that cannot change the trick.
5. **The contract decision has the most leverage.** 61% of the reference's
   decisions cannot change the deal outcome (`TuppiProject/docs/findings/README.md`).
   Switching the forehand's contract changed the outcome in 85.5% of play-outs
   (`TuppiProject/docs/showing/results_s1b.md`). With locked bids, that decision
   can only be improved by agreed style, not by signals.
6. **The forehand's RAMI break-even is 12 HCP** (A=4, K=3, Q=2, J=1).
   - Each card of rank 2-4 counts about −0.9 HCP against declaring.
   - Once the total points are known, aces and kings add nothing extra.
   - Near 12, one HCP is worth about 0.003-0.004 equity per decision.
   - The forehand bids blind in both the sequential and the locked game, so
     this result carries over, apart from how later seats behave.

   (`TuppiProject/docs/valuation/rami_declaration.md`)
7. **The bot's showing results come from the sequential game.** Its showing
   gains (it declares RAMI in 48.7% of deals vs 37.7%, and makes 79.6%;
   `docs/STATUS.md`) were measured where later seats see earlier cards. How
   much of that carries over to locked bids is unknown.

## 4. The convention already in use: the NOLO short-suit lead

**As the owner describes it (2026-09-23):**

- **Who and when.** Every player's first lead, in the early game. That is not
  fixed, but is roughly the first five tricks. A player whose first lead comes
  as late as trick 9 has no convention.
- **The suit.** Your shortest suit, usually one or two cards. It is led even
  when it is a singleton honour.
- **The card.** Not part of the convention. Most commonly the *largest* card
  of the suit.
- **The partner.** Generally leads the suit back; that is the point of the
  signal. The partner decides by their own hand:
  - with a strong hand, they support the teammate by leading the teammate's
    suit back;
  - with a worse hand, they lead their own shortest suit.
- **Exceptions.** Top players sometimes skip it when it would cost unnecessary
  tricks, especially with very good NOLO cards. What counts as "very good" is
  subjective. One example: a couple of short suits holding only very low
  cards.
- **Strength.** Not verified.

**The table's system is really a rule about who needs the void.** A player
with a dangerous NOLO hand voids themselves. A player with a safe hand spends
their lead helping the partner void instead. A leader with a very safe hand may
not void at all. This matches what the bot data says a void is worth (3.1): it
pays only by letting you discard high cards later, so it is worth the most to
the player holding the most high cards.

**How the hands fall (random hands):**

| Shortest suit you can lead | Share of hands |
| --- | ---: |
| 1 card | 30.7% |
| 2 cards | 54.9% |
| 3 cards | 13.1% |
| 4 cards | 1.2% |

- "One or two cards" covers 86% of hands.
- 30% of hands have two or more suits tied for shortest.
- In a singleton shortest suit, the card is J or higher 30% of the time, 7-10
  30%, and 2-6 40%.
- In a doubleton shortest suit, the higher card is J or higher 46% of the time,
  7-10 38%, and 2-6 16%.
- So "lead the largest" usually means leading an honour or a 7-10 at trick 1.
  In NOLO the other players duck under it when they can, so that card usually
  wins the trick. It is taken only when some follower holds nothing lower in
  the suit.

**The table's version is a different system from the one the bot tested, and
it hangs together.**

- The bot tested: lowest card first, no return. That leaves the leader holding
  the *higher* card, which is why returning the suit looked bad (3.2).
- The table plays: largest card first, partner returns the suit. When the
  partner leads the suit back, the leader can play the *low* card that remains,
  which is likely to lose, and is then void.
- So the earlier negative result about returning **does not refute the table's
  version**. It tested another combination.
- The table's version pays for this up front: the large card often wins trick
  1.
- Which of the two is better is unknown. Neither combination has been measured
  against the other.

**The exceptions have a sound basis.** A void is worth something only because
it lets you discard high cards later. A hand with few high cards has little to
discard, but still pays the early cost. How often such hands occur:

| Hand | Share |
| --- | ---: |
| At most one card J or higher | 3.5% |
| At most two cards J or higher | 14.8% |
| HCP 4 or less | 8.8% |

The owner's example of a very good hand, a couple of short suits holding only
very low cards, is rare:

| At least two suits that are void, or 1-2 cards all at or below... | Share of hands |
| --- | ---: |
| 5 | 0.6% |
| 6 | 1.2% |
| 7 | 2.1% |

At least *one* such suit is common (21-34%). So if strong players deviate
mainly with hands like these, the signal stays right well over 85% of the time.
A deviation also hints "my NOLO hand is safe".

**"Early game" also has a basis.** In the bot data the void costs tricks 1-4
and pays back from trick 9, breaking even around tricks 5-6 (3.1). So a void
started late has too little time to pay off. That fits both "roughly the first
five tricks" and "no convention at trick 9". The exact cut-off can be measured.

**What the partner can be sure of:** the leader holds at least as many cards in
every other suit they hold, unless this is one of the exceptions. There is no
rule about the card, so the led card says nothing reliable about what else the
leader holds in the suit.

**What the opponents learn:** the same, since everyone at the table knows the
convention.

## 5. New conventions

Every proposal here is tested against one question: **which decision does it
change, and would the cards alone not already decide it?**

The first round of this section (C1-C3) failed that test when reviewed with the
owner. The reasons are kept in 5.2, because they show where conventions can
and cannot help in this game.

### 5.1 Where conventions can help in Tuppi, and where they can't

A convention adds value only when all three of these hold:

1. The signaller has a **free choice**: cards of equal value to the trick.
2. The partner faces a **decision that depends on hidden, suit-by-suit
   information**.
3. **The play would not reveal that information in time anyway.**

**NOLO mostly fails these tests.**

- **Choices are rarely free.** "Duck with your highest card that still loses"
  and "throw your worst card" decide most plays. The owner: "the value and
  shape of cards direct the gameplay more than the convention".
- **The decisions depend on individual suits:** voids, unguarded high cards,
  low exit cards.
  - The table's short-suit lead already sends the most useful piece, which is
    shape.
  - Discards reveal voids for free.
- **What is still free cannot carry suit-by-suit information.** The bid card
  (random today) can only say something about the whole hand, or one bit
  about the black suits.

**RAMI passes them better.**

- **Following with a small card, when you cannot or need not win, is a truly
  free choice.** Following makes up about three plays in four in RAMI, and in
  RAMI the follower plays lowest 87.6% of the time (`handoff.md` §2.1). So the
  choice of *which* small card is usually open.
- **The partner's decisions are suit-by-suit and carry high stakes:** which
  suit to continue, where the entries are, when a long suit will run, and
  whether a steal (7 tricks, doubled points) is on.
- **No hand is visible, so both partnerships can use their own signals.**

**Bidding also passes (C4).** The locked bid is the decision with the most
leverage, and an agreed style is the only coordination available.

### 5.2 Reviewed and demoted: C1, C2 and C3

**C1 - The bid card shows your high cards. Demoted.**

The rule was: with four or more aces and picture cards, show your highest black
3-9; otherwise show your lowest. Here is what that could change in NOLO,
decision by decision.

- **Whether to help partner void** (C2). Feeding partner a discard pays only if
  partner has something to discard, and almost every hand does. Even after a
  "few high cards" show, **91% of partners still hold two or more aces or
  picture cards**. The signal only moves the expected count from 3.3 to 4.2 or
  2.6. That rarely changes the answer. What changes the answer is **your own
  cards**: whether you hold a low card in partner's suit that won't win, and
  what your own void would cost.
- **Following and discarding.** These are decisions about one suit, and a count
  over the whole hand doesn't say which suit.
- **Who should be on lead** ("I don't want to start next"). That depends on
  having exit cards in particular suits.
- **It goes stale fast.** By the middle of the deal, the play has shown far
  more.
- **The opponents get exactly the same information.**

**What use is left:** placing cards in RAMI, that is, who is likely to hold a
missing honour. Both sides get that use equally. **Verdict: not worth
teaching.** It stays on the test list only as a cheap check of this reasoning.

**C2 - The safer partner helps the more dangerous one. Folded back into the
table's rule.** Without C1, it *is* the table's rule. The owner's point holds:
the actual cards decide.

Here is the same decision as a rule of thumb based on your own cards. It is
strategy, not a convention: **lead partner's short suit back when you hold a
low card there that will not win the trick; otherwise lead your own shortest.**
It goes into experiment 7.2 as one way to define "a strong hand".

**C3 - One trick, two bad cards. Dropped.** The table already does it,
including the exception: you don't take over the trick when you don't want to
lead next.

### 5.3 The credible new candidates: RAMI signals

These are imported from whist, where no hand is visible either. They are new
only if the table doesn't use them yet (question 6 in section 8).

**R2 - Attitude.** *The main candidate.*

- **Rule.** When your partner has led and you are not winning the trick
  (partner's card is already winning, or you can't beat the current winner),
  play:
  - a **high small card** (6-8) if you want the suit continued, meaning you hold
    an honour (A, K or Q) or four or more cards in it;
  - **your lowest** if not.
- **The decision it changes:** your partner's choice to continue the suit or
  switch when they next lead. The cards alone don't settle this, because your
  partner cannot see whether you hold the king behind their ace, or length
  that will run.
- **Cost:** only the rare case where the signalling card could have won later.
  So signal only with cards that can never win.
- **Leak:** the other side reads it too. But they face the same blindness, so a
  pair that signals and reads gains against a pair that does neither.

**R4 - First discard: from a suit you don't want led.**

- You keep the guards and length in your good suits, which is also good play,
  so it costs nothing.
- **The decision it changes:** which suit your partner leads next.
- It works for the declaring pair too: a partner's discards tell the declarer
  where the partner's strength is *not*.

**R1 - Lead the top of touching honours:** the A from A-K, the K from K-Q, the
Q from Q-J.

- Free, since the choice cannot change the trick.
- **The decision it changes:** whether your partner overtakes, keeps a card
  back so the suit is not blocked, or returns the suit. They now know you hold
  the next card down.

**R5 - Return partner's suit.** When you gain the lead, return the suit your
partner led first, unless you have a clearly better one.

- This keeps the partnership working on one long suit.
- It is the RAMI mirror of the table's NOLO return.
- **Against it:** it too is partly decided by the cards (how many you hold in
  partner's suit). Today the bot's RAMI lead only looks at its own hand, so the
  two can be compared directly.

**R3 - Count** (high then low shows an even number) in the opponents' suits.
It tells you when their long suit will run out. It is harder to use at the
table, so it comes later.

### 5.4 C4 - Bidding by seat and by score (locked bids)

This is still the only way to coordinate the contract, since no card can signal
before the bid (section 0).

**B1 - Your bid counts only if every earlier seat passed. So bid as if they
all did.**

| Your seat | Your bid counts only if | So you may assume |
| --- | --- | --- |
| Forehand | always | nothing |
| Second | the forehand (opponent) passed | your right-hand opponent is below their RAMI threshold |
| Third | the forehand (partner) and second seat passed | your partner and your right-hand opponent are both below theirs |
| Fourth (dealer) | all three passed | your partner and both opponents are below theirs |

- **The agreed threshold is the message.** If the forehand declares on light
  hands, a forehand pass means "weak", and the third seat needs more to
  declare.
- The four thresholds have to be set together; their values are unmeasured.
- **Table form:** one number per seat, counted in aces and kings or in A/K/Q/J
  (appendix).

**B2 - A score plan the partnership shares, for bidding and for play.**

- **When the opponents are up:** your deal win only resets the score, so the
  margin does not matter. Bid on lighter hands. In play:
  - NOLO: six tricks is as good as none;
  - RAMI: seven is as good as thirteen;
  - defending a RAMI: go for the steal first. If it is out of reach, every
    trick you take cuts their gain.
- **When you are up and close to 52:** be stricter, and protect the lead.

The same hand is worth about 2.6 times more at either end of the score range
(`handoff.md` §2.5). Card-play-only score adjustments measured zero in an
earlier bot (`handoff.md` §3.5), so most of the value should come from bidding.

### 5.5 C5 - Sooli exchange (deferred until `project_target_v2` lands)

**The exchange is the only private channel in the game.** The RAMI pair sees
neither exchanged card (see `TuppiProject-sooli/docs/rules/project_target_v2.md`),
so a convention here leaks nothing.

- **X1 - The default.** The soolaaja gives away their most dangerous card. The
  partner returns their lowest card in ace-low order, an ace if they have one,
  and not in the suit they just received.
  - An ace can never win a trick for the soolaaja, who always plays last.
  - The give often empties a suit, and returning a card into that suit costs
    the soolaaja a discard.
- **X2 - Choosing between equally low cards: an untested idea.** Return in the
  suit where you hold the *fewest* cards, since the soolaaja is longer there.
  - Holding one card of a suit, the soolaaja averages 4.0 cards in it; holding
    seven, 2.0.
  - The void inference is weak: the soolaaja is void in a suit only 0.2-7% of
    the time, depending on your length.
  - Whether longer or shorter is the better place for a guard card is a
    question for the sooli solver.
- **Why deferred.** Several v2 rule details are still working assumptions
  (Q5 in `SOOLI_PLAN.md`). The sooli solver and heuristics are uncommitted work
  in `native/`. Nothing here should touch them.

### 5.6 Also considered and rejected

| Idea | Why not |
| --- | --- |
| Pass card as a RAMI support signal (the first version's S1) | Impossible with locked bids: the partner has already bid when it is revealed. |
| Bid card shows your high cards (C1) | See 5.2: whole-hand information, when NOLO decisions depend on individual suits. |
| Bid-card *suit* names your short suit | Only clubs or spades can be named, and a hand's shortest suit is red half the time. |
| Meaning in the RAMI declarer's red card | The defence sees it first and leads first. |
| Rank and suit both carrying meaning | Too much to apply at table speed, and the error rates add up. |
| Signals while following in NOLO | "Duck with the highest card that still loses" decides most follows, so there is almost no free choice to signal with. |
| Forehand leads their long suit to help a partner in danger | It feeds the opponents' voids just as much. |
| A "rescue me" high lead late in NOLO | A rescue needs a higher card in that suit plus a safe exit, which is rare. |
| Detailed sooli give codes | Sooli is about 4% of deals, which is too rare to justify extra memory load before measurement. |

**Supporting practice kept from earlier:**

- **N1 / N2:** the table's short-suit lead and return (section 4).
- **N3:** duck with your highest card that still loses. As an agreement it
  turns "no card between this one and the winning card" into a fact the
  partner can use (`TuppiProject/docs/nolo/behavioural_inference_hypotheses.md`).

## 6. Assessment

| ID | Convention | How often | Cost to follow | Opponents see it | Effort to learn | Evidence | Next step |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N1, N2 | Short-suit lead and return (in use) | Every NOLO deal | Depends on the variant | Yes (table-wide) | Already known | The bot's variant is measured; the table's is not | **Measure first** |
| **R2** | RAMI attitude | Most tricks where you follow partner's lead | About none | Yes | Low to medium | Standard in whist and bridge; unmeasured here | **Main new candidate** |
| **R4, R1** | RAMI first discard; top of touching honours | Often in RAMI | None | Yes | Low | As above | Try with R2 |
| R5 | Return partner's suit in RAMI | Often in RAMI | Sometimes | Yes | Low | None | Measure |
| C4 (B1, B2) | Bidding by seat; score plan | Every deal | None | Over time | Low: a few numbers | Seat and score matter | Measure; needs locked-bid rules |
| C5 (X1, X2) | Sooli exchange | About 4% of deals | None | **No** (private) | Low | None | After v2 |
| C1 | Bid card shows high cards | - | - | - | - | Demoted (5.2) | Optional check only |
| C2, C3 | Serve rule; one trick, two bad cards | - | - | - | - | Already table practice | - |
| R3 | RAMI count | Sometimes | None | Yes | Medium | None | Later |

**The recommendation is now RAMI, not NOLO.** For the reference bots RAMI is
78% of deals (`TuppiProject/docs/database/phase7_charter.md`). It is where free
choices meet real decisions that the cards alone don't settle. Try **R2 + R4 +
R1** first. In NOLO, the table's own system is the thing to measure and tune,
not to add to.

## 7. How to test (later; nothing here is scheduled)

The detailed, costed plan for 7.2 (NOLO) and 7.3 (RAMI signals) is in
[`LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md`](LOCKED_BIDS_AND_CONVENTION_TESTS_PLAN.md),
Parts B and C. Where the two differ, the plan wins.

**Constraint.** Sooli work is active in `native/`, `tuppi_ai/bridge.py`,
`tuppi_ai/native.py` and the `TuppiProject-sooli` worktree. Nothing below
should touch those until it lands. Human-versus-human games are not recorded,
so the owner's description in section 4 is the human baseline.

**7.1 The general design: four arms per convention, same deals, duplicate.**

| Arm | Setup | What the difference measures |
| --- | --- | --- |
| A | No convention | Baseline |
| B | One pair *follows* the convention; nobody reads it | B − A: the cost of following |
| C | As B, and that pair's partner reads it | C − B: the value to the partner, which is the short run with opponents unaware |
| D | As C, and the opponents read it too | D − C: the leak; D − A is the long run at a regular table |

- The search bot plays every decision the convention does not cover, on all
  four seats, standing in for competent players.
- "Reading" a convention means drawing only worlds consistent with it
  (rejection sampling). That is exact inference, so it is an upper bound on
  what a person gets.
- A noisy arm lets the signaller deviate, as strong players do, and has the
  reader down-weight worlds instead of rejecting them.

**7.2 First experiment: the table's NOLO system.** Use forced NOLO deals, since
the contract does not matter to the lead, as in `void_seeking_lead.md`.

| Variant | First early lead | Partner's first early lead |
| --- | --- | --- |
| V0 | The search bot decides (no convention) | Search |
| V1 | Shortest suit, lowest card | Own shortest suit (the bot-tested system) |
| V2 | Shortest suit, largest card | Return the suit with a strong hand, else own shortest (the table's system) |
| V2r | Shortest suit, largest card | Always return the suit |
| V3 | Shortest suit, lowest card | As V2 |
| V4 | As V2, but a very safe hand skips the convention | As V2 |

- "Strong" or "very safe" is swept over simple rules about your own cards:
  - **you hold a low card in partner's suit that will not win** (5.2's rule of
    thumb);
  - few A/K/Q/J;
  - a short suit of very low cards.
- Also cross each variant with the early-game cut-off: the first lead counts
  if it comes by trick 3, 5 (the table's rough figure) or 7.
- Endpoint: NOLO deal-win rate and tricks. Earlier lead studies needed 900 to
  1,200 deals to see a large effect (z ≈ 8). Differences between variants will
  be smaller, so plan on a few thousand deals.
- This needs no rules change: NOLO leads are the same in the sequential and
  the locked game.

**7.3 Second experiment: RAMI signals (R2, R4, R1), with the four arms of 7.1.**

- **Following the convention.** The signaller's choice of small card follows
  the rule. It only operates among cards the search values equally, so arm B
  should cost about zero. That is itself a check that the choice really is
  free.
- **Reading it.** The reader samples worlds consistent with the signal. For
  example, "encourage" means an honour (A, K or Q) or four or more cards in the
  suit.
- **Settings.** Use full RAMI deals at 0-0. Report results separately for the
  declaring pair and the defenders.

**7.4 Third: C4 seat thresholds.** This needs locked bids in the engine, or at
least in the native core used for measurement: hide earlier shows until
everyone has bid. It depends on the rules decision in section 0. Search one
threshold per seat under natural passes, at 0-0 first, then by score band.

**7.5 Optional: C1 as a check of 5.2.** 5.2's reasoning predicts that C1's
arm C gain is about zero in NOLO.

**7.6 Check that people can apply it.** Before trying anything at the table,
run a short quiz of positions. This fits the T2 training features in
`TASKS.md`.

**7.7 Table trials check comfort, not value.** Human samples are tiny: the
owner managed 21 benchmark deals, with a ±0.018 interval. The value estimate
has to come from the bot measurements.

## 8. The owner's answers (2026-09-23) and what is still open

**Answered:**

1. **Scope.** The short-suit lead applies to all players in the early game.
   There is no convention if your first lead comes at trick 9.
2. **The card.** Not always the lowest; more commonly the largest. There is no
   convention for which card.
3. **Singleton honours.** They are still led; it does not change the idea.
4. **Returning.** The partner leading the suit back is generally the idea.
5. **HCP.** Players do not count HCP, but they could be taught.
6. **Disclosure.** Rules are not announced.
7. **Records.** Human-versus-human games are not recorded.
8. **Strength and exceptions.** The system's strength is not verified. Top
   players sometimes skip it when it would cost unnecessary tricks,
   especially with very good NOLO cards.
9. **Locked bids.** Bid cards are locked before any other card is seen
   (section 0). The declaration is locked too, including the spoken
   counter-colour bid (*vastaväri*), which must be honoured. Cards after the
   first RAMI are never turned over.
10. **Return versus own shortest.** The partner decides. With a strong hand
    they may support the teammate by leading the teammate's suit; with a worse
    hand they lead their own shortest.
11. **"Early game".** Not fixed; roughly the first five tricks.
12. **"Very good NOLO cards".** Subjective. One example: a couple of short
    suits holding only very low cards.
13. **Bid cards today.** Chosen generally at random.
14. **Throwing on partner's tricks.** Players generally do throw a bad card
    onto a partner's trick, unless they have a reason not to, for example not
    wanting to lead next.
15. **The owner's critique.** C1's value in NOLO is unclear. C2 is how humans
    already play, and the value and shape of the cards direct play more than
    the convention does. This led to 5.1 and 5.2.
16. **Locked bids.** The project switches to locked bid cards (decided
    2026-09-23; see section 0).
17. **Answer 10, confirmed.** "Their best suit" means the teammate's short
    suit: a partner with a strong hand leads it back.

**Still open:**

1. **RAMI signals today.** Do players use any?
   - Which card do they lead from A-K?
   - Do they play high-low to encourage?
   - Do their discards mean anything?

   If they do, 5.3 is less new than it looks.
2. **Sooli.** Is there a traditional way people choose the give and the return?

## Appendix: how the new numbers were made

Random 13-card hands dealt from a shuffled 52-card deck, in plain Python with
no project code:

| Hands | Seed | Used for |
| ---: | --- | --- |
| 300,000 | 20260923 | Sections 2 and 4, and the withdrawn S1 |
| 200,000 | 7 | The aces-and-kings comparison |
| 300,000 | 20260924 | Short-suit card ranks and "safe" hands |
| 300,000 | 20260925 | Short suits of very low cards |
| 300,000 | 20260926 | C1's classes and the partnership mix |
| 200,000 | 20260927 | C1's review: 91% of low-show hands still hold 2+ A/K/Q/J |

- C5's void numbers are exact hypergeometric values, not simulation.
- HCP is counted A=4, K=3, Q=2, J=1.
- "Passer" means a hand with fewer than 12 HCP (the forehand's measured
  break-even), which is an approximation.
- Everything else is quoted from the files cited.

**C1's information count (demoted), kept for reference.** Rule: show your
highest black 3-9 with four or more A/K/Q/J, else your lowest.

- After a 7-9 show the hand has 4.2 such cards (9.2 HCP); after a 3-5 show,
  2.6 (6.4 HCP).
- The signal is right 84% of the time for high hands and 90% for low hands.

**Withdrawn S1's information count, kept for reference:**

| Rule | Mean HCP after a 7-9 show | Mean HCP after a 3-5 show |
| --- | ---: | ---: |
| Show highest with HCP 9+, else lowest | 9.7 | 6.0 |
| Same, with "two or more aces and kings" | 9.2 | 6.1 |
| Always show lowest | 8.3 | 7.5 |

<details><summary>Script (core of it)</summary>

```python
import random
DECK = [(s, r) for s in range(4) for r in range(2, 15)]   # s: 0,1 red; 2,3 black; A=14
HCP = {14: 4, 13: 3, 12: 2, 11: 1}
random.seed(20260926)
for _ in range(300_000):
    random.shuffle(DECK); h = DECK[:13]
    hcp = sum(HCP.get(r, 0) for _, r in h)
    if hcp >= 12: continue                                        # approximate passer
    black = sorted(r for s, r in h if s >= 2 and 3 <= r <= 9)     # bid-card choices
    if not black: continue
    high = sum(1 for _, r in h if r >= 11) >= 4                   # C1: four or more A/K/Q/J
    shown = black[-1] if high else black[0]
    # tally hcp and the A/K/Q/J count by shown class (7-9 / 6 / 3-5), and how
    # often the class read by the partner matches `high`
```
</details>
