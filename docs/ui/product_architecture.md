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
  public-event, completed-deal, or public-match-result serializers.
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

Each completed 13-trick deal is projected as the canonical public
`tuppi.engine.deal_result.v1` record. Swift archives those records immediately,
idempotently by `deal_ref`, grouped under `match_ref`; incomplete deals and
active-deal private hands are never client history records. A completed-deal v3
analysis may add that finished deal's now-public original hands to its local
archive. The filtered analysis endpoints do not expose search, belief, learning,
or hidden-hand diagnostics from live play.

The server's durable `ResearchDealResult` retains the original four hands and
canonical played result. Completed-deal v3 uses those exact hands to build an
`ExplicitDeal` and lets four fresh `partner_aware_v1` agents independently play
showing and all 13 tricks through the production engine from the original
dealer and score. The post-deal response contains both canonical results and the
original hands; the Swift replay also reconstructs hands from each result's 52
public plays and verifies that reconstruction against the server payload. No
live projection contains this data.

The analysis endpoints additionally return reference-agreement statistics and,
on showing decisions, the reference policy's RAMI/NOLO scalars.
Per-deal analysis is available to every participant as soon as a deal is
complete, in any room; only the whole-match endpoint waits for the terminal
result. Swift opens it as a value-keyed secondary macOS window, so the table can
remain open and usable while completed deals are reviewed.

AI pacing is room state. The host selects a supported millisecond delay before
the match starts, all lobby clients receive the value, and persistence restores
it after a server restart. The environment setting remains only the default for
new rooms.

## Current acceptance boundary

Automated Python tests, Swift tests, and the real localhost interop harness
cover the integrated process boundary. They do not establish LAN routing,
macOS firewall behavior, signed distribution, or a real two-Mac GUI session.
Those remain Product Stabilization 2 acceptance gates.
