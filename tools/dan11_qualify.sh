#!/bin/sh
# One finite, serial qualification sequence; no background jobs or training.
set -eu
dan_python="$1"
dan_output="$2"
"$dan_python" tools/dan_probe.py --count 16 --out "$dan_output/DEVELOPMENT_16.json"
"$dan_python" tools/dan_probe.py --count 16 --seed-start 512 --out "$dan_output/FRESH_16.json"
"$dan_python" tools/dan_probe.py --count 8 --seed-start 512 --audit --out "$dan_output/AUDIT_FRESH_8.json"
"$dan_python" tools/dan11_bidding.py --deals 1024 --out "$dan_output/BIDDING_1024.json"
"$dan_python" tools/dan_probe.py --natural --count 64 --out "$dan_output/NATURAL_64.json"
