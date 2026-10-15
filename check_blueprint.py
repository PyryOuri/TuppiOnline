#!/usr/bin/env python3
"""Local lint of deploy/render.yaml and start.sh (DEP-01). Not Render's validation.

    python3 deploy/check_blueprint.py [directory containing render.yaml and start.sh]

Catches the settings this project relies on and the field combination Render
rejected. It does not replace `render blueprints validate` or Render's
Blueprint preview, which remain the provider gate before a release.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent)
blueprint = (root / "render.yaml").read_text()
start = (root / "start.sh").read_text()
lines = [line.split("#", 1)[0].rstrip() for line in blueprint.splitlines()]
text = "\n".join(lines)
problems = []
has_disk = re.search(r"^\s+disk:\s*$", text, re.M) is not None
if has_disk and re.search(r"^\s+maxShutdownDelaySeconds:", text, re.M):
    problems.append("maxShutdownDelaySeconds is not supported for a service with a disk")
for pattern, meaning in [
    (r"^\s+runtime:\s*docker\s*$", "Docker runtime"),
    (r"^\s+region:\s*frankfurt\s*$", "Frankfurt region"),
    (r"^\s+plan:\s*0\.5c-512mb\s*$", "Starter plan 0.5c-512mb"),
    (r"^\s+numInstances:\s*1\s*$", "one instance (the disk allows no more)"),
    (r"^\s+healthCheckPath:\s*/healthz\s*$", "health check /healthz"),
    (r"^\s+autoDeployTrigger:\s*off\s*$", "manual deploys"),
    (r"^\s+mountPath:\s*/data\s*$", "disk mounted at /data"),
    (r"key:\s*TUPPI_SERVER_DATA_DIR\s*\n\s+value:\s*/data/rooms\s*$", "rooms on the disk"),
    (r"key:\s*TUPPI_ROOM_PASSCODE\s*\n\s+sync:\s*false\s*$", "passcode prompted as a secret"),
]:
    if not re.search(pattern, text, re.M):
        problems.append(f"missing: {meaning}")
if not has_disk:
    problems.append("missing: persistent disk")
drain = re.search(r"--timeout-graceful-shutdown\s+(\d+)", start)
if drain is None or int(drain.group(1)) >= 30:
    problems.append("start.sh must drain within Render's default 30-second stop window")
if problems:
    print("\n".join(problems))
    sys.exit(1)
print(f"render.yaml and start.sh pass the local lint (drain {drain.group(1)} s). "
      "Render's own validation is still required.")
