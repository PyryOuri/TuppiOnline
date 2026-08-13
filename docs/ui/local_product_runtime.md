# Local product runtime and verification

## Dedicated environment

Use a product environment separate from historical research environments:

```bash
python3 -m venv "$HOME/.venvs/tuppi-product"
"$HOME/.venvs/tuppi-product/bin/python" -m pip install -e '.[dev,server]'
"$HOME/.venvs/tuppi-product/bin/python" -m tuppi_server --check
```

The `server` extra contains `uvicorn` and `websockets`. The preflight imports
both and reports `tuppi.network.v1`; an HTTP-only ASGI installation is not
accepted.

Start a localhost server with:

```bash
"$HOME/.venvs/tuppi-product/bin/python" -m tuppi_server
```

Use `tools/start_private_alpha_server.sh` for the later LAN pass. Runtime state
defaults to `~/Library/Application Support/Tuppi/server` and may be isolated
with `TUPPI_SERVER_DATA_DIR`. It contains credentials and private hands and
must not be committed or shared with clients.

`TUPPI_SERVER_AI_ACTION_DELAY_SECONDS` sets the default for newly created
rooms. The room host can then select 0, 0.5, 1, 1.5, 2, 2.5, 3, 4, or 5 seconds
from the Swift lobby before play starts; the stored wire value is integer
milliseconds and survives a server restart.

`TUPPI_CONTRACT_ROLLOUT_SAMPLES` controls the observation-safe paired
RAMI/NOLO continuations used only for close bot showing decisions. The private
alpha defaults to 8 possible hidden worlds; use `0` to retain the frozen
heuristic without background evaluation. Values must be integers from 0 to 64.

## Fixture synchronization

From the Python repository:

```bash
python tools/sync_tuppi_client_bundle.py \
  --client-root /path/to/TuppiClient --sync
python tools/sync_tuppi_client_bundle.py \
  --client-root /path/to/TuppiClient --check
```

Do not edit the Swift fixture JSON manually.

## Local cross-language gate

The checked-in XCTest uses the production `TuppiHTTPClient` and
`TuppiWebSocketClient` against a real Python process:

```bash
TUPPI_PRODUCT_PYTHON="$HOME/.venvs/tuppi-product/bin/python" \
TUPPI_PRODUCT_PROJECT_ROOT=/path/to/TuppiProject \
TUPPI_PRODUCT_PORT=18765 \
swift test --filter LocalInteropTests/testRealPythonServerRoundTripReconnectAndRestart
```

It checks compatibility, room creation, room-level AI delay, AI profile
exposure, readiness, a
canonical observation, accepted/duplicate/stale actions, disconnect/reconnect,
raw reconnect-observation decoding, persistent server restart, restored event
cursor, continued play, canonical per-deal delivery, and early solo-practice
deal diagnostics. Credentials intentionally remain in the test/client
process across only the server restart.

The server answers application `ping` with `pong`. The client retains its
bounded automatic backoff and manual `retryConnection()` path. Broader network
UX and Keychain persistence are deferred to private-alpha hardening.
