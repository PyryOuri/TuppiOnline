# `tuppi.network.v1` contract

The Python repository is the source of truth for the complete implemented
network protocol. `schemas/network/protocol_manifest.json` is the inventory;
the adjacent strict JSON Schemas define each HTTP payload and WebSocket
envelope. Unknown fields are rejected by server parsers and schemas.

## Canonical embedded engine payloads

The wire contract reuses, without a client-specific game-state translation:

- `tuppi.engine.player_observation.v1`;
- `tuppi.engine.public_event.v1`;
- `tuppi.engine.match_result.v1`.

The schemas for these payloads remain under `schemas/engine/`. Swift has
hand-written Codable DTOs, but the exported wire recordings are decoded through
those production DTOs on every test run.

## HTTP messages

- compatibility result;
- create-room request/result;
- join-room request/result;
- AI-seat configuration request/result;
- ready request/result;
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

The completed-match analysis result is `tuppi.analysis.post_match.v2`. It is a
seat-scoped, ranked response with `Exact`, `Rule-based`, and `Reference`
evidence categories. `Reference` is expressly not an optimality claim. The
endpoint rejects active matches; no live WebSocket message contains analysis.
The versioned union schema retains v1 only for committed fixture compatibility.

## Reconnect

`reconnect.payload.last_applied_event_index` is the last public event already
applied by the client. `reconnect_result.payload` contains:

```text
status: connected
observation: raw tuppi.engine.player_observation.v1
event_delta: public events after the supplied cursor
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
