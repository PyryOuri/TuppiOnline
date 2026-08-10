#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
tuppi_python=${TUPPI_PYTHON:-python3}

if ! command -v "$tuppi_python" >/dev/null 2>&1; then
    echo "Python was not found. Set TUPPI_PYTHON to a Python 3.11-3.14 executable." >&2
    exit 1
fi

if ! "$tuppi_python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    echo "Tuppi requires Python 3.11-3.14." >&2
    exit 1
fi

if ! "$tuppi_python" -c 'import uvicorn' >/dev/null 2>&1; then
    echo "The server dependency is missing." >&2
    echo "Install it once from this repository with:" >&2
    echo "  $tuppi_python -m pip install -e '.[server]'" >&2
    exit 1
fi

export PYTHONPATH="$repo_root/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$tuppi_python" -m tuppi_server \
    --lan \
    --port "${TUPPI_SERVER_PORT:-8765}" \
    "$@"
