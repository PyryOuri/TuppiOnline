# UI-H2 — Real post-deal and post-match diagnostics

UI-H2 is a completed-*deal* diagnostic pipeline. It runs only over deals that
have finished, never over a deal in progress, and cannot affect an accepted
action: no live WebSocket message carries analysis, and the generator is a
read-only replay of the durable match record.

Between-deal review is open to every participant of any room (see "Between-deal
review"). Whole-match review still waits for the terminal result.

## Authoritative contract

The live endpoint returns `tuppi.analysis.post_match.v3`. The versioned union
schema is `schemas/network/post_match_analysis.schema.json`; the strict v3
shape is `schemas/network/post_match_diagnostics_v3.schema.json`. Legacy
`tuppi.analysis.post_match.v1` and `.v2` remain schema-valid so old deterministic
fixture replays and already-archived client history keep decoding. While the
overall transport is still `tuppi.network.v1`, the Swift live-session boundary
also accepts v2 from an older paired server; it does not accept v1 live or any
unknown future version.
The per-deal envelope is `tuppi.analysis.completed_deal.v3`
(`schemas/network/completed_deal_analysis_v3.schema.json`). It extends the v2
diagnostic envelope with the exact played deal, original hands, four-bot replay,
and comparison. Its versioned union retains v1 and v2 for archived-history and
fixture compatibility.

```text
POST /v1/rooms/{room_code}/analysis
{"session_token":"..."}
```

The whole-match endpoint authenticates the room participant, requires a terminal
runner, and generates a response only for that participant's seat. The per-deal
endpoint requires only that the requested deal is *complete*: it is open to every
participant of any room between deals, and is documented under "Between-deal
review" below. It returns a public
match summary and zero to ten ranked decision items. Every item is bound to the
accepted `show_accepted` or `card_played` public event and contains the actual
action, suggested action, historical legal actions, contract/role/trick/score
context, deterministic explanation text, and an explicit evidence label.

## Review fields (v3)

v3 adds three fields that v2 deliberately withheld. They exist so a player can
see *how far* a decision was from the reference policy rather than only that it
differed. All three describe the analysed seat's own decision over its own legal
actions, so they disclose nothing the player did not already hold.

- `summary.reference_agreement` — aggregate statistics over **every**
  reconstructed decision for that seat, not only the ten returned items:
  decision and match counts overall and split by showing/trick play, the
  rank-1/rank-2/lower distribution, the mean played rank, the mean legal-action
  count, and `indifferent_count`. Because the reference's own pick is always
  rank one, `match_count` equals `top_rank_count`; the validator enforces it.
  `forced_decision_count` records decisions with exactly one legal action.
  Those agree by construction — roughly a quarter of trick-play decisions are
  forced — so the raw share would flatter any player. The validator requires
  `forced_decision_count <= match_count`, and the client shows an "aidot
  valinnat" figure that removes them from both sides of the ratio.
- `reference_ranking` (per item) — `played_rank`, `legal_action_count`,
  `strictly_better_count`, the reference's own `reference_action`, and
  `reference_indifferent`. The three states are mutually exclusive: the played
  action *is* the reference pick (rank 1, none better); it tied with the pick and
  only the documented engine-index tie-break separated them
  (`reference_indifferent`); or at least one action scored strictly higher.
  An indifferent decision is ranked *below* a measured disagreement when the ten
  items are selected, and carries `reason_code`
  `reference_policy_tie_break`.
- `contract_reasoning` (showing items only; null on trick play) — the reference
  policy's showing scalars from `tuppi_agents.showing_scalars`, its own
  `reference_contract`, and `verdict_notes`. For `partner_aware_v1`
  (`simple_show_v1`) the scalars are `simple_rami_score`, `simple_nolo_score`,
  `simple_rami_threshold`, and `simple_nolo_veto_threshold`: RAMI is declared iff
  the score clears the threshold *and* the NOLO score does not trip the veto, so
  the two comparisons are the whole explanation.

This is a deliberate widening of the client boundary. It stays narrow in three
ways: every field is constructed by `post_match_diagnostics.py` rather than
forwarded from a `DecisionDiagnostics` mapping; `verdict_notes` is filtered to
the closed `VERDICT_NOTES` set, so a new internal reason code cannot reach a
client until somebody adds it there; and the `_CLIENT_PRIVATE_KEYS` guard is
unchanged, so a raw diagnostics dictionary still fails closed. Raw observations,
private hands, observation digests, search trees, belief particles, and training
diagnostics remain unserialized.

## Historical reconstruction

`src/tuppi_server/post_match_diagnostics.py` replays the durable explicit deals
and accepted actions from the initial match state. Immediately before each
local-seat action it creates the canonical formal `PlayerObservation`. This is
the only input sent to `partner_aware_v1`; the reference policy never receives
the final deal, opponent hands, or a reconstructed omniscient observation.

During play, the complete deal remains available only to server-side engine and
diagnostic code. After formal completion, completed-deal v3 may reveal the now
public four hands and both canonical result transcripts. The response is still
seat-scoped for diagnostics/comparison and is validated against the
authoritative public event log and retained shuffle. Raw observations,
observation digests, raw score vectors, rule-feature contribution mappings,
search trees, belief particles, and training diagnostics are not serialized.
The purpose-built review fields are the only derived policy numbers that cross
the boundary.

## Evidence sources

- `Exact` / `perfect_information_exact`: the frozen Phase 5B solver compares
  legal plays when at most four tricks remain. A diagnostic is emitted only
  for a positive exact trick-value loss. The payload records chosen value,
  best value, difference, and tied optimal cards. It is labelled explicitly as
  a perfect-information late-game result.
- `Rule-based` / `objective_rule_pattern`: conservative deterministic findings
  currently cover a cheaper legal card that wins the same realised trick and
  overtaking a currently winning partner when a legal card would leave the
  partner ahead. Explanations state their counterfactual limit.
- `Reference` / `reference_policy_only`: `partner_aware_v1` is queried with the
  historical formal observation. Disagreement is a comparison, never proof of
  an error or mathematical optimality.

PIMC, root UCT, multi-observer ISMCTS, and behavioural-belief particles are not
imported or used as coaching authorities.

## Between-deal review

`POST /v1/rooms/{room_code}/deals/{deal_number}/analysis` returns the per-deal
envelope for any authenticated participant as soon as that deal is complete. It
no longer waits for 52 and is no longer restricted to a one-human/three-bot
practice room.

Disclosure is safe because the deal is over. All 52 cards have been played, and
the next deal is an independent shuffle, so revealing the completed deal's four
original hands cannot expose current or future hidden play. A deal still in
progress stays closed (`deal_not_complete`), and the whole-match endpoint still
requires a terminal runner (`match_not_complete`). No WebSocket projection or
active-deal HTTP response contains `initial_hands` or `bot_replay`.

The response remains authenticated and seat-scoped for diagnostics and
comparison. Every participant may request a finished deal; all see the same bot
transcript, while signed points and differences use that participant's original
partnership. `analysis_locked_until_match_complete` is retired from this path;
the Swift client still maps the code so an older server produces a clear
message.

The client archives each completed deal immediately. `Analysoi jako` opens a
separate value-keyed macOS window and fetches v3 on demand. The main table stays
mounted and connected, and play may continue independently. The full response
is persisted with that deal, so closing and reopening the analysis window does
not require another server request.

## Same-shuffle bot replay

`src/tuppi_server/completed_deal_review.py` starts from the authoritative
`ResearchDealResult` already retained by the live runner. It creates an
`ExplicitDeal` with the same `deal_id`, four hands, dealer, match/deal identity,
event offset, and pre-deal score. `create_deal_state` derives the same forehand
under the production rules.

Four fresh `partner_aware_v1` agents, one for each seat, then receive only their
normal formal observations. They independently choose every showing action and
every card play; the human contract and transcript are not forced. A RAMI show
therefore stops showing normally, while four NOLO choices reach play normally.
Every action passes through `apply_action`, and the terminal result comes from
`deal_result_from_state`, so NOLO, successful RAMI, and stolen-RAMI scoring are
the production engine's scoring.

The policy is deterministic, so v3 reports `analysis_seed: null`. It returns:

- `actual_result`: the canonical played `DealResult`;
- `bot_replay`: the canonical independently generated `DealResult`;
- `initial_hands`: the authoritative four 13-card hands;
- `bot_policy`: profile, policy identity, determinism, seed, and all four seats;
- `comparison`: local-team tricks, signed deal points, local match score, score
  margin, and each bot-minus-actual difference.

The interpretation is deliberately limited: these are the points current Tuppi
bots scored from the same deal, not an optimal or uniquely correct line.

Exact findings rank first, then objective tactical findings, important showing
comparisons, and remaining reference disagreements. At most one diagnostic is
returned for one historical decision, and the response is capped at ten rather
than returning every disagreement.

## Persistence and restart

The generator is deterministic from the restart-safe private match record.
After first generation, the server writes a separate atomic cache entry for the
room/deal/seat. Its metadata binds the completed-deal schema and content-derived
bot policy identity; changing either invalidates the entry. A cache hit replays
the stored actions through the production engine and checks it against the
authoritative shuffle, without invoking the bot policy again. The Swift archive
keeps the same full v3 payload for offline reopening on that Mac.

Historical filtered v1/v2 analysis artifacts remain decodable for compatibility,
but a real `LiveMatchRunner` returns v3. Raw solver or AI-internal diagnostics
are not persisted.

## Swift behavior

After each canonical completed deal is archived, the live table offers
`Analysoi jako`. The button does not exist before any deal has completed and it
never targets the active deal. It opens a separate `WindowGroup` keyed by
`deal_ref`, rather than replacing the table route.

The existing terminal `Analysoi peli` action remains available for whole-match
diagnostics; it is distinct from the per-deal bot comparison.

The window shows human and bot summaries side by side, explicitly signed
bot-minus-human trick, deal-point, local match-score, and score-margin
differences, plus the benchmark disclaimer. A segmented control switches between
`Oma peli` and `Bottien peli` while preserving the nearest whole-trick stage.
Beginning, previous, next, end, and slider controls navigate the 13 tricks. All
four post-deal hands are visible. Diagnostics apply only to the human transcript;
selecting one switches to `Oma peli` and jumps to its trick. Exact, Rule-based,
and Reference source/confidence labels stay visible.

Older archived responses stay readable: the review fields are optional in the
Swift DTOs, so a v1 or v2 entry decodes with them absent and simply shows no
agreement panel.

Room/session credentials remain memory-only. Server-process restart recovery
works while the client remains open; client-process restart recovery and
Keychain storage remain deferred to physical private-alpha hardening.

## Verification boundary

Automated Python tests cover historical state/observation reconstruction,
exact output, reference replay/ranking, the same authoritative cards/dealer/
forehand/pre-score, four independent bot seats, showing termination, all three
production scoring outcomes, partnership-relative differences, strict schemas,
determinism, cache reuse/invalidation, and the live hidden-state boundary.
Swift tests cover v3 decoding and validation, v1/v2 archive compatibility,
human/bot summary arithmetic, point/trick separation, separate-window routing,
completed-only availability, persisted reopening, both replays, shared
whole-trick navigation, diagnostics jumps, and loading/error/empty states. The
opt-in localhost test completes a real match and validates the same v3 boundary
used by `Analysoi jako`.

Physical two-Mac/LAN, firewall, signing, notarization, and real-player quality
review are separate acceptance gates.
