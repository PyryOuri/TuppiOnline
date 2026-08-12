#!/usr/bin/env python3
"""Run and render the research-only RAMI/NOLO threshold experiment."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from tuppi_analysis.rami_nolo_threshold import ExperimentConfig, run_experiment


DEFAULT_OUTPUT_ROOT = Path(
    "/Users/pyryouri/Developer/TuppiRuns/rami-nolo-threshold"
)
DEFAULT_REPORT = Path("docs/analysis/rami_nolo_threshold.md")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tune a RAMI strength threshold on direct deterministic deals, then "
            "compare the frozen candidate with production on a fresh held-out split."
        )
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tuning-decisions", type=int, default=4_096)
    parser.add_argument("--validation-decisions", type=int, default=4_096)
    parser.add_argument("--bootstrap-replicates", type=int, default=5_000)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--tuning-seed", default="rami-nolo-threshold-tuning-v1"
    )
    parser.add_argument(
        "--validation-seed", default="rami-nolo-threshold-validation-v1"
    )
    parser.add_argument(
        "--analysis-seed", default="rami-nolo-threshold-analysis-v1"
    )
    return parser.parse_args()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_json(path: Path, value: object) -> None:
    _atomic_text(
        path,
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
    )


def _write_jsonl(path: Path, records: tuple[dict[str, object], ...]) -> None:
    lines = [
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        for record in records
    ]
    _atomic_text(path, "\n".join(lines) + "\n")


def _write_csv(path: Path, rows: tuple[dict[str, object], ...], fields: list[str]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_text(path, stream.getvalue())


def _number(value: object, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def _percent(value: object, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{100.0 * float(value):.{digits}f}%"


def _threshold_label(row: dict[str, object]) -> str:
    if row["control"] is not None:
        return str(row["control"]).replace("_", " ").upper()
    return _number(row["threshold"], 2)


def _selected_sweep_rows(
    sweep: tuple[dict[str, object], ...], selection: dict[str, object]
) -> list[dict[str, object]]:
    numeric = [row for row in sweep if row["threshold"] is not None]
    targets = {
        float(selection["numeric_best_threshold"]),
        float(selection["selected_candidate_threshold"]),
        float(selection["plateau_low"]),
        float(selection["plateau_high"]),
        15.0,
        float(numeric[0]["threshold"]),
        float(numeric[-1]["threshold"]),
    }
    candidate = float(selection["selected_candidate_threshold"])
    targets.update((candidate - 1.0, candidate + 1.0))
    selected = [
        row
        for row in numeric
        if any(abs(float(row["threshold"]) - target) < 1e-12 for target in targets)
    ]
    selected.extend(row for row in sweep if row["control"] is not None)
    return sorted(
        selected,
        key=lambda row: (
            row["threshold"] is None,
            float(row["threshold"]) if row["threshold"] is not None else str(row["control"]),
        ),
    )


def _svg_curve(
    sweep: tuple[dict[str, object], ...], selection: dict[str, object]
) -> str:
    rows = [row for row in sweep if row["threshold"] is not None]
    width, height = 920, 480
    left, right, top, bottom = 75, 25, 35, 65
    plot_width = width - left - right
    plot_height = height - top - bottom
    xs = [float(row["threshold"]) for row in rows]
    ys = [float(row["mean_partnership_utility"]) for row in rows]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if min_y == max_y:
        min_y -= 1.0
        max_y += 1.0
    padding = max(0.1, (max_y - min_y) * 0.08)
    min_y -= padding
    max_y += padding

    def px(value: float) -> float:
        return left + (value - min_x) / (max_x - min_x) * plot_width

    def py(value: float) -> float:
        return top + (max_y - value) / (max_y - min_y) * plot_height

    points = " ".join(f"{px(x):.2f},{py(y):.2f}" for x, y in zip(xs, ys, strict=True))
    plateau_x = px(float(selection["plateau_low"]))
    plateau_width = px(float(selection["plateau_high"])) - plateau_x
    current_x = px(15.0)
    candidate_x = px(float(selection["selected_candidate_threshold"]))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<rect x="{plateau_x:.2f}" y="{top}" width="{max(1.0, plateau_width):.2f}" height="{plot_height}" fill="#dbeafe" opacity="0.65"/>',
        f'<line x1="{left}" y1="{top + plot_height}" x2="{width-right}" y2="{top + plot_height}" stroke="#111827"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" stroke="#111827"/>',
    ]
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        y_value = min_y + fraction * (max_y - min_y)
        y = py(y_value)
        lines.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="#e5e7eb"/>'
        )
        lines.append(
            f'<text x="{left-10}" y="{y+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{y_value:.2f}</text>'
        )
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x_value = min_x + fraction * (max_x - min_x)
        x = px(x_value)
        lines.append(
            f'<text x="{x:.2f}" y="{top+plot_height+24}" text-anchor="middle" font-family="sans-serif" font-size="12">{x_value:.1f}</text>'
        )
    lines.extend(
        [
            f'<polyline points="{points}" fill="none" stroke="#0f766e" stroke-width="2.5"/>',
            f'<line x1="{current_x:.2f}" y1="{top}" x2="{current_x:.2f}" y2="{top+plot_height}" stroke="#dc2626" stroke-width="2" stroke-dasharray="7 5"/>',
            f'<line x1="{candidate_x:.2f}" y1="{top}" x2="{candidate_x:.2f}" y2="{top+plot_height}" stroke="#2563eb" stroke-width="2" stroke-dasharray="3 4"/>',
            f'<text x="{width/2:.1f}" y="20" text-anchor="middle" font-family="sans-serif" font-size="16" font-weight="600">Tuning threshold curve</text>',
            f'<text x="{width/2:.1f}" y="{height-15}" text-anchor="middle" font-family="sans-serif" font-size="13">RAMI score threshold (production NOLO veto fixed at 2)</text>',
            f'<text x="18" y="{height/2:.1f}" text-anchor="middle" transform="rotate(-90 18 {height/2:.1f})" font-family="sans-serif" font-size="13">Mean acting-partnership deal utility</text>',
            f'<text x="{current_x+5:.2f}" y="{top+16}" font-family="sans-serif" font-size="11" fill="#dc2626">current 15</text>',
            f'<text x="{candidate_x+5:.2f}" y="{top+31}" font-family="sans-serif" font-size="11" fill="#2563eb">candidate {_number(selection["selected_candidate_threshold"], 2)}</text>',
            '</svg>',
        ]
    )
    return "\n".join(lines) + "\n"


def _strata_table(strata: dict[str, object]) -> str:
    boundary = strata["boundary_strata"]
    if not isinstance(boundary, dict):
        return "No stratified results available."
    labels = {
        "hand_hcp": "Hand HCP",
        "longest_suit_length": "Longest suit",
        "suit_shape": "Suit shape",
        "shown_card_rank": "Shown-card rank",
        "dealer_forehand_position": "Dealer/forehand position",
        "previous_nolo_shows": "Previous NOLO shows",
        "match_score_category": "Match-score category",
    }
    output = [
        "| Dimension | Most NOLO-favouring stratum | Most RAMI-favouring stratum |",
        "|---|---:|---:|",
    ]
    for dimension, label in labels.items():
        raw_rows = boundary.get(dimension, ())
        rows = [row for row in raw_rows if int(row["decisions"]) >= 20]
        if not rows:
            output.append(f"| {label} | — | — |")
            continue
        low = min(rows, key=lambda row: float(row["mean_rami_minus_nolo_utility"]))
        high = max(rows, key=lambda row: float(row["mean_rami_minus_nolo_utility"]))
        output.append(
            f"| {label} | {low['stratum']}: {_number(low['mean_rami_minus_nolo_utility'])} (n={low['decisions']}) "
            f"| {high['stratum']}: {_number(high['mean_rami_minus_nolo_utility'])} (n={high['decisions']}) |"
        )
    return "\n".join(output)


def _report(
    result: dict[str, object], *, output_root: Path, command: str
) -> str:
    production = result["production_rule"]
    selection = result["tuning_selection"]
    comparison = result["validation_comparison"]
    tuning_manifest = result["tuning_manifest"]
    validation_manifest = result["validation_manifest"]
    sweep = result["tuning_threshold_sweep"]
    probabilities = result["validation_probability_by_score"]
    strata = result["stratified_analysis"]
    payoff = result["payoff_analysis"]
    if not all(
        isinstance(value, dict)
        for value in (
            production,
            selection,
            comparison,
            tuning_manifest,
            validation_manifest,
            strata,
            payoff,
        )
    ):
        raise RuntimeError("experiment result is malformed")
    if not isinstance(sweep, tuple) or not isinstance(probabilities, tuple):
        raise RuntimeError("experiment result tables are malformed")
    current_metrics = comparison["current_metrics"]
    candidate_metrics = comparison["candidate_metrics"]
    if not isinstance(current_metrics, dict) or not isinstance(candidate_metrics, dict):
        raise RuntimeError("validation metrics are malformed")

    sweep_lines = [
        "| Threshold/control | Mean utility | RAMI frequency | RAMI success | Stolen RAMI | Points scored | Points conceded |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in _selected_sweep_rows(sweep, selection):
        sweep_lines.append(
            f"| {_threshold_label(row)} | {_number(row['mean_partnership_utility'])} "
            f"| {_percent(row['rami_frequency'])} | {_percent(row['rami_success_rate'])} "
            f"| {_percent(row['stolen_rami_rate'])} | {_number(row['expected_positive_points'])} "
            f"| {_number(row['expected_points_conceded'])} |"
        )

    low = min(
        float(selection["plateau_low"]),
        float(selection["selected_candidate_threshold"]),
        15.0,
    ) - 2.0
    high = max(
        float(selection["plateau_high"]),
        float(selection["selected_candidate_threshold"]),
        15.0,
    ) + 2.0
    probability_lines = [
        "| RAMI score | n | RAMI succeeds | RAMI stolen | RAMI − NOLO utility | Veto-pass n | Veto-pass success | Veto-pass RAMI − NOLO |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in probabilities:
        score = float(row["rami_score"])
        if low <= score <= high and int(row["decisions"]) >= 5:
            probability_lines.append(
                f"| {_number(score, 2)} | {row['decisions']} | {_percent(row['rami_success_probability'])} "
                f"| {_percent(row['stolen_rami_probability'])} | {_number(row['mean_rami_minus_nolo_utility'])} "
                f"| {row['nolo_veto_pass_count']} | {_percent(row['veto_pass_rami_success_probability'])} "
                f"| {_number(row['veto_pass_mean_rami_minus_nolo_utility'])} |"
            )
    if len(probability_lines) == 2:
        probability_lines.append("| — | — | — | — | — | — | — | — |")

    interval = comparison["bootstrap_95_ci"]
    interval_text = (
        "—"
        if not isinstance(interval, list)
        else f"[{_number(interval[0])}, {_number(interval[1])}]"
    )
    production_rami = production["rami_score"]
    production_nolo = production["nolo_score"]
    eligibility = production["showing_eligibility"]
    if not isinstance(production_rami, dict) or not isinstance(production_nolo, dict) or not isinstance(eligibility, dict):
        raise RuntimeError("production-rule details are malformed")

    gate = str(result["decision_gate"])
    text = f"""# RAMI versus NOLO showing threshold

This is a research-only counterfactual experiment over the frozen `partner_aware_v1` policy. It does **not** modify or register a new production agent, and it directly generates deterministic deals without opening or reading any fixture bank. `sealed_bank_opened` is `false` in every result manifest.

## Current production decision rule

`partner_aware_v1` uses:

```text
RAMI score = {production_rami['formula']}
NOLO score = {production_nolo['formula']}
choose RAMI iff RAMI score >= {production_rami['threshold']:.1f}
                 and NOLO score <= {production_nolo['veto_threshold']:.1f}
```

HCP is A=4, K=3, Q=2, J=1; controls are aces plus kings. Low cards are ranks 2–4, top-five cards are 10–A, and honours are J–A. The second comparison is an independent NOLO-suitability veto, so the production rule is not a single unconstrained scalar threshold.

Match score does not affect this profile (`match_state_enabled=false`). The experiment nevertheless cycles through table, up, down, and near-target match scores to verify that conclusion in context.

Both contracts are always legally expressible under the authoritative fallback hierarchy. Ranks 3–9 of the contract colour are preferred (red for RAMI, black for NOLO); otherwise an eligible off-colour 3–9 is shown verbally, and if none exists any hand card may be shown verbally. Conditional on a contract, the policy chooses the lowest eligible rank and then HDCS suit precedence. A RAMI declaration ends showing immediately; NOLO passes showing clockwise until another player declares RAMI or all four declare NOLO.

## Design and corpus

Each decision record starts both forced branches from the same immutable, private-state digest and preserves deal, seat, dealer, partnership, public showing history, hand, and match score. The forced action is the policy's own best-ranked legal action for that contract (the lowest eligible rank under this profile). Four ordinary frozen `partner_aware_v1` policies complete showing and trick play. A forced NOLO can therefore lead to a later player's RAMI, which is part of the real value of choosing NOLO now.

The estimand is the local contract choice at production-reachable showing states. Thresholds are applied to the same focal-decision corpus, while every later showing/play decision remains the frozen production policy, exactly as specified for the counterfactual comparison.

The primary utility is signed production deal points for the acting partnership: points won minus points conceded. This retains the real scoring asymmetry: made RAMI is `4 × (declaring tricks − 6)` while stolen RAMI is `8 × (defender tricks − 6)`. Trick count is secondary.

- Tuning: **{tuning_manifest['decisions']} decisions from {tuning_manifest['retained_source_deals']} generated source deals** (`{tuning_manifest['direct_generator_seed']}`).
- Fresh held-out validation: **{validation_manifest['decisions']} decisions from {validation_manifest['retained_source_deals']} generated source deals** (`{validation_manifest['direct_generator_seed']}`).
- Statistical cluster: source deal; confidence intervals resample whole source deals because one deal can contribute multiple decisions.
- Validation discipline: the candidate was frozen from tuning before validation; validation compares only that candidate with production. The full validation threshold curve was not inspected.

## Tuning threshold sweep

The sweep covers every 0.25 point across the observed RAMI-score range plus two points at each tail, holds the production NOLO veto at 2, includes threshold 15, and adds explicit always-RAMI and always-NOLO controls. The complete dense table is in `{output_root / 'tuning_threshold_sweep.csv'}` and the curve is in `{output_root / 'threshold_curve.svg'}`.

{chr(10).join(sweep_lines)}

- Numerical tuning maximum: **{_number(selection['numeric_best_threshold'], 2)}** (mean utility {_number(selection['numeric_best_utility'])}).
- Prespecified one-SE near-optimal interval: **{_number(selection['plateau_low'], 2)} to {_number(selection['plateau_high'], 2)}**.
- Tuning-selected central candidate: **{_number(selection['selected_candidate_threshold'], 2)}**.
- Production threshold 15 in plateau: **{str(selection['production_threshold_in_plateau']).lower()}**.

## Fresh held-out comparison

| Policy | Mean utility | Deal-win probability | Expected tricks | RAMI frequency | RAMI success | Stolen RAMI | Points scored | Points conceded |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Current 15.00 | {_number(current_metrics['mean_partnership_utility'])} | {_percent(current_metrics['win_probability'])} | {_number(current_metrics['expected_tricks'])} | {_percent(current_metrics['rami_frequency'])} | {_percent(current_metrics['rami_success_rate'])} | {_percent(current_metrics['stolen_rami_rate'])} | {_number(current_metrics['expected_positive_points'])} | {_number(current_metrics['expected_points_conceded'])} |
| Candidate {_number(selection['selected_candidate_threshold'], 2)} | {_number(candidate_metrics['mean_partnership_utility'])} | {_percent(candidate_metrics['win_probability'])} | {_number(candidate_metrics['expected_tricks'])} | {_percent(candidate_metrics['rami_frequency'])} | {_percent(candidate_metrics['rami_success_rate'])} | {_percent(candidate_metrics['stolen_rami_rate'])} | {_number(candidate_metrics['expected_positive_points'])} | {_number(candidate_metrics['expected_points_conceded'])} |

- Mean paired utility difference, candidate minus current: **{_number(comparison['mean_utility_difference'])} points per decision**.
- Source-deal-cluster bootstrap 95% CI: **{interval_text}** ({comparison['bootstrap_replicates']} replicates).
- Decisions choosing a different contract: **{comparison['changed_decisions']} / {validation_manifest['decisions']}**, across **{comparison['changed_source_deals']} source deals**.
- Decision-level win/tie/loss across all decisions: **{comparison['decision_level_win_tie_loss']}**; among the {comparison['changed_decisions']} changed choices: **{comparison['changed_decision_win_tie_loss']}**.
- Source-deal-level win/tie/loss across all source deals: **{comparison['source_deal_level_win_tie_loss']}**; among the {comparison['changed_source_deals']} affected deals: **{comparison['changed_source_deal_win_tie_loss']}**.

## Success probability and payoff around the threshold

{chr(10).join(probability_lines)}

Within one RAMI-score point of the tuning plateau (and only where the production NOLO veto passes), RAMI succeeded in **{_percent(payoff['boundary_rami_success_probability'])}** of {payoff['boundary_decisions']} held-out decisions. Mean successful RAMI points were **{_number(payoff['mean_points_if_rami_made'])}** and mean stolen-RAMI points conceded were **{_number(payoff['mean_points_if_rami_stolen'])}**. Combining those empirical RAMI payoffs with the observed NOLO utility gives an approximate break-even RAMI success probability of **{_percent(payoff['payoff_implied_break_even_success_probability'])}**. The first adequately populated exact score bin with non-negative veto-pass RAMI-minus-NOLO utility was **{_number(payoff['empirical_first_nonnegative_score_bin'], 2)}**, at an empirical RAMI success probability of **{_percent(payoff['empirical_success_probability_at_first_nonnegative_bin'])}**. Exact quarter-point bins are visibly noisy and non-monotone, so candidate selection uses the tuning plateau rather than this first crossing. These are environment-specific empirical estimates, not assumed 50% or 60% cutoffs.

## Stratified findings

The prespecified boundary subset contains **{strata['boundary_decisions']}** held-out veto-passing decisions. Full strata are in `{output_root / 'stratified_analysis.json'}`.

{_strata_table(strata)}

Global-threshold adequacy: **appears adequate at the tested resolution** — {strata['single_threshold_reason']}. Some small cells have large descriptive effects, but cells below the prespecified `n >= 100` evidence rule are hypothesis-generating only. The experiment does not implement a context-dependent replacement.

## Reproduction and artifacts

From the repository root:

```bash
{command}
```

Machine-readable records, sweep tables, the paired comparison, score-conditional probabilities, stratification, summary, hashes, and plot are under `{output_root}`. The decision JSONL files contain the exact acting hand and public history plus a full private-state digest; complete deals can be regenerated from the declared split seed and source-deal index.

Decision-gate reason: {result['decision_gate_reason']}.

{gate}
"""
    return text


def _artifact_manifest(output_root: Path, report: Path) -> dict[str, object]:
    artifacts = []
    for path in sorted(output_root.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        payload = path.read_bytes()
        artifacts.append(
            {
                "bytes": len(payload),
                "path": path.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    report_payload = report.read_bytes()
    return {
        "artifacts": artifacts,
        "production_agent_modified": False,
        "report": {
            "path": str(report),
            "sha256": hashlib.sha256(report_payload).hexdigest(),
        },
        "schema_version": "tuppi.analysis.rami_nolo_artifact_manifest.v1",
        "sealed_bank_opened": False,
    }


def main() -> None:
    args = _arguments()
    config = ExperimentConfig(
        tuning_decisions=args.tuning_decisions,
        validation_decisions=args.validation_decisions,
        tuning_seed=args.tuning_seed,
        validation_seed=args.validation_seed,
        analysis_seed=args.analysis_seed,
        bootstrap_replicates=args.bootstrap_replicates,
        workers=args.workers,
    )
    output_root = args.output_root.resolve()
    report_path = args.report.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    last_progress: dict[str, int] = {}

    def progress(split: str, completed: int, total: int) -> None:
        interval = max(1, total // 20)
        if completed == total or completed == 1 or completed % interval == 0:
            if last_progress.get(split) != completed:
                print(
                    f"{split}: source deals {completed}/{total}",
                    file=sys.stderr,
                    flush=True,
                )
                last_progress[split] = completed

    result = run_experiment(config, progress=progress)
    tuning_records = result["tuning_corpus"]
    validation_records = result["validation_corpus"]
    tuning_sweep = result["tuning_threshold_sweep"]
    probability_rows = result["validation_probability_by_score"]
    if not all(
        isinstance(value, tuple)
        for value in (tuning_records, validation_records, tuning_sweep, probability_rows)
    ):
        raise RuntimeError("experiment returned malformed artifact tables")

    _write_json(output_root / "config.json", result["config"])
    _write_json(output_root / "production_rule.json", result["production_rule"])
    _write_jsonl(output_root / "tuning_decisions.jsonl", tuning_records)
    _write_jsonl(output_root / "validation_decisions.jsonl", validation_records)
    _write_json(output_root / "tuning_threshold_sweep.json", tuning_sweep)
    _write_csv(
        output_root / "tuning_threshold_sweep.csv",
        tuning_sweep,
        [
            "threshold",
            "control",
            "is_current",
            "decisions",
            "source_deals",
            "mean_partnership_utility",
            "mean_source_deal_utility",
            "win_probability",
            "expected_tricks",
            "rami_count",
            "rami_frequency",
            "rami_success_rate",
            "stolen_rami_rate",
            "expected_positive_points",
            "expected_points_conceded",
        ],
    )
    _write_json(output_root / "tuning_selection.json", result["tuning_selection"])
    _write_json(output_root / "validation_comparison.json", result["validation_comparison"])
    _write_json(output_root / "validation_probability_by_score.json", probability_rows)
    _write_csv(
        output_root / "validation_probability_by_score.csv",
        probability_rows,
        [
            "rami_score",
            "decisions",
            "nolo_veto_pass_count",
            "rami_success_probability",
            "stolen_rami_probability",
            "mean_rami_utility",
            "mean_nolo_utility",
            "mean_rami_minus_nolo_utility",
            "veto_pass_rami_success_probability",
            "veto_pass_stolen_rami_probability",
            "veto_pass_mean_rami_minus_nolo_utility",
        ],
    )
    _write_json(output_root / "stratified_analysis.json", result["stratified_analysis"])
    _write_json(output_root / "payoff_analysis.json", result["payoff_analysis"])
    _atomic_text(
        output_root / "threshold_curve.svg",
        _svg_curve(tuning_sweep, result["tuning_selection"]),  # type: ignore[arg-type]
    )

    summary = {
        key: value
        for key, value in result.items()
        if key
        not in {
            "tuning_corpus",
            "tuning_threshold_sweep",
            "validation_corpus",
            "validation_probability_by_score",
        }
    }
    summary["artifact_files"] = [
        "config.json",
        "manifest.json",
        "payoff_analysis.json",
        "production_rule.json",
        "stratified_analysis.json",
        "summary.json",
        "threshold_curve.svg",
        "tuning_decisions.jsonl",
        "tuning_selection.json",
        "tuning_threshold_sweep.csv",
        "tuning_threshold_sweep.json",
        "validation_comparison.json",
        "validation_decisions.jsonl",
        "validation_probability_by_score.csv",
        "validation_probability_by_score.json",
    ]
    _write_json(output_root / "summary.json", summary)

    default_report_path = (Path.cwd() / DEFAULT_REPORT).resolve()
    report_argument = (
        str(DEFAULT_REPORT)
        if report_path == default_report_path
        else str(report_path)
    )
    command = (
        "PYTHONPATH=src python3 tools/run_rami_nolo_threshold.py "
        f"--output-root {output_root} --report {report_argument} "
        f"--tuning-decisions {config.tuning_decisions} "
        f"--validation-decisions {config.validation_decisions} "
        f"--bootstrap-replicates {config.bootstrap_replicates} "
        f"--workers {config.workers} "
        f"--tuning-seed {config.tuning_seed} "
        f"--validation-seed {config.validation_seed} "
        f"--analysis-seed {config.analysis_seed}"
    )
    _atomic_text(
        report_path,
        _report(result, output_root=output_root, command=command),
    )
    _write_json(output_root / "manifest.json", _artifact_manifest(output_root, report_path))
    elapsed = time.perf_counter() - started
    print(
        json.dumps(
            {
                "candidate_threshold": result["tuning_selection"]["selected_candidate_threshold"],  # type: ignore[index]
                "decision_gate": result["decision_gate"],
                "elapsed_seconds": elapsed,
                "output_root": str(output_root),
                "report": str(report_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
