#!/bin/sh
set -eu
dan_python="$1"
dan_output="$2"
"$dan_python" -m pytest -q -p no:cacheprovider tests/test_dan.py tests/test_lite.py::test_lite_bot_plays_without_pytorch_and_repeats_exactly tests/test_heidi12.py::test_controller_refuses_a_mode_whose_network_is_missing
"$dan_python" tools/dan_probe.py --count 16 --seed-start 512 --out "$dan_output/FRESH_16_FINAL.json"
"$dan_python" tools/dan_probe.py --count 8 --seed-start 512 --audit --out "$dan_output/AUDIT_FRESH_8_FINAL.json"
"$dan_python" tools/dan11_bidding.py --deals 1024 --seed-start 1024 --out "$dan_output/BIDDING_FRESH_1024.json"
"$dan_python" tools/dan_probe.py --natural --count 64 --out "$dan_output/NATURAL_64_FINAL.json"
