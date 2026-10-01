"""Ranked report of where partner_aware_lead_v2 loses, from tools/heuristic_mining.py output.

For each situation group: decisions, the share where the teacher (VRPO3)
disagrees, the mean priced gain of switching to the teacher's action per
disagreement (with its standard error), and the total gain available per deal
(sum of gains / deals). Groups are ranked by that total. One-step gains do not
add up exactly across decisions; the ranking says where to look, and a rule is
only judged by real paired games.

    python tools/heuristic_report.py runs/heuristic/mine1.pkl --out docs/HEURISTIC_MINING.md
"""

from __future__ import annotations

import argparse
import collections
import gzip
import math
import pickle
from pathlib import Path

LEVELS = {
    "situation": ("phase", "contract", "role", "pos"),
    "situation + heuristic reasons": ("phase", "contract", "role", "pos", "reasons"),
    "situation + alternative": ("phase", "contract", "pos", "led_suit_follow", "partner_winning", "heur_rank",
                                "teacher_rank", "same_suit"),
    "showing": ("phase", "n_shows", "heur_contract", "teacher_contract"),
}


def _key(r: dict, fields) -> tuple:
    return tuple(r.get(f) for f in fields)


def table(rows: list[dict], fields, deals: int, top: int, min_n: int, only_phase: str | None = None) -> list[str]:
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        if only_phase and r["phase"] != only_phase:
            continue
        groups[_key(r, fields)].append(r)
    out = []
    for key, g in groups.items():
        dis = [r for r in g if r["heur"] != r["teacher"]]
        gains = [r["q_teacher"] - r["q_heur"] for r in dis]
        if len(gains) < min_n:
            continue
        m = sum(gains) / len(gains)
        sd = math.sqrt(sum((x - m) ** 2 for x in gains) / (len(gains) - 1)) if len(gains) > 1 else float("nan")
        se = sd / math.sqrt(len(gains))
        zero = sum(1 for x in gains if abs(x) < 1e-9) / len(gains)
        out.append((sum(gains) / deals, key, len(g), len(dis) / len(g), m, se, zero))
    out.sort(key=lambda x: -x[0])
    lines = ["| " + " | ".join(fields) + " | decisions | disagree | gain per disagreement | zero-gain share | **gain per deal** |",
             "| " + " | ".join("---" for _ in fields) + " | ---: | ---: | ---: | ---: | ---: |"]
    for total, key, n, rate, m, se, zero in out[:top]:
        lines.append("| " + " | ".join(str(k) for k in key) +
                     f" | {n} | {rate:.0%} | {m:+.4f} ± {1.96 * se:.4f} | {zero:.0%} | **{total:+.5f}** |")
    return lines


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("data", type=Path)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--min-n", type=int, default=100)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    blob = pickle.load(gzip.open(a.data))
    rows, deals = blob["rows"], blob["args"]["deals"]
    dis = [r for r in rows if r["heur"] != r["teacher"]]
    gains = [r["q_teacher"] - r["q_heur"] for r in dis]
    clone_dis = [r for r in rows if r["priced"] and r["clone"] != r["heur"]]
    lines = [f"# Where partner_aware_lead_v2 loses: disagreement mining against VRPO3",
             "",
             f"Source: `{a.data}` ({deals} deals, {len(rows)} decisions, {blob['seconds'] / 60:.0f} min).",
             "",
             f"- Teacher disagrees on {len(dis) / len(rows):.1%} of decisions; mean priced gain per disagreement "
             f"{sum(gains) / len(gains):+.5f}; summed one-step gain {sum(gains) / deals:+.4f} per deal (both teams' "
             "decisions; one-step gains do not add up to a policy difference).",
             f"- Clone fidelity: the clone picks the heuristic's action on "
             f"{sum(r['clone'] == r['heur'] for r in rows) / len(rows):.1%} of decisions"
             + (f"; where it differs, its action prices {sum(r['q_clone'] - r['q_heur'] for r in clone_dis) / len(clone_dis):+.5f} "
                f"against the heuristic's (n={len(clone_dis)})." if clone_dis else "."),
             "- gain = q[teacher action] - q[heuristic action], every legal action played out from the exact "
             "full state with the heuristic's clone on all seats; the acting team's match-equity change.", ""]
    for name, fields in LEVELS.items():
        lines += [f"## By {name}", ""]
        lines += table(rows, fields, deals, a.top, a.min_n, only_phase="show" if name == "showing" else
                       ("play" if name == "situation + alternative" else None))
        lines.append("")
    text = "\n".join(lines)
    if a.out:
        a.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
