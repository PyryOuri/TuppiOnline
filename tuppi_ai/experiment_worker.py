"""Persist a child identity and wait for the queue's launch acknowledgement before exec."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .experiment_io import read_json, write_json


def main():
    path = Path(sys.argv[1])
    spec = read_json(path)
    write_json(path.parent / "child.json", {"pid": os.getpid(), "token": spec["token"]}, replace=False)
    deadline = time.monotonic() + 10
    permit = path.parent / "go.json"
    while time.monotonic() < deadline:
        if os.getppid() != spec["parent_pid"]:
            raise SystemExit("Queue runner disappeared before launch acknowledgement")
        if permit.exists():
            if read_json(permit).get("token") != spec["token"]:
                raise SystemExit("Launch acknowledgement does not match this attempt")
            os.execv(spec["argv"][0], spec["argv"])
        time.sleep(0.02)
    raise SystemExit("No launch acknowledgement; workload was not started")


if __name__ == "__main__":
    main()
