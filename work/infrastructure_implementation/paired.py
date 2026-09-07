"""Run the timing harness in alternating order and report paired results."""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
from pathlib import Path

PYTHON = "/Users/pyryouri/.venvs/tuppi-product/bin/python"
HARNESS = Path(__file__).with_name("harness.py")

# Six rounds a side; the ABBA order cancels any monotone drift on the host.
ORDER = ["A", "B", "B", "A", "A", "B", "B", "A", "A", "B", "B", "A"]


def run(src: str, only: str, out: Path, reps: int) -> dict:
    subprocess.run(
        [PYTHON, str(HARNESS), "--src", src, "--mode", "timing",
         "--out", str(out), "--reps", str(reps), "--only", only],
        check=True, stdout=subprocess.DEVNULL,
    )
    return json.loads(out.read_text())


def main() -> int:
    label_a, src_a, label_b, src_b, only, reps, out_dir = (
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4],
        sys.argv[5], int(sys.argv[6]), Path(sys.argv[7]))
    out_dir.mkdir(parents=True, exist_ok=True)
    runs: dict[str, list[dict]] = {label_a: [], label_b: []}
    for index, side in enumerate(ORDER):
        label, src = (label_a, src_a) if side == "A" else (label_b, src_b)
        path = out_dir / f"{only}-{index:02d}-{label}.json"
        runs[label].append(run(src, only, path, reps))
        print(f"round {index:02d} {label} -> {path.name}", flush=True)
    payload = dict(only=only, reps=reps, order=ORDER,
                   labels=[label_a, label_b], runs=runs)
    combined = out_dir / f"{only}-paired.json"
    combined.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    print(f"wrote {combined}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
