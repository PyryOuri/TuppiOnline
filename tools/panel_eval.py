"""Panel evaluation: a candidate against several opponents, paired with a reference agent.

docs/ROBUSTNESS_PLAN.md. For each opponent of the panel, the candidate and the
reference play the same base deals against it (`tuppi_ai.evaluate`, 4
rotations x 2 seatings); the per-deal difference candidate minus reference is
the measure. When the opponent is the reference itself (bot-vs-bot), the
evaluation value is already that difference. The headline is the mean over
the *strong* opponents; *guard* opponents (the heuristic) must not show a
loss.

    python tools/panel_eval.py --name P1-vrpo-opp --candidate "<spec>" --reference "<spec>" \\
        --strong live=<spec> vrpo3=models/vrpo3_final.pt --guard heur=partner_aware_lead_v3
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(spec: str, opponent: str, deals: int, seed: str, scores: str, workers: int, out: Path) -> dict:
    if not out.exists():
        cmd = [PY, "-m", "tuppi_ai.evaluate", "--checkpoint", spec, "--opponent", opponent, "--ruleset", "v3",
               "--deals", str(deals), "--workers", str(workers), "--scores", scores, "--seed", seed, "--out", str(out)]
        subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env={**__import__("os").environ, "PYTHONPATH": str(ROOT)})
    return json.loads(out.read_text())


def paired(a: list[float], b: list[float]) -> tuple[float, float]:
    d = [y - x for x, y in zip(a, b)]
    m = sum(d) / len(d)
    se = math.sqrt(sum((x - m) ** 2 for x in d) / (len(d) - 1) / len(d))
    return m, se


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--strong", nargs="+", default=[], help="name=spec opponents that define the headline")
    p.add_argument("--guard", nargs="*", default=[], help="name=spec opponents that must not show a loss")
    p.add_argument("--deals", type=int, default=512)
    p.add_argument("--scores", default="uniform")
    p.add_argument("--seed", default="panel-v1")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--out", type=Path, default=ROOT / "runs" / "panel")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind, items in (("strong", a.strong), ("guard", a.guard)):
        for item in items:
            name, spec = item.split("=", 1)
            seed = f"{a.seed}|{name}"
            cand = run(a.candidate, spec, a.deals, seed, a.scores, a.workers, a.out / f"{a.name}__{name}__cand.json")
            if spec == a.reference:  # bot-vs-bot: the value is the paired difference
                v = cand["values"]
                m = sum(v) / len(v)
                se = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1) / len(v))
            else:
                ref = run(a.reference, spec, a.deals, seed, a.scores, a.workers,
                          a.out / f"REF__{abs(hash(a.reference)) % 10**8}__{name}__{a.deals}__{a.scores}.json")
                m, se = paired(ref["values"], cand["values"])
            rows.append({"kind": kind, "opponent": name, "diff": m, "se": se,
                         "cand_declared": cand["cand_declared"]})
            print(f"{kind:6s} {name:10s} candidate - reference {m:+.5f} ± {1.96 * se:.5f}  "
                  f"(candidate declares RAMI {cand['cand_declared']:.1%})", flush=True)
    strong = [r for r in rows if r["kind"] == "strong"]
    if strong:
        m = sum(r["diff"] for r in strong) / len(strong)
        se = math.sqrt(sum(r["se"] ** 2 for r in strong)) / len(strong)
        print(f"STRONG-PANEL MEAN {m:+.5f} ± {1.96 * se:.5f}")
        rows.append({"kind": "headline", "diff": m, "se": se})
    (a.out / f"{a.name}.json").write_text(json.dumps({"rows": rows, "args": vars(a)}, default=str, indent=1))


if __name__ == "__main__":
    main()
