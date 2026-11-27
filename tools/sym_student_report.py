"""Summarise tools/sym_student_compare.sh results: OUT/RESULTS.md and OUT/RESULTS.json.

    python tools/sym_student_report.py --dir <OUT>

Values are match equity per base deal, candidate (the student) minus the released network, with
95% intervals as tuppi_ai.evaluate computes them (normal, over base deals); `pairs` is the
candidate's complete-match win rate. "No-change deals" are base deals whose eight games give
the two arms exactly equal results (value exactly 0).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

STEPS = [
    ("plain_zero.json", "Network alone (greedy): student vs VRPO4, 0-0"),
    ("plain_uniform.json", "Network alone (greedy): student vs VRPO4, uniform scores"),
    ("nelli_dup.json", "Nelli (lite C1H): student vs VRPO4 (Nelli 1.1), uniform scores"),
    ("nelli_pairs.json", "Nelli (lite C1H): complete matches from 0-0, student vs Nelli 1.1"),
    ("heidi_w128.json", "Heidi screen W128 PIB8: student anchor vs VRPO4 anchor (Heidi 1.2), uniform"),
    ("heidi_w1024.json", "Heidi W1024 PIB8 (as released): student anchor vs Heidi 1.2, uniform"),
]


def ledger(dirpath: Path) -> dict:
    out = {}
    path = dirpath / "LEDGER.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                out[e.get("label", "")] = e
    return out


def nelli_heidi(dirpath: Path, led: dict) -> dict | None:
    """Pool the nelli_heidi chunks (independent seeds) over base deals."""
    files = sorted((dirpath / "nelli_heidi").glob("c[0-9][0-9].json"))
    if not files:
        return None
    values, cpu = [], 0.0
    for f in files:
        r = json.loads(f.read_text())
        values += r["values"]
        e = led.get(f"sym-nelli_heidi_{f.stem}") or led.get(f"sym-nelli_heidi_{f.stem}-dryrun") or {}
        cpu += e.get("cpu_s") or 0.0
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else float("nan")
    half = 1.96 * sd / math.sqrt(n) if n > 1 else float("nan")
    out = {"file": "nelli_heidi/", "title": "Nelli (C1H) on the student vs Heidi 1.2 W1024, uniform",
           "chunks": len(files), "base_deals": n, "mean": mean, "sd": sd, "ci95": [mean - half, mean + half],
           "cpu_h": f"{cpu / 3600:.2f}"}
    dup = dirpath / "nelli_dup.json"
    if dup.exists() and n > 1:
        d = json.loads(dup.read_text())
        dl, dh = d["ci95"]
        h2 = math.hypot(half, (dh - dl) / 2)
        m2 = mean - d["equity_per_deal"]
        out["implied_nelli11"], out["implied_nelli11_ci95"] = m2, [m2 - h2, m2 + h2]
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", type=Path, required=True)
    a = p.parse_args()
    rows, lines = [], ["# Suit-symmetry student vs the released bots", "",
                       "Candidate minus released network; match equity per base deal, 95% intervals.", "",
                       "| Measure | Base deals / pairs | Result | No-change deals | CPU h |", "|---|---:|---|---:|---:|"]
    led = ledger(a.dir)
    for fname, title in STEPS:
        f = a.dir / fname
        if not f.exists():
            lines.append(f"| {title} | | not run | | |")
            continue
        r = json.loads(f.read_text())
        label = {"plain_zero.json": "plain0", "plain_uniform.json": "plainu", "nelli_dup.json": "nelli_dup",
                 "nelli_pairs.json": "nelli_pairs", "heidi_w128.json": "heidi128", "heidi_w1024.json": "heidi1024"}[fname]
        entry = next((e for k, e in led.items() if k.startswith(f"sym-{label}")), None)
        cpu = entry.get("cpu_s") if entry else None
        cpu_h = f"{cpu / 3600:.2f}" if isinstance(cpu, (int, float)) else ""
        if r.get("mode") == "pairs":
            lo, hi = r["ci95"]
            res = f"win rate {r['win_rate']:.4f} [{lo:.4f}, {hi:.4f}] ({r['unfinished_matches']} unfinished)"
            rows.append({"file": fname, "title": title, "pairs": r["pairs"], "win_rate": r["win_rate"], "ci95": r["ci95"],
                         "unfinished": r["unfinished_matches"], "cpu_h": cpu_h})
            lines.append(f"| {title} | {r['pairs']} | {res} | | {cpu_h} |")
        else:
            lo, hi = r["ci95"]
            same = sum(1 for v in r["values"] if v == 0.0)
            res = f"{r['equity_per_deal']:+.5f} [{lo:+.5f}, {hi:+.5f}]"
            rows.append({"file": fname, "title": title, "base_deals": r["base_deals"], "mean": r["equity_per_deal"],
                         "ci95": r["ci95"], "no_change_deals": same, "won": r["won"], "cand_declared": r["cand_declared"],
                         "opp_declared": r["opp_declared"], "candidate": r["candidate"], "opponent": r["opponent"],
                         "seed": r["seed"], "scores": r["scores"], "cpu_h": cpu_h})
            lines.append(f"| {title} | {r['base_deals']} | {res} | {same} | {cpu_h} |")
    nh = nelli_heidi(a.dir, led)
    if nh:
        rows.append(nh)
        lo, hi = nh["ci95"]
        lines += ["", "## Nelli on the student vs Heidi 1.2 (W1024 as released), uniform scores", "",
                  f"Pooled over {nh['chunks']} chunks ({nh['base_deals']} base deals, {nh['cpu_h']} CPU h): "
                  f"**{nh['mean']:+.5f} [{lo:+.5f}, {hi:+.5f}]** per deal (negative: Heidi is stronger); "
                  f"per-base-deal SD {nh['sd']:.4f}."]
        if "implied_nelli11" in nh:
            m, (l2, h2) = nh["implied_nelli11"], nh["implied_nelli11_ci95"]
            lines.append(f"Implied Nelli 1.1 vs Heidi 1.2 (this minus the Nelli duplicate's student gain, "
                         f"independent samples): {m:+.5f} [{l2:+.5f}, {h2:+.5f}].")
    fails = a.dir / "failures.jsonl"
    if fails.exists() and fails.read_text().strip():
        lines += ["", "Failures:", "", "```", fails.read_text().strip(), "```"]
    (a.dir / "RESULTS.md").write_text("\n".join(lines) + "\n")
    (a.dir / "RESULTS.json").write_text(json.dumps(rows, indent=1) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
