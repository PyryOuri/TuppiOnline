# Tuppi private-alpha product architecture

This document is the current architecture reference for the Python side of the
native product. The rules, engine, evaluation, exact, search, belief, and
learning packages retain their Phase 6 identities; the product layer is an
adapter around them, not a replacement.

```text
SwiftUI application
  ├── fixture mode ── checked-in Python-exported public bundle
  └── live mode ───── HTTP + WebSocket, tuppi.network.v1
                              │
                              ▼
                         tuppi_server
                   RoomManager / LiveMatchRunner
                     │        │          │
             projection.py   │     atomic private room records
                     │        │
                     ▼        ▼
              canonical tuppi_engine observation/events/results
                              │
                       project_target_v1
```

## Authority boundaries

- `tuppi_engine.MatchState` is authoritative for legality and transitions.
- `src/tuppi_server/projection.py` is the sole state-to-wire boundary. It
  accepts authoritative state and calls the canonical player-observation,
  public-event, or public-match-result serializers.
- Network code cannot serialize `MatchState`, `DealState`, explicit deals, or
  initial hands. Sentinel tests cover initial state, showing, trick play,
  stale responses, reconnect, terminal result, and ordinary logging.
- Live deals use `random.SystemRandom`; no deterministic seed or private deal
  identity is put on the wire. Explicit deterministic deals remain available
  only for research and fixture generation.
- AI seats use the registered Phase 4 `partner_aware_v1` agent by default. The
  agent receives its formal `PlayerObservation`, and the engine validates its
  action. First-legal play is an explicit test profile only.

## Runtime and durability

The server is a single ASGI process. `RoomManager` owns room codes, opaque
session credentials, human/AI seats, readiness, and the live runner. Optional
file persistence stores one private canonical record per room. Restart recovery
restores the explicit private deal and accepted actions, replays them through
the current engine, compares regenerated public events, and fails closed on
tampering.

The Swift client keeps room/session credentials in memory. A server can restart
and the same running client can reconnect; restarting the client loses those
credentials. Keychain storage and account identity are deliberately deferred.

The filtered `tuppi.analysis.post_match.v1` endpoint is post-match only. It
does not expose search, belief, learning, or hidden-hand diagnostics and is not
a claim of a production coaching system.

## Current acceptance boundary

Automated Python tests, Swift tests, and the real localhost interop harness
cover the integrated process boundary. They do not establish LAN routing,
macOS firewall behavior, signed distribution, or a real two-Mac GUI session.
Those remain Product Stabilization 2 acceptance gates.
