"""Cheap root-prior decision diagnostics on a completed bank; no model or native imports.

Q changes are model predictions on fixed baseline trajectories, not measured
policy gains. Partial/adaptive pricing is excluded; allocation cannot be replayed.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tuppi_ai.policy_prior import action_scores, select_action, soft_offsets

SCHEMA = "tuppi.root_prior_bank.v1"


def summarize(records: list[dict], strengths: list[float]) -> dict:
    if not records or records[0].get("schema") != SCHEMA or records[0].get("kind") != "manifest":
        raise ValueError("root-prior manifest missing or wrong schema")
    meta = records[0]
    if meta.get("ruleset") != "project_target_v3" or not isinstance(meta.get("worlds"), int) or meta["worlds"] < 1:
        raise ValueError("bank must identify v3 and a positive world count")
    if records[-1].get("kind") != "completion":
        raise ValueError("bank is incomplete (no completion record)")
    if not strengths:
        raise ValueError("at least one strength is required")
    for tau in strengths:
        soft_offsets([0], tau)
    rows, skipped, seen = [], 0, set()
    for record in records[1:-1]:
        if record.get("kind") == "deal":
            continue
        if record.get("kind") != "decision":
            raise ValueError("unknown bank record")
        key = (record["deal"], record["step"])
        if key in seen:
            raise ValueError("duplicate source decision")
        seen.add(key)
        ids, values, logits, counts = (record[name] for name in ("action_ids", "values", "actor_logits", "world_counts"))
        if len(set(ids)) != len(ids) or not len(ids) == len(values) == len(logits) == len(counts):
            raise ValueError("legal ids, values, logits and world counts must align")
        phase = record["phase"]
        bounds = (0, 52) if phase == "TRICK_PLAY" else (52, 156) if phase == "SHOWING" else None
        if bounds is None or not all(type(i) is int and bounds[0] <= i < bounds[1] for i in ids):
            raise ValueError("ordinary legal action ids required")
        action_scores(values)
        soft_offsets(logits, 0)
        if record["baseline_action"] not in ids:
            raise ValueError("baseline action is outside the legal set")
        if not all(type(n) is int and 1 <= n <= meta["worlds"] for n in counts):
            raise ValueError("invalid sample counts")
        if any(n != meta["worlds"] for n in counts):
            skipped += 1
            continue
        rows.append(record)
    if records[-1].get("decisions") != len(seen):
        raise ValueError("completion decision count does not match the bank")
    arms = []
    for tau in strengths:
        changes, deltas = [], []
        for row in rows:
            chosen = select_action(row["values"], soft_offsets(row["actor_logits"], tau))
            original = row["action_ids"].index(row["baseline_action"])
            changes.append(chosen != original)
            deltas.append(row["values"][chosen] - row["values"][original])
        arms.append({"strength": tau, "changed_decisions": sum(changes),
                     "change_fraction": statistics.fmean(changes) if rows else None,
                     "mean_model_Q_change": statistics.fmean(deltas) if rows else None})
    return {"schema": SCHEMA, "source_manifest": meta, "eligible_decisions": len(rows),
            "eligible_deals": len({r["deal"] for r in rows}), "skipped_partial_pricing": skipped,
            "arms": arms, "strength_evidence": False,
            "qualification": "Fixed-trajectory diagnostics only. Fresh games must test changed policies and adaptive allocation."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("bank", type=Path)
    p.add_argument("--tau", type=float, nargs="+", required=True)
    a = p.parse_args()
    records = [json.loads(s) for s in a.bank.read_text().splitlines() if s.strip()]
    print(json.dumps(summarize(records, a.tau), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
