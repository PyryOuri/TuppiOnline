"""Summarise a paired timing file into the acceptance-gate numbers."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def median(values):
    return statistics.median(values) if values else float("nan")


def reduction(before, after):
    return 100.0 * (before - after) / before if before else float("nan")


def pooled(runs, extract):
    """Every individual measurement from every round of one side."""

    values = []
    for run in runs:
        values.extend(extract(run))
    return values


def per_round(runs, extract):
    return [median(extract(run)) for run in runs]


def line(name, before, after, gate=None):
    delta = reduction(before, after)
    verdict = ""
    if gate is not None:
        verdict = f"  gate>={gate:.0f}%  {'PASS' if delta >= gate else 'FAIL'}"
    print(f"  {name:34s} {before*1000:9.3f} ms -> {after*1000:9.3f} ms "
          f"{delta:7.2f}% less{verdict}")


def engine(data, labels, runs):
    before_label, after_label = labels
    print(f"\nINF-01  twelve-deal batch CPU  ({before_label} -> {after_label})")

    def batch_cpu(run):
        return [row["timing"]["cpu"]["total"] for row in run["engine_batch"]]

    before = pooled(runs[before_label], batch_cpu)
    after = pooled(runs[after_label], batch_cpu)
    print(f"  measurements: {len(before)} vs {len(after)}")
    line("whole batch (pooled median)", median(before), median(after), 25)
    print("  per-round medians "
          f"{before_label}: {[round(v, 4) for v in per_round(runs[before_label], batch_cpu)]}")
    print("  per-round medians "
          f"{after_label}:  {[round(v, 4) for v in per_round(runs[after_label], batch_cpu)]}")
    for stratum, gate in (("NOLO", 20), ("RAMI", 20), ("natural", None)):
        def extract(run, stratum=stratum):
            return [row["strata"][stratum] for row in run["engine_batch"]]
        line(f"stratum {stratum} (timed sections)",
             median(pooled(runs[before_label], extract)),
             median(pooled(runs[after_label], extract)), gate)

    def cold(run):
        return [run["engine_batch_cold"]["cpu"]["total"]]
    line("fresh process, first batch",
         median(pooled(runs[before_label], cold)),
         median(pooled(runs[after_label], cold)))
    digests = {label: {row["digest"] for run in runs[label]
                       for row in run["engine_batch"]} for label in labels}
    print(f"  action digests identical: "
          f"{digests[before_label] == digests[after_label]} "
          f"({len(digests[before_label] | digests[after_label])} distinct)")


def uct(data, labels, runs):
    before_label, after_label = labels
    print(f"\nINF-02  fast-UCT decisions  ({before_label} -> {after_label})")
    positions = [(row["position"], row["budget"])
                 for row in runs[before_label][0]["uct"]]
    for budget in (2, 4, 8, 16):
        total_before = total_after = 0.0
        for position, row_budget in positions:
            if row_budget != budget:
                continue
            def extract(run, position=position, budget=budget):
                return [row["timing"]["cpu"]["median"] for row in run["uct"]
                        if row["position"] == position and row["budget"] == budget]
            total_before += median(pooled(runs[before_label], extract))
            total_after += median(pooled(runs[after_label], extract))
        line(f"six positions, budget {budget}", total_before, total_after,
             10 if budget == 8 else None)
    print("  per position, budget 8:")
    for position, row_budget in positions:
        if row_budget != 8:
            continue
        def extract(run, position=position):
            return [row["timing"]["cpu"]["median"] for row in run["uct"]
                    if row["position"] == position and row["budget"] == 8]
        line(f"    {position}", median(pooled(runs[before_label], extract)),
             median(pooled(runs[after_label], extract)))
    for key, name in (("void_seeking_agents", "four void-lead agents"),
                      ("four_construct_calls", "four separate construct calls")):
        def extract(run, key=key):
            return [run[key]["cpu"]["median"]]
        line(name, median(pooled(runs[before_label], extract)),
             median(pooled(runs[after_label], extract)))
    digests = {label: {(row["position"], row["budget"], row["digest"])
                       for run in runs[label] for row in run["uct"]}
               for label in labels}
    print(f"  decision payload digests identical: "
          f"{digests[before_label] == digests[after_label]}")


def live(data, labels, runs):
    before_label, after_label = labels
    print(f"\nINF-03  live match_update CPU  ({before_label} -> {after_label})")
    keys = [(row["probe"], row["tricks"], row["recipients"], row["phase"])
            for row in runs[before_label][0]["live_update"]]
    for probe, tricks, recipients, phase in keys:
        def extract(run, probe=probe, recipients=recipients):
            return [row["timing"]["cpu"]["median"] for row in run["live_update"]
                    if row["probe"] == probe and row["recipients"] == recipients]
        gate = (35 if (tricks in (6, 12) and recipients == 4
                       and phase == "TRICK_PLAY") else None)
        line(f"{tricks:2d} tricks {phase[:5].lower():5s} "
             f"{recipients} recipient(s)",
             median(pooled(runs[before_label], extract)),
             median(pooled(runs[after_label], extract)), gate)
    payloads = {label: {(row["probe"], row["recipients"], row["payload_bytes"])
                        for run in runs[label] for row in run["live_update"]}
                for label in labels}
    print(f"  payload byte counts identical: "
          f"{payloads[before_label] == payloads[after_label]}")


def main() -> int:
    data = json.loads(Path(sys.argv[1]).read_text())
    labels = data["labels"]
    runs = data["runs"]
    print(f"paired workload {data['only']}  reps/process={data['reps']}  "
          f"order={''.join(data['order'])}")
    first = runs[labels[0]][0]
    if "engine_batch" in first:
        engine(data, labels, runs)
    if "uct" in first:
        uct(data, labels, runs)
    if "live_update" in first:
        live(data, labels, runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
