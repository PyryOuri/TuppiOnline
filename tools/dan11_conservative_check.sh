#!/bin/sh
set -eu
dan_python="$1"
dan_output="$2"
"$dan_python" -m pytest -q -p no:cacheprovider tests/test_dan.py::test_real_bidding_matches_nelli11_or_changes_rami_to_nolo tests/test_dan.py::test_native_browser_entry_matches_python_transaction tests/test_dan.py::test_name_and_new_version_are_in_checkpoint tests/test_dan.py::test_pending_replay_abort_commit_and_reload_do_not_double_spend tests/test_dan.py::test_terminal_preview_starts_and_accepts_quit
"$dan_python" tools/dan11_bidding.py --deals 1024 --seed-start 2048 --out "$dan_output/BIDDING_FRESH_1024.json"
"$dan_python" tools/dan_probe.py --natural --count 64 --out "$dan_output/NATURAL_64.json"
