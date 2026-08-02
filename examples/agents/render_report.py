#!/usr/bin/env python3
"""Render the frozen Phase 4 report into the evaluation document.

The results section of ``docs/agents/phase4_evaluation.md`` is generated from
``reports/phase4/baseline_report.json`` so that prose and numbers cannot drift.
Run from the repository root:

    PYTHONPATH=src python examples/agents/render_report.py
"""

from __future__ import annotations

from pathlib import Path

from tuppi_agents.evaluation import load_report


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "phase4" / "baseline_report.json"
DOCUMENT = ROOT / "docs" / "agents" / "phase4_evaluation.md"
BEGIN = "<!-- BEGIN GENERATED RESULTS -->"
END = "<!-- END GENERATED RESULTS -->"


def _number(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return str(value)
    return f"{value:.{digits}f}"


def _interval(values) -> str:
    if not values:
        return "n/a"
    return f"[{values[0]:.2f}, {values[1]:.2f}]"


def _comparison_rows(comparisons, wanted: str) -> list[str]:
    rows = [
        "| Comparison | Team A | Team B | n | Mean paired utility (A - B) | 95% CI | Bootstrap CI | Sign p | Perm p | A deal win rate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in comparisons:
        if item["result_class"] != wanted:
            continue
        inference = item["primary_inference"]
        outcome = item["outcome_metrics"]
        rows.append(
            "| `{name}` | {a} | {b} | {n} | {mean} | {ci} | {boot} | {sign} | {perm} | {win} |".format(
                name=item["name"],
                a=item["team_a"]["name"].replace("_clone", ""),
                b=item["team_b"]["name"].replace("_clone", ""),
                n=inference["independent_base_deals"],
                mean=_number(inference["mean_paired_utility"]),
                ci=_interval(inference["confidence_interval"]),
                boot=_interval(inference["bootstrap_confidence_interval"]),
                sign=_number(inference["sign_test_p_value"], 3),
                perm=_number(inference["paired_permutation_p_value"], 3),
                win=_number(outcome["team_a_deal_win_rate"], 3),
            )
        )
    return rows if len(rows) > 2 else []


def _behaviour_rows(comparisons) -> list[str]:
    rows = [
        "| Comparison | RAMI rate | Stolen RAMI given RAMI | Reset rate | Mean tricks A | Mean tricks B | Failed games | Censored |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in comparisons:
        contract = item["contract_metrics"]
        outcome = item["outcome_metrics"]
        execution = item["execution_metrics"]
        rows.append(
            "| `{name}` | {rami} | {stolen} | {reset} | {ta} | {tb} | {failed} | {cens} |".format(
                name=item["name"],
                rami=_number(contract["rami_declaration_rate"], 3),
                stolen=_number(contract["stolen_rami_rate_given_rami"], 3),
                reset=_number(outcome["reset_rate"], 3),
                ta=_number(outcome["mean_tricks_team_a"]),
                tb=_number(outcome["mean_tricks_team_b"]),
                failed=execution["failed_games"],
                cens=item["censored_games"],
            )
        )
    return rows


def _match_rows(comparisons) -> list[str]:
    rows = [
        "| Comparison | Streams | Completed games | Censored | Match win rate A |",
        "| --- | --- | --- | --- | --- |",
    ]
    found = False
    for item in comparisons:
        if item["mode"] != "match":
            continue
        found = True
        execution = item["execution_metrics"]
        rows.append(
            "| `{name}` | {n} | {ok} | {cens} | {win} |".format(
                name=item["name"],
                n=item["primary_inference"]["independent_base_deals"],
                ok=execution["successful_games"],
                cens=item["censored_games"],
                win=_number(item["outcome_metrics"]["match_win_rate_team_a"], 3),
            )
        )
    return rows if found else []


def _crossplay_rows(crossplay) -> list[str]:
    if not crossplay:
        return []
    names = {item["team_id"]: item["name"] for item in crossplay["team_names"]}
    rows = [
        "| Row team | Column team | Mean paired utility (row orientation) | n | Failures |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell in crossplay["cells"]:
        if cell["row_team_id"] == cell["column_team_id"]:
            continue
        rows.append(
            "| {row} | {column} | {value} | {n} | {failures} |".format(
                row=names.get(cell["row_team_id"], "?").replace("_clone", ""),
                column=names.get(cell["column_team_id"], "?").replace("_clone", ""),
                value=_number(cell["mean_paired_utility_row_orientation"]),
                n=cell["independent_base_deals"],
                failures=cell["failure_count"],
            )
        )
    return rows


def _performance_rows(performance) -> list[str]:
    if not performance:
        return []
    rows = [
        "| Agent | Deals/s | Mean action latency (ms) | p95 (ms) | Relative wall clock |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in performance["throughput"]:
        latency = item["latency"]
        rows.append(
            "| `{agent}` | {rate} | {mean} | {p95} | {rel} |".format(
                agent=item["agent"],
                rate=_number(item["deals_per_second"]),
                mean=_number((latency["mean_seconds"] or 0) * 1000, 3),
                p95=_number((latency["p95_seconds"] or 0) * 1000, 3),
                rel=_number(item["relative_wall_clock"], 3),
            )
        )
    return rows


def render() -> str:
    report = load_report(REPORT)
    comparisons = report["comparisons"]
    lines: list[str] = ["", "## Frozen results", ""]
    lines.append(
        "Generated from `reports/phase4/baseline_report.json` by "
        "`examples/agents/render_report.py`. Paired utility is signed deal "
        "points per independently generated base deal, positive for Team A. "
        "These are development-bank numbers: descriptive, not sealed."
    )
    for title, wanted in (
        ("### Ladder and development comparisons", "development"),
        ("### Ablations", "ablation"),
        ("### Protocol-control floor", "protocol_control"),
    ):
        rows = _comparison_rows(comparisons, wanted)
        if rows:
            lines.extend(["", title, ""])
            lines.extend(rows)
    if comparisons:
        lines.extend(["", "### Declaration and outcome behaviour", ""])
        lines.extend(_behaviour_rows(comparisons))
    match_rows = _match_rows(comparisons)
    if match_rows:
        lines.extend(["", "### Complete-match results", ""])
        lines.extend(match_rows)
    crossplay_rows = _crossplay_rows(report.get("crossplay"))
    if crossplay_rows:
        lines.extend(["", "### Cross-play (8 base deals per cell, descriptive)", ""])
        lines.extend(crossplay_rows)
    performance_rows = _performance_rows(report.get("performance"))
    if performance_rows:
        lines.extend(["", "### Performance", ""])
        lines.extend(performance_rows)
        performance = report["performance"]
        overhead = performance.get("diagnostics_overhead", {})
        if overhead:
            lines.extend(
                [
                    "",
                    "Diagnostics overhead ratio for `match_aware_v1`: "
                    f"{_number(overhead.get('overhead_ratio'), 3)} wall clock, "
                    "with provably identical play.",
                ]
            )
        lines.extend(["", performance["note"]])
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    text = DOCUMENT.read_text(encoding="utf-8")
    start = text.index(BEGIN) + len(BEGIN)
    end = text.index(END)
    DOCUMENT.write_text(text[:start] + render() + text[end:], encoding="utf-8")
    print(DOCUMENT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
