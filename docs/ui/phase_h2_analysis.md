# UI-H2 — Real post-match diagnostics

UI-H2 is a completed-match-only diagnostic pipeline. It never runs during an
active competitive game and cannot affect an accepted action.

## Authoritative contract

The live endpoint returns `tuppi.analysis.post_match.v2`. The versioned union
schema is `schemas/network/post_match_analysis.schema.json`; the strict v2
shape is `schemas/network/post_match_diagnostics_v2.schema.json`. Legacy
`tuppi.analysis.post_match.v1` remains schema-valid only so old deterministic
fixture replays keep decoding.

```text
POST /v1/rooms/{room_code}/analysis
{"session_token":"..."}
```

The endpoint authenticates the room participant, requires a terminal runner,
and generates a response only for that participant's seat. It returns a public
match summary and zero to ten ranked decision items. Every item is bound to the
accepted `show_accepted` or `card_played` public event and contains the actual
action, suggested action, historical legal actions, contract/role/trick/score
context, deterministic explanation text, and an explicit evidence label.

## Historical reconstruction

`src/tuppi_server/post_match_diagnostics.py` replays the durable explicit deals
and accepted actions from the initial match state. Immediately before each
local-seat action it creates the canonical formal `PlayerObservation`. This is
the only input sent to `partner_aware_v1`; the reference policy never receives
the final deal, opponent hands, or a reconstructed omniscient observation.

The complete finished deal is available only to the server-side post-match
exact and deterministic rule checks. The generated client response is
seat-scoped and is validated again against the authoritative public event log.
Raw observations, private hands, search trees, score vectors, rule-feature
contributions, belief particles, and training diagnostics are not serialized.

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

Exact findings rank first, then objective tactical findings, important showing
comparisons, and remaining reference disagreements. At most one diagnostic is
returned for one historical decision, and the response is capped at ten rather
than returning every disagreement.

## Persistence and restart

The generator is deterministic from the restart-safe private match record, so
it can regenerate the same seat-scoped response after server restart while the
client retains its room/session credential. Raw solver or AI diagnostics are
not persisted. Historical filtered v1 analysis artifacts are still validated
on load for compatibility and tamper detection, but a real `LiveMatchRunner`
uses the v2 generator.

## Swift behavior

The normal result screen appears first and offers `Analysoi peli`. The Swift
client fetches v2 through its production HTTP client, verifies match and seat
identity, stores the filtered response with local public match history, and
opens replay. Choosing an item jumps to its exact public event and highlights
the played card and suggested alternative. Exact, rule-based, and reference
labels remain visible. Replay remains available for empty or failed analysis.

Room/session credentials remain memory-only. Server-process restart recovery
works while the client remains open; client-process restart recovery and
Keychain storage remain deferred to physical private-alpha hardening.

## Verification boundary

Automated Python tests cover historical state/observation reconstruction,
exact output, reference replay, ranking, strict schemas, seat scoping, public
event binding, empty responses, restart material, and terminal-only exposure.
Swift tests cover production DTO decoding, loading/error/empty state,
source labels, replay navigation, action highlighting, persisted replay data,
and live-play rejection. The opt-in localhost test completes a real match,
requests v2 diagnostics, decodes them, and resolves a replay cursor.

Physical two-Mac/LAN, firewall, signing, notarization, and real-player quality
review are separate acceptance gates.
