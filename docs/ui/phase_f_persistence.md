# UI-F — local persistence and server-restart recovery

## Scope

UI-F adds restart-safe private-alpha rooms without introducing a paid service
or a database dependency.  The server remains a single Python process around
`tuppi_engine`; persistence is a directory containing one canonical JSON file
per room.

The persisted record contains:

- room code, host token, human session tokens, seats, names, and readiness;
- configured AI seats and lifecycle;
- every complete live explicit deal, including private hands;
- every accepted human and server-side AI action in order;
- the public event sequence and per-action event batches.

These files are server-private.  They are never passed through the projection
boundary or included in a WebSocket message.

Post-match analysis is stored separately as
`analysis-<ROOMCODE>.json`. It contains only the already filtered
`tuppi.analysis.post_match.v1` response envelope, never raw diagnostics,
observations, score vectors, search metadata, or private deals. The file uses
the same `0700` directory and `0600` file permissions and atomic replacement
as the room record.

## Recovery algorithm

On server startup, `RoomManager` loads each room file and:

1. validates the room and session metadata;
2. recreates a pristine `MatchState` with the original match reference, score,
   and dealer;
3. restores each retained explicit deal rather than generating a new one;
4. replays accepted actions through `apply_match_action`;
5. regenerates the public event batches and compares them byte-for-byte as
   canonical JSON objects with the persisted records;
6. validates the resulting authoritative state with `validate_match_state`;
7. exposes the room for reconnect only if every check succeeds.

If an analysis artifact exists, recovery additionally requires that the room
has a terminal runner, the artifact schema is valid, its match reference is
the runner's match reference, and every analyzed action is still bound to the
replayed public event log. A malformed, orphaned, or mismatched analysis file
fails closed.

A malformed or tampered room record fails closed and prevents that server
process from starting.  It is not silently discarded.

## Write semantics

Room records are written with canonical JSON to a temporary file in the same
directory, flushed, fsynced, and atomically replaced.  The persistence root is
created with mode `0700`; room files use mode `0600`.

The record is saved after room creation, joining, configuration, readiness, and
before an accepted action acknowledgement is sent to the client.  A crash can
therefore lose an in-flight request, but it cannot make an acknowledged action
appear accepted after recovery unless its durable record was written first.

## Local deployment

The default server data directory on macOS is:

```text
~/Library/Application Support/Tuppi/server
```

It can be overridden for testing or a portable local setup:

```bash
TUPPI_SERVER_DATA_DIR=/path/to/tuppi-data \
python -m uvicorn tuppi_server.app:app --host 0.0.0.0 --port 8765
```

The first alpha still has no accounts. The opaque session token in the room
creation/join response is the reconnect credential and is retained in the
server record. The current Swift client retains its copy only in memory.
Server restart recovery therefore works while the client process remains
alive, as proven by the localhost interoperability harness. Client application
restart recovery is incomplete; Keychain persistence belongs to the next
private-alpha hardening phase and is not part of Product Stabilization 1.

## Deliberate non-goals

- multi-process coordination;
- PostgreSQL or Redis;
- historical match browsing UI;
- database migrations;
- public deal reveal;
- cloud backups or automatic conflict resolution.

Those belong to a later persistence/history phase if the private alpha proves
useful.  A backup of the local data directory is intentionally an explicit
operator action because it contains private hands.
