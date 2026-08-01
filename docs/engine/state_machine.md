# Engine state machine

## Explicit phases

The engine records phase explicitly with `EnginePhase`; it does not infer phase
from nullable contract or score fields.

| Phase | Meaning | Current actor | Accepted operation |
| --- | --- | --- | --- |
| `AWAITING_DEAL` | Pristine match with no active deal. | None | Begin an explicit deal. |
| `SHOWING` | Ordered showing is unresolved. | Next showing seat | `ShowAction` only. |
| `TRICK_PLAY` | Contract is resolved and cards are being played. | Next seat in the current trick | `PlayCardAction` only. |
| `DEAL_COMPLETE` | Thirteen tricks finished; match remains nonterminal. | None | Begin the next explicit deal. |
| `MATCH_COMPLETE` | Thirteen tricks finished and a team has at least 52 points. | None | No transition. |

`AWAITING_DEAL` is a match-only phase. A `DealState` rejects that phase because
it always represents an active or completed deal.

The permitted phase graph is:

```text
AWAITING_DEAL ---- begin explicit deal ----> SHOWING
                                               |
                           NOLO, unresolved ---+
                                               |
                first RAMI or fourth NOLO      v
                                           TRICK_PLAY
                                               |
                           partial/next trick -+
                                               |
                           after trick 13       v
                                 +-------------+-------------+
                                 |                           |
                        nonterminal score              score >= 52
                                 v                           v
                         DEAL_COMPLETE                MATCH_COMPLETE
                                 |
                         begin next deal
                                 v
                              SHOWING
```

## Match and deal construction

`create_match` requires a nonterminal one-sided `MatchScore`, an explicit
dealer in seats 0 through 3, and a nonempty public `match_ref`. The pristine
match contains no cards or events. Public references use the schema-exact
`[A-Za-z0-9_.:-]` alphabet and are never derived from hidden cards.

`begin_explicit_deal` is allowed only from `AWAITING_DEAL` or
`DEAL_COMPLETE`. It requires an `ExplicitDeal` containing four ordered
13-card hands that partition the standard deck. The supplied dealer must equal
the match coordinator's dealer exactly.

The transition creates a private `DealState` with:

- phase `SHOWING`;
- current actor equal to the forehand;
- unchanged initial/current hands;
- no resolved contract or trick history;
- zero team tricks; and
- one `deal_started` public event.

The deal's first event index equals the length of the match event history, so
event indices remain contiguous across deal boundaries.

## Showing transitions

Only the current actor may submit an engine `ShowAction`. The action carries
the seat, shown card, and explicit declared contract. The engine validates it
against that seat's complete private 13-card hand through
`tuppi_rules.validate_show_action`. `verbal_required` is derived by the rules
package and recorded in the accepted public show; agents cannot provide it.

After an accepted NOLO that does not complete an all-NOLO sequence:

- phase remains `SHOWING`;
- current actor advances one seat clockwise;
- hands remain unchanged; and
- `show_accepted` is appended.

After the first RAMI declaration, or after the fourth NOLO declaration:

- showing resolves immediately;
- contract, declarer, and first leader are derived;
- phase becomes `TRICK_PLAY`;
- current actor becomes the first leader; and
- `show_accepted`, `contract_resolved`, and `trick_started` are appended in
  that order.

No action after the first RAMI can enter the showing history. The shown card
remains in its owner's hand and can later be played normally.

## Trick-play transitions

Only the current actor may submit a `PlayCardAction`. The engine validates that
the card is held and follows the led suit when possible. It then removes the
single card from that seat's ordered hand without reordering the remaining
cards and appends `card_played`.

For positions one through three in a trick, phase remains `TRICK_PLAY` and the
actor advances clockwise. On the fourth card:

1. the four-card trick is validated;
2. the highest led-suit card determines the winner;
3. an immutable `CompletedTrick` is appended;
4. the winner's team trick total increases;
5. `trick_completed` is appended; and
6. if fewer than 13 tricks are complete, the winner becomes the next leader
   and `trick_started` is appended.

There is no early completion after seven tricks or after a score outcome has
become mathematically certain. A deal remains in `TRICK_PLAY` until the
thirteenth four-card trick has completed. A fourteenth trick is impossible
because completion clears `current_actor` and leaves the action-accepting
phases.

## Deal completion and scoring

After trick 13, the engine first asks `tuppi_rules.validate_completed_deal` to
revalidate all 52 plays, leader chaining, card uniqueness, and follow-suit
behavior. It then:

1. derives NOLO or RAMI scoring from team trick totals;
2. classifies the outcome as `NOLO`, `MADE_RAMI`, or `STOLEN_RAMI`;
3. applies the rising-score transition;
4. appends `deal_completed` and `match_score_changed`; and
5. chooses exactly one terminal branch.

If the resulting score is below 52, the dealer rotates clockwise,
`dealer_rotated` is appended, and phase becomes `DEAL_COMPLETE`. If the score
is 52 or greater, no dealer rotation is performed, `match_completed` is
appended, and phase becomes `MATCH_COMPLETE`.

Scoring is therefore never applied to a partial deal, and a down-team win that
resets the up team still occurs only after all 13 tricks.

## Match progression

When an active deal completes, `MatchState` records a research-private result,
updates its score, and either stores the next dealer or becomes terminal. A
subsequent `begin_explicit_deal` checks the next explicit dealer rather than
normalizing it.

The completed-deal sequence is revalidated for continuity:

- deal numbers are contiguous from zero;
- the first result agrees with the initial score and dealer;
- every later score-before equals the preceding score-after;
- every later dealer equals the preceding next dealer; and
- no result follows a terminal result.

An explicit input sequence may end after a nonterminal deal. The CLI option
`--require-complete-match` changes that finite successful run into an error
unless the supplied sequence reaches at least 52. An explicit deal appearing
after match completion is always rejected.

## Strict action rejection

`apply_action` and `apply_match_action` never search for a replacement action.
They report typed errors:

- `WrongActorError` for an action from a seat other than `current_actor`;
- `WrongPhaseError` for play before showing, showing after resolution, or a
  transition without an active deal;
- `TerminalStateError` for a direct action or coordinator transition after
  completion;
- `InvalidActionError` for malformed or illegal show/play semantics;
- `DealSequenceError` for a mismatched explicit dealer, and from the finite
  runner when its supplied sequence contains a deal after match completion;
  and
- `StateInvariantError` if a supposedly internal state is inconsistent.

State validation occurs before public transitions, and frozen dataclass
construction validates the resulting state again. Invalid inputs are neither
clamped nor silently converted.

## Defensive invariants

The state validator reconstructs current hands by replaying accepted public
plays from the original hands. It checks that:

- no card is played twice;
- current hands exactly equal the replay result;
- every play was legal at its historical point;
- showing is the clockwise forehand prefix;
- stored show actions reproduce the authoritative verbal flag;
- trick indices and leaders are contiguous;
- each winner leads the next trick;
- team totals equal the counted trick winners;
- phase-specific nullable and terminal fields are consistent;
- ending score reproduces the authoritative rising-score transition;
- event indices are contiguous; and
- each event carries the active match and deal public references; and
- the complete typed event sequence exactly reconstructs from accepted shows,
  tricks, scores, and dealer/terminal state.

These checks favor correctness and fault detection over premature transition
performance optimization.
