#!/bin/sh
set -eu
install -d -m 0700 -o 10001 -g 10001 "$TUPPI_SERVER_DATA_DIR"
exec gosu tuppi python -m uvicorn tuppi_server.hosted_site:create_hosted_site \
  --factory --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 \
  --ws-max-size 32768 --timeout-keep-alive 15 --timeout-graceful-shutdown 120 \
  --no-access-log
