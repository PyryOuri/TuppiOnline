"""Run the finite Dan qualification roster; --audit is a separate CPU stage."""
import argparse
import json
from pathlib import Path
from tuppi_ai.dan_preview import probe, natural

p = argparse.ArgumentParser()
p.add_argument("--count", type=int, default=16)
p.add_argument("--audit", action="store_true")
p.add_argument("--natural", action="store_true")
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
if a.natural and a.audit:
    p.error("natural preview and estimation audit are separate stages")
report = natural(a.count) if a.natural else probe(a.count, a.audit)
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
print(json.dumps({"deals": report["deals"], "reasons": report["reasons"], "out": str(a.out)} if a.natural else
    {"positions": len(report["positions"]), "accepted": report["accepted"],
     "guard_cpu_seconds": report["guard_cpu_seconds"], "out": str(a.out)}))
