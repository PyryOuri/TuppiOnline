"""Paired/clustered endpoints, censoring bounds, MSE endpoints and cost accounting (C0.07).

Rules implemented here (IMPLEMENTATION_SPEC.md 2.4, 3.4, 9):

- A cluster (base deck bundle, match pair, originating deal) is the unit; its
  rows are never resampled separately.
- An unresolved or failed leg is never scored 0.5. Match summaries report the
  decided-only result and worst-case bounds (each unresolved leg set to 0 and
  to 1 *before* pairing); a 0.5 midpoint appears only as a labelled
  descriptive sensitivity.
- Identical policies are analysed like any other pair; nothing forces 0.5 or 0.
- Reference noise cancels from a DIFFERENCE of MSEs in expectation, not from
  their ratio: `mse_endpoints` subtracts the estimated reference variance
  (from independent reference replicates) before forming a ratio.
- Local savings do not add up to a program saving: `total_saving_bound`.
"""

from __future__ import annotations

import math
import statistics as st

import numpy as np

Z95 = 1.959963984540054


def mean_ci(values, z: float = Z95) -> dict:
    """Mean and normal 95% interval over independent cluster values (ddof=1)."""
    v = [float(x) for x in values]
    n = len(v)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "se": None, "ci95": None}
    m = st.fmean(v)
    sd = st.stdev(v) if n > 1 else float("nan")
    se = sd / math.sqrt(n) if n > 1 else float("nan")
    return {"n": n, "mean": m, "sd": sd, "se": se, "ci95": [m - z * se, m + z * se] if n > 1 else None}


def cluster_bootstrap(clusters: dict, stat, reps: int, rng: np.random.Generator) -> dict:
    """Bootstrap resampling whole clusters (each value may be any object `stat` accepts as a list)."""
    keys = sorted(clusters)
    if not keys:
        raise ValueError("no clusters")
    point = stat([clusters[k] for k in keys])
    draws = []
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        draws.append(stat([clusters[keys[i]] for i in pick]))
    draws = np.sort(np.array(draws, dtype=float))
    return {"point": point, "reps": reps, "ci95": [float(np.quantile(draws, 0.025)),
                                                    float(np.quantile(draws, 0.975))],
            "clusters": len(keys)}


def bundle_summary(bundles: list[dict], value_bounds: tuple[float, float] = (-1.0, 1.0)) -> dict:
    """Duplicate-deal endpoint: equity per base bundle, with unresolved bundles bounded, never dropped.

    A bundle's value is the mean over its games. A failed game is replaced by
    the lower / upper end of `value_bounds` (a per-game equity change lies in
    [-1, 1]) to give worst-case bounds; the resolved-only mean is labelled
    descriptive (complete-case analysis is not generally unbiased).
    """
    lo_vals, hi_vals, resolved = [], [], []
    for b in bundles:
        games = [r.get("candidate_value") for r in b.get("rows", [])]
        if b["resolved"]:
            resolved.append(b["value"])
            lo_vals.append(b["value"])
            hi_vals.append(b["value"])
        elif games:
            lo_vals.append(sum(value_bounds[0] if v is None else v for v in games) / len(games))
            hi_vals.append(sum(value_bounds[1] if v is None else v for v in games) / len(games))
        else:
            lo_vals.append(value_bounds[0])
            hi_vals.append(value_bounds[1])
    out = mean_ci(resolved)
    out.update({"bundles": len(bundles), "unresolved_bundles": [b["index"] for b in bundles if not b["resolved"]],
                "lower_bound": mean_ci(lo_vals), "upper_bound": mean_ci(hi_vals),
                "resolved_only_label": "descriptive: resolved bundles only (complete-case)",
                "note": "unresolved bundles are retained and bounded, not deleted or imputed"})
    return out


LEG_VALUE = {"win": 1.0, "loss": 0.0}


def match_summary(pairs: list[dict]) -> dict:
    """Complete-match endpoint with censoring bounds (R04).

    Pair score = mean over its two legs of the candidate's win indicator. For
    each unresolved/failed leg the lower bound uses 0 and the upper bound 1,
    per leg and within the pair, before averaging over pairs.
    """
    lower, upper, decided, midpoint = [], [], [], []
    unresolved_legs = failed_legs = 0
    for p in pairs:
        lo = hi = mid = 0.0
        known = []
        for leg in p["legs"]:
            v = LEG_VALUE.get(leg["outcome"])
            if v is None:
                unresolved_legs += leg["outcome"] == "unresolved"
                failed_legs += leg["outcome"] == "failed"
                lo += 0.0
                hi += 1.0
                mid += 0.5
            else:
                lo += v
                hi += v
                mid += v
                known.append(v)
        n_legs = len(p["legs"])
        if n_legs == 0:
            raise ValueError(f"pair {p.get('pair')} has no legs")
        lower.append(lo / n_legs)
        upper.append(hi / n_legs)
        midpoint.append(mid / n_legs)
        if len(known) == n_legs:
            decided.append(sum(known) / n_legs)
    lo_ci, hi_ci = mean_ci(lower), mean_ci(upper)
    return {"pairs": len(pairs), "unresolved_legs": unresolved_legs, "failed_legs": failed_legs,
            "decided_pairs": mean_ci(decided), "lower_bound": lo_ci, "upper_bound": hi_ci,
            "conclusion_robust_to_censoring": (lo_ci["ci95"] is not None and hi_ci["ci95"] is not None
                                              and (lo_ci["ci95"][0] > 0.5 or hi_ci["ci95"][1] < 0.5)),
            "descriptive_midpoint_sensitivity": {"mean": st.fmean(midpoint) if midpoint else None,
                                                 "label": "0.5 per unresolved leg; descriptive only, "
                                                          "not an unbiased match-win estimate"}}


def mse_endpoints(candidate, baseline, reference_reps, case_ids=None, deal_ids=None, *, reps: int = 0,
                  rng: np.random.Generator | None = None) -> dict:
    """Gap-MSE endpoints against an independent noisy reference (V11), averaged within case then deal.

    Each row is one (case, action) gap: candidate and baseline estimates and
    R >= 2 independent reference replicates. With r_bar the replicate mean
    and v_r = s^2 / R its estimated variance:

    - E[(c - r_bar)^2] = MSE_c + Var(r_bar): both raw MSEs carry the same
      reference variance, which cancels in the DIFFERENCE only;
    - the raw ratio is biased toward 1; the corrected ratio subtracts the
      estimated reference variance from both terms first.

    Squared errors are averaged within each case, then within each base deal,
    then over deals (spec 3.4). With `reps` > 0 a bootstrap over base deals
    gives intervals for the difference and the corrected ratio.
    """
    c = np.asarray(candidate, float)
    b = np.asarray(baseline, float)
    r = np.asarray(reference_reps, float)
    if r.ndim != 2 or r.shape[1] < 2 or r.shape[0] != len(c) or len(b) != len(c):
        raise ValueError("reference_reps must be [rows, R>=2] aligned with the estimates")
    n = len(c)
    case_ids = np.arange(n) if case_ids is None else np.asarray(case_ids)
    deal_ids = case_ids if deal_ids is None else np.asarray(deal_ids)
    r_bar = r.mean(axis=1)
    v_r = r.var(axis=1, ddof=1) / r.shape[1]
    parts = np.stack([(c - r_bar) ** 2, (b - r_bar) ** 2, v_r], axis=1)

    def by_deal(rows_idx):
        cases = {}
        for i in rows_idx:
            cases.setdefault((deal_ids[i], case_ids[i]), []).append(parts[i])
        deals = {}
        for (d, _c), rows in cases.items():
            deals.setdefault(d, []).append(np.mean(rows, axis=0))
        return {d: np.mean(v, axis=0) for d, v in deals.items()}

    def endpoints(deal_means):
        m = np.mean(list(deal_means.values()), axis=0)
        raw_c, raw_b, noise = (float(x) for x in m)
        corr_c, corr_b = raw_c - noise, raw_b - noise
        return raw_c, raw_b, noise, corr_c, corr_b

    per_deal = by_deal(range(n))
    raw_c, raw_b, noise, corr_c, corr_b = endpoints(per_deal)
    out = {"raw_mse_candidate": raw_c, "raw_mse_baseline": raw_b, "mean_reference_variance": noise,
           "mse_difference": raw_c - raw_b, "raw_ratio": raw_c / raw_b if raw_b > 0 else None,
           "corrected_mse_candidate": corr_c, "corrected_mse_baseline": corr_b,
           "corrected_ratio": corr_c / corr_b if corr_b > 0 else None, "deals": len(per_deal),
           "averaging": "within case, then within base deal, then over deals",
           "note": "reference noise cancels in the difference only; the raw ratio is biased toward 1"}
    if reps:
        rng = rng or np.random.default_rng(0)
        keys = sorted(per_deal)
        diffs, ratios = [], []
        for _ in range(reps):
            pick = [keys[i] for i in rng.integers(0, len(keys), len(keys))]
            m = np.mean([per_deal[k] for k in pick], axis=0)
            diffs.append(m[0] - m[1])
            if m[1] - m[2] > 0:
                ratios.append((m[0] - m[2]) / (m[1] - m[2]))
        out["mse_difference_ci95"] = [float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))]
        out["corrected_ratio_ci95"] = ([float(np.quantile(ratios, 0.025)), float(np.quantile(ratios, 0.975))]
                                       if ratios else None)
        out["bootstrap"] = {"unit": "base deal", "reps": reps, "ratio_reps_defined": len(ratios)}
    return out


def total_saving_bound(branch_cpu_fraction: float, within_branch_saving: float,
                       overhead_fraction: float = 0.0) -> dict:
    """Direct total CPU saving cannot exceed f*r before overhead (V10)."""
    f, r = branch_cpu_fraction, within_branch_saving
    if not (0 <= f <= 1 and r <= 1):
        raise ValueError("fractions out of range")
    return {"branch_cpu_fraction": f, "within_branch_saving": r, "upper_bound_before_overhead": f * r,
            "net_bound": f * r - overhead_fraction}


def power_n(sd: float, delta: float) -> float:
    """Two-sided 5%, 80% power planning approximation n = 7.85 s^2 / delta^2."""
    return 7.85 * sd * sd / (delta * delta)


def precision_n(sd: float, half_width: float) -> float:
    return (Z95 * sd / half_width) ** 2


def latency_summary(ms) -> dict:
    """p50/p95/p99 with their sample size; tails from few timings are flagged unstable."""
    v = np.sort(np.asarray(list(ms), float))
    if not len(v):
        return {"n": 0}
    q = {p: float(np.quantile(v, p / 100)) for p in (50, 95, 99)}
    return {"n": len(v), "p50_ms": q[50], "p95_ms": q[95], "p99_ms": q[99], "max_ms": float(v[-1]),
            "tail_unstable": len(v) < 100}
