# Tuppi current product

Updated 14 October 2026. This is the entry point for building, maintaining,
and extending the current game. Dated research reports retain their original
claims and validation boundaries.

## Product sources

| Component | Source | Role |
|---|---|---|
| macOS application | [TuppiClient-current](TuppiClient-current/README.md) | Finnish SwiftUI/AppKit interface; macOS 14 or later |
| Rules, engine and server | [TuppiProject-current](TuppiProject-current/README.md) | Authoritative rules, room state, HTTP/WebSocket, persistence and projections |
| Bot | [TuppiAI](TuppiAI/README.md) | Native search, trained policies, sooli and review |
| Browser candidate | [TuppiBrowser](TuppiBrowser/README.md) | Offline WebAssembly and network adapter; private offline HTTPS candidate published, local Linux image qualified, device/host gates pending |
| Hosted engine candidate | [TuppiProject-browser-network](TuppiProject-browser-network/docs/HOSTED_BROWSER.md) | Isolated authoritative browser-room implementation; no live integration |
| Hosted bot candidate | [TuppiAI-hosted](TuppiAI-hosted/docs/HOSTED_BUILD.md) | Frozen models, portable/BLAS native builds; macOS and local Linux reference checks passed |
| Installed application | `Tuppi.app` | Existing macOS app; source/build identity is captured separately |

The main `TuppiProject` and `TuppiClient` checkouts contain unfinished work.
Do not reset or replace them when maintaining the current product. Training
and other research checkouts have separate roles and frozen comparisons.

## Rules and bot configuration

The product uses [project_target_v3](TuppiProject-current/docs/rules/project_target_v3.md):
blind locked bids, NOLO/RAMI, sooli, and the existing rising match score.
Transport and analysis schema versions are independent of the ruleset.

Current source configuration is:

| Setting | Value | Source |
|---|---|---|
| Live sampled worlds | 1,024 | `TuppiProject-current/src/tuppi_server/match_runner.py` |
| Research factory default | 128 | `TuppiAI/tuppi_ai/best.py` |
| Exact ordinary tail | Six tricks | `TuppiAI/tuppi_ai/best.py` |
| Opponent and team rollout policy | VRPO1 `vrpo1_actor_0504.pt` | `TuppiAI/tuppi_ai/best.py` |
| Anchor policy | VRPO3 `vrpo3_final.pt` | `TuppiAI/tuppi_ai/best.py` |
| Anchor margin | Play 0.003, bids 0.03 | `TuppiAI/tuppi_ai/best.py` |
| Adaptive bidding | Batch 128, z 2.5, delta 0.005 | `TuppiAI/tuppi_ai/best.py` |
| Showing-fallback sampler fix | Enabled for the current product | `TuppiAI/tuppi_ai/best.py` |
| RAMI margin | 0.0 | `TuppiAI/tuppi_ai/best.py` |

An already-running server may retain earlier source, models or native code.
Source configuration alone does not attest its loaded state. The existing
dated [results ledger](TuppiAI/docs/STATUS.md) supplies the evidence for policy
choices; maintenance does not establish a new strength result.

## Play and build

Run `./start_tuppi_server.sh`, then open `Tuppi.app`. The default connection
is `http://127.0.0.1:8765`. `--lan` enables a separate local-network setup.
Server/save data contains private hands and credentials and stays outside
source/release bundles.

The Swift package uses the full Xcode toolchain:

```sh
cd TuppiClient-current
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift build --jobs 2
DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer swift test --jobs 2
```

The server/bot need a Python environment with NumPy, PyTorch, pytest for tests,
and uvicorn/websockets for serving. Select the current engine and bot explicitly
with `PYTHONPATH`; historical environment path files can otherwise select a
different checkout. The release capture records the observed versions rather
than treating dependency ranges as a lock file.

Build native code only in the intended checkout using its `native/build.sh`.
The current backend uses macOS Accelerate and dispatch. A browser build needs
a qualified portable backend; changing a filename extension does not port it.

## Maintenance and validation

Use [tools/tuppi_maintenance.py](tools/tuppi_maintenance.py) to capture, verify,
and restore source plus installed artifacts into an isolated validation copy.
It includes required untracked source, Git patches, model hashes, and native
binary identity, and excludes user runtime data. Its capture directory must
be new; restoration also requires a new destination.

```sh
python3 tools/tuppi_maintenance.py capture audit_deliverables/release_capture
python3 tools/tuppi_maintenance.py verify audit_deliverables/release_capture
python3 tools/tuppi_maintenance.py restore audit_deliverables/release_capture --target audit_deliverables/release_validation
```

Run meaningful v3 rules/engine, server/projection/persistence, Swift, native
differential, schema/fixture and interop checks against that isolated copy.
Keep research-library pytest sessions separate from production native tests.
Source hashes, runtime checks, UI/device checks, and strength evidence are
different acceptance records.

Cleanup removes regenerable caches after build validation. Research runs,
models, old saves, original handoffs, and unfinished work retain explicit
retention records. Supported historical schema readers and fixtures remain
until a migration/support decision is recorded.

The October maintenance pass removes unused Python buffer allocation from
native-only searches. W128/W1024 fixed-deal action/value fingerprints matched
the captured baseline. This saves array capacity, rather than establishing
a new resident-memory or strength result. The existing running server was
not restarted during maintenance.

## Offline browser programme

The [compact128 integration report](audit_deliverables/tuppi_compact128_integration_20261014/REPORT.md)
records the qualified speedups now promoted into the browser and hosted bot.
The owner-private offline Site uses the new runtime, while old saves keep their
compatible engine. Three paired fixed-input rounds measured median CPU reductions
of 30.5% on macOS, 41.1% on local Linux through Rosetta and 17.1% on Node WASM,
with exact per-backend decisions, values and controller state. The trained Linux
image passed full-game recovery checks and 19 source/package regressions passed.
Models, search settings and UI are unchanged. Physical iPhone and native host
qualification remain separate; hosting is still undecided.

The agreed order is release capture and cleanup, measured improvements,
WebAssembly feasibility, an offline browser game, device qualification, then
advanced review tools and network play. The bot runs locally on each device.
The browser downloads its assets initially and caches a complete release.

The [implementation plan](audit_deliverables/tuppi_maturity_plan_20261013/PLAN.md)
defines milestones and acceptance gates. Current execution records belong in
`audit_deliverables/tuppi_maturity_implementation_20261013/`, separately from
the original planning and research packages.

The [offline/network implementation report](audit_deliverables/tuppi_offline_network_implementation_20261014/REPORT.md)
records the 14 October continuation. The
[owner-private offline candidate](https://tuppi-offline-202b74f.sos-health-p-7158.chatgpt.site)
is published for iPhone qualification. Browser rooms with bot seats, observing
seat rotation and durable reconnect are implemented in isolated candidates.
Source/Node/HTTP and macOS/Linux controller checks passed. The local Linux x86-64
image also passed a complete trained-bot game, reconnect/reload, midgame restart
and replacement-container volume recovery. Native host capacity, physical iPhone
and Swift/browser acceptance remain required. Hosting is undecided at the user's
request; the Docker context is portable and Render remains a prepared proposal.
No paid or public network service was created. These candidates do not replace
the live native product or activate research work.
