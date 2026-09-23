# Sooli: rules analysis and implementation plan

Status: **plan only, nothing implemented.** Rules as given by the owner on
2026-09-24; Q1-Q4 answered the same day (section 2). Q5 items are working
assumptions until the owner corrects them.

## 1. The rules, and what they imply

Given (owner's text, condensed): after RAMI is declared, one defender (the
*soolaaja*) may choose to play alone against the two RAMI players. Soolaaja and
partner exchange exactly one card, hidden from the opponents; the partner then
takes no further part. Three players play: the RAMI side leads, both RAMI
players play before the soolaaja in every trick, so the soolaaja is always
last. Ace is low. Follow suit if able. The soolaaja must take no trick: the
deal ends at once if they take one (RAMI pair +24); if they take none in all
13 tricks the sooli pair gets +24.

What follows from that:

* **Seats.** Declarer D and partner D+2 are the RAMI pair. The soolaaja S is
  D+1 or D+3; the partner P = S+2 sits out. P's 13 cards (after the exchange)
  are **dead**: out of play for the whole deal, hidden from everyone but P.
* **39 cards in play, 3 per trick.** Play order within a trick is *not*
  clockwise when S sits between the RAMI players: it is leader (RAMI), other
  RAMI player, then S.
* **Every completed trick is won by a RAMI player** (otherwise the deal
  ended), so the RAMI side does lead every trick; the trick winner leads next.
* **When S can lose a trick.** Only when following suit with every remaining
  card of that suit above the highest card already played to the trick. A void
  S discards safely (off-suit cards never win). Seeing both RAMI cards first,
  S ducks with the highest card that still loses, keeping low cards as exits.
* **Ace low inverts the weapons.** The ace is the safest card, the king the
  most dangerous. The RAMI pair's *low* cards (A, 2, 3...) are the attacking
  resource: lead a suit where S may hold only high cards and play under them.
  A declarer's high-card RAMI hand is often a poor sooli attacker, which is
  why sooli can pay.
* **The exchange** lets S shed its most dangerous card and take in, ideally, a
  low one; the partner does not see S's hand when choosing what to give.
* **Information.** RAMI players see neither S's hand nor the dead hand: 26
  unseen cards split 13/13 between a live hand and a dead one. Shown cards are
  public, but after the exchange a shown card of S or P may have moved to the
  other, so "shown card is in S's hand" weakens to "in S's hand or dead".
  S knows its own hand, the card it gave (so one dead card), the card it
  received, and P's shown card.
* **Stakes.** 24 points either way. From 0-0 that is a match-equity swing of
  roughly +-0.12 per deal, so the call is worth making when success is likely
  enough to beat the value of an ordinary defence (defending a RAMI is on
  average a losing deal for the defenders). Rough break-even: success
  probability around 45%, strongly dependent on the score (a sooli win when
  up at 28+ ends the match; a loss when the opponents are up 28+ ends it for
  them).
* **Frequency.** Humans play it about once per 20 RAMI deals (~4% of all
  deals). Small share, high stakes: a good or bad sooli policy is worth
  perhaps a few thousandths of equity per deal overall, comparable to the
  refinements tried on the main bot.

## 2. Rule decisions

Answered by the owner on 2026-09-24:

* **Q1 - Calling.** Either defender, asked in seat order; the first to accept
  plays sooli. Assumed order: the defender clockwise after the declarer is
  asked first, then the other (*to confirm*). The second defender decides
  knowing the first declined.
* **Q2 - Exchange.** **The soolaaja gives first**; the partner sees that card,
  then gives one back. So the soolaaja chooses without knowing the return,
  and the partner chooses knowing one card the soolaaja wanted rid of.
* **Q3 - First lead.** **The declarer** leads trick 1; afterwards the trick
  winner leads (always a RAMI player).
* **Q4 - Scoring.** **Like any deal win** under the rising score: the winner
  adds 24 if up or at 0-0; a down team's win only resets the score to 0-0.

Working assumptions (Q5, to be corrected if wrong): ace low means
A < 2 < ... < K, in sooli only; sooli exists only after a RAMI declaration;
the dealer rotates as usual; the RAMI side has no counter-move; the dead hand
is not revealed during play; a shown card may be exchanged.

What the answers mean for the bot:

* The soolaaja's give is a pure risk decision (shed the most dangerous card,
  e.g. a king or a high card without a low companion), made without knowing
  the return.
* The partner's return is informed: it knows one card the soolaaja wanted
  gone, which says something about the soolaaja's hand. It should return a low
  card (the ace is safest) that does not create a new danger.
* Because the declarer leads first and trick winners lead after, the
  attackers' lead order is fixed by who wins; the second attacker always sees
  the lead before playing.
* A sooli win by the down team is worth a reset, not 24 points, so calling
  sooli when down is judged against defence as a way of winning the deal, and
  a sooli loss hands the RAMI pair 24.

## 3. Implementation plan

Each phase ends with tests; nothing merges into another author's files
without coordination.

### Phase A - specification

A new ruleset identifier, e.g. `project_target_v2` = v1 + sooli, as
TuppiProject's versioning policy requires for any change to legal actions,
contract resolution, deal completion or scoring. English and Finnish spec,
decision table, machine-readable config, worked examples. `project_target_v1`
stays unchanged, so every existing result keeps its meaning.

### Phase B - reference implementation (TuppiProject, own branch)

On a separate `git worktree` branch so the dirty main worktree is untouched.
* `tuppi_rules`: sooli call validity, exchange validation, three-player trick
  order, ace-low trick winner, early end, 24-point scoring, match transition.
* `tuppi_engine`: new explicit phases (e.g. `SOOLI_DECISION`,
  `SOOLI_EXCHANGE`, `SOOLI_PLAY`), new actions (call/pass, exchange card),
  private observation fields (the card you gave or received), public events
  (sooli called; an exchange happened, without card identities), serialization
  and schemas.
* The existing agents need a sooli behaviour under v2 (the incumbent has
  none): never call, give the lowest card, and a simple sooli card-play
  heuristic, so that bot-vs-bot evaluation includes sooli at all.
* Normative tests and examples, in the style of the v1 rules tests.

### Phase C - native core (TuppiAI)

Ruleset flag in the C deal state; sooli phases and action ids; three-player
trick logic, ace-low comparison, early termination, scoring; observation and
encoder support (sooli flag, roles, exchange knowledge). Differential tests
against the Phase B reference, step by step, as for v1.

### Phase D - the sooli bot

1. **Perfect-information sooli solver (C).** Sooli is a yes/no game (can the
   RAMI pair force one trick?) with the soolaaja always last, so strong
   pruning should make even full 13-trick positions cheap. Tested against
   brute force on small positions. Used as the play-out evaluator.
2. **Sooli heuristics (C).** Soolaaja: duck with the highest losing card,
   discard the most dangerous card when void. Attackers: lead suits where the
   soolaaja is most likely to be forced, play under. Exchange: give the lowest
   spare card; return the most dangerous card. Serves as rollout policy,
   baseline, and the incumbent's sooli behaviour.
3. **Sooli-aware world sampling.** The dead hand as a 13-card holding that
   never plays; shown cards of S and P may have moved in the exchange; S's
   own knowledge of one dead card.
4. **Search for every sooli decision** (soolaaja play, attacker play, both
   exchange choices): the same sample-worlds-and-evaluate method as the main
   bot, comparing two evaluators by measurement: heuristic play-outs versus
   exact solving per world (exact solving lets the attackers "see" the
   soolaaja's hand, so it is pessimistic for the soolaaja; play-outs may be
   optimistic; the better one is whichever wins more in duplicate tests).
5. **The call.** For the defender deciding: estimate sooli success
   probability by sampling worlds, simulating the exchange, and evaluating;
   estimate the value of ordinary defence with the existing search; call when
   the match-equity value of sooli is higher. Score-aware by construction.
6. **Declaring RAMI with sooli in mind.** The showing search's play-outs let
   defenders call sooli by the same rule, so RAMI declarations price the risk.
7. **Evaluation.**
   - Forced-sooli duplicate bank: deals with a sooli called, each role (S,
     attackers) played by the candidate and by the baseline on the same cards.
   - Full-game duplicate with sooli enabled, against the incumbent plus its
     sooli heuristic.
   - Call frequency and success rate, sanity-checked against the human rate
     (~1 in 20 RAMI deals). The bot's best rate may differ; it is a check, not
     a target.
   - Latency per decision.
8. Optional, only if search is not enough: learning on sooli-only positions
   in the native engine (short episodes, yes/no outcome, a far cleaner signal
   than full Tuppi).
9. Re-fit the match-equity table once sooli outcomes enter the deal
   distribution.

### Phase E - server, protocol, client

New actions and events in the protocol; UI for the sooli prompt, the exchange,
three-card tricks with the partner sitting out, and replays and analysis of
sooli deals. Overlaps with T1; the server files involved carry another
author's uncommitted work.

### Phase F - training features

Sooli in the T2 training features (call advice, exchange advice, play review).

## 4. Risks

* Rule details decided wrongly would ripple through every layer: the Q5
  assumptions and the seat order in Q1 should be confirmed before Phase B.
* No human sooli data: the bot's opponent model for human soolaajas and
  attackers is a guess; only the owner's games can check it.
* Client UI work is the largest single chunk and depends on T1 decisions.
* Coordination with the other author's in-flight TuppiProject changes.
