#!/bin/sh
set -eu
# Every accepted move is saved before it is acknowledged, so a short drain
# loses nothing; with a disk, Render starts the new instance only after this
# one stops, so a long drain only lengthens the deploy's downtime.
install -d -m 0700 -o 10001 -g 10001 "$TUPPI_SERVER_DATA_DIR"
exec gosu tuppi python -m uvicorn tuppi_server.hosted_site:create_hosted_site \
  --factory --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 \
  --ws-max-size 32768 --timeout-keep-alive 15 --timeout-graceful-shutdown 10 \
  --no-access-log
