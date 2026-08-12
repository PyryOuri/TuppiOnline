# `tuppi.network.v1` contract

The Python repository is the source of truth for the complete implemented
network protocol. `schemas/network/protocol_manifest.json` is the inventory;
the adjacent strict JSON Schemas define each HTTP payload and WebSocket
envelope. Unknown fields are rejected by server parsers and schemas.

## Canonical embedded engine payloads

The wire contract reuses, without a client-specific game-state translation:

- `tuppi.engine.player_observation.v1`;
- `tuppi.engine.public_event.v1`;
- `tuppi.engine.deal_result.v1`;
- `tuppi.engine.match_result.v1`.

The schemas for these payloads remain under `schemas/engine/`. Swift has
hand-written Codable DTOs, but the exported wire recordings are decoded through
those production DTOs on every test run.

## HTTP messages

- compatibility result;
- create-room request/result;
- join-room request/result;
- AI-seat configuration request/result;
- host-controlled room settings request/result (AI delay in milliseconds);
- ready request/result;
- authenticated completed-deal analysis request/result;
- authenticated safe post-match analysis request/result;
- server error.

## WebSocket messages

- `hello` / `hello_ack` and incompatible `compatibility_result`;
- `lobby_snapshot` and `ready`;
- `match_update`;
- `action_submission` / `action_acknowledgement`;
- `reconnect` / `reconnect_result`;
- `protocol_error`;
- application-level `ping` / `pong`.

Action acknowledgements use client action IDs for idempotency. `accepted`
applies once, `duplicate` returns the original acknowledgement semantics
without another engine transition, `stale` returns the current cursor and is
followed by an authorized reconnect projection, and `rejected` includes a
bounded error code.

The completed-match analysis result is `tuppi.analysis.post_match.v3`. The
current per-deal result is `tuppi.analysis.completed_deal.v3`. Both contain
seat-scoped, ranked diagnostics with `Exact`, `Rule-based`, and `Reference`
evidence categories. `Reference` is expressly not an optimality claim. The
per-deal endpoint is available to an authenticated participant as soon as the
requested deal is complete, in any room; an incomplete deal returns
`deal_not_complete`. The whole-match endpoint still requires a finished match.
No live WebSocket message contains analysis or completed-deal hidden state.

Post-match v3 and completed-deal v2/v3 carry
`summary.reference_agreement` (how often the analysed
seat matched the reference policy across every reconstructed decision),
per-item `reference_ranking` (where the played action sat in that policy's own
ordering), and, for showing decisions, `contract_reasoning` (the RAMI/NOLO
scalars and closed-set verdict notes). Completed-deal v3 additionally carries
the authoritative original hands and played result, a full four-bot
`partner_aware_v1` result for that exact retained deal, policy/determinism
metadata, and partnership-relative comparison values. It is a benchmark, not an
optimal-play claim. See `docs/ui/phase_h2_analysis.md` for the boundary argument.
The versioned union schemas retain earlier versions for committed fixture and
archived-history compatibility. Because the overall transport remains
`tuppi.network.v1`, the Swift live-session boundary accepts completed-deal
v1/v2/v3 and the current/preceding post-match versions; unknown versions still
fail closed.

## Reconnect

`reconnect.payload.last_applied_event_index` is the last public event already
applied by the client. `reconnect_result.payload` contains:

```text
status: connected
observation: raw tuppi.engine.player_observation.v1
event_delta: public events after the supplied cursor
completed_deals: canonical public tuppi.engine.deal_result.v1 records
match_result: optional canonical terminal result
```

There is no fixture-only wrapper around `observation`. The showing, partial
trick, reset, stale-action, live reconnect, and server-restart recordings all
use this same DTO.

## Verification

Python validates every exported request/response recording against the schema
identified in that recording. The bundle includes protocol/ruleset identity,
schema identities and digests, generated-file inventory, and SHA-256 checksums.
The Swift verifier checks those identities and checksums and decodes every
supported recording through production types. The deterministic sync tool's
read-only mode detects any copied-bundle drift.
