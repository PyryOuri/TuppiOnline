# `project_target_v3`: project Tuppi rules with sooli and locked bids

## Status and provenance

| Field | Value |
| --- | --- |
| Base ruleset | `project_target_v2` (v1 plus sooli), unchanged except as stated here |
| Addition | **locked bids**: the bid cards are chosen blind, as in the real game |
| Source type | Project-owner decision |
| Decision date | 2026-09-23 |
| Status | Authoritative for this project; the ruleset of the real game |

`project_target_v3` is `project_target_v2` with locked bids. Every rule of
`project_target_v2` (and through it `project_target_v1`) applies unchanged:
which cards may be shown for which declaration, the fallbacks, the contract
resolution, trick play, sooli and scoring. Only **what a player may see while
bidding** changes. `project_target_v1` and `project_target_v2` are not
modified and remain separate rulesets.

The machine-readable companion is `configs/rules/project_target_v3.json`.

## Locked bids

A **bid** is exactly a show of `project_target_v1`: one card from one's own
hand together with a declaration, NOLO or RAMI, with the same card
eligibility, colour rule and verbal fallbacks (including the spoken
counter-colour bid, *vastaväri*, which must be honoured).

1. **All four players choose their bid without seeing anyone else's.**
2. **The bids are revealed in seat order, starting from the forehand**
   (the player clockwise after the dealer).
3. **The first RAMI in that order declares**: its bidder is the declarer, as
   in `project_target_v1`. If all four bid NOLO, the contract is NOLO.
4. **Bids after the first RAMI are never revealed** and have no effect.

Sooli follows exactly as in `project_target_v2`: after a RAMI the defenders
are asked in seat order.

### Worked examples

* The forehand bids RAMI: the forehand is the declarer; the other three bids
  are never seen.
* The forehand and the next seat bid NOLO and the third seat bids RAMI: the
  first three bids are revealed, the third seat declares, the fourth bid is
  never seen.
* All four bid NOLO: all four bids are revealed and NOLO is played.

## What each player knows

* **While bidding:** only one's own hand, the score, the dealer, and which
  seats have already locked a bid. Not a single card or declaration of anyone
  else's, and not whether anyone has declared RAMI.
* **When showing resolves:** the revealed bids, in order (exactly as the
  shows of `project_target_v1`), and the contract.

## Reference collection (implementation note)

The reference engine keeps taking bids one seat at a time in seat order and
stops at the first RAMI, but a seat choosing its bid sees no other bid.
Because a bid after the first RAMI never takes effect, this gives the same
outcomes and the same information as all four locking at once; being asked
tells a seat only that the earlier bids were NOLO, which is the one case in
which its bid matters. In the public event log each bid appears as
`bid_locked` (the seat only); at resolution the bids taken are revealed as
`show_accepted` events, in order, before `contract_resolved`.

The live server collects the human players' bids simultaneously: every human
locks a bid while seeing nothing of the others; the bids are then applied in
seat order; locked bids after the first RAMI are discarded unseen and are
never stored.

## Ruleset versioning

As for `project_target_v1`: this ruleset is immutable once used for recorded
experiments; any behavioural change needs a new identifier.
