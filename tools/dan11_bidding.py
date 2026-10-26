"""Bounded paired bid comparison; no rollouts, fitting, Torch or GPU."""
import argparse
import json
from pathlib import Path
from tuppi_ai.dan11_bidding import compare

p = argparse.ArgumentParser()
p.add_argument("--deals", type=int, default=1024)
p.add_argument("--seed-start", type=int, default=0)
p.add_argument("--out", type=Path, required=True)
a = p.parse_args()
r = compare(a.deals, a.seed_start)
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
print(json.dumps({k:v for k,v in r.items() if k != "rows"}))
