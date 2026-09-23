# `project_target_v2`: project Tuppi rules with the sooli subgame

## Status and provenance

| Field | Value |
| --- | --- |
| Base ruleset | `project_target_v1`, unchanged except as stated here |
| Addition | the **sooli** subgame |
| Source type | Project-owner specification |
| Specification date | 2026-09-24 |
| Status | Authoritative for this project |

`project_target_v2` is `project_target_v1` plus sooli. Every rule of
`project_target_v1` (players, deck, dealer, showing, contract resolution, RAMI
and NOLO trick play and scoring, the rising-score match) applies unchanged
unless a sooli is played. `project_target_v1` itself is not modified: results
recorded under it keep their meaning, and it remains a separate ruleset.

The machine-readable companion is `configs/rules/project_target_v2.json`; the
executable reference is `tuppi_rules.sooli` together with the v1 modules.

## Definitions

- **Soolaaja**: the defender who plays sooli, alone against the two RAMI
  players.
- **Sooli partner**: the soolaaja's partner. After the card exchange this
  player takes no further part in the deal; their hand is **dead**.
- **RAMI pair**: the declarer and the declarer's partner.

## When sooli can be played

Sooli exists only in a RAMI deal. After the first RAMI declaration ends
showing, and before any card is played, the two defenders are asked in seat
order whether to play sooli:

1. first the defender clockwise after the declarer, `(declarer + 1) mod 4`;
2. then, if the first declines, the other defender, `(declarer + 3) mod 4`.

The first defender to accept becomes the soolaaja; no further defender is
asked. If both decline, the deal continues as an ordinary RAMI deal under
`project_target_v1` (first leader `(declarer - 1) mod 4`, 13 tricks of four
cards, RAMI scoring). NOLO deals have no sooli.

Each answer is public. The RAMI pair has no counter-move.

## Card exchange

1. The soolaaja gives exactly one card from their hand to the sooli partner.
2. The sooli partner, having seen that card, gives exactly one card back.
   It must not be the card just received.

Exchanged cards are not shown to the RAMI pair: they learn only that the
exchange took place. The soolaaja and the partner each know both exchanged
cards. A card shown during showing may be exchanged. After the exchange the
sooli partner's 13 cards are out of play for the rest of the deal and are not
revealed during play.

## Sooli trick play

Three players are active: the soolaaja and the RAMI pair.

- **Card order: ace is low.** Within a suit, ranks from low to high are
  A, 2, 3, ..., 10, J, Q, K. This order applies only in sooli trick play; it
  does not change showing.
- **Following suit.** The leader may play any held card. Each other player must
  follow the led suit if able; a player void in it may play any held card.
  Off-suit cards cannot win.
- **Order of play.** The **declarer leads the first trick**. In every trick the
  leader plays first, the other RAMI player second, and the soolaaja last. The
  winner of a trick leads the next. (Every trick that does not end the deal is
  won by a RAMI player, so the leader is always a RAMI player.)
- **Trick winner.** The highest card of the led suit, in ace-low order.

## End and scoring

- If the soolaaja wins a trick, the deal **ends immediately**. The RAMI pair
  wins the deal and scores **24 points**.
- If the soolaaja completes all 13 tricks without winning one, the soolaaja's
  team wins the deal and scores **24 points**.

The 24 points enter the rising-score match exactly like any other deal win:
from 0-0 the winner becomes up with 24; the up team adds 24 when it wins; when
the down team wins, the up score is erased and no points are awarded. The
match ends when the up team reaches 52 or more. The dealer then rotates as
after any completed, nonterminal deal.

Implementation summary:

```text
sooli_success = soolaaja_tricks == 0 after 13 tricks
sooli_failure = soolaaja wins any trick (deal ends at that trick)
deal points   = 24 to the winning side
```

## Invalid states and edge cases

- Sooli decisions only in a RAMI deal, only by the defenders, only in the
  stated order, and only before the first card is played.
- At most one soolaaja per deal.
- The exchange happens exactly once, soolaaja first, and the partner may not
  return the received card.
- A sooli deal has 3 cards per trick, 1 to 13 tricks, and the dead hand never
  plays.
- Invalid actions are rejected with a typed error and never substituted, as in
  `project_target_v1`.

## Ruleset versioning

As for `project_target_v1`: this ruleset is immutable once used for recorded
experiments; any behavioural change needs a new identifier.
