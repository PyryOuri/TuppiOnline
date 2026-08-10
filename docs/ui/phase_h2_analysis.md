# UI-H2 — Post-match decision analysis

The first UI-H2 slice is a replay-only analysis panel. It is not available in
the live table and cannot affect a submitted action.

## Contract

The client-facing contract is `tuppi.analysis.post_match.v1`, defined in
`schemas/network/post_match_analysis.schema.json`. It is a filtered product
projection, not a transport copy of the research search diagnostics.

The payload may contain:

- the public match reference and event index;
- the analyzed seat and decision phase;
- the played and recommended legal actions;
- ranked alternatives;
- human-readable explanation and limitations;
- a source identifier.

The payload must not contain:

- private initial hands or opponent cards;
- explicit live deal identifiers or server randomness;
- search seeds, sampled worlds, hidden-hand assignments, or search trees;
- unbounded raw engine observations.

The Python agent repository already has privacy-safe diagnostic structures, but
those structures are not sent directly to the client. The server adapter now
lives in `src/tuppi_server/analysis.py`. It accepts only the serialized
`tuppi.agents.decision_diagnostics.v1` record plus bounded, user-facing
explanation metadata and constructs the response field-by-field.

The adapter requires the analyzed action to match a public
`show_accepted`/`card_played` event. It also verifies the match reference,
deal number, seat, phase, trick index, canonical engine action, selected
candidate, and deterministic score ordering. If an authorized visible-card
set is supplied, every card named by the diagnostics and output must be in
that set.

The adapter rejects PIMC/search diagnostics and recursively rejects private
keys such as `world_set`, `decision_seed`, hidden hands, explicit deals, and
full observations. Raw score vectors, feature contributions, rule IDs,
observation digests, agent identities, and search metadata are never copied
to the client response.

The server now stores only the filtered envelope as a private
`analysis-<ROOMCODE>.json` artifact next to the UI-F room record. It can be
retrieved by an authenticated participant with:

```text
POST /v1/rooms/{room_code}/analysis
{"session_token":"..."}
```

The endpoint is read-only. Before storing, loading after restart, or returning
the response, the server binds every analysis to the authoritative public
event log and checks the accepted action, event index, deal number, phase, and
trick index. Existing UI-F room records remain compatible because the analysis
artifact is separate from the private runner record.

The live playing AI and production analysis generator remain separate. The
default `partner_aware_v1` playing agent is not presented as an analysis
engine and cannot create fake recommendations merely to populate this
endpoint. If a justified analysis generator is introduced later, its server-side hook is
`RoomManager.record_post_match_analyses(...)`; there is still no client-facing
analysis write endpoint.

## Current implementation

The Swift client includes two deterministic `ui_h2_fixture` analyses for the
`example-exact-52` match fixture:

- the initial RAMI showing;
- the first trick-play decision.

Selecting an analysis jumps the replay cursor to its event. The panel labels
fixture content explicitly and displays its limitations, so demo content cannot
be mistaken for a production strength estimate.

## Non-goals

This phase does not expose raw PIMC diagnostics, perfect-information oracle
comparisons, hidden-hand inference, coaching scores, or live recommendations.

## Validation

The adapter tests validate the response against
`schemas/network/post_match_analysis.schema.json` and cover showing, trick
play, event mismatches, PIMC rejection, nested private keys, unauthorized
card codes, deterministic alternative ordering, authenticated retrieval,
restart persistence, public-event binding, and tamper rejection.
