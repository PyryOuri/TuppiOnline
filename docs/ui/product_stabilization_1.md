# Product Stabilization 1 closeout

Date: 10 August 2026

Outcome: **P1 — integration successful**. The remaining release gate is the
separate Product Stabilization 2 physical two-Mac private-alpha acceptance.

## Preservation and base

- Swift interrupted state: preserved as commit
  `d63479cc2d8ae120e918e7afb629913cc602f6ae` in `TuppiClient`.
- Stale Python product state: preserved from parent
  `aef17609aacb0abccd12671f68e9ec32926e6df7` as commit
  `a9a459202c94b63466935a3887c861833255b64c` on
  `product/private-alpha-snapshot`.
- Authoritative integration base:
  `57161cd65a4fd1e3d586592404898b980d3ff68e` (Phase 6, package 0.11.0).
- Integrated package version: 0.12.0. The frozen learning-layer identity
  remains 0.11.0.

Both preservation commits passed `git fsck --full` and have verified same-disk
Git bundle copies. Those bundles are not off-machine disaster recovery.

## Acceptance evidence

- Python product/server/UI: 43 passed.
- Python rules/engine/agents: 688 passed.
- Full Python suite: 1,477 passed, 7 skipped in 20m39s. Two skips are existing
  position/data-dependent search cases; five are optional PyTorch tests because
  the historical learning environment no longer exists. No training ran.
- Swift clean scratch build: passed with Xcode 26.6 / Swift 6.3.3 and no
  compiler warnings.
- Swift clean scratch unit suite: 14 passed, 1 external-process gate skipped as
  designed.
- Real localhost Swift-Python gate: 1 passed. It used production HTTP and
  WebSocket clients to verify compatibility, room creation, partner-aware AI
  profile, readiness, canonical observation, accepted/duplicate/stale actions,
  disconnect/reconnect, server restart using the same private state directory,
  restored cursors, and continued play.
- Wheel: isolated PEP 517 build and clean core-only install passed. Inspection
  confirmed server/fixture modules, network schemas, and product docs and found
  no runtime state, secrets, caches, or virtual environments.

## Product stage matrix

| Stage | Status | Evidence boundary |
|---|---|---|
| UI-A | complete/accepted | Authoritative schemas/export, checksums, production Swift DTO decoding, drift check |
| UI-B | functionally implemented | Native four-seat SwiftUI table builds and fixture tests pass |
| UI-C | partial | Legal fixture interaction exists; not a complete local mock product flow |
| UI-D | complete/accepted | Current engine server/projection boundary passes real localhost interoperability |
| UI-E | partial | Local live flow passes; physical LAN/firewall/two-Mac GUI acceptance is outstanding |
| UI-F | partial | Server restart recovery passes while client credentials remain in memory; client restart recovery is absent |
| UI-G | not started | No signing/notarization acceptance |
| UI-H | partial | Public replay and explicitly labelled fixture analysis exist; no production analysis generator |
| UI-I | not started | No coaching/training application |

## Deliberate boundaries

- AI-strength research remains frozen after Phase 6 R4; no Phase 6A, PPO, or
  new Phase 5 work was started.
- `partner_aware_v1` remains the practical playing reference and the normal
  private-alpha AI profile.
- The sealed promotion bank remains unopened.
- Client session credentials remain memory-only; Keychain work is deferred.
- Localhost evidence does not claim two-Mac, firewall, notarization, or signed
  distribution acceptance.

## Next task

Run Product Stabilization 2 as a physical two-Mac acceptance pass: real LAN
create/join, human and AI seats, firewall behavior, disconnect/reconnect,
server restart, privacy inspection, responsive GUI review, and full match
completion. Do not reopen AI research as part of that phase.
