# UI-A protocol and fixture bundle

UI-A exports deterministic, privacy-safe resources for the native Swift client.
The exporter replays the checked-in explicit engine examples through the
authoritative `tuppi_engine` APIs. It does not invent a second game-state
representation.

## Export

From the repository root:

```bash
PYTHONPATH=src python -m tuppi_ui_fixtures.exporter \
  --output-dir /tmp/tuppi-ui-fixtures
```

The output contains:

```text
manifest.json
compatibility.json
sha256sums.json
fixtures/
  <scenario>/
    seat-0.json
    seat-1.json
    seat-2.json
    seat-3.json
    public-events.json
    accepted-actions.json
    deal-summaries.json
    match-result.json          # terminal scenarios only
transport/
  cases.json
  wire-recordings.json
protocol-manifest.json
```

The bundle contains no explicit deals, initial hands, fixed scripts, deal
identifiers, research results, or full engine state. Each seat file contains
only the canonical `PlayerObservation` for that seat at each recorded state.

## Canonical payloads

The bundle embeds or references these engine payloads without re-encoding game
state:

* `tuppi.engine.player_observation.v1`
* `tuppi.engine.public_event.v1`
* `tuppi.engine.match_result.v1`

`showing_ui_hints.v1` is presentation metadata only. It explains the
authoritatively legal show actions, including whether the verbal fallback is
required. The server must still derive and validate the action independently.

## Visibility rule

The accepted-action transcript is present only because this is a development
fixture bundle. It is suitable for deterministic playback and tests, not for a
live seat feed. A production WebSocket response must contain only the
authorized observation, public events, and approved transport metadata for its
recipient.

## Authority and drift checks

The Python repository is the source of truth for `tuppi.network.v1`.
`schemas/network/protocol_manifest.json` inventories every implemented HTTP
and WebSocket message, while the strict JSON Schemas in the same directory
validate the envelope and reuse the canonical engine schemas for observations,
events, and match results.

Synchronize the checked-in Swift resources only with:

```bash
python tools/sync_tuppi_client_bundle.py \
  --client-root /path/to/TuppiClient --sync
```

The read-only `--check` form fails if any file is missing, extra, or different.
Swift tests then verify bundle identity and checksums and decode every wire
recording through production DTOs. Reconnect recordings contain a raw canonical
`PlayerObservation` at `payload.observation`, exactly like the live server.
