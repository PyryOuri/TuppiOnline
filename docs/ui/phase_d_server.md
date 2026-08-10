# UI-D — live Python server boundary

## Scope

This phase adds the smallest useful live-server core for the native macOS
client. It is intentionally in-memory and account-free for the private alpha.
The authoritative game remains `tuppi_engine`; the server never reimplements
showing, follow-suit, trick resolution, or score transitions.

The current topology is:

```text
TuppiClient
    │ HTTPS bootstrap / ASGI WebSocket
    ▼
tuppi_server
    ├── RoomManager
    ├── LiveMatchRunner
    ├── live CSPRNG deal generation
    ├── optional local atomic room persistence (UI-F)
    ├── filtered post-match analysis artifact
    └── projection.py  ← only wire-state boundary
        ▼
    tuppi_engine
```

## Current transport surface

HTTP bootstrap endpoints:

- `POST /v1/rooms` — create a room; optional `ai_seats` supports solo alpha.
- `POST /v1/rooms/{code}/join` — join the next open human seat.
- `POST /v1/rooms/{code}/configure` — host changes unoccupied AI seats.
- `POST /v1/rooms/{code}/ready` — mark the session ready.
- `POST /v1/rooms/{code}/analysis` — authenticated participant retrieves the
  filtered post-match analysis envelope after completion.

The analysis request body contains only `session_token`. It returns `200` with
the versioned response, `404` for an unknown room or session, and `409` when
the match is not complete or no analysis has been generated yet. There is no
client-facing write endpoint for analysis.

The WebSocket endpoint is `/v1/ws`. The first message is an authenticated
`hello` containing `protocol_version`, `room_code`, and `session_token`.
Subsequent messages are `ready`, `reconnect`, `action_submission`, and `ping`.
Server messages include `hello_ack`, `lobby_snapshot`,
`action_acknowledgement`, `match_update`, `reconnect_result`, `pong`, and
`protocol_error`.

An accepted action is acknowledged and then published as a per-seat
`match_update`. A stale action is acknowledged with `status: stale` and
followed by a `reconnect_result` containing the current authorized observation
and public event delta. A duplicate action is acknowledged as `duplicate` and
does not apply the engine transition again.

The live ASGI submission path uses an asynchronous runner continuation. When
the next authoritative actor is an AI seat, the server waits five seconds by
default before applying that AI action. This applies to showing actions,
trick leads, and cards played into an already started trick, so each bot move
has time to be seen.

## Security boundary

`projection.py` accepts an authoritative `MatchState` and a seat, then calls
the engine's canonical `match_observation_for` and `observation_to_data`.
Network code never serializes `MatchState`, `DealState`, `initial_hands`, or
`ExplicitDeal`. Public event serialization uses the existing
`tuppi.engine.public_event.v1` serializer.

Live deals are shuffled with `random.SystemRandom`. The explicit deal and its
derived private deal id remain inside `LiveMatchRunner`.

Normal private-alpha AI seats resolve the authoritative Phase 4
`partner_aware_v1` registration. The AI receives only its formal player
observation and every selected action is applied through the engine. The
first-legal agent remains available only as an explicit test profile.

## Deliberate non-goals

- accounts and persistent history;
- PostgreSQL/Redis;
- historical match browsing UI;
- public deployment or TLS termination;
- new AI-strength research or client-visible search diagnostics;
- chat, spectators, matchmaking, ratings, live recommendations, or the final
  AI analysis generator.

The command-line server requires the optional `server` dependency. The
preferred entry point is module-based, so it does not depend on a `uvicorn`
executable being present on the shell `PATH`:

```bash
python -m pip install -e '.[server]'
python -m tuppi_server
```

The default listener is `127.0.0.1:8765`. For a same-network private alpha,
use the repository launcher:

```bash
tools/start_private_alpha_server.sh
```

It starts `python -m tuppi_server --lan`, prints the local addresses that
clients can enter in the Swift app, and gives an actionable dependency error
if `uvicorn` has not been installed. The listener and port can also be set
with `TUPPI_SERVER_HOST` and `TUPPI_SERVER_PORT`. The server supports a
read-only installation check:

```bash
python -m tuppi_server --check
```

The `server` extra installs both `uvicorn` and its required `websockets`
backend. The preflight imports both, preventing an HTTP-only installation from
being mistaken for a working live runtime.

The default local server data directory remains
`~/Library/Application Support/Tuppi/server`. A public deployment still
requires TLS termination or a private network tunnel; the LAN launcher is not
an internet-facing deployment.

## Validation

The isolated repository is validated with the engine, fixture-exporter, and
server regression commands in the repository's test configuration. The server
tests cover live CSPRNG deal structure, observation privacy,
accepted/duplicate/stale/rejected actions, room readiness, HTTP bootstrap,
WebSocket authentication, match updates, and stale-action reconnect payloads.

Product Stabilization 1 additionally runs a production Swift networking
harness against a real localhost Python process, including accepted,
duplicate, stale, reconnect, and server-restart recovery flows. This does not
replace the later two-Mac LAN/firewall acceptance pass.

UI-F adds the restart-recovery contract described in
`docs/ui/phase_f_persistence.md`; its recovery tests live alongside the server
tests.
