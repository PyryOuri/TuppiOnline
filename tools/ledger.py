"""Run one command and append its CPU, wall and peak memory to a ledger.

    python tools/ledger.py --ledger <dir> --label <label> [--note <text>] -- <command...>

Writes one JSON line per command to <dir>/LEDGER.jsonl and rewrites
<dir>/LEDGER.json with the entries and their totals. CPU is the children's
user plus system time from getrusage; peak RSS is the largest child's.
Research/base-network-20261022.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ledger", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--note", default="")
    p.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args()
    cmd = a.command[1:] if a.command and a.command[0] == "--" else a.command
    if not cmd:
        raise SystemExit("no command")
    d = Path(a.ledger)
    d.mkdir(parents=True, exist_ok=True)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.time()
    load0 = os.getloadavg()
    rc = subprocess.call(cmd)
    wall = time.time() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss = after.ru_maxrss  # bytes on macOS, kilobytes on Linux
    if sys.platform != "darwin":
        rss *= 1024
    entry = {"label": a.label, "note": a.note, "command": cmd, "start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
             "wall_s": round(wall, 2), "cpu_s": round((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime), 2),
             "max_rss_mib": round(rss / 2**20, 1), "exit": rc, "load_at_start": [round(x, 1) for x in load0]}
    with open(d / "LEDGER.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    entries = [json.loads(l) for l in open(d / "LEDGER.jsonl")]
    totals = {"entries": len(entries), "cpu_h": round(sum(e["cpu_s"] for e in entries) / 3600, 3),
              "wall_h": round(sum(e["wall_s"] for e in entries) / 3600, 3),
              "max_rss_mib": max([e["max_rss_mib"] for e in entries if e.get("max_rss_mib") is not None] or [0])}
    (d / "LEDGER.json").write_text(json.dumps({"totals": totals, "entries": entries}, indent=1) + "\n")
    print(json.dumps(entry), file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
